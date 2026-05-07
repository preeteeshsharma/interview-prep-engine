from __future__ import annotations

import httpx

from app.integrations.search.base import SearchHit, SearchResult
from app.lib.logging import get_logger

logger = get_logger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


class TavilySearchProvider:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_raw_content": False,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_TAVILY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        hits = [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                published_date=r.get("published_date", ""),
            )
            for r in data.get("results", [])
        ]
        logger.info("tavily.search.done", query=query, hits=len(hits))
        return SearchResult(query=query, hits=hits, source="tavily")
