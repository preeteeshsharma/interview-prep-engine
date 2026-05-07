from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.integrations.anthropic_client import complete
from app.lib.json_utils import strip_fences
from app.lib.logging import get_logger
from app.schemas.domain import RoundType
from typing import get_args

logger = get_logger(__name__)

_VALID_ROUNDS = set(get_args(RoundType))

_SYSTEM = f"""Today is {{today}}.

Extract interview prep details from the user message. Return ONLY valid JSON:
{{
  "company": "<company name or null>",
  "role": "<role/level or null>",
  "interview_date": "<YYYY-MM-DD or null>",
  "days_until_interview": <integer or null>,
  "rounds": [<list from: dsa, lld, sysdesign, behavioral, hiring_manager> or null]
}}

Rules:
- company: proper noun, first clear entity mentioned
- role: job title/level (e.g. "senior backend engineer", "L5 SWE", "software engineer")
- interview_date: parse natural dates like "june 15", "15th june", "next monday" relative to today
- days_until_interview: compute from today to interview_date if date is given, else null
- rounds: only include if explicitly mentioned; null if not mentioned
- Return null for any field not mentioned or unclear
"""


@dataclass
class PrepIntent:
    company: str | None = None
    role: str | None = None
    interview_date: str | None = None
    days_until_interview: int | None = None
    rounds: list[str] | None = None

    def missing(self) -> list[str]:
        gaps = []
        if not self.role:
            gaps.append("role (e.g. 'senior backend', 'L5 SWE')")
        if not self.interview_date:
            gaps.append("interview date (e.g. 'june 15')")
        if not self.rounds:
            gaps.append("rounds (dsa / lld / sysdesign / behavioral / hiring_manager)")
        return gaps

    def with_defaults(self) -> "PrepIntent":
        return PrepIntent(
            company=self.company,
            role=self.role or "software engineer",
            interview_date=self.interview_date,
            days_until_interview=self.days_until_interview or 7,
            rounds=self.rounds or ["dsa", "lld", "sysdesign", "behavioral"],
        )

    def merge(self, other: "PrepIntent") -> "PrepIntent":
        """Merge a follow-up parse into existing partial intent."""
        return PrepIntent(
            company=self.company or other.company,
            role=self.role or other.role,
            interview_date=self.interview_date or other.interview_date,
            days_until_interview=self.days_until_interview or other.days_until_interview,
            rounds=self.rounds or other.rounds,
        )

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "role": self.role,
            "interview_date": self.interview_date,
            "days_until_interview": self.days_until_interview,
            "rounds": self.rounds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PrepIntent":
        return cls(
            company=d.get("company"),
            role=d.get("role"),
            interview_date=d.get("interview_date"),
            days_until_interview=d.get("days_until_interview"),
            rounds=d.get("rounds"),
        )


async def parse_prep_intent(message: str) -> PrepIntent:
    """Use Claude to extract structured prep intent from a natural language message."""
    system = _SYSTEM.replace("{today}", date.today().isoformat())
    try:
        raw = await complete(
            messages=[{"role": "user", "content": message}],
            system=system,
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
        )
        data = json.loads(strip_fences(raw))
        rounds = data.get("rounds")
        if rounds:
            rounds = [r for r in rounds if r in _VALID_ROUNDS]
        return PrepIntent(
            company=data.get("company"),
            role=data.get("role"),
            interview_date=data.get("interview_date"),
            days_until_interview=data.get("days_until_interview"),
            rounds=rounds or None,
        )
    except Exception as exc:
        logger.warning("parse_prep_intent.failed", error=str(exc), message=message, exc_info=True)
        return PrepIntent()
