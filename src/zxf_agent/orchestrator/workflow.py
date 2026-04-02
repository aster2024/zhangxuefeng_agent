from __future__ import annotations

from zxf_agent.agents import plan as plan_agent
from zxf_agent.agents import profile as profile_agent
from zxf_agent.agents import search_agent
from zxf_agent.agents.router import route
from zxf_agent.db.repo import SessionRepo
from zxf_agent.llm.client import chat
from zxf_agent.persona import ZXF_SYSTEM_PROMPT


async def handle(message: str, session_id: str | None = None) -> dict:
    """
    主入口。接收一条用户消息，返回 reply + 当前状态。

    返回结构：
    {
      "session_id": "xxx",
      "reply": "...",
      "status": "collecting" | "planned",
      "plan": {...} | None,
    }
    """
    session = _load_or_create(session_id)
    sid = session.id

    messages = list(session.messages or [])
    messages.append({"role": "user", "content": message})

    # --- Router ---
    intent = await route(message)

    # --- GENERAL: 直接 LLM 回答 ---
    if intent == "GENERAL":
        reply = await chat(
            user_prompt=message,
            system_prompt=ZXF_SYSTEM_PROMPT,
            operation="general",
        )
        messages.append({"role": "assistant", "content": reply})
        SessionRepo.update(sid, messages=messages)
        return {"session_id": sid, "reply": reply, "status": "collecting", "plan": None}

    # --- PLANNING / CLARIFY: 提取 profile ---
    profile = await profile_agent.extract(messages)
    missing = profile_agent.missing_fields(profile)

    if missing:
        reply = await profile_agent.followup_question(profile)
        messages.append({"role": "assistant", "content": reply})
        SessionRepo.update(sid, messages=messages, profile=profile, status="collecting")
        return {"session_id": sid, "reply": reply, "status": "collecting", "plan": None}

    # --- 信息完整，执行规划 ---
    search_result = await search_agent.run(profile)
    plan = plan_agent.assemble(search_result, profile)
    plan = await plan_agent.add_summary(plan)

    reply = _build_reply(plan)
    messages.append({"role": "assistant", "content": reply})
    SessionRepo.update(sid, messages=messages, profile=profile, status="planned", plan=plan)

    return {"session_id": sid, "reply": reply, "status": "planned", "plan": plan}


# ---------------------------------------------------------------------------

def _load_or_create(session_id: str | None):
    if session_id:
        session = SessionRepo.get(session_id)
        if session:
            return session
    return SessionRepo.create(session_id)


def _build_reply(plan: dict) -> str:
    lines = [plan.get("summary", ""), ""]

    rank = plan.get("student_rank")
    confidence = plan.get("rank_confidence", 0)
    if rank:
        conf_note = "（数据置信度较低，建议自行核验）" if confidence < 0.6 else ""
        lines.append(f"你的估算位次：约 {rank} 名 {conf_note}")
        lines.append("")

    for tier, label, emoji in [("reach", "冲", "🔥"), ("match", "稳", "✅"), ("safety", "保", "🛡️")]:
        items = plan.get(tier, [])
        if not items:
            continue
        lines.append(f"{emoji} 【{label}】")
        for u in items:
            conf_note = " ⚠️置信度低" if u["confidence"] < 0.5 else ""
            lines.append(f"  · {u['name']}  参考位次：{u['avg_min_rank']}{conf_note}")
        lines.append("")

    lines.append("⚠️ 院校位次来自 gaokao.cn API，学生位次为估算值，请务必在阳光高考平台二次核验后再填报。")
    return "\n".join(lines).strip()
