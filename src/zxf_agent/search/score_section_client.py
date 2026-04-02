"""
score_section_client.py — 用百度搜索结果获取考生一分一段位次

百度搜索 "{省份}高考{年份}一分一段 {分数}分 {科目} 位次" 时，
搜索结果页直接返回掌上高考结构化卡片（排名区间）及各结果摘要（含分数→位次）。

依赖：playwright（pip install playwright && playwright install chromium）
未安装时此模块返回 (None, 0.0)，上层自动降级到 _rough_rank。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional


async def get_rank_for_score(
    province: str,
    score: int,
    subject_type: str,
    year: int = 2024,
) -> tuple[int | None, float]:
    """
    返回 (rank, confidence)。
    用百度搜索结果页解析位次，失败返回 (None, 0.0)。
    """
    rank = await _baidu_score_rank(province, score, subject_type, year)
    if rank:
        return rank, 0.85
    return None, 0.0


async def _baidu_score_rank(
    province: str, score: int, subject_type: str, year: int
) -> Optional[int]:
    """
    Playwright + 百度搜索 → 解析一分一段位次。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    # 映射科目到百度搜索词
    subj_map = {
        "理科": "理科", "文科": "文科",
        "物理组": "物理类", "历史组": "历史类",
        "综合": "物理类",
    }
    subj_str = subj_map.get(subject_type, "物理类")

    query = f"{province}高考{year}年一分一段 {score}分 {subj_str} 位次"
    url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(query)

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
                viewport={"width": 1280, "height": 800},
            )
            # 规避 webdriver 检测
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            # 先访问百度首页建立 cookie
            await page.goto("https://www.baidu.com/", timeout=15_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
            # 再搜索
            await page.goto(url, timeout=20_000, wait_until="networkidle")
            await page.wait_for_timeout(1500)

            # 检测百度验证码，被封时快速返回 None
            is_captcha = await page.evaluate(
                "() => document.body.innerText.includes('请完成下方验证') || "
                "document.body.innerText.includes('百度安全验证')"
            )
            if is_captcha:
                await browser.close()
                return None

            text = await page.inner_text("body")
            await browser.close()

        return _parse_rank_from_text(text, score)
    except Exception:
        return None


def _parse_rank_from_text(text: str, target_score: int) -> Optional[int]:
    """
    从百度搜索结果文字中提取位次。

    百度返回两种高价值来源：
    1. 掌上高考结构化卡片：
       "高考分数\n650分\n同分人数\nXXX人\n排名区间\n3429-3561"
    2. 正文摘要：
       "640分对应的位次是5273"、"670分对应的位次是1316"
    """
    # 策略1：掌上高考卡片 —— "排名区间\nA-B" 格式
    m = re.search(r"排名区间\s*[\n\r]*\s*(\d+)\s*[-–]\s*(\d+)", text)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        return (low + high) // 2  # 取中位

    # 策略2："X分对应的位次是Y" / "X分 位次 Y"
    patterns = [
        rf"{target_score}\s*分[^。\n]{{0,30}}位次[是为：:]\s*(\d{{3,6}})",
        rf"{target_score}\s*分[^。\n]{{0,20}}对应[^。\n]{{0,10}}位次[^\d]{{0,5}}(\d{{3,6}})",
        rf"位次[是为：:]\s*(\d{{3,6}})[^。\n]{{0,30}}{target_score}\s*分",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            rank = int(m.group(1))
            if 100 <= rank <= 900_000:
                return rank

    # 策略3：从摘要片段插值
    # 如："640分对应的位次是5273，590分对应的位次是17554"
    pairs = re.findall(r"(\d{3})\s*分[^。\n]{0,20}位次[^\d]{0,5}(\d{3,6})", text)
    score_rank_pairs = []
    for s_str, r_str in pairs:
        s, r = int(s_str), int(r_str)
        if 200 <= s <= 750 and 100 <= r <= 900_000:
            score_rank_pairs.append((s, r))

    if score_rank_pairs:
        score_rank_pairs.sort(key=lambda x: x[0], reverse=True)
        # 精确匹配
        for s, r in score_rank_pairs:
            if s == target_score:
                return r
        # 插值：找最近的两个点
        above = [(s, r) for s, r in score_rank_pairs if s > target_score]
        below = [(s, r) for s, r in score_rank_pairs if s < target_score]
        if above and below:
            s_hi, r_hi = above[-1]
            s_lo, r_lo = below[0]
            ratio = (target_score - s_hi) / (s_lo - s_hi)
            rank = int(r_hi + ratio * (r_lo - r_hi))
            return rank
        elif below:
            return below[0][1]  # 最接近的下界
        elif above:
            return above[-1][1]  # 最接近的上界

    return None
