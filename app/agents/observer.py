from __future__ import annotations

import json

from app.integrations.llm_client import complete
from app.lib.json_utils import strip_fences
from app.lib.logging import get_logger
from app.schemas.agent_io import RubricScore

logger = get_logger(__name__)

_SYSTEM = """You are a silent observer scoring a mock technical interview transcript.
Score the candidate (NOT the interviewer) on five dimensions, each 1–5:

  depth          — technical depth and accuracy of answers
  clarity        — structure and communication quality
  edge_cases     — whether they proactively raised edge cases and constraints
  time_management — pacing; did they stay on track without rushing or stalling?
  requirements   — did they clarify and respect the stated requirements?

Scoring guide: 1 = poor, 2 = below average, 3 = adequate, 4 = good, 5 = excellent.

Respond ONLY with a JSON object (no other text):
{
  "depth": <1-5>,
  "clarity": <1-5>,
  "edge_cases": <1-5>,
  "time_management": <1-5>,
  "requirements": <1-5>
}
"""


class Observer:
    async def score(self, transcript: list[dict]) -> RubricScore:
        """Score the candidate's performance from the transcript so far."""
        if not transcript:
            return RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)

        formatted = "\n".join(
            f"[{t['role'].upper()} turn {t['turn']}]: {t['content']}"
            for t in transcript
        )
        raw = await complete(
            messages=[{"role": "user", "content": f"Transcript:\n\n{formatted}"}],
            system=_SYSTEM,
            model="claude-haiku-4-5-20251001",  # cheaper — rubric scoring is a smaller task
            max_tokens=128,
        )
        try:
            return RubricScore.model_validate_json(strip_fences(raw))
        except Exception as exc:
            logger.warning("observer.parse_failed", error=str(exc), raw=raw[:200], exc_info=True)
            return RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)
