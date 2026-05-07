from __future__ import annotations

import asyncio
from typing import get_args

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import settings
from app.integrations.github_client import commit_file
from app.lib.user_context import get_user_context as _get_ctx
from sqlalchemy import select

from app.db.models import MockSession, PrepPlan
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
from app.tools.parse_prep_intent import PrepIntent, parse_prep_intent
from app.tools.record_completion import record_completion
from app.tools.research_company import research_company

_orchestrator = MockOrchestrator()
_tutor = Tutor()

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
_DEFAULT_ROUND_TYPES: list[str] = [r for r in get_args(RoundType) if r not in {"hiring_manager", "unknown"}]


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
    """Generate research + plan for a fully-resolved PrepIntent."""
    from datetime import datetime as _datetime, timezone as _tz

    final = intent.with_defaults()
    company = final.company or "Unknown"
    role = final.role
    round_types = final.rounds
    scheduled_for = None
    if final.interview_date:
        try:
            scheduled_for = _datetime.strptime(final.interview_date, "%Y-%m-%d").replace(
                tzinfo=_tz.utc
            )
        except ValueError:
            pass

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()
        match = next((i for i in interviews if i.company.lower() == company.lower()), None)

    if match:
        effective_role = match.role if match.role != "Unknown" else role
        rounds = match.round_types
        research = await run_research(match.company, effective_role)
        plan_md = await generate_plan(
            interview_id=match.id,
            company=match.company,
            role=effective_role,
            round_types=rounds,
            research_context=research,
        )
        async with async_session_factory() as session:
            await PrepPlanRepository(session).create(
                interview_id=match.id,
                plan_md=plan_md,
                time_budget_min=120,
            )
        await _commit_plan_to_vault(match.id, match.company, plan_md, research)
        return f"Researching & planning {match.company} ({effective_role}):\n\n{plan_md[:1200]}…\n\n(Full plan + sources in prep-vault)"

    async with async_session_factory() as session:
        interview = await InterviewRepository(session).create(
            company=company,
            role=role,
            round_types=round_types,
            scheduled_for=scheduled_for,
        )

    research = await run_research(company, role)
    plan_md = await generate_plan(
        interview_id=interview.id,
        company=company,
        role=role,
        round_types=round_types,
        research_context=research,
    )

    async with async_session_factory() as session:
        await PrepPlanRepository(session).create(
            interview_id=interview.id,
            plan_md=plan_md,
            time_budget_min=120,
        )

    await _commit_plan_to_vault(interview.id, company, plan_md, research)
    date_str = f" on {final.interview_date}" if final.interview_date else ""
    return f"Plan for {company} ({role}){date_str}:\n\n{plan_md[:1200]}…\n\n(Full plan + sources in prep-vault)"


async def _commit_plan_to_vault(interview_id: int, company: str, plan_md: str, research: str = "") -> None:
    try:
        ctx = await _get_ctx()
        slug = company.lower().replace(" ", "-")
        await commit_file(
            path=f"plans/plan-{interview_id}-{slug}.md",
            content=plan_md,
            message=f"plan: {company} interview #{interview_id}",
            github_token=ctx.github_token,
            vault_repo=ctx.vault_repo,
        )
        if research:
            await commit_file(
                path=f"research/research-{interview_id}-{slug}.md",
                content=research,
                message=f"research: {company} interview #{interview_id}",
                github_token=ctx.github_token,
                vault_repo=ctx.vault_repo,
            )
    except Exception as exc:
        logger.warning("twilio.vault_commit_failed", interview_id=interview_id, error=str(exc), exc_info=True)


async def _handle_mock(sender: str, args: list[str]) -> str:
    round_type = args[0].lower() if args else "behavioral"
    if round_type not in _MOCK_ROUNDS:
        return f"Unknown round '{round_type}'. Use: dsa, lld, sysdesign, behavioral"

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    if not interviews:
        return "No active interview found. Forward an invite email first, or run: prep <company>"

    interview = interviews[0]

    async with async_session_factory() as session:
        session_obj = await MockSessionRepository(session).create(
            interview_id=interview.id,
            round_type=round_type,
        )
        session_id = session_obj.id

    logger.info("mock.session.created", session_id=session_id, round_type=round_type)

    company = interview.company
    role = interview.role
    opening = await _orchestrator.start(session_id, round_type, company, role)
    return f"Mock started (session #{session_id}).\n\n{opening}"


async def _handle_done(sender: str, args: list[str]) -> str:
    rating = args[0].lower() if args else ""
    if rating not in {"easy", "medium", "hard"}:
        return "Usage: done easy / done medium / done hard"

    # Find the most recent incomplete prep plan across all active interviews.
    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()
        if not interviews:
            return "No active interviews found. Forward an invite email first."

        result = await session.execute(
            select(PrepPlan)
            .where(
                PrepPlan.interview_id.in_([i.id for i in interviews]),
                PrepPlan.completed_at.is_(None),
                PrepPlan.skipped.is_(False),
            )
            .order_by(PrepPlan.generated_at.desc())
            .limit(1)
        )
        plan = result.scalar_one_or_none()

    if not plan:
        return "No pending drill to mark. Get a plan first: prep <company>"

    return await record_completion(plan.id, rating)


async def _handle_status(sender: str) -> str:
    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()

    if not interviews:
        return "No active interviews. Forward an invite to get started."

    lines = ["Active interviews:"]
    for i in interviews:
        rounds = ", ".join(i.round_types)
        scheduled = i.scheduled_for.strftime("%b %d") if i.scheduled_for else "TBD"
        lines.append(f"  • {i.company} — {i.role} | {rounds} | {scheduled}")
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
    """Start a Socratic study session using the latest research from vault."""
    ctx = await _get_ctx()

    # Find latest research file in vault.
    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()
    if not interviews:
        return "No active interview. Run 'prep <company>' first."

    interview = interviews[0]
    slug = interview.company.lower().replace(" ", "-")
    research_path = f"research/research-{interview.id}-{slug}.md"

    try:
        research_context = await read_file(
            path=research_path,
            github_token=ctx.github_token,
            vault_repo=ctx.vault_repo,
        )
    except Exception:
        return f"No research found for {interview.company}. Run 'prep {interview.company}' first to generate it."

    # Start a study session (round_type="study" reuses MockSession).
    async with async_session_factory() as session:
        session_obj = await MockSessionRepository(session).create(
            interview_id=interview.id,
            round_type="study",
        )
        session_id = session_obj.id

    opening = await _tutor.start_session(research_context)

    import json
    transcript = [{"role": "tutor", "content": opening, "turn": 0}]
    async with async_session_factory() as session:
        await MockSessionRepository(session).update_transcript(
            id=session_id,
            transcript_json=json.dumps(transcript),
        )

    return f"Study session started.\n\n{opening}"


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

    asyncio.create_task(_bg())

    # Twilio expects a 200 with empty TwiML (we reply via API, not TwiML).
    return Response(content="<Response/>", media_type="application/xml")
