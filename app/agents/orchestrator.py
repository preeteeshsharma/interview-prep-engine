from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from app.agents.coach import Coach
from app.agents.interviewer import Interviewer
from app.agents.observer import Observer
from app.db.models import MockSession
from app.db.repos.mock_sessions import MockSessionRepository
from app.db.repos.weak_patterns import WeakPatternRepository
from app.db.session import async_session_factory
from app.integrations.github_client import commit_file
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.schemas.agent_io import Critique, RubricScore

logger = get_logger(__name__)

_interviewer = Interviewer()
_observer = Observer()
_coach = Coach()

# V1: single-user — active session is the latest open MockSession.
# Production: add sender_e164 column to MockSession for multi-user support.


async def _load_session(session_id: int) -> MockSession:
    async with async_session_factory() as session:
        result = await session.execute(
            select(MockSession).where(MockSession.id == session_id)
        )
        mock = result.scalar_one()
        # Detach from session before returning
        session.expunge(mock)
        return mock


async def _get_transcript(session_id: int) -> list[dict]:
    mock = await _load_session(session_id)
    if not mock.transcript_json:
        return []
    return json.loads(mock.transcript_json)


async def _save_transcript(session_id: int, transcript: list[dict]) -> None:
    async with async_session_factory() as session:
        await MockSessionRepository(session).update_transcript(
            id=session_id,
            transcript_json=json.dumps(transcript),
        )


class MockOrchestrator:
    async def start(self, session_id: int, round_type: str, company: str, role: str) -> str:
        """Called once when a mock session begins. Returns the opening question."""
        opening = await _interviewer.start_session(round_type, company, role)
        transcript = [{"role": "interviewer", "content": opening, "turn": 0}]
        await _save_transcript(session_id, transcript)
        logger.info("orchestrator.session.started", session_id=session_id, round_type=round_type)
        return opening

    async def run_turn(self, session_id: int, user_message: str) -> str:
        """Process one candidate turn. Returns the next interviewer question.

        Runs Interviewer.next_turn() and Observer.score() in parallel via asyncio.gather.
        Observer never blocks user-visible latency — its result is persisted silently.
        """
        transcript = await _get_transcript(session_id)
        mock = await _load_session(session_id)
        round_type = mock.round_type

        # Append candidate's reply before scoring / generating next question.
        candidate_turn = {
            "role": "candidate",
            "content": user_message,
            "turn": len(transcript),
        }
        transcript.append(candidate_turn)

        # Interviewer and Observer run in parallel.
        # return_exceptions=True so Observer failure never kills the user's turn.
        turn_result, rubric_result = await asyncio.gather(
            _interviewer.next_turn(transcript, round_type),
            _observer.score(transcript),
            return_exceptions=True,
        )
        if isinstance(turn_result, Exception):
            raise turn_result
        turn_output = turn_result
        rubric = (
            rubric_result
            if not isinstance(rubric_result, Exception)
            else RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)
        )
        if isinstance(rubric_result, Exception):
            logger.warning("orchestrator.observer_failed", error=str(rubric_result), exc_info=True)

        # Append interviewer's next question.
        interviewer_turn = {
            "role": "interviewer",
            "content": turn_output.question,
            "turn": len(transcript),
        }
        transcript.append(interviewer_turn)

        await _save_transcript(session_id, transcript)

        # Persist latest rubric into session (overwrite — we keep the most recent).
        async with async_session_factory() as session:
            result = await session.execute(
                select(MockSession).where(MockSession.id == session_id)
            )
            mock_row = result.scalar_one()
            mock_row.rubric_json = rubric.model_dump_json()
            await session.commit()

        logger.info(
            "orchestrator.turn.done",
            session_id=session_id,
            turn=len(transcript),
            rubric=rubric.model_dump(),
        )
        return turn_output.question

    async def end_session(self, session_id: int) -> str:
        """End the session: run Coach (post-session), persist, update weak_patterns.

        Coach runs serially after the session — it needs the full transcript.
        Returns a formatted summary to send to the user.
        """
        transcript = await _get_transcript(session_id)
        if not transcript:
            return "No transcript found for this session."

        # Load latest rubric (accumulated from run_turn calls).
        mock = await _load_session(session_id)
        rubric = (
            RubricScore.model_validate_json(mock.rubric_json)
            if mock.rubric_json
            else RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)
        )

        try:
            critique = await _coach.critique(transcript, rubric)
        except Exception as exc:
            logger.error("orchestrator.coach_failed", session_id=session_id, error=str(exc), exc_info=True)
            critique = Critique(entries=[], overall_summary="Critique unavailable.")

        async with async_session_factory() as session:
            await MockSessionRepository(session).finalize(
                id=session_id,
                rubric_json=rubric.model_dump_json(),
                critique_json=critique.model_dump_json(),
            )

        # Bump weak_patterns for each critique entry.
        async with async_session_factory() as session:
            wp_repo = WeakPatternRepository(session)
            for entry in critique.entries:
                await wp_repo.upsert(
                    pattern=entry.issue[:120],
                    weight_bump=1.0,
                    session_id=session_id,
                )

        # Commit transcript + critique to prep-vault.
        vault_content = _format_vault_entry(transcript, rubric, critique)
        try:
            # V2: pass sender_phone into end_session() and derive ctx from it.
            ctx = await get_user_context()
            await commit_file(
                path=f"mocks/session-{session_id}.md",
                content=vault_content,
                message=f"mock: session #{session_id} — {mock.round_type}",
                github_token=ctx.github_token,
                vault_repo=ctx.vault_repo,
            )
        except Exception as exc:
            logger.warning("orchestrator.vault_commit_failed", path=f"mocks/session-{session_id}.md", error=str(exc), exc_info=True)

        logger.info("orchestrator.session.ended", session_id=session_id)
        return _format_summary(rubric, critique)


def _format_summary(rubric: RubricScore, critique: Critique) -> str:
    score = rubric.total()
    lines = [
        f"Session complete. Score: {score}/25",
        f"  depth:{rubric.depth} clarity:{rubric.clarity} edges:{rubric.edge_cases} "
        f"time:{rubric.time_management} reqs:{rubric.requirements}",
        "",
        critique.overall_summary,
    ]
    if critique.entries:
        lines.append("\nTop feedback:")
        for e in critique.entries[:3]:
            lines.append(f"  • {e.issue}")
            lines.append(f"    → {e.suggestion}")
    lines.append("\nFull transcript in prep-vault.")
    return "\n".join(lines)


def _format_vault_entry(transcript: list[dict], rubric: RubricScore, critique: Critique) -> str:
    turns = "\n\n".join(
        f"**[Turn {t['turn']} — {t['role'].upper()}]**\n{t['content']}"
        for t in transcript
    )
    entries = "\n".join(
        f"- Turn {e.quote_offset}: {e.issue}\n  → {e.suggestion}"
        for e in critique.entries
    )
    return f"""# Mock Session Transcript

## Rubric
| Dimension | Score |
|---|---|
| Depth | {rubric.depth}/5 |
| Clarity | {rubric.clarity}/5 |
| Edge cases | {rubric.edge_cases}/5 |
| Time management | {rubric.time_management}/5 |
| Requirements | {rubric.requirements}/5 |

## Coach Summary
{critique.overall_summary}

## Feedback
{entries or "No specific feedback entries."}

---

## Transcript
{turns}
"""
