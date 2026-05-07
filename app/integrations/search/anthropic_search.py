from __future__ import annotations

import anthropic

from app.integrations.search.base import SearchHit, SearchResult
from app.lib.logging import get_logger

logger = get_logger(__name__)


class AnthropicSearchProvider:
    """Uses Anthropic's native web_search tool as a search backend."""

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search for: {query}\n\n"
                    f"Return the top {max_results} results as a numbered list with: "
                    "title, URL, date (if available), and a 2-3 sentence summary of the content."
                ),
            }],
        )
        # Extract text from final response
        text = next(
            (b.text for b in response.content if hasattr(b, "text")),
            "",
        )
        # Wrap the synthesized text as a single hit — Anthropic returns prose, not structured results
        hits = [SearchHit(title=f"Anthropic web search: {query}", url="", content=text)]
        logger.info("anthropic_search.done", query=query)
        return SearchResult(query=query, hits=hits, source="anthropic")
