"""
gaokao_client.py — 直接调用 zjzw.cn/gaokao.cn API 获取结构化录取数据

API 发现来源：逆向 gaokao.cn 前端 JS
Base URL: https://api.zjzw.cn/web/api/
关键接口:
  - apidata/api/gkv3/school/lists  → 院校搜索（keyword 参数）
  - apidata/api/gk/score/province  → 分省录取分数线（min_section = 位次）

注意：此 API 为公共接口，无需鉴权，合理使用（有 SQLite 缓存）。
"""
from __future__ import annotations

import asyncio
import urllib.parse
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# 省份名 → province_id 映射（标准国家行政区划代码前两位）
# ---------------------------------------------------------------------------
PROVINCE_ID_MAP = {
    "北京": 11, "天津": 12, "河北": 13, "山西": 14, "内蒙古": 15,
    "辽宁": 21, "吉林": 22, "黑龙江": 23,
    "上海": 31, "江苏": 32, "浙江": 33, "安徽": 34, "福建": 35,
    "江西": 36, "山东": 37,
    "河南": 41, "湖北": 42, "湖南": 43, "广东": 44, "广西": 45, "海南": 46,
    "重庆": 50, "四川": 51, "贵州": 52, "云南": 53, "西藏": 54,
    "陕西": 61, "甘肃": 62, "青海": 63, "宁夏": 64, "新疆": 65,
}

_BASE = "https://api.zjzw.cn/web/api/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.gaokao.cn/",
}
_TIMEOUT = 15


async def _get(params: dict) -> dict:
    """发一次 GET 请求，返回解析后的 JSON。失败返回 {}。"""
    qs = urllib.parse.urlencode(params)
    url = f"{_BASE}?{qs}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()


async def lookup_school_id(name: str) -> Optional[int]:
    """
    根据院校名称查找 school_id。
    返回第一个完全匹配的 school_id，找不到返回 None。
    """
    try:
        data = await _get({"uri": "apidata/api/gkv3/school/lists", "keyword": name, "page": 1, "size": 5})
        items = data.get("data", {}).get("item", [])
        # 优先精确匹配
        for item in items:
            if item.get("name") == name:
                return int(item["school_id"])
        # 退而求其次：第一个结果
        if items:
            return int(items[0]["school_id"])
    except Exception:
        pass
    return None


async def get_admission_ranks(
    school_id: int,
    province_id: int,
    years: list[int],
) -> dict[int, Optional[int]]:
    """
    并发获取指定院校在指定生源省份的历年最低录取位次。

    返回: {2024: 26574, 2023: 31156, 2022: 22816}
    找不到的年份值为 None。
    """
    async def _fetch_year(year: int) -> tuple[int, Optional[int]]:
        try:
            data = await _get({
                "uri": "apidata/api/gk/score/province",
                "school_id": school_id,
                "local_province_id": province_id,
                "year": year,
                "page": 1,
                "size": 20,
            })
            items = data.get("data", {}).get("item", [])
            ranks = [
                int(item["min_section"])
                for item in items
                if item.get("min_section") and str(item["min_section"]).lstrip("-").isdigit()
                and int(item["min_section"]) > 0
            ]
            if ranks:
                # 多条记录取最小位次（位次小 = 录取要求更低，更容易被纳入稳/保）
                # 实际含义：不同专业组/科目组里最容易录取的那个
                return year, min(ranks)
        except Exception:
            pass
        return year, None

    results = await asyncio.gather(*[_fetch_year(y) for y in years])
    return dict(results)


async def fetch_university_ranks(
    name: str,
    province: str,
    years: Optional[list[int]] = None,
) -> Optional[dict]:
    """
    高层接口：给定院校名和考生所在省份，返回历年位次数据。

    返回:
    {
        "name": "苏州大学",
        "school_id": 118,
        "rank_by_year": {"2024": 26574, "2023": 31156, "2022": 22816},
        "avg_min_rank": 26981,
        "confidence": 0.95,
        "source": "gaokao_api",
    }
    失败返回 None。
    """
    if years is None:
        years = [2024, 2023, 2022]

    province_id = PROVINCE_ID_MAP.get(province)
    if not province_id:
        return None

    school_id = await lookup_school_id(name)
    if not school_id:
        return None

    rank_by_year = await get_admission_ranks(school_id, province_id, years)
    valid = {str(y): r for y, r in rank_by_year.items() if r}
    if not valid:
        return None

    ranks = list(valid.values())
    avg = int(sum(ranks) / len(ranks))

    return {
        "name": name,
        "school_id": school_id,
        "rank_by_year": valid,
        "avg_min_rank": avg,
        "confidence": 0.95,  # 结构化 API，置信度高
        "source_snippet": f"来源：gaokao.cn API，位次数据 {list(valid.keys())}",
    }


# ---------------------------------------------------------------------------
# 百度志愿预测卡片（掌上高考）— 一次搜索直接返回冲/稳/保院校列表
# ---------------------------------------------------------------------------

async def fetch_volunteer_plan_baidu(
    province: str,
    score: int,
    subject_type: str = "",
) -> Optional[dict]:
    """
    搜百度"{省份}高考{分数}分"，解析掌上高考志愿预测卡片。
    卡片直接给出冲/稳/保分类 + 当年最低分/位次，无需额外查询。

    返回：
    {
        "reach":  [{"name": "中国科技大学", "min_rank": 4096, "min_score": 580}, ...],
        "match":  [...],
        "safety": [...],
    }
    失败返回 None。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    subj_map = {
        "理科": "理科", "文科": "文科",
        "物理组": "物理类", "历史组": "历史类",
    }
    subj_str = subj_map.get(subject_type, "")
    query = f"{province}高考{score}分 {subj_str}".strip()
    url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)

    # 提取页面上所有院校（不管显隐），用差量法区分各 tab 新增的院校
    _JS_EXTRACT_ALL = """
    () => {
        const schools = [];
        document.querySelectorAll('[data-module="school-content"]').forEach(el => {
            const name = el.querySelector('[data-module="school-name"]')
                           ?.textContent?.trim();
            let minRank = null, minScore = null;
            el.querySelectorAll('[class*="school-info-key"]').forEach(keyEl => {
                const keyText = keyEl.textContent?.trim() || '';
                const valEl   = keyEl.nextElementSibling;
                const val     = parseInt(valEl?.textContent?.trim());
                if (keyText.includes('最低位次')) minRank  = isNaN(val) ? null : val;
                if (keyText.includes('最低分') && !keyText.includes('位次'))
                    minScore = isNaN(val) ? null : val;
            });
            if (name && minRank) {
                schools.push({ name, minRank, minScore });
            }
        });
        return schools;
    }
    """

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                viewport={"width": 1280, "height": 800},
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            await page.goto("https://www.baidu.com/", timeout=15_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
            await page.goto(url, timeout=20_000, wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # CAPTCHA detection: if Baidu shows a slider verification, bail out immediately
            is_captcha = await page.evaluate(
                "() => document.body.innerText.includes('请完成下方验证') || "
                "document.body.innerText.includes('百度安全验证')"
            )
            if is_captcha:
                await browser.close()
                return None

            result: dict = {"reach": [], "match": [], "safety": []}
            seen_names: set = set()

            # 点击每个 tab，用 dispatchEvent 确保 React 事件监听被触发
            # 差量逻辑：只把"新出现"的院校归入当前 tab 的档位
            for tab_idx, tier_key in [(0, "reach"), (1, "match"), (2, "safety")]:
                await page.evaluate(
                    "(idx) => {"
                    "  const el = document.querySelector('[data-module=\"tab-' + idx + '\"]');"
                    "  if (el) {"
                    "    el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));"
                    "  }"
                    "}",
                    tab_idx,
                )
                await page.wait_for_timeout(1500)
                all_schools = await page.evaluate(_JS_EXTRACT_ALL)
                for s in all_schools:
                    name = s["name"]
                    if name not in seen_names:
                        seen_names.add(name)
                        result[tier_key].append({
                            "name":      name,
                            "min_rank":  s["minRank"],
                            "min_score": s.get("minScore"),
                        })

            await browser.close()

        if not any(result.values()):
            return None
        return result

    except Exception:
        return None


# ---------------------------------------------------------------------------
# 百度搜索 Playwright 解析（作为 zjzw API 失败时的备用，查单所院校历年位次）
# ---------------------------------------------------------------------------

async def fetch_university_ranks_baidu(
    name: str,
    province: str,
    years: Optional[list[int]] = None,
) -> Optional[dict]:
    """
    用 Playwright 搜百度，解析院校在该省的历年录取最低位次。
    百度搜索结果页直接嵌入了结构化录取分数线表格（含位次列）。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    if years is None:
        years = [2024, 2023, 2022]

    import urllib.parse
    import re

    rank_by_year: dict[str, Optional[int]] = {}
    source_snippet = ""

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )

            for year in years:
                page = await context.new_page()
                query = f"{name} {province} {year}年 录取最低位次 分数线"
                url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)
                try:
                    await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    html = await page.content()
                    rank = _parse_baidu_university_rank(html, name, province, year)
                    if rank:
                        rank_by_year[str(year)] = rank
                        if not source_snippet:
                            source_snippet = f"来源：百度搜索结果，{year}年位次 {rank}"
                except Exception:
                    pass
                finally:
                    await page.close()

            await browser.close()
    except Exception:
        return None

    valid = {y: r for y, r in rank_by_year.items() if r}
    if not valid:
        return None

    ranks = list(valid.values())
    avg = int(sum(ranks) / len(ranks))

    return {
        "name": name,
        "school_id": None,
        "rank_by_year": valid,
        "avg_min_rank": avg,
        "confidence": 0.80,
        "source_snippet": source_snippet or f"来源：百度搜索，{name} {province}",
    }


def _parse_baidu_university_rank(html: str, name: str, province: str, year: int) -> Optional[int]:
    """
    从百度搜索结果 HTML 中提取院校在指定省份指定年份的录取最低位次。
    百度卡片里有 <td>最低分</td><td>位次</td> 结构。
    """
    import re

    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean)

    # 策略1：找 "最低分 … 位次" 列结构中的位次数字
    # 百度结构化表格里顺序通常是: 批次 | 专业组 | 最低分 | 位次 | 人数
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    ranks = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        texts = [re.sub(r"<[^>]+>", "", c).strip().replace(",", "") for c in cells]
        nums = [int(t) for t in texts if re.fullmatch(r"\d+", t)]
        # 找到分数（350-750）+ 紧随其后的位次（500-900000）
        for i, n in enumerate(nums):
            if 350 <= n <= 750 and i + 1 < len(nums):
                candidate = nums[i + 1]
                if 500 <= candidate <= 900_000:
                    ranks.append(candidate)

    if ranks:
        return min(ranks)  # 取最低位次（最好的那个）

    # 策略2：正则从文本中找 "位次 XXXXX" 附近的数字
    pat = r"(?:最低位次|录取位次)[^\d]{0,5}(\d{3,6})"
    matches = re.findall(pat, clean)
    valid_ranks = [int(m) for m in matches if 500 <= int(m) <= 900_000]
    if valid_ranks:
        return min(valid_ranks)

    return None
