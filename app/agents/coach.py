from __future__ import annotations

import json

from pydantic import ValidationError

from app.integrations.anthropic_client import complete
from app.lib.logging import get_logger
from app.schemas.agent_io import Critique, CritiqueEntry, RubricScore

logger = get_logger(__name__)

_SYSTEM = """You are a post-interview coach reviewing a completed mock interview transcript.
Your job: give the candidate targeted, actionable feedback grounded in specific transcript moments.

Rules:
- Every entry in "entries" MUST cite a real transcript turn via quote_offset (0-indexed integer).
  quote_offset refers to the turn index in the transcript array.
  Do NOT fabricate or paraphrase — cite the actual turn where the issue occurred.
- Each issue must have a concrete suggestion, not "do better" or "be more specific".
- Keep overall_summary to 3 sentences max.

Respond ONLY with a JSON object (no other text):
{
  "entries": [
    {"quote_offset": <int>, "issue": "<what went wrong>", "suggestion": "<specific fix>"},
    ...
  ],
  "overall_summary": "<3 sentence summary>"
}
"""

_MAX_RETRIES = 2


class Coach:
    async def critique(self, transcript: list[dict], rubric: RubricScore) -> Critique:
        """Generate a grounded critique. Validates quote_offsets; retries once if invalid."""
        transcript_len = len(transcript)
        formatted = "\n".join(
            f"[turn {t['turn']}] {t['role'].upper()}: {t['content']}"
            for t in transcript
        )
        rubric_summary = (
            f"Rubric scores — depth:{rubric.depth} clarity:{rubric.clarity} "
            f"edge_cases:{rubric.edge_cases} time_management:{rubric.time_management} "
            f"requirements:{rubric.requirements}"
        )
        user_msg = f"{rubric_summary}\n\nTranscript ({transcript_len} turns):\n\n{formatted}"

        error_context = ""
        for attempt in range(_MAX_RETRIES):
            prompt = user_msg if not error_context else f"{user_msg}\n\nPrevious attempt was rejected: {error_context}"
            raw = await complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                model="claude-sonnet-4-6",
                max_tokens=1024,
            )
            try:
                parsed = json.loads(raw.strip())
                entries_raw = parsed.get("entries", [])
                # Validate every quote_offset is a real transcript index.
                valid_entries = []
                invalid = []
                for e in entries_raw:
                    offset = e.get("quote_offset", -1)
                    if isinstance(offset, int) and 0 <= offset < transcript_len:
                        valid_entries.append(CritiqueEntry.model_validate(e))
                    else:
                        invalid.append(offset)

                if invalid and attempt < _MAX_RETRIES - 1:
                    error_context = (
                        f"Invalid quote_offsets: {invalid}. "
                        f"Transcript has {transcript_len} turns (valid offsets: 0–{transcript_len - 1})."
                    )
                    logger.warning("coach.invalid_offsets", invalid=invalid, attempt=attempt)
                    continue

                return Critique(
                    entries=valid_entries,
                    overall_summary=parsed.get("overall_summary", ""),
                )
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                logger.warning("coach.parse_failed", error=str(exc), raw=raw[:200], exc_info=True)
                if attempt < _MAX_RETRIES - 1:
                    error_context = f"JSON parse failed: {exc}"
                    continue

        # Exhausted retries — return empty critique rather than crashing.
        logger.error("coach.retries_exhausted", transcript_len=transcript_len)
        return Critique(entries=[], overall_summary="Coach could not generate a valid critique.")
