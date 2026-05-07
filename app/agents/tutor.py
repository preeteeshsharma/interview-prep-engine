from __future__ import annotations

import json
from pathlib import Path

from app.integrations.anthropic_client import complete
from app.lib.logging import get_logger

logger = get_logger(__name__)

_SKILL = (Path(__file__).parent.parent / "skills" / "interview_prep_assistant.md").read_text()


class Tutor:
    async def start_session(self, research_context: str) -> str:
        """Begin a study session. research_context is the full research report from vault.

        Returns the opening message — lists classified questions and asks which to start.
        """
        opening_prompt = (
            f"Here is the interview research for this session:\n\n"
            f"{research_context}"
        )
        return await complete(
            messages=[{"role": "user", "content": opening_prompt}],
            system=_SKILL,
            model="claude-sonnet-4-6",
            max_tokens=1024,
        )

    async def run_turn(self, transcript: list[dict], user_message: str) -> str:
        """Process one candidate turn in Socratic tutoring mode."""
        messages = _transcript_to_messages(transcript)
        messages.append({"role": "user", "content": user_message})
        return await complete(
            messages=messages,
            system=_SKILL,
            model="claude-sonnet-4-6",
            max_tokens=1024,
        )


def _transcript_to_messages(transcript: list[dict]) -> list[dict]:
    return [
        {"role": "assistant" if t["role"] == "tutor" else "user", "content": t["content"]}
        for t in transcript
    ]
