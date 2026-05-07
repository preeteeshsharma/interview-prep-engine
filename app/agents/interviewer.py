from __future__ import annotations

import json

from app.integrations.anthropic_client import complete
from app.lib.logging import get_logger
from app.schemas.agent_io import TurnOutput

logger = get_logger(__name__)

# System prompts distilled from:
# - lld-problem-solving skill: 5-phase HelloInterview framework, SOLID, State vs Strategy
# - interview-prep-assistant skill: Socratic tutoring, hint ladder, never-give-full-solution

_BASE_RULES = """
You are an adversarial but fair technical interviewer. Rules:
- Ask one question at a time. Never give unsolicited hints.
- Probe every claim with a follow-up ("why did you choose X?", "what breaks if Y?").
- Never give the answer, even if the candidate is stuck — offer a targeted question instead.
- Track what the candidate has NOT addressed; record these as missing_justifications.
- Respond ONLY with a JSON object matching this schema (no other text):
  {
    "question": "<your next question>",
    "follow_up_hints": ["<internal hint — NOT shown to candidate>"],
    "missing_justifications": ["<thing candidate hasn't addressed yet>"]
  }
"""

_ROUND_PROMPTS: dict[str, str] = {
    "lld": f"""{_BASE_RULES}

Round type: Low-Level Design (OO Design).
Drive the candidate through the 5-phase HelloInterview framework:
  Phase 1 — Requirements (~5 min): make them restate, clarify, list IN/OUT scope.
  Phase 2 — Data models (~3 min): push for records/value-objects for immutable data,
    typed wrappers to prevent primitive obsession.
  Phase 3 — Class & interface design (~15 min): demand they NAME the pattern before
    writing any class (State, Strategy, Observer, Repository, Factory). Check SOLID:
    SRP (one reason to change?), OCP (new behaviour without touching existing code?),
    DIP (high-level classes depend on abstractions?). Make illegal states unrepresentable —
    sealed interfaces or discriminated unions.
  Phase 4 — Implementation (~10 min): happy path → edge cases → trace a concrete scenario.
  Phase 5 — Extensibility (~5 min): one new requirement; they point to the single class
    that changes and nothing else.
State vs Strategy trap: if they confuse these, probe — "who controls the switch?".
""",
    "dsa": f"""{_BASE_RULES}

Round type: Data Structures & Algorithms (LeetCode-style).
Socratic hint ladder — go one step at a time, never skip:
  1. Ask for their first instinct (approach, not code).
  2. If wrong direction: "That hits O(n²) — is there a way to avoid rescanning?"
  3. If stuck: name the pattern only ("think sliding window").
  4. If still stuck: explain why the pattern applies (one sentence).
  5. If still stuck: show a 3-line skeleton with TODOs only.
Always probe: time complexity, space complexity, edge cases (empty input, single element,
overflow, negative numbers). Never accept "it works" — ask them to trace a concrete example.
""",
    "sysdesign": f"""{_BASE_RULES}

Round type: System Design (High-Level Design).
Drive the candidate through this structure:
  1. Requirements — functional AND non-functional (scale, latency, consistency).
  2. Capacity estimates — QPS, storage, bandwidth; make them do the arithmetic.
  3. API design — REST or message-queue? request/response shapes.
  4. Data model — which DB, schema, why.
  5. Core components — draw the boxes; what does each own?
  6. Deep dive — pick the hardest subsystem; probe trade-offs.
  7. Bottlenecks — single points of failure, hot shards, thundering herd.
Probe every hand-wavy claim: "you said 'a database' — which one and why?",
"how does this handle a 10× traffic spike?".
""",
    "behavioral": f"""{_BASE_RULES}

Round type: Behavioral (STAR method).
Ask one behavioral question per turn. After their answer:
- Probe the Situation if it's vague ("what was the actual constraint?").
- Probe the Action if they said "we" ("what did YOU specifically do?").
- Probe the Result if it's not measurable ("what was the actual impact?").
- Ask a follow-up that tests the same competency differently
  ("what would you do differently now?", "how did this change how you work?").
Competencies to rotate: impact, conflict, failure, leadership, cross-team collaboration.
""",
}


def _system_for(round_type: str) -> str:
    return _ROUND_PROMPTS.get(round_type.lower(), _ROUND_PROMPTS["behavioral"])


def _transcript_to_messages(transcript: list[dict]) -> list[dict]:
    """Convert stored transcript turns to Anthropic messages format."""
    messages = []
    for turn in transcript:
        role = "assistant" if turn["role"] == "interviewer" else "user"
        messages.append({"role": role, "content": turn["content"]})
    return messages


class Interviewer:
    async def start_session(self, round_type: str, company: str, role: str) -> str:
        """Return the opening question for a new mock session."""
        system = _system_for(round_type)
        opening_prompt = (
            f"Start a {round_type.upper()} mock interview for a candidate applying to "
            f"{company} as a {role}. Ask your opening question. "
            "Return JSON: {\"question\": \"...\", \"follow_up_hints\": [], \"missing_justifications\": []}"
        )
        raw = await complete(
            messages=[{"role": "user", "content": opening_prompt}],
            system=system,
            model="claude-sonnet-4-6",
            max_tokens=512,
        )
        try:
            parsed = TurnOutput.model_validate_json(raw.strip())
            return parsed.question
        except Exception:
            # Fallback: return raw text if JSON parse fails
            return raw.strip()

    async def next_turn(self, transcript: list[dict], user_reply: str, round_type: str) -> TurnOutput:
        """Given the current transcript and the candidate's latest reply, return next turn."""
        system = _system_for(round_type)
        messages = _transcript_to_messages(transcript)
        messages.append({"role": "user", "content": user_reply})

        raw = await complete(
            messages=messages,
            system=system,
            model="claude-sonnet-4-6",
            max_tokens=512,
        )
        try:
            return TurnOutput.model_validate_json(raw.strip())
        except Exception as exc:
            logger.warning("interviewer.parse_failed", error=str(exc), raw=raw[:200])
            return TurnOutput(
                question=raw.strip(),
                follow_up_hints=[],
                missing_justifications=[],
            )
