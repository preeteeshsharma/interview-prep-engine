import json
from typing import get_args

from app.integrations.anthropic_client import complete
from app.lib.logging import get_logger
from app.schemas.domain import RoundType

logger = get_logger(__name__)

# Distilled from interview-research skill: round identification logic.
# The skill searches Blind/Glassdoor/Reddit for real interview data; here we
# classify from the JD text directly using the same taxonomy.
_SYSTEM = """You analyze job descriptions and extract the interview round types a candidate will face.

Valid round types (return the exact strings below):
  "DSA"            — data structures and algorithms / coding screens (LeetCode-style)
  "LLD"            — low-level design / OO design (design a music player, parking lot, etc.)
  "sysdesign"      — system design / high-level design (design Twitter, Uber, etc.)
  "behavioral"     — behavioral / STAR / culture-fit / values rounds
  "hiring_manager" — hiring-manager round (relationship-building, not purely technical)
  "unknown"        — any round that clearly doesn't fit the above

Rules:
- Read both explicit signals ("coding round", "system design interview") and implicit ones
  ("strong CS fundamentals" → DSA; "design complex distributed systems" → sysdesign;
   "culture add" → behavioral; "meet the team lead" → hiring_manager)
- Only include types that are strongly indicated — do not guess
- Include each type at most once
- Output ONLY a JSON array of strings, no other text

Examples:
  JD: "Strong CS fundamentals. Rounds: phone screen, system design, behavioral."
  Output: ["DSA", "sysdesign", "behavioral"]

  JD: "Backend engineer. Rounds: two coding rounds, one low-level design, hiring manager."
  Output: ["DSA", "LLD", "hiring_manager"]

  JD: "Senior SWE. Four rounds: 2 coding, 1 system design, 1 culture fit."
  Output: ["DSA", "sysdesign", "behavioral"]
"""

_VALID: set[str] = set(get_args(RoundType))


async def classify_rounds(jd_text: str) -> list[str]:
    """Return a list of RoundType strings extracted from a job description."""
    raw = await complete(
        messages=[{"role": "user", "content": f"Job description:\n\n{jd_text}"}],
        system=_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=128,
    )
    try:
        parsed = json.loads(raw.strip())
        if not isinstance(parsed, list):
            raise ValueError("expected list")
        rounds = [r for r in parsed if r in _VALID]
        if not rounds:
            rounds = ["unknown"]
    except Exception as exc:
        logger.warning("classify_rounds.parse_failed", raw=raw[:200], error=str(exc))
        rounds = ["unknown"]

    logger.info("classify_rounds.done", rounds=rounds)
    return rounds
