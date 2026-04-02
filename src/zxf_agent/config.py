from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_name: str = "zxf-agent"
    database_url: str = "sqlite:///./zxf_agent.db"

    # LLM provider 可选值:
    #   mock                — 无需 key，本地规则回复
    #   anthropic           — Claude API（claude-sonnet-4-5 等）
    #   openai-compatible   — DeepSeek / Qwen / Doubao / OpenAI 等
    llm_provider: str = "mock"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"  # anthropic provider 时此项忽略

    # 搜索 provider 可选值:
    #   none        — 不搜索，走 mock 降级
    #   duckduckgo  — 完全免费，无需 key，质量一般
    #   serper      — 2500次免费额度，Google 结果，中文质量最好
    #   tavily      — 1000次/月免费
    web_search_provider: str = "none"  # none | serper | tavily
    serper_api_key: str = ""
    tavily_api_key: str = ""

    # 搜索缓存有效期（天）
    search_cache_ttl_days: int = 180

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
