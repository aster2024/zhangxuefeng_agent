from __future__ import annotations

from zxf_agent.llm.client import chat
from zxf_agent.persona import ZXF_SYSTEM_PROMPT

_SUMMARY_PROMPT = """你刚刚为考生生成了以下志愿方案：

考生信息：
- 省份：{province}，分数：{score}，位次：{rank}，选科：{subject_type}
- 目标城市：{cities}，填报目标：{goal}

志愿方案（已按冲/稳/保分层）：
{plan_text}

用张雪峰的口吻，以"帮你出了这个方案，逻辑是……"的角度，写 2~3 句话解释方案设计思路和注意事项。
注意：这是你为考生制定的方案，不是考生自己提交的，不要说"你的方案"或"你这个方案"。
不要重复列院校名字，直接说关键点。
"""

# 分层阈值（基于 avg_min_rank 的百分比）
# student_rank - avg_min_rank 为正数表示考生位次比录取线差（位次数值越大越靠后）
_REACH_MAX_GAP_PCT = 0.12   # 比录取线差 0~12%：冲
_MATCH_GOOD_PCT = 0.25      # 比录取线好 0~25%：稳
# 好于 25%：保


def assemble(search_result: dict, profile: dict) -> dict:
    """
    纯规则分层，不调用 LLM（LLM 只用于生成 summary）。
    当 search_result 含 pre_tiered 时直接使用掌上高考分层结果；
    否则回退到基于 gap 公式的自动分层（兜底路径）。
    返回结构化 plan dict。
    """
    student_rank = search_result.get("student_rank")

    # Bug 1 fix: use 掌上高考 pre-assigned tiers when available
    pre_tiered = search_result.get("pre_tiered")
    if pre_tiered:
        reach = pre_tiered.get("reach", [])
        match = pre_tiered.get("match", [])
        safety = pre_tiered.get("safety", [])
        return {
            "student_rank": student_rank,
            "rank_confidence": search_result.get("rank_confidence"),
            "reach": [_fmt(u) for u in reach[:3]],
            "match": [_fmt(u) for u in match[:4]],
            "safety": [_fmt(u) for u in safety[:3]],
            "profile": profile,
        }

    # Fallback: gap-formula tiering (used when pre_tiered is not set)
    universities = search_result.get("universities", [])

    reach, match, safety = [], [], []

    for u in universities:
        avg = u["avg_min_rank"]
        if student_rank is None:
            # 没有位次时全归稳档，让用户自判
            match.append(u)
            continue

        gap = student_rank - avg  # 正数：考生比录取线差；负数：考生更好

        if 0 < gap <= avg * _REACH_MAX_GAP_PCT:
            reach.append(u)
        elif -avg * _MATCH_GOOD_PCT <= gap <= 0:
            match.append(u)
        elif gap < -avg * _MATCH_GOOD_PCT:
            safety.append(u)
        # gap 超过 REACH_MAX_GAP_PCT（差太多）：不推荐，跳过

    # 兜底：若展示院校数 < 5（三档均空，或高分小省候选全落入安全垫太远区域），
    # 按位次从好到差比例分配，确保用户至少看到足够的候选院校
    total_shown = len(reach) + len(match) + len(safety)
    if total_shown < 5 and universities and student_rank:
        sorted_unis = sorted(universities, key=lambda u: u["avg_min_rank"])
        n = len(sorted_unis)
        # 最好的 1/4 归冲，中间 1/2 归稳，后面 1/4 归保
        cut1, cut2 = max(1, n // 4), max(1, n * 3 // 4)
        reach = sorted_unis[:cut1]
        match = sorted_unis[cut1:cut2]
        safety = sorted_unis[cut2:]

    return {
        "student_rank": student_rank,
        "rank_confidence": search_result.get("rank_confidence"),
        "reach": [_fmt(u) for u in reach[:3]],
        "match": [_fmt(u) for u in match[:4]],
        "safety": [_fmt(u) for u in safety[:3]],
        "profile": profile,
    }


async def add_summary(plan: dict) -> dict:
    """调用 LLM 生成张雪峰风格的方案说明，注入到 plan['summary']。"""
    profile = plan["profile"]
    plan_text = _plan_to_text(plan)

    summary = await chat(
        user_prompt=_SUMMARY_PROMPT.format(
            province=profile.get("province", ""),
            score=profile.get("score", ""),
            rank=plan.get("student_rank", "未知"),
            subject_type=profile.get("subject_type", ""),
            cities="、".join(profile.get("target_cities") or []) or "不限",
            goal=profile.get("goal") or "不限",
            plan_text=plan_text,
        ),
        system_prompt=ZXF_SYSTEM_PROMPT,
        operation="plan_summary",
    )
    plan["summary"] = summary
    return plan


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _fmt(u: dict) -> dict:
    return {
        "name": u["name"],
        "avg_min_rank": u["avg_min_rank"],
        "rank_by_year": u["rank_by_year"],
        "confidence": u["confidence"],
        "source_snippet": u["source_snippet"],
    }


def _plan_to_text(plan: dict) -> str:
    lines = []
    for tier, label in [("reach", "冲"), ("match", "稳"), ("safety", "保")]:
        items = plan.get(tier, [])
        if items:
            names = "、".join(u["name"] for u in items)
            lines.append(f"【{label}】{names}")
    return "\n".join(lines) if lines else "（无候选院校）"
