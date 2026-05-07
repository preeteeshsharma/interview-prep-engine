from __future__ import annotations

import asyncio
from typing import get_args

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import settings
from app.integrations.github_client import commit_file, load_vault_context, list_vault_rounds
from app.lib.user_context import get_user_context as _get_ctx
from sqlalchemy import select

from app.db.models import MockSession
from app.db.repos.interviews import InterviewRepository
from app.db.repos.mock_sessions import MockSessionRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.repos.wa_window import WaWindowRepository
from app.db.session import async_session_factory
from app.integrations.twilio_client import send_whatsapp
from app.lib.chunker import chunk_message
from app.lib.logging import get_logger
from app.schemas.domain import RoundType
from app.schemas.webhooks import TwilioInbound
from app.agents.orchestrator import MockOrchestrator
from app.agents.researcher import research as run_research
from app.agents.tutor import Tutor
from app.integrations.github_client import read_file
from app.lib.user_context import get_user_context
from app.tools.generate_plan import generate_plan
from app.tools.parse_prep_intent import PrepIntent, _map_label_to_round, parse_prep_intent
from app.tools.record_completion import record_completion
from app.tools.research_company import research_company

_orchestrator = MockOrchestrator()
_tutor = Tutor()


def _first_heading(plan_md: str) -> str | None:
    for line in plan_md.splitlines():
        if line.strip().startswith("### "):
            return line.strip().lstrip("# ").strip()
    return None

router = APIRouter()
logger = get_logger(__name__)

_HELP = (
    "Commands:\n"
    "  prep <company> — generate a prep plan\n"
    "  mock <round>   — start a mock (dsa/lld/sysdesign/behavioral)\n"
    "  done <rating>  — mark drill complete (easy/medium/hard)\n"
    "  status         — show active interviews"
)

# Derived from the domain's RoundType; exclude rounds with no mock handler.
_MOCK_ROUNDS: set[str] = {r.lower() for r in get_args(RoundType)} - {"hiring_manager", "unknown"}

# Strong references to in-flight background tasks — prevents GC before completion.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def _validate_twilio_signature(request: Request, params: dict) -> None:
    signature = request.headers.get("X-Twilio-Signature", "")
    # Fly.io terminates TLS and forwards as http:// internally.
    # Twilio signs with the public https:// URL, so we must reconstruct it.
    url = str(request.url).replace("http://", "https://", 1)
    if not RequestValidator(settings.twilio_auth_token).validate(url, params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ---------------------------------------------------------------------------
# Intent parsing
# ---------------------------------------------------------------------------

def _parse_intent(body: str) -> tuple[str, list[str]]:
    """Return (intent, args) from a WhatsApp message body."""
    parts = body.strip().split(maxsplit=1)
    if not parts:
        return "unknown", []
    verb = parts[0].lower()
    rest = parts[1].split() if len(parts) > 1 else []

    if verb == "prep":
        return "prep", rest
    if verb == "mock":
        return "mock", rest
    if verb == "done":
        return "done", rest
    if verb == "status":
        return "status", []
    if verb == "study":
        return "study", rest
    if verb == "link":
        return "link", rest  # V2: link <email> associates phone → User account
    return "freeform", parts  # treat entire body as freeform mock turn


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

async def _handle_prep(sender: str, args: list[str]) -> str:
    """Parse prep intent from args, ask for missing fields, or generate plan."""
    raw_message = " ".join(args) if args else ""
    if not raw_message:
        return (
            "Tell me about your interview:\n"
            "  e.g. prep Zapier senior backend, june 15, dsa lld\n"
            "  or just: prep Google"
        )

    intent = await parse_prep_intent(raw_message)

    gaps = intent.missing()
    if gaps:
        # Save partial intent so the follow-up can merge into it.
        async with async_session_factory() as session:
            await WaWindowRepository(session).set_pending_prep(sender, intent.to_dict())
        gap_str = "\n  • ".join(gaps)
        return f"Got it. Still need:\n  • {gap_str}\n\nReply with the missing details (I'll use defaults if you skip)."

    return await _execute_prep(sender, intent)


async def _handle_prep_followup(sender: str, pending: dict, body: str) -> str:
    """Merge follow-up message into pending intent, then proceed (with defaults)."""
    existing = PrepIntent.from_dict(pending)
    new_parse = await parse_prep_intent(body)
    merged = existing.merge(new_parse)

    async with async_session_factory() as session:
        await WaWindowRepository(session).clear_pending_prep(sender)

    # Apply defaults for anything still missing — never ask twice.
    final = merged.with_defaults()
    return await _execute_prep(sender, final)


async def _execute_prep(sender: str, intent: PrepIntent) -> str:
    """Generate research + plan for a fully-resolved PrepIntent.

    For multi-round prep (e.g. 'prep google dsa lld'), runs research once and
    creates one Interview + PrepPlan per round, all sharing the same vault content.
    """
    from datetime import datetime as _datetime, timezone as _tz

    final = intent.with_defaults()
    company = final.company or "Unknown"
    role = final.role
    round_types = final.rounds  # list, e.g. ["DSA", "LLD"]
    scheduled_for = None
    if final.interview_date:
        try:
            scheduled_for = _datetime.strptime(final.interview_date, "%Y-%m-%d").replace(
                tzinfo=_tz.utc
            )
        except ValueError:
            pass

    round_label = (final.round_labels or [None])[0]
    single_round_type = round_types[0] if len(round_types) == 1 else None

    # Find or create one Interview per round, check idempotency per round.
    interviews_to_run: list[tuple] = []  # (interview, round_type)
    for rt in round_types:
        async with async_session_factory() as session:
            match = await InterviewRepository(session).find_active_by_company_round(company, rt)

        if match:
            async with async_session_factory() as session:
                pending = await PrepPlanRepository(session).get_pending(match.id)
            date_changed = (
                final.interview_date
                and match.scheduled_for
                and match.scheduled_for.date().isoformat() != final.interview_date
            )
            if pending and not date_changed:
                if len(round_types) == 1:
                    return (
                        f"Active plan for {match.company} ({rt}) already exists.\n"
                        f"Send 'done {company.lower()} {rt.lower()} easy/medium/hard' to complete it."
                    )
                continue  # skip this round in multi-round; others may still need plans
            interviews_to_run.append((match, rt))
        else:
            async with async_session_factory() as session:
                new_interview = await InterviewRepository(session).create(
                    company=company, role=role, round_type=rt, scheduled_for=scheduled_for,
                )
            interviews_to_run.append((new_interview, rt))

    if not interviews_to_run:
        return f"All rounds for {company} already have active plans. Send 'done' when finished."

    # Research once for the company (covers all rounds).
    effective_role = interviews_to_run[0][0].role if interviews_to_run[0][0].role != "Unknown" else role
    research = await run_research(company, effective_role, round_type=single_round_type, round_label=round_label)
    plan_md = await generate_plan(
        interview_id=interviews_to_run[0][0].id,
        company=company,
        role=effective_role,
        round_types=round_types,
        research_context=research,
    )
    vault_path = await _commit_plan_to_vault(
        interviews_to_run[0][0].id, company, plan_md, research,
        round_label=round_label or single_round_type,
    )
    drill_label = _first_heading(plan_md)

    for interview, _ in interviews_to_run:
        async with async_session_factory() as session:
            await PrepPlanRepository(session).create(
                interview_id=interview.id,
                time_budget_min=120,
                vault_path=vault_path,
                drill_label=drill_label,
            )

    date_str = f" on {final.interview_date}" if final.interview_date else ""
    rounds_str = " + ".join(round_types)
    return f"Plan for {company} ({role}) — {rounds_str}{date_str}:\n\n{plan_md[:1200]}…\n\n(Full plan + sources in prep-vault)"


async def _commit_plan_to_vault(
    interview_id: int,
    company: str,
    plan_md: str,
    research: str = "",
    round_label: str | None = None,
) -> str | None:
    """Commit plan (and optionally research) to vault. Returns plan path on success, None on failure."""
    import time as _time
    try:
        ctx = await _get_ctx()
        company_slug = company.lower().replace(" ", "-")
        round_slug = (round_label or "general").lower().replace(" ", "-")
        epoch = int(_time.time())
        base = f"{company_slug}/{round_slug}/{epoch}"
        plan_path = f"{base}-plan.md"
        await commit_file(
            path=plan_path,
            content=plan_md,
            message=f"plan: {company} — {round_label or 'general'} #{interview_id}",
            github_token=ctx.github_token,
            vault_repo=ctx.vault_repo,
        )
        if research:
            await commit_file(
                path=f"{base}-research.md",
                content=research,
                message=f"research: {company} — {round_label or 'general'} #{interview_id}",
                github_token=ctx.github_token,
                vault_repo=ctx.vault_repo,
            )
        return plan_path
    except Exception as exc:
        logger.warning("twilio.vault_commit_failed", interview_id=interview_id, error=str(exc), exc_info=True)
        return None


async def _handle_mock(sender: str, args: list[str]) -> str:
    raw = " ".join(args)

    # Parse company + round from args using the same LLM parser as prep.
    intent = await parse_prep_intent(raw) if raw else PrepIntent()
    company_hint = intent.company
    round_hint = (intent.rounds or [None])[0]

    # If round not extracted by LLM, try the first arg directly.
    if not round_hint and args:
        candidate = args[-1].lower()
        if candidate in _MOCK_ROUNDS:
            round_hint = candidate

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    if not interviews:
        return "No active interviews. Forward an invite or run: prep <company>"

    # Resolve company.
    interview = None
    interview = _resolve_interview(interviews, company_hint, round_hint)
    if interview is None and company_hint and not round_hint:
        # Company matched but multiple rounds — pick by round_hint from the mock round
        pass
    if interview is None:
        # Multiple active interviews, ambiguous — ask once.
        options = "\n".join(f"  • {i.company} — {i.round_type or 'general'} ({i.role})" for i in interviews)
        pending = {"_command": "mock", "round": round_hint}
        async with async_session_factory() as session:
            await WaWindowRepository(session).set_pending_prep(sender, pending)
        return f"Which interview?\n{options}\n\nReply: mock <company> <round>"

    # Use the interview's own round_type if no explicit round given.
    round_type = round_hint or (interview.round_type.lower() if interview.round_type else None)
    if not round_type:
        pending = {"_command": "mock", "company": interview.company, "round": None}
        async with async_session_factory() as session:
            await WaWindowRepository(session).set_pending_prep(sender, pending)
        return "Which round? dsa / lld / sysdesign / behavioral"

    round_type = round_type.lower()
    if round_type not in _MOCK_ROUNDS:
        return f"Unknown round '{round_type}'. Use: dsa, lld, sysdesign, behavioral"

    return await _execute_mock(sender, interview, round_type)


async def _execute_mock(sender: str, interview, round_type: str) -> str:
    ctx = await _get_ctx()
    company_slug = interview.company.lower().replace(" ", "-")
    research, plan = await load_vault_context(
        company_slug, round_type,
        github_token=ctx.github_token, vault_repo=ctx.vault_repo,
    )

    async with async_session_factory() as session:
        session_obj = await MockSessionRepository(session).create(
            interview_id=interview.id,
            round_type=round_type,
        )
        session_id = session_obj.id

    logger.info("mock.session.created", session_id=session_id, round_type=round_type)
    opening = await _orchestrator.start(
        session_id, round_type, interview.company, interview.role,
        research=research, plan=plan,
    )
    return f"Mock started (session #{session_id}).\n\n{opening}"


async def _handle_mock_followup(sender: str, pending: dict, body: str) -> str:
    new_intent = await parse_prep_intent(body)
    company_hint = pending.get("company") or (new_intent.company)
    round_hint = pending.get("round") or ((new_intent.rounds or [None])[0])

    # Try direct round word if LLM missed it.
    if not round_hint:
        word = body.strip().split()[0].lower() if body.strip() else ""
        if word in _MOCK_ROUNDS:
            round_hint = word

    async with async_session_factory() as session:
        await WaWindowRepository(session).clear_pending_prep(sender)
        interviews = await InterviewRepository(session).list_active()

    interview = _resolve_interview(interviews, company_hint, round_hint)
    if interview is None and interviews:
        interview = interviews[0]
    if interview is None:
        return "No active interviews found."

    round_type = round_hint or (interview.round_type.lower() if interview.round_type else "behavioral")
    round_type = round_type.lower()
    if round_type not in _MOCK_ROUNDS:
        round_type = "behavioral"

    return await _execute_mock(sender, interview, round_type)


async def _handle_done(sender: str, args: list[str]) -> str:
    rating = next((a.lower() for a in args if a.lower() in {"easy", "medium", "hard"}), None)
    if not rating:
        return "Usage: done easy / done medium / done hard\n  e.g. done google dsa easy"

    round_hint = next((_map_label_to_round(a) for a in args if _map_label_to_round(a)), None)
    remaining = [a for a in args
                 if a.lower() not in {"easy", "medium", "hard"} and not _map_label_to_round(a)]
    company_hint = " ".join(remaining).strip() or None

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    if not interviews:
        return "No active interviews found. Forward an invite or run: prep <company>"

    # Try to resolve to a single interview using company + round hints.
    interview = _resolve_interview(interviews, company_hint, round_hint)
    if interview is None:
        options = "\n".join(
            f"  • {i.company} — {i.round_type or 'general'} ({i.role})" for i in interviews
        )
        pending = {"_command": "done", "rating": rating, "round": round_hint}
        async with async_session_factory() as session:
            await WaWindowRepository(session).set_pending_prep(sender, pending)
        return f"Which interview?\n{options}\n\nReply: done <company> [round] {rating}"

    return await _execute_done(interview, rating)


def _resolve_interview(interviews: list, company_hint: str | None, round_hint: str | None):
    """Return a single interview from the list given optional company and round hints."""
    candidates = interviews
    if company_hint:
        candidates = [i for i in candidates if i.company.lower() == company_hint.lower()]
    if round_hint:
        candidates = [i for i in candidates if i.round_type == round_hint]
    if len(candidates) == 1:
        return candidates[0]
    if not company_hint and not round_hint and len(interviews) == 1:
        return interviews[0]
    return None


async def _execute_done(interview, rating: str) -> str:
    async with async_session_factory() as session:
        plan = await PrepPlanRepository(session).get_pending(interview.id)

    if not plan:
        rt = f" {interview.round_type}" if interview.round_type else ""
        return (
            f"No pending drill for {interview.company}{rt}. "
            f"Get a plan first: prep {interview.company.lower()}"
            + (f" {interview.round_type.lower()}" if interview.round_type else "")
        )

    return await record_completion(plan.id, rating)


async def _handle_done_followup(sender: str, pending: dict, body: str) -> str:
    async with async_session_factory() as session:
        await WaWindowRepository(session).clear_pending_prep(sender)
        interviews = await InterviewRepository(session).list_active()

    rating = pending.get("rating", "")
    if not rating:
        rating = next((w.lower() for w in body.split() if w.lower() in {"easy", "medium", "hard"}), "medium")

    round_hint = pending.get("round") or next(
        (_map_label_to_round(w) for w in body.split() if _map_label_to_round(w)), None
    )
    words = [w for w in body.split()
             if w.lower() not in {"easy", "medium", "hard"} and not _map_label_to_round(w)]
    company_hint = " ".join(words).strip() or None

    interview = _resolve_interview(interviews, company_hint, round_hint)
    if interview is None and interviews:
        interview = interviews[0]
    if interview is None:
        return "No active interviews found."

    return await _execute_done(interview, rating)


async def _handle_status(sender: str) -> str:
    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    if not interviews:
        return "No active interviews. Forward an invite to get started."

    lines = ["Active interviews:"]
    for i in interviews:
        round_str = i.round_type or "general"
        scheduled = i.scheduled_for.strftime("%b %d") if i.scheduled_for else "TBD"
        lines.append(f"  • {i.company} — {i.role} | {round_str} | {scheduled}")
    return "\n".join(lines)


async def _handle_freeform(sender: str, body: str) -> str:
    """Route to the active session (mock or study), or end it if the user says 'end'."""
    import json as _json

    async with async_session_factory() as session:
        result = await session.execute(
            select(MockSession)
            .where(MockSession.ended_at.is_(None))
            .order_by(MockSession.started_at.desc())
            .limit(1)
        )
        active = result.scalar_one_or_none()

    if not active:
        return _HELP

    if body.strip().lower() in {"end", "stop", "quit"}:
        if active.round_type == "study":
            async with async_session_factory() as session:
                await MockSessionRepository(session).finalize(
                    id=active.id, rubric_json="", critique_json="",
                )
            return "Study session ended. Run 'study' to start a new one."
        return await _orchestrator.end_session(active.id)

    # Study session → tutor; mock session → orchestrator
    if active.round_type == "study":
        transcript = _json.loads(active.transcript_json or "[]")
        reply = await _tutor.run_turn(transcript, body)
        transcript.append({"role": "candidate", "content": body, "turn": len(transcript)})
        transcript.append({"role": "tutor", "content": reply, "turn": len(transcript)})
        async with async_session_factory() as session:
            await MockSessionRepository(session).update_transcript(
                id=active.id, transcript_json=_json.dumps(transcript),
            )
        return reply

    return await _orchestrator.run_turn(active.id, body)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def _handle_study(sender: str, args: list[str]) -> str:
    ctx = await _get_ctx()
    raw = " ".join(args)

    intent = await parse_prep_intent(raw) if raw else PrepIntent()
    company_hint = intent.company
    round_hint = (intent.rounds or [None])[0]

    # Resolve company — from args, or single active interview.
    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    company_slug = None
    company_label = company_hint

    if company_hint:
        match = next((i for i in interviews if i.company.lower() == company_hint.lower()), None)
        company_slug = company_hint.lower().replace(" ", "-")
        company_label = match.company if match else company_hint
    elif len(interviews) == 1:
        company_slug = interviews[0].company.lower().replace(" ", "-")
        company_label = interviews[0].company
    elif interviews:
        options = "\n".join(f"  • {i.company} ({i.role})" for i in interviews)
        pending = {"_command": "study", "round": round_hint}
        async with async_session_factory() as session:
            await WaWindowRepository(session).set_pending_prep(sender, pending)
        return f"Which interview?\n{options}\n\nReply: study <company> <round>"
    else:
        return "No active interviews. Run 'prep <company>' first."

    # Resolve round — from args, or list available vault rounds.
    round_slug = round_hint.lower() if round_hint else None

    if not round_slug:
        available = await list_vault_rounds(
            company_slug, github_token=ctx.github_token, vault_repo=ctx.vault_repo
        )
        if len(available) == 1:
            round_slug = available[0]
        elif available:
            options = " / ".join(available)
            pending = {"_command": "study", "company": company_label, "round": None}
            async with async_session_factory() as session:
                await WaWindowRepository(session).set_pending_prep(sender, pending)
            return f"Which round for {company_label}? {options}\n\nReply: study {company_label.lower()} <round>"
        else:
            return f"No prep found for {company_label}. Run 'prep {company_label}' first."

    return await _execute_study(sender, company_slug, company_label, round_slug, ctx)


async def _execute_study(sender: str, company_slug: str, company_label: str, round_slug: str, ctx) -> str:
    research, plan = await load_vault_context(
        company_slug, round_slug,
        github_token=ctx.github_token, vault_repo=ctx.vault_repo,
    )

    if not research and not plan:
        return f"No prep found for {company_label} / {round_slug}. Run 'prep {company_label} {round_slug}' first."

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()
    match = next((i for i in interviews if i.company.lower().replace(" ", "-") == company_slug), None)
    interview_id = match.id if match else (interviews[0].id if interviews else None)

    if interview_id is None:
        return "No active interview found. Run 'prep <company>' first."

    async with async_session_factory() as session:
        session_obj = await MockSessionRepository(session).create(
            interview_id=interview_id,
            round_type="study",
        )
        session_id = session_obj.id

    opening = await _tutor.start_session(research=research, plan=plan)

    import json
    transcript = [{"role": "tutor", "content": opening, "turn": 0}]
    async with async_session_factory() as session:
        await MockSessionRepository(session).update_transcript(
            id=session_id,
            transcript_json=json.dumps(transcript),
        )

    return f"Study session started.\n\n{opening}"


async def _handle_study_followup(sender: str, pending: dict, body: str) -> str:
    ctx = await _get_ctx()
    new_intent = await parse_prep_intent(body)

    company_hint = pending.get("company") or new_intent.company
    round_hint = pending.get("round") or ((new_intent.rounds or [None])[0])

    async with async_session_factory() as session:
        await WaWindowRepository(session).clear_pending_prep(sender)
        interviews = await InterviewRepository(session).list_active()

    company_slug = None
    company_label = company_hint or ""
    if company_hint:
        match = next((i for i in interviews if i.company.lower() == company_hint.lower()), None)
        company_slug = company_hint.lower().replace(" ", "-")
        company_label = match.company if match else company_hint
    elif interviews:
        company_slug = interviews[0].company.lower().replace(" ", "-")
        company_label = interviews[0].company

    if not company_slug:
        return "No active interviews found."

    round_slug = round_hint.lower() if round_hint else None
    if not round_slug:
        available = await list_vault_rounds(company_slug, github_token=ctx.github_token, vault_repo=ctx.vault_repo)
        round_slug = available[0] if available else "general"

    return await _execute_study(sender, company_slug, company_label, round_slug, ctx)


async def _handle_link(sender: str, args: list[str]) -> str:
    """Associate this WhatsApp number with a registered email account.

    V2 implementation: look up User by email, set whatsapp_phone = sender.
    V1: not yet implemented — single owner only.
    """
    if not args:
        return "Usage: link <your-email>"
    email = args[0]
    logger.info("twilio.link.not_implemented", sender=sender, email=email,
                hint="V2: UserRepository(session).link_phone(email, sender)")
    return "Multi-user linking coming in V2. You're already set up as the owner."


async def _route(payload: TwilioInbound) -> str:
    sender = payload.From
    body = payload.Body

    async with async_session_factory() as session:
        await WaWindowRepository(session).record_inbound(sender)

    # V2: get_user_context(sender_phone=sender) returns per-user config from DB.
    # V1: sender is passed but ignored — always returns owner context.
    _ctx = await get_user_context(sender_phone=sender)

    # Check if we're mid-prep conversation (waiting for missing fields).
    async with async_session_factory() as session:
        pending = await WaWindowRepository(session).get_pending_prep(sender)

    if pending:
        # Any non-command reply is treated as the follow-up answer.
        verb = body.strip().split()[0].lower() if body.strip() else ""
        if verb not in {"prep", "mock", "done", "status", "study", "link"}:
            command = pending.get("_command", "prep")
            if command == "mock":
                return await _handle_mock_followup(sender, pending, body)
            elif command == "study":
                return await _handle_study_followup(sender, pending, body)
            elif command == "done":
                return await _handle_done_followup(sender, pending, body)
            else:
                return await _handle_prep_followup(sender, pending, body)
        # User typed a new command — discard pending state.
        async with async_session_factory() as session:
            await WaWindowRepository(session).clear_pending_prep(sender)

    intent, args = _parse_intent(body)

    logger.info("twilio.intent", sender=sender, intent=intent, args=args)

    if intent == "prep":
        return await _handle_prep(sender, args)
    if intent == "mock":
        return await _handle_mock(sender, args)
    if intent == "done":
        return await _handle_done(sender, args)
    if intent == "status":
        return await _handle_status(sender)
    if intent == "study":
        return await _handle_study(sender, args)
    if intent == "link":
        return await _handle_link(sender, args)
    if intent == "freeform":
        return await _handle_freeform(sender, body)
    return _HELP


async def _respond(to: str, text: str) -> None:
    """Send reply in chunks, respecting the 4096-char WhatsApp limit."""
    chunks = chunk_message(text)
    for chunk in chunks:
        await send_whatsapp(to=to, body=chunk)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/hooks/twilio")
async def twilio_webhook(request: Request) -> Response:
    form_data = await request.form()
    params = dict(form_data)
    _validate_twilio_signature(request, params)

    payload = TwilioInbound(
        From=params.get("From", ""),
        Body=params.get("Body", ""),
        MessageSid=params.get("MessageSid", ""),
    )
    logger.info("twilio.inbound", from_=payload.From, message_sid=payload.MessageSid)

    # Route in background so webhook returns immediately.
    async def _bg():
        try:
            reply = await _route(payload)
            await _respond(to=payload.From, text=reply)
        except Exception as exc:
            logger.error("twilio.route.error", error=str(exc), exc_info=True)
            try:
                await send_whatsapp(to=payload.From, body="Something went wrong. Try again.")
            except Exception as send_exc:
                logger.error("twilio.fallback_send_failed", error=str(send_exc), exc_info=True)

    # Keep a strong reference so the task isn't GC'd before it completes.
    _task = asyncio.create_task(_bg())
    _background_tasks.add(_task)
    _task.add_done_callback(_background_tasks.discard)

    # Twilio expects a 200 with empty TwiML (we reply via API, not TwiML).
    return Response(content="<Response/>", media_type="application/xml")
