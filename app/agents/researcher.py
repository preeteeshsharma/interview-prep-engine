from __future__ import annotations

from pathlib import Path

from app.integrations.anthropic_client import complete_with_tools
from app.lib.logging import get_logger

logger = get_logger(__name__)

_SKILL = (Path(__file__).parent.parent / "skills" / "interview_research.md").read_text()

_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


async def research(company: str, role: str, round_type: str | None = None) -> str:
    """Run interview-research skill with live web search.

    Returns a fully sourced, cited research report in the skill's output format.
    round_type=None → full process research; round_type="dsa" → questions-mode for that round.
    """
    if round_type:
        query = (
            f"{company} {role} {round_type} interview questions 2024 2025 — "
            f"what questions were asked, confirmed from real candidates"
        )
    else:
        query = (
            f"{company} {role} interview process 2024 2025 — "
            f"full loop breakdown, all rounds, timeline, what each round tests"
        )

    logger.info("researcher.start", company=company, role=role, round_type=round_type)

    result = await complete_with_tools(
        messages=[{"role": "user", "content": query}],
        system=_SKILL,
        tools=[_WEB_SEARCH_TOOL],
        model="claude-sonnet-4-6",
        max_tokens=4096,
    )

    logger.info("researcher.done", company=company, role=role, chars=len(result))
    return result
