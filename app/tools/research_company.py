from __future__ import annotations

import asyncio

from app.integrations.search.factory import get_search_provider
from app.integrations.search.base import SearchResult
from app.lib.logging import get_logger

logger = get_logger(__name__)

_provider = get_search_provider()


async def research_company(company: str, role: str) -> str:
    """Run parallel searches and return a combined context string for plan generation."""
    queries = [
        f"{company} {role} interview experience 2025",
        f"{company} {role} interview questions LeetCode Blind",
        f"{company} {role} system design interview 2024 2025",
    ]

    results: list[SearchResult] = await asyncio.gather(
        *[_provider.search(q, max_results=4) for q in queries],
        return_exceptions=True,
    )

    sections = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("research_company.search_failed", error=str(result), exc_info=True)
            continue
        sections.append(result.as_context())

    if not sections:
        logger.warning("research_company.all_searches_failed", company=company, role=role)
        return ""

    combined = "\n\n---\n\n".join(sections)
    logger.info("research_company.done", company=company, role=role, sections=len(sections))
    return combined
