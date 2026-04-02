from __future__ import annotations

import httpx

from zxf_agent.config import settings


async def search(query: str, max_results: int = 3) -> list[dict]:
    """
    统一搜索入口。
    provider 优先级：serper > tavily > none
    """
    provider = settings.web_search_provider.lower().strip()

    if provider == "serper" and settings.serper_api_key:
        return await _serper(query, max_results)
    if provider == "tavily" and settings.tavily_api_key:
        return await _tavily(query, max_results)
    return []


async def _serper(query: str, max_results: int) -> list[dict]:
    """
    Serper.dev — Google 搜索结果，中文覆盖最好。
    免费 2500 次，无需信用卡：https://serper.dev/signup
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": settings.serper_api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": max_results, "gl": "cn", "hl": "zh-cn"},
        )
        resp.raise_for_status()
        items = resp.json().get("organic", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
            }
            for r in items[:max_results]
        ]


async def _tavily(query: str, max_results: int) -> list[dict]:
    """Tavily — 1000 次/月免费：https://tavily.com"""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in results[:max_results]
        ]
