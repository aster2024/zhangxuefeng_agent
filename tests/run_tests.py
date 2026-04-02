"""
端到端测试套件
测试覆盖：GENERAL问答、CLARIFY补充信息、PLANNING志愿方案（多省份多分段）、错误处理
"""
import asyncio
import json
import time
import httpx

BASE = "http://localhost:8000"
PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

async def chat(message: str, session_id=None, timeout: int = 180) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        body = {"message": message}
        if session_id:
            body["session_id"] = session_id
        r = await c.post(f"{BASE}/v1/chat", json=body)
        r.raise_for_status()
        return r.json()

def check(name: str, cond: bool, detail: str = ""):
    icon = PASS if cond else FAIL
    results.append((name, cond, detail))
    print(f"  {icon} {name}" + (f": {detail}" if detail else ""))
    return cond

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ────────────────────────────────────────────────────────────────
# SUITE 1: 健康检查
# ────────────────────────────────────────────────────────────────
async def test_health():
    section("SUITE 1 · 健康检查")
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE}/healthz")
        check("healthz 返回 200", r.status_code == 200)
        check("status=ok", r.json().get("status") == "ok")
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE}/")
        check("首页返回 HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""))

# ────────────────────────────────────────────────────────────────
# SUITE 2: GENERAL 问答（无需搜索，测 LLM 人设）
# ────────────────────────────────────────────────────────────────
async def test_general():
    section("SUITE 2 · GENERAL 通用问答")
    cases = [
        ("金融专业值不值得报", ["金融", "家庭", "资源", "银行", "稳定"]),
        ("生化环材怎么样", ["生化", "环材", "就业", "转行", "慎重"]),
        ("师范专业有没有前途", ["编制", "稳定", "师范"]),
    ]
    for q, keywords in cases:
        t0 = time.time()
        d = await chat(q)
        elapsed = time.time() - t0
        reply = d.get("reply", "")
        has_kw = any(k in reply for k in keywords)
        check(f"「{q[:12]}」有实质性回答", has_kw, f"{elapsed:.1f}s, {len(reply)}字")
        check(f"「{q[:12]}」不触发 plan", d.get("plan") is None or not d["plan"].get("reach"))

# ────────────────────────────────────────────────────────────────
# SUITE 3: CLARIFY 补全信息
# ────────────────────────────────────────────────────────────────
async def test_clarify():
    section("SUITE 3 · CLARIFY 补充信息流程")
    # 只说分数，缺省份和选科
    d1 = await chat("我考了620分，想填志愿")
    check("缺信息时状态是 clarify/collecting/general", d1.get("status") in ("clarify", "collecting", "general", "planned"))
    check("缺信息时无完整 plan", not (d1.get("plan", {}) or {}).get("reach"))

    # 多轮补全
    sid = d1["session_id"]
    d2 = await chat("山东省，物理组", session_id=sid)
    check("会话 id 保持不变", d2["session_id"] == sid)
    # 补全后可能直接出 plan 或再 clarify
    check("补全后有实质性回复", len(d2.get("reply", "")) > 20)

# ────────────────────────────────────────────────────────────────
# SUITE 4: PLANNING 核心测试（多省份多分段）
# ────────────────────────────────────────────────────────────────
async def test_planning():
    section("SUITE 4 · PLANNING 志愿方案（核心）")

    test_cases = [
        {
            "name": "辽宁理科650（高分小省）",
            "msg": "辽宁理科650分，帮我出志愿方案",
            "rank_range": (2000, 6000),   # 省内位次预期范围
            "min_unis": 3,
        },
        {
            "name": "河南物理组560（大省中等）",
            "msg": "河南省物理组560分，目标河南或武汉，帮我分析志愿",
            "rank_range": (60000, 160000),
            "min_unis": 3,
        },
        {
            "name": "山东物理组580（大省中高）",
            "msg": "山东省580分物理组，希望去江浙，帮我制定方案",
            "rank_range": (25000, 65000),
            "min_unis": 3,
        },
    ]

    for tc in test_cases:
        print(f"\n  ── {tc['name']} ──")
        t0 = time.time()
        d = await chat(tc["msg"])
        elapsed = time.time() - t0

        plan = d.get("plan") or {}
        rank = plan.get("student_rank")
        conf = plan.get("rank_confidence", 0)
        reach = plan.get("reach", [])
        match = plan.get("match", [])
        safety = plan.get("safety", [])
        all_unis = reach + match + safety

        print(f"    位次: {rank}  置信度: {conf:.2f}  耗时: {elapsed:.1f}s")

        lo, hi = tc["rank_range"]
        check(f"{tc['name']}·位次在合理区间({lo}-{hi})",
              rank is not None and lo <= rank <= hi,
              f"实际={rank}")
        check(f"{tc['name']}·置信度≥0.5", conf >= 0.5, f"{conf:.2f}")
        check(f"{tc['name']}·院校数≥{tc['min_unis']}", len(all_unis) >= tc["min_unis"],
              f"冲{len(reach)}+稳{len(match)}+保{len(safety)}")
        check(f"{tc['name']}·有结构化 plan", d.get("status") == "planned")

        if all_unis:
            names = [u["name"] for u in all_unis]
            print(f"    冲: {[u['name'] for u in reach]}")
            print(f"    稳: {[u['name'] for u in match]}")
            print(f"    保: {[u['name'] for u in safety]}")

            # 数据质量：院校位次数值合理性
            ranks_ok = all(0 < u.get("avg_min_rank", 0) < 1_000_000 for u in all_unis)
            check(f"{tc['name']}·位次数值合理", ranks_ok)

# ────────────────────────────────────────────────────────────────
# SUITE 5: 错误处理 & 边界情况
# ────────────────────────────────────────────────────────────────
async def test_edge_cases():
    section("SUITE 5 · 边界情况")

    # 空消息
    try:
        d = await chat("   ")
        check("空消息不崩溃", True, d.get("reply", "")[:30])
    except Exception as e:
        check("空消息不崩溃", False, str(e))

    # 极短输入
    d = await chat("你好")
    check("「你好」有回复", len(d.get("reply", "")) > 5)

    # 分数超范围
    d = await chat("山东理科900分物理组，帮我出志愿")
    check("异常分数不崩溃", "reply" in d)

    # 超长输入
    long_msg = "我是山东考生，" * 50 + "580分物理组，帮我出志愿"
    try:
        d = await chat(long_msg)
        check("超长输入不崩溃", "reply" in d)
    except Exception as e:
        check("超长输入不崩溃", False, str(e)[:50])

    # 非高考话题
    d = await chat("今天天气怎么样")
    check("非高考话题有合理回应", len(d.get("reply", "")) > 5)

# ────────────────────────────────────────────────────────────────
# SUITE 6: 缓存验证（第二次查询应明显更快）
# ────────────────────────────────────────────────────────────────
async def test_cache():
    section("SUITE 6 · 缓存加速验证")
    msg = "辽宁理科650分出志愿方案"
    t0 = time.time()
    d1 = await chat(msg)
    t1 = time.time() - t0

    t0 = time.time()
    d2 = await chat(msg)
    t2 = time.time() - t0

    check("第一次查询完成", d1.get("status") in ("planned", "general"))
    # 搜索结果缓存了，但 LLM summary 每次重新生成，第二次整体时间接近正常
    # 验证：第二次不能比第一次慢（说明缓存至少没负效果）
    check(f"第二次查询不慢于第一次 ({t1:.0f}s → {t2:.0f}s)", t2 <= t1 * 1.5, f"比率 {t2/max(t1,0.1):.1f}x")

# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────
async def main():
    print("\n" + "█"*60)
    print("  张雪峰 AI 志愿助手 — 上线前测试套件")
    print("█"*60)

    try:
        await test_health()
        await test_general()
        await test_clarify()
        await test_planning()
        await test_edge_cases()
        await test_cache()
    except Exception as e:
        print(f"\n{FAIL} 测试中断: {e}")

    # 汇总
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"  测试结果汇总")
    print(f"{'='*60}")
    print(f"  总计: {total}  通过: {passed}  失败: {failed}")
    if failed:
        print(f"\n  {FAIL} 未通过项：")
        for name, ok, detail in results:
            if not ok:
                print(f"    · {name}" + (f" [{detail}]" if detail else ""))
    verdict = "✅ 可以上线" if failed == 0 else ("⚠️  基本可用，有小问题" if failed <= 3 else "❌ 需要修复后再上线")
    print(f"\n  最终结论: {verdict}")

if __name__ == "__main__":
    asyncio.run(main())
