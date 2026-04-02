from __future__ import annotations

import json

from zxf_agent.llm.client import chat

_SYSTEM = "你是意图分类器，只输出 JSON，不解释。"

_PROMPT = """判断用户消息的意图，输出以下 JSON 之一：
{{"type": "GENERAL"}}   — 泛问题，聊志愿/专业/就业方向，不需要查具体数据
{{"type": "PLANNING"}}  — 提到了分数+省份+选科，可以开始规划
{{"type": "CLARIFY"}}   — 想规划但缺少省份/分数/选科

用户消息：{message}
"""


async def route(message: str) -> str:
    """返回 'GENERAL' | 'PLANNING' | 'CLARIFY'"""
    result = await chat(
        user_prompt=_PROMPT.format(message=message),
        system_prompt=_SYSTEM,
        json_mode=True,
        operation="route",
    )
    try:
        return json.loads(result).get("type", "GENERAL")
    except Exception:
        return "GENERAL"
