from __future__ import annotations

import json
import re

import httpx

from zxf_agent.config import settings
from zxf_agent.persona import ZXF_SYSTEM_PROMPT


async def chat(
    user_prompt: str,
    system_prompt: str = ZXF_SYSTEM_PROMPT,
    json_mode: bool = False,
    operation: str = "",
) -> str:
    """
    统一 LLM 调用入口。
    operation 用于 mock 模式下判断做什么事，可选值：
      route | extract_profile | general | candidates |
      extract_rank | extract_detail | plan_summary
    """
    if settings.llm_provider == "mock" or not settings.llm_api_key:
        return _mock(operation, user_prompt)

    if settings.llm_provider == "anthropic":
        return await _call_anthropic(system_prompt, user_prompt)

    # OpenAI-compatible: DeepSeek / Qwen / Doubao / openai 等
    return await _call_openai_compatible(system_prompt, user_prompt, json_mode)


async def _call_openai_compatible(system_prompt: str, user_prompt: str, json_mode: bool) -> str:
    payload: dict = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    """Anthropic Messages API（与 OpenAI 格式不同，system 在顶层）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.llm_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


# ---------------------------------------------------------------------------
# Mock 实现 —— 无 API Key 时也能跑通主流程
# ---------------------------------------------------------------------------

def _mock(operation: str, prompt: str) -> str:
    if operation == "route":
        return _mock_route(prompt)
    if operation == "extract_profile":
        return _mock_extract_profile(prompt)
    if operation == "followup":
        return _mock_followup(prompt)
    if operation == "general":
        return _mock_general(prompt)
    if operation == "candidates":
        return _mock_candidates(prompt)
    if operation == "extract_rank":
        return _mock_extract_rank(prompt)
    if operation == "extract_detail":
        return _mock_extract_detail(prompt)
    if operation == "plan_summary":
        return _mock_plan_summary(prompt)
    return "（mock）请配置 LLM_API_KEY 以启用真实回复。"


def _mock_route(prompt: str) -> str:
    # 只分析"用户消息："之后的内容，避免匹配模板文字
    m = re.search(r"用户消息[：:](.*)", prompt, re.DOTALL)
    text = m.group(1).strip() if m else prompt

    has_score = bool(re.search(r"\d{3}", text))
    has_province = any(p in text for p in ["北京", "上海", "山东", "河南", "广东", "江苏", "浙江", "四川", "湖北", "湖南", "安徽", "河北", "陕西", "福建"])
    has_subject = any(s in text for s in ["物理", "历史", "理科", "文科", "物化", "史政"])
    wants_plan = any(k in text for k in ["估分", "报考", "志愿", "录取", "填报", "冲稳保"])

    if wants_plan or (has_score and has_province):
        if has_score and has_province and has_subject:
            return '{"type": "PLANNING"}'
        return '{"type": "CLARIFY"}'
    return '{"type": "GENERAL"}'


def _mock_extract_profile(prompt: str) -> str:
    province = None
    for p in ["北京", "上海", "山东", "河南", "广东", "江苏", "浙江", "四川", "湖北", "湖南", "安徽", "河北", "陕西", "福建", "辽宁"]:
        if p in prompt:
            province = p
            break

    score = None
    m = re.search(r"(\d{3})\s*分", prompt)
    if not m:
        m = re.search(r"估分\D{0,3}(\d{3})", prompt)
    if m:
        score = int(m.group(1))

    subject_type = None
    for combo, label in [("物化生", "物理组"), ("物化地", "物理组"), ("物生地", "物理组"),
                          ("史政地", "历史组"), ("史化生", "历史组"),
                          ("物理", "物理组"), ("历史", "历史组"),
                          ("理科", "理科"), ("文科", "文科")]:
        if combo in prompt:
            subject_type = label
            break

    cities: list[str] = []
    for city in ["北京", "上海", "深圳", "广州", "南京", "杭州", "苏州", "武汉", "成都", "西安", "济南", "青岛"]:
        if city in prompt:
            cities.append(city)
    # 地区关键词
    if "江浙" in prompt:
        cities = list(set(cities + ["南京", "杭州", "苏州"]))
    if "长三角" in prompt:
        cities = list(set(cities + ["上海", "南京", "杭州"]))

    goal = None
    for kw in ["求稳", "就业稳定", "考公", "互联网", "出国", "保研", "读研"]:
        if kw in prompt:
            goal = kw
            break

    return json.dumps({
        "province": province,
        "score": score,
        "subject_type": subject_type,
        "target_cities": cities,
        "goal": goal,
    }, ensure_ascii=False)


def _mock_followup(prompt: str) -> str:
    if "省份" in prompt:
        return "你是哪个省的考生？"
    if "分数" in prompt:
        return "分数出来了吗？估分大概多少？"
    if "选科" in prompt:
        return "你选的啥科？物理组还是历史组？"
    return "能说得具体点吗，省份、分数、选科这三个我都需要。"


def _mock_general(prompt: str) -> str:
    if "金融" in prompt:
        return "普通家庭的孩子，学金融我要泼冷水。没资源，毕业大概率去银行柜台坐柜，或者卖保险。真正赚钱的金融岗位，你得看你家认识谁。想要稳定，电气、药学、师范比金融实在多了。你家有金融行业的资源吗？"
    if "计算机" in prompt or "CS" in prompt:
        return "计算机现在确实卷，但需求还在。关键是要看院校平台——普通二本的计算机和985的计算机，差距不是一星半点。如果你分数够上个好学校，计算机还是值得考虑的。分数不够，不如选电气或者自动化，就业面更宽。"
    if "师范" in prompt:
        return "师范是我比较推荐普通家庭去考虑的方向，特别是数学、物理、化学这些理科师范。编制、稳定、寒暑假，抗周期性特别强。现在考编竞争虽然激烈，但至少有个明确的出路。"
    if "医学" in prompt or "临床" in prompt:
        return "学医要想清楚，周期太长——本科5年，规培3年，出来都30岁了还是住院医，收入一般。但如果真的想学，一定要冲好学校，普通院校的医学真的很难走出来。你家有医疗资源吗？"
    return "（mock模式）具体问题具体分析，说说你的情况——省份、分数、选科，我给你出主意。"


def _mock_candidates(prompt: str) -> str:
    # 根据目标城市返回不同候选
    if "江浙" in prompt or "苏州" in prompt or "南京" in prompt or "杭州" in prompt:
        return json.dumps({"universities": [
            "苏州大学", "南京工业大学", "江苏大学", "扬州大学",
            "浙江工业大学", "杭州电子科技大学", "宁波大学",
            "南京师范大学", "河海大学", "南京信息工程大学",
        ]}, ensure_ascii=False)
    if "广东" in prompt or "深圳" in prompt or "广州" in prompt:
        return json.dumps({"universities": [
            "广东工业大学", "广州大学", "深圳大学", "华南农业大学",
            "广东财经大学", "南方医科大学", "广州医科大学",
        ]}, ensure_ascii=False)
    # 默认全国范围
    return json.dumps({"universities": [
        "郑州大学", "苏州大学", "湖南大学", "西南大学",
        "南京工业大学", "浙江工业大学", "河海大学",
        "江苏大学", "扬州大学", "宁波大学",
    ]}, ensure_ascii=False)


def _mock_extract_rank(prompt: str) -> str:
    # 从 prompt 中抠分数，给一个粗略位次
    m = re.search(r"分数\s*(\d{3,})\s*分", prompt)
    if not m:
        m = re.search(r"(\d{3})\s*分", prompt)
    score = int(m.group(1)) if m else 500
    # 粗略位次估算（参考山东大省，非线性）
    # 实际情况需要真实一分一段表
    rank = _rough_rank(score)
    confidence = 0.4  # mock 数据，置信度统一标低
    return json.dumps({"rank": rank, "confidence": confidence}, ensure_ascii=False)


def _mock_extract_detail(prompt: str) -> str:
    # 根据院校名字给一个假的位次（mock用，无实际参考价值）
    # 范围设在 50000~130000，覆盖 550 分考生的冲稳保区间
    import hashlib
    h = int(hashlib.md5(prompt[:20].encode()).hexdigest(), 16) % 80000
    base = 50000 + h
    return json.dumps({
        "2024": base,
        "2023": base + 1200,
        "2022": base - 800,
        "confidence": 0.3,
        "source_snippet": "（mock数据，无实际参考价值，请配置搜索 API）",
    }, ensure_ascii=False)


def _rough_rank(score: int, province: str = "") -> int:
    """
    粗略的分数→位次映射，基准参考山东省（~95万考生）。
    对小省份按考生规模缩放，避免严重高估位次。
    """
    # 基准表（参考山东理科/综合，约60万理科考生）
    table = [
        (700, 500), (680, 2000), (660, 5000), (640, 12000),
        (620, 22000), (600, 35000), (580, 52000), (560, 72000),
        (550, 85000), (540, 100000), (520, 130000), (500, 165000),
        (480, 205000), (460, 250000), (0, 500000),
    ]
    base_rank = 500000
    for threshold, rank in table:
        if score >= threshold:
            base_rank = rank
            break

    # 各省 2024 年高考报名人数（万）→ 缩放系数（相对山东95万）
    province_scale = {
        "河南": 1.37, "广东": 1.05, "四川": 0.88, "湖南": 0.76,
        "安徽": 0.76, "山东": 1.00, "湖北": 0.59, "河北": 0.58,
        "江苏": 0.53, "贵州": 0.51, "广西": 0.49, "云南": 0.42,
        "浙江": 0.42, "陕西": 0.36, "山西": 0.29, "江西": 0.28,
        "辽宁": 0.29, "重庆": 0.28, "黑龙江": 0.20, "吉林": 0.18,
        "福建": 0.17, "新疆": 0.17, "内蒙古": 0.16, "甘肃": 0.16,
        "上海": 0.05, "北京": 0.06, "天津": 0.06, "海南": 0.07,
        "宁夏": 0.08, "青海": 0.05, "西藏": 0.02,
    }
    scale = province_scale.get(province, 1.0)
    return max(100, int(base_rank * scale))


def _mock_plan_summary(prompt: str) -> str:
    return (
        "（mock模式）根据你的位次和目标城市，我给你分了冲稳保三档。"
        "冲的是有希望但不确定的，稳的是基本能录，保的是兜底。"
        "注意，这是 mock 数据，请配置真实搜索 API 获取准确分数线。"
        "志愿表填完记得去阳光高考平台二次核验每所学校的历年录取数据。"
    )
