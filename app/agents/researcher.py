from __future__ import annotations

from pathlib import Path

from app.integrations.llm_client import complete_with_tools
from app.lib.logging import get_logger

logger = get_logger(__name__)

_SKILL = (Path(__file__).parent.parent / "skills" / "interview_research.md").read_text()

_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


async def research(
    company: str,
    role: str,
    round_type: str | None = None,
    round_label: str | None = None,
) -> str:
    """Run interview-research skill with live web search.

    Returns a fully sourced, cited research report in the skill's output format.
    round_type=None → full process research; round_type="dsa" → questions-mode for that round.
    round_label: the original round name from the invite (e.g. "Coding Ability and Problem Solving")
                 — used in addition to the canonical type for better search coverage.
    """
    if round_type:
        label = round_label or round_type
        query = (
            f"Research {company} {role} interview questions — questions mode. "
            f"The round is called '{label}' (canonical type: {round_type})."
        )
    else:
        query = f"Research the {company} {role} interview process — process mode."

    logger.info("researcher.start", company=company, role=role, round_type=round_type)

    result = await complete_with_tools(
        messages=[{"role": "user", "content": query}],
        system=_SKILL,
        tools=[_WEB_SEARCH_TOOL],
        model="claude-sonnet-4-6",
        max_tokens=6000,
    )

    logger.info("researcher.done", company=company, role=role, chars=len(result))
    return result
