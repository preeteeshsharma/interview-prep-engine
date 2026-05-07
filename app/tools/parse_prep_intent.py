from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.integrations.llm_client import complete
from app.lib.json_utils import strip_fences
from app.lib.logging import get_logger
from app.schemas.domain import RoundType
from typing import get_args

logger = get_logger(__name__)

_VALID_ROUNDS = set(get_args(RoundType))

# Python-side alias map — applied after LLM parse as a reliable fallback.
# Keys are lowercase substrings; value is the canonical round type.
_ROUND_ALIAS_MAP: list[tuple[str, str]] = [
    ("coding ability and problem solving", "dsa"),
    ("coding ability", "dsa"),
    ("problem solving", "dsa"),
    ("data structures", "dsa"),
    ("algorithms", "dsa"),
    ("technical screen", "dsa"),
    ("coding round", "dsa"),
    ("coding interview", "dsa"),
    ("leetcode", "dsa"),
    ("low level design", "lld"),
    ("object oriented design", "lld"),
    ("oo design", "lld"),
    ("machine coding", "lld"),
    ("object design", "lld"),
    ("system design", "sysdesign"),
    ("high level design", "sysdesign"),
    ("architecture round", "sysdesign"),
    ("design round", "sysdesign"),
    ("behavioural", "behavioral"),
    ("culture fit", "behavioral"),
    ("bar raiser", "behavioral"),
    ("hr round", "behavioral"),
    ("hiring manager", "hiring_manager"),
    ("manager round", "hiring_manager"),
    ("leadership round", "hiring_manager"),
    ("hm round", "hiring_manager"),
]


def _map_label_to_round(label: str) -> str | None:
    """Map a free-form round label to a canonical RoundType."""
    lower = label.lower()
    # Exact canonical match first
    if lower in _VALID_ROUNDS:
        return lower
    # Substring alias matching (longest alias wins via list order)
    for alias, canonical in _ROUND_ALIAS_MAP:
        if alias in lower:
            return canonical
    return None

_SYSTEM = """Today is {today}.

Extract interview prep details from the user message. Return ONLY valid JSON:
{
  "company": "<company name or null>",
  "role": "<role/level or null>",
  "interview_date": "<YYYY-MM-DD or null>",
  "days_until_interview": <integer or null>,
  "rounds": [<canonical list — see mapping below> or null],
  "round_labels": [<original round names as written by user> or null]
}

Round mapping — map any mention to the canonical type:
- dsa: "dsa", "coding", "algorithms", "data structures", "problem solving",
        "coding ability", "coding ability and problem solving", "leetcode",
        "technical screen", "coding round", "coding interview"
- lld: "lld", "low level design", "object oriented design", "oo design",
        "machine coding", "object design"
- sysdesign: "sysdesign", "system design", "hld", "high level design",
              "architecture", "design round"
- behavioral: "behavioral", "behavioural", "values", "hr round", "culture fit",
               "people skills", "bar raiser"
- hiring_manager: "hiring manager", "hm round", "manager round", "leadership round"

Rules:
- company: proper noun, first clear entity mentioned
- role: job title/level (e.g. "senior backend engineer", "L5 SWE", "software engineer")
- interview_date: parse natural dates like "june 15", "15th june", "next monday" relative to today
- days_until_interview: compute from today to interview_date if date is given, else null
- rounds: canonical types only, using the mapping above; null if no round mentioned
- round_labels: the original words the user used to describe the rounds (e.g. "Coding Ability and Problem Solving"); null if no round mentioned
- Return null for any field not mentioned or unclear
"""


@dataclass
class PrepIntent:
    company: str | None = None
    role: str | None = None
    interview_date: str | None = None
    days_until_interview: int | None = None
    rounds: list[str] | None = None
    round_labels: list[str] | None = None  # original round names from the invite

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
            round_labels=self.round_labels,
        )

    def merge(self, other: "PrepIntent") -> "PrepIntent":
        """Merge a follow-up parse into existing partial intent."""
        return PrepIntent(
            company=self.company or other.company,
            role=self.role or other.role,
            interview_date=self.interview_date or other.interview_date,
            days_until_interview=self.days_until_interview or other.days_until_interview,
            rounds=self.rounds or other.rounds,
            round_labels=self.round_labels or other.round_labels,
        )

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "role": self.role,
            "interview_date": self.interview_date,
            "days_until_interview": self.days_until_interview,
            "rounds": self.rounds,
            "round_labels": self.round_labels,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PrepIntent":
        return cls(
            company=d.get("company"),
            role=d.get("role"),
            interview_date=d.get("interview_date"),
            days_until_interview=d.get("days_until_interview"),
            rounds=d.get("rounds"),
            round_labels=d.get("round_labels"),
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
        round_labels = data.get("round_labels") or None

        # Filter LLM-produced rounds to valid canonical types
        if rounds:
            rounds = [r for r in rounds if r in _VALID_ROUNDS]

        # Fallback: if LLM didn't produce canonical rounds, try mapping from labels
        # Also catches cases where the user typed the label directly in the message
        if not rounds:
            labels_to_map = round_labels or []
            # Also try mapping raw words from the original message
            mapped = [_map_label_to_round(l) for l in labels_to_map]
            if not any(mapped):
                mapped = [_map_label_to_round(message)]
            rounds = list(dict.fromkeys(r for r in mapped if r)) or None

        return PrepIntent(
            company=data.get("company"),
            role=data.get("role"),
            interview_date=data.get("interview_date"),
            days_until_interview=data.get("days_until_interview"),
            rounds=rounds or None,
            round_labels=round_labels,
        )
    except Exception as exc:
        logger.warning("parse_prep_intent.failed", error=str(exc), message=message, exc_info=True)
        return PrepIntent()
