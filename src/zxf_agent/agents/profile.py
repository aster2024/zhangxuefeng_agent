from __future__ import annotations

import json

from zxf_agent.llm.client import chat
from zxf_agent.persona import ZXF_SYSTEM_PROMPT

_EXTRACT_SYSTEM = "你是信息提取器，只输出 JSON，不解释。"

_EXTRACT_PROMPT = """从对话中提取考生信息，未提及的字段填 null。

对话记录：
{conversation}

提取规则：
1. score：优先使用【最近一条用户消息】中明确提到的分数，忽略历史消息中的旧分数
2. province：如果最近消息未提省份，可沿用对话中提到的省份
3. subject_type：同上，可沿用历史中提到的选科

输出格式：
{{
  "province": "山东",
  "score": 550,
  "subject_type": "物理组",
  "target_cities": ["苏州", "杭州"],
  "goal": "求稳"
}}

subject_type 可选值：物理组 | 历史组 | 理科 | 文科 | 综合
（新高考省份用"物理组"/"历史组"或"综合"；老高考省份用"理科"/"文科"。考生说"综合"时直接填"综合"）
"""

_FOLLOWUP_PROMPT = """考生信息还不完整，缺少：{missing}

用张雪峰的口吻，用一句自然的口语追问。不要像填表，要像聊天。"""

REQUIRED_FIELDS = ("province", "score", "subject_type")


async def extract(messages: list[dict]) -> dict:
    """从对话历史中提取结构化 profile。"""
    conversation = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
        for m in messages[-8:]
    )
    result = await chat(
        user_prompt=_EXTRACT_PROMPT.format(conversation=conversation),
        system_prompt=_EXTRACT_SYSTEM,
        json_mode=True,
        operation="extract_profile",
    )
    try:
        profile = json.loads(result)
    except Exception:
        profile = {}

    profile.setdefault("province", None)
    profile.setdefault("score", None)
    profile.setdefault("subject_type", None)
    profile.setdefault("target_cities", [])
    profile.setdefault("goal", None)
    return profile


def missing_fields(profile: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not profile.get(f)]


async def followup_question(profile: dict) -> str:
    missing = missing_fields(profile)
    labels = {"province": "省份", "score": "分数", "subject_type": "选科"}
    missing_labels = "、".join(labels[f] for f in missing if f in labels)
    return await chat(
        user_prompt=_FOLLOWUP_PROMPT.format(missing=missing_labels),
        system_prompt=ZXF_SYSTEM_PROMPT,
        operation="followup",
    )
