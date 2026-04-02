from __future__ import annotations

import asyncio
import json

from zxf_agent.llm.client import chat
from zxf_agent.search import cache as search_cache
from zxf_agent.search.client import search
from zxf_agent.search.gaokao_client import fetch_university_ranks, fetch_university_ranks_baidu, fetch_volunteer_plan_baidu
from zxf_agent.search.score_section_client import get_rank_for_score

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_RANK_PROMPT = """从以下搜索结果中提取"{province}"省 {year} 年分数 {score} 分（{subject_type}）对应的高考位次。

搜索结果：
{snippets}

输出 JSON：
{{
  "rank": 42000,
  "confidence": 0.85
}}

rank 填整数，找不到明确数字就填 null，confidence 填 0~1。
"""

_CANDIDATES_PROMPT = """考生信息：
- 省份：{province}，该省位次约 {rank}（全省排名，越小越强），全国等价位次约 {national_equiv}（换算为山东省规模的等价排名）
- 选科：{subject_type}
- 目标城市/地区：{cities}
- 填报目标：{goal}

请列出 8~12 所适合该考生的候选院校，要求：
1. 以全国等价位次 {rank_range_low}~{rank_range_high} 为参考（即山东省该位次段可录取的水平），选出适合该考生的院校
2. 覆盖冲/稳/保三个层次，包括省外有竞争力的院校（985/211/强双一流均可）
3. 优先目标城市/地区，但不要局限于本省普通院校，好学校应在全国范围选
4. {c9_note}

只输出 JSON：{{"universities": ["苏州大学", "大连理工大学", ...]}}
"""

_CANDIDATES_FROM_SEARCH_PROMPT = """考生信息：
- 省份：{province}，分数：{score}，选科：{subject_type}
- 全国等价位次约 {national_equiv}

以下是搜索"该省该分数冲稳保院校推荐"的结果：
{search_snippets}

请从搜索结果中提取院校名称（包含但不限于搜索结果提到的院校）。
结合搜索结果和你的知识，列出 8~12 所适合该考生的候选院校（全名，含括号内校区信息）。
{c9_note}

只输出 JSON：{{"universities": ["苏州大学", "大连理工大学", ...]}}
"""

_DETAIL_PROMPT = """从以下搜索结果中提取"{university}"在"{province}"省（{subject_type}）近三年录取最低位次。

搜索结果：
{snippets}

输出 JSON：
{{
  "2024": 38500,
  "2023": 37200,
  "2022": 39100,
  "confidence": 0.85,
  "source_snippet": "原文中支撑这些数字的那句话"
}}

没有某年数据就填 null，找不到任何数据则 confidence < 0.4。
"""

# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run(profile: dict) -> dict:
    """
    返回：
    {
      "student_rank": 42000,
      "rank_confidence": 0.85,
      "universities": [
        {
          "name": "苏州大学",
          "avg_min_rank": 38500,
          "rank_by_year": {"2025": 38500},
          "confidence": 0.85,
          "source_snippet": "...",
        },
        ...
      ]
    }
    """
    province = profile["province"]
    score = int(profile["score"])
    subject_type = profile.get("subject_type", "")

    # Phase 1: 考生位次
    student_rank, rank_confidence = await _get_student_rank(profile)

    # Phase 2+3 主路径：百度掌上高考志愿预测卡片
    # 直接返回该省份+分数的冲/稳/保院校列表 + 当年最低位次，一次搞定
    cache_key = f"volunteer_plan|{province}|{score}|{subject_type}"
    cached = search_cache.get(cache_key)
    baidu_plan = cached if cached else await fetch_volunteer_plan_baidu(province, score, subject_type)
    if baidu_plan and any(baidu_plan.get(t) for t in ("reach", "match", "safety")):
        if not cached:
            # Cache raw baidu_plan (pre-tiered, basic data) so enrichment can run fresh from zjzw API each time
            search_cache.set(cache_key, baidu_plan)

        # Collect all schools from baidu_plan to enrich concurrently with zjzw API (Bug 2)
        all_school_names: list[str] = []
        for tier in ("reach", "match", "safety"):
            for s in baidu_plan.get(tier, []):
                all_school_names.append(s["name"])

        detail_tasks = [_get_university_detail(name, profile) for name in all_school_names]
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
        detail_map: dict[str, dict] = {}
        for name, res in zip(all_school_names, detail_results):
            if isinstance(res, dict) and res:
                detail_map[name] = res

        # Build pre_tiered：保留掌上高考分层，avg_min_rank 始终用百度卡片预测值
        # zjzw 历史数据（2022-2024）只补充到 rank_by_year 作为参考趋势，不影响排名显示
        # 原因：掌上高考用自身预测模型，zjzw 返回实际录取位次，两者含义不同，不能混用
        pre_tiered: dict[str, list[dict]] = {}
        for tier in ("reach", "match", "safety"):
            tier_schools = []
            for s in baidu_plan.get(tier, []):
                name = s["name"]
                card_rank = s["min_rank"]
                detail = detail_map.get(name)
                # rank_by_year：以百度卡片 2025 预测为基准，附上 zjzw 历史年份
                rank_by_year: dict = {"2025": card_rank}
                if detail and detail.get("rank_by_year"):
                    rank_by_year.update(detail["rank_by_year"])  # 补充 2022-2024 历史
                tier_schools.append({
                    "name": name,
                    "avg_min_rank": card_rank,          # 始终用掌上高考预测（与分层一致）
                    "rank_by_year": rank_by_year,
                    "confidence": 0.90 if detail else 0.85,
                    "source_snippet": (
                        f"掌上高考25年预测位次{card_rank}，历年均值约{detail['avg_min_rank']}"
                        if detail else f"来源：百度掌上高考志愿预测，25年最低位次 {card_rank}"
                    ),
                })
            pre_tiered[tier] = tier_schools

        # Flat universities list (for backwards compatibility with plan.py gap-formula path)
        universities = _convert_baidu_plan(baidu_plan)

        return {
            "student_rank": student_rank,
            "rank_confidence": rank_confidence,
            "universities": universities,
            "pre_tiered": pre_tiered,
        }

    # 兜底路径：LLM 生成候选名单 + 逐校查位次（原逻辑保留）
    candidate_names = await _get_candidate_names(profile, student_rank)
    tasks = [_get_university_detail(name, profile) for name in candidate_names]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    universities = [item for item in results if isinstance(item, dict) and item.get("avg_min_rank")]
    universities.sort(key=lambda u: u["avg_min_rank"])

    return {
        "student_rank": student_rank,
        "rank_confidence": rank_confidence,
        "universities": universities,
    }


def _convert_baidu_plan(baidu_plan: dict) -> list[dict]:
    """将百度志愿预测卡片结果转换为 universities 列表格式。"""
    universities = []
    for s in baidu_plan.get("reach", []) + baidu_plan.get("match", []) + baidu_plan.get("safety", []):
        universities.append({
            "name": s["name"],
            "avg_min_rank": s["min_rank"],
            "rank_by_year": {"2025": s["min_rank"]},
            "confidence": 0.85,
            "source_snippet": f"来源：百度掌上高考志愿预测，25年最低位次 {s['min_rank']}",
        })
    universities.sort(key=lambda u: u["avg_min_rank"])
    return universities


# ---------------------------------------------------------------------------
# Phase 1: 考生位次
# ---------------------------------------------------------------------------

async def _get_student_rank(profile: dict) -> tuple[int | None, float]:
    province = profile["province"]
    score = profile["score"]
    subject_type = profile.get("subject_type", "")
    year = 2024

    cache_key = f"rank|{province}|{score}|{subject_type}|{year}"
    cached = search_cache.get(cache_key)
    # 只用高置信度缓存；低置信度的允许重新尝试 Playwright
    if cached and cached.get("rank") and cached.get("confidence", 0) >= 0.8:
        return cached.get("rank"), cached.get("confidence", 0.5)

    # 策略 1：Playwright / API 直接读一分一段表（最准确）
    rank, confidence = await get_rank_for_score(province, int(score), subject_type, year)
    if rank:
        search_cache.set(cache_key, {"rank": rank, "confidence": confidence})
        return rank, confidence

    # 策略 2：搜索 + LLM 提取
    hits1 = await search(f"{province} {year} 一分一段 {score}分 {subject_type} 位次", max_results=3)
    hits2 = await search(f"{province}高考{year}年{score}分排名位次{subject_type}", max_results=2)
    hits = hits1 + hits2
    snippets = _format_snippets(hits)

    result_str = await chat(
        user_prompt=_RANK_PROMPT.format(
            province=province, year=year, score=score,
            subject_type=subject_type, snippets=snippets,
        ),
        system_prompt="你是数据提取器，只输出 JSON。",
        json_mode=True,
        operation="extract_rank",
    )
    try:
        data = json.loads(result_str)
    except Exception:
        data = {"rank": None, "confidence": 0.3}

    rank = data.get("rank")
    confidence = data.get("confidence", 0.3)

    if rank:
        search_cache.set(cache_key, {"rank": rank, "confidence": confidence})
        return rank, confidence

    # 策略 3：粗略公式兜底（按省份考生规模缩放）
    from zxf_agent.llm.client import _rough_rank
    rank = _rough_rank(int(score), province)
    confidence = 0.3
    # 不缓存兜底结果，下次重新尝试策略 1
    return rank, confidence


# ---------------------------------------------------------------------------
# Phase 2: 候选院校名单（LLM 生成）
# ---------------------------------------------------------------------------

async def _get_candidate_names(profile: dict, student_rank: int | None) -> list[str]:
    # 候选名单也缓存（以省份+分数+科目+城市+目标为 key），避免 LLM 每次生成不一致
    cities_str = "、".join(sorted(profile.get("target_cities") or [])) or "不限"
    cand_cache_key = f"candidates|{profile['province']}|{profile.get('score')}|{profile.get('subject_type')}|{cities_str}|{profile.get('goal') or ''}"
    cached_cands = search_cache.get(cand_cache_key)
    if cached_cands and cached_cands.get("universities"):
        return cached_cands["universities"]

    cities = cities_str
    # 顶尖档次提示：需根据省内位次换算全国等价水平
    # 不同省份考生规模差异极大，需要先折算成"全国等价位次"再判断
    from zxf_agent.llm.client import _rough_rank
    province = profile["province"]
    score = profile.get("score", 0)
    # 省份缩放系数（相对于山东95万基准），用于反推全国等价位次
    _PROVINCE_SCALE = {
        "河南": 1.37, "广东": 1.05, "四川": 0.88, "湖南": 0.76,
        "安徽": 0.76, "山东": 1.00, "湖北": 0.59, "河北": 0.58,
        "江苏": 0.53, "贵州": 0.51, "广西": 0.49, "云南": 0.42,
        "浙江": 0.42, "陕西": 0.36, "山西": 0.29, "江西": 0.28,
        "辽宁": 0.29, "重庆": 0.28, "黑龙江": 0.20, "吉林": 0.18,
        "福建": 0.17, "新疆": 0.17, "内蒙古": 0.16, "甘肃": 0.16,
        "上海": 0.05, "北京": 0.06, "天津": 0.06, "海南": 0.07,
    }
    scale = _PROVINCE_SCALE.get(province, 1.0)
    # 全国等价位次 = 省内位次 / 省份缩放系数（小省5000名 ≈ 大省20000名）
    national_equiv = int(student_rank / scale) if student_rank and scale > 0 else student_rank

    # 候选院校范围用全国等价位次，LLM 对全国排名认知准确，对小省省内排名认知差
    rank_low = int(national_equiv * 0.5) if national_equiv else 1000
    rank_high = int(national_equiv * 2.0) if national_equiv else 500000

    if national_equiv and national_equiv <= 3000:
        c9_note = "该考生全国等价位次极优，可以推荐顶尖 985 院校（清北复交浙等）"
    elif national_equiv and national_equiv <= 15000:
        c9_note = "该考生全国等价位次优秀，可以推荐中上游 985/211，不要推荐清北"
    elif national_equiv and national_equiv <= 50000:
        c9_note = "可以推荐普通 985/211，不要推荐顶尖院校"
    else:
        c9_note = "不要推荐 985 院校，推荐双一流或普通本科"

    # 优先用 Serper 搜索真实推荐结果，让 LLM 从搜索结果中提取（更可靠），而非凭记忆生成
    serper_hits = await search(
        f"{province}高考{score}分 冲稳保 院校推荐 2025 {profile.get('subject_type', '')}",
        max_results=5,
    )
    if serper_hits:
        search_snippets = _format_snippets(serper_hits)
        result_str = await chat(
            user_prompt=_CANDIDATES_FROM_SEARCH_PROMPT.format(
                province=profile["province"],
                score=score,
                subject_type=profile.get("subject_type", ""),
                national_equiv=national_equiv or "未知",
                search_snippets=search_snippets,
                c9_note=c9_note,
            ),
            system_prompt="你是高考志愿专家，只输出 JSON。",
            json_mode=True,
            operation="candidates",
        )
    else:
        # Serper 无结果（无 API key 或超配额）时退回纯 LLM 生成
        result_str = await chat(
            user_prompt=_CANDIDATES_PROMPT.format(
                province=profile["province"],
                rank=student_rank or "未知",
                national_equiv=national_equiv or "未知",
                subject_type=profile.get("subject_type", ""),
                cities=cities,
                goal=profile.get("goal") or "不限",
                rank_range_low=rank_low,
                rank_range_high=rank_high,
                c9_note=c9_note,
            ),
            system_prompt="你是高考志愿专家，只输出 JSON。",
            json_mode=True,
            operation="candidates",
        )
    try:
        unis = json.loads(result_str).get("universities", [])
        if unis:
            search_cache.set(cand_cache_key, {"universities": unis})
        return unis
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Phase 3: 单所院校历年位次
# ---------------------------------------------------------------------------

async def _get_university_detail(name: str, profile: dict) -> dict | None:
    province = profile["province"]
    subject_type = profile.get("subject_type", "")
    cache_key = f"detail|{name}|{province}|{subject_type}"

    cached = search_cache.get(cache_key)
    # 跳过低置信度的旧缓存（confidence < 0.9 说明是 LLM 提取的，优先重新用 API 查）
    if cached and cached.get("confidence", 0) >= 0.9:
        return _build_university(name, cached)

    # Phase 3a: 优先用结构化 API 直接获取位次数据（高置信度）
    api_result = await fetch_university_ranks(name, province)
    if api_result and api_result.get("avg_min_rank"):
        data = {
            "2024": api_result["rank_by_year"].get("2024"),
            "2023": api_result["rank_by_year"].get("2023"),
            "2022": api_result["rank_by_year"].get("2022"),
            "confidence": api_result["confidence"],
            "source_snippet": api_result["source_snippet"],
        }
        search_cache.set(cache_key, data)
        return _build_university(name, data)

    # Phase 3b: 百度 Playwright 解析（比 LLM 提取更可靠）
    baidu_result = await fetch_university_ranks_baidu(name, province)
    if baidu_result and baidu_result.get("avg_min_rank"):
        data = {
            "2024": baidu_result["rank_by_year"].get("2024"),
            "2023": baidu_result["rank_by_year"].get("2023"),
            "2022": baidu_result["rank_by_year"].get("2022"),
            "confidence": baidu_result["confidence"],
            "source_snippet": baidu_result["source_snippet"],
        }
        search_cache.set(cache_key, data)
        return _build_university(name, data)

    # Phase 3c: 最终 fallback —— Serper/Tavily 搜索 + LLM 提取
    hits_2024, hits_2023, hits_2022 = await asyncio.gather(
        search(f"{name} {province} {subject_type} 2024年 录取最低位次", max_results=2),
        search(f"{name} {province} {subject_type} 2023年 录取最低位次", max_results=1),
        search(f"{name} {province} {subject_type} 2022年 录取最低位次", max_results=1),
    )
    hits = hits_2024 + hits_2023 + hits_2022
    snippets = _format_snippets(hits)

    result_str = await chat(
        user_prompt=_DETAIL_PROMPT.format(
            university=name, province=province,
            subject_type=subject_type, snippets=snippets,
        ),
        system_prompt="你是数据提取器，只输出 JSON。",
        json_mode=True,
        operation="extract_detail",
    )
    try:
        data = json.loads(result_str)
    except Exception:
        data = {"confidence": 0.1}

    search_cache.set(cache_key, data)
    return _build_university(name, data)


def _build_university(name: str, data: dict) -> dict | None:
    ranks = [data.get(y) for y in ("2024", "2023", "2022") if data.get(y)]
    if not ranks:
        return None
    avg = int(sum(ranks) / len(ranks))
    return {
        "name": name,
        "avg_min_rank": avg,
        "rank_by_year": {y: data.get(y) for y in ("2024", "2023", "2022")},
        "confidence": data.get("confidence", 0.3),
        "source_snippet": data.get("source_snippet", ""),
    }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _format_snippets(hits: list[dict]) -> str:
    if not hits:
        return "（无搜索结果）"
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"[{i}] {h.get('title', '')}\n{h.get('snippet', '')}\n来源：{h.get('url', '')}")
    return "\n\n".join(parts)
