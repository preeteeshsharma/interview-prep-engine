from __future__ import annotations

from app.integrations.search.base import SearchProvider, SearchResult
from app.lib.logging import get_logger

logger = get_logger(__name__)


class FallbackSearchProvider:
    """Tries primary; falls back to secondary on any exception."""

    def __init__(self, primary: SearchProvider, fallback: SearchProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        try:
            return await self._primary.search(query, max_results)
        except Exception as exc:
            logger.warning("search.primary_failed", error=str(exc), exc_info=True)
            return await self._fallback.search(query, max_results)


def get_search_provider() -> SearchProvider:
    from app.config import settings
    from app.integrations.search.anthropic_search import AnthropicSearchProvider
    from app.integrations.search.tavily import TavilySearchProvider

    anthropic_provider = AnthropicSearchProvider(api_key=settings.anthropic_api_key)

    if settings.tavily_api_key:
        return FallbackSearchProvider(
            primary=TavilySearchProvider(api_key=settings.tavily_api_key),
            fallback=anthropic_provider,
        )
    return anthropic_provider
