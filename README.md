# 张雪峰 AI 志愿助手

> 🕯 谨以此项目，悼念张雪峰老师（1984.5 — 2026.3.24）

---

## 悼念

2026 年 3 月 24 日，张雪峰老师因心源性猝死在苏州离世，年仅 41 岁。

他用十余年时间，用最直白的语言，帮助无数普通家庭的孩子看清高考志愿里的信息差。他不是学术权威，不是名校出身，却成了 6000 万人信任的"志愿参谋"。他的风格是：不讲废话，不绕弯子，直接告诉你你能上哪、该上哪。

他走得太突然，留下了很多还没说完的事。

这个项目，是我们尝试用 AI 把他做的事延续下去的一点努力——不是替代，只是传承。

---

## 项目简介

**张雪峰 AI 志愿助手**是一个基于大语言模型的高考志愿规划工具，模仿张雪峰老师的说话风格，结合实时网络检索，为考生提供冲/稳/保三档院校建议。

数据来源：
- **百度掌上高考**志愿预测卡片（Playwright 实时抓取，2025 年最低录取位次）
- **掌上高考 API**（历年 2022–2024 录取数据）
- **Serper / Google 搜索**（候选院校辅助检索）

---

## 功能

- 对话式信息收集：省份、分数、选科、目标城市、志愿目标
- 自动查询考生一分一段位次（实时）
- 冲/稳/保三档院校推荐，附历年录取位次趋势
- 张雪峰风格的总结点评
- 结果缓存（180 天），重复查询秒级响应

---

## 架构

```
用户消息
  ↓
Router（意图识别）
  ├─ GENERAL  → LLM 直接回答（张雪峰人设）
  └─ PLANNING → Profile 提取 → Search Agent → Plan Agent → 回复

Search Agent：
  Phase 1  一分一段位次  → 百度 Playwright → Serper+LLM → 粗略公式
  Phase 2  院校数据      → 百度掌上高考卡片（主）→ Serper+LLM+API（备）
```

技术栈：FastAPI · SQLite · Playwright · httpx · Anthropic / DeepSeek API

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 配置环境变量（复制并填入 API Key）
cp .env.example .env

# 3. 启动服务
PYTHONPATH=src uvicorn src.zxf_agent.main:app --reload

# 4. 打开浏览器
open http://localhost:8000
```

---

## 环境变量说明（`.env`）

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | `anthropic` / `openai-compatible` / `mock` |
| `LLM_MODEL` | 模型名，如 `deepseek-chat` / `claude-sonnet-4-5` |
| `LLM_API_KEY` | LLM API Key |
| `LLM_BASE_URL` | OpenAI 兼容接口地址（使用 DeepSeek/Qwen 时填写） |
| `WEB_SEARCH_PROVIDER` | `serper`（推荐）/ `none` |
| `SERPER_API_KEY` | Serper API Key（[serper.dev](https://serper.dev) 注册，有免费额度） |

---

## 免责声明

1. 本项目仅供技术学习与研究交流，不构成任何教育、升学或职业建议。
2. AI 生成内容可能存在滞后、偏差或错误，请务必在**阳光高考平台**等官方渠道二次核验后再填报。
3. 任何基于本项目结果做出的决策与后果，由使用者独立判断并承担。
4. 本项目与张雪峰老师本人及其公司无任何官方关联，所有内容仅为致敬。
5. 第三方数据源（百度掌上高考、掌上高考 API 等）的准确性与时效性由对应来源负责。

---

*愿认真、坦诚、敢说真话的教育精神被继续传承。*
