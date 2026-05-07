from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SearchHit:
    title: str
    url: str
    content: str
    published_date: str = ""


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    source: str = ""

    def as_context(self) -> str:
        """Format search results as a readable context block for LLM prompts."""
        if not self.hits:
            return "No search results found."
        parts = [f"[Source: {self.source}] Search results for: {self.query}\n"]
        for i, hit in enumerate(self.hits, 1):
            date = f" ({hit.published_date})" if hit.published_date else ""
            parts.append(f"{i}. {hit.title}{date}\n   {hit.url}\n   {hit.content}\n")
        return "\n".join(parts)


@runtime_checkable
class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> SearchResult: ...
