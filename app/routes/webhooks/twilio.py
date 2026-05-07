from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from twilio.request_validator import RequestValidator

from app.config import settings
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
from app.schemas.webhooks import TwilioInbound
from app.agents.orchestrator import MockOrchestrator
from app.lib.user_context import get_user_context
from app.tools.generate_plan import generate_plan
from app.tools.record_completion import record_completion

_orchestrator = MockOrchestrator()

router = APIRouter()
logger = get_logger(__name__)

_HELP = (
    "Commands:\n"
    "  prep <company> — generate a prep plan\n"
    "  mock <round>   — start a mock (dsa/lld/sysdesign/behavioral)\n"
    "  done <rating>  — mark drill complete (easy/medium/hard)\n"
    "  status         — show active interviews"
)


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def _validate_twilio_signature(request: Request, params: dict) -> None:
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
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
    if verb == "link":
        return "link", rest  # V2: link <email> associates phone → User account
    return "freeform", parts  # treat entire body as freeform mock turn


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

async def _handle_prep(sender: str, args: list[str]) -> str:
    if not args:
        return "Usage: prep <company name>"

    company = " ".join(args)

    async with async_session_factory() as session:
        interviews = await InterviewRepository(session).list_active()
        match = next((i for i in interviews if i.company.lower() == company.lower()), None)

    if match:
        rounds = json.loads(match.round_types)
        plan_md = await generate_plan(
            interview_id=match.id,
            company=match.company,
            role=match.role,
            round_types=rounds,
        )
        async with async_session_factory() as session:
            await PrepPlanRepository(session).create(
                interview_id=match.id,
                plan_md=plan_md,
                time_budget_min=120,
            )
        return f"New plan for {match.company} ({match.role}):\n\n{plan_md[:1500]}…\n\n(Full plan in prep-vault)"

    # No active interview — create a bare one with unknown rounds and generate plan.
    async with async_session_factory() as session:
        interview = await InterviewRepository(session).create(
            company=company,
            role="Unknown",
            round_types=["DSA", "LLD", "sysdesign", "behavioral"],
        )

    plan_md = await generate_plan(
        interview_id=interview.id,
        company=company,
        role="Unknown",
        round_types=["DSA", "LLD", "sysdesign", "behavioral"],
    )

    async with async_session_factory() as session:
        await PrepPlanRepository(session).create(
            interview_id=interview.id,
            plan_md=plan_md,
            time_budget_min=120,
        )

    return f"Plan for {company}:\n\n{plan_md[:1500]}…\n\n(Full plan in prep-vault)"


async def _handle_mock(sender: str, args: list[str]) -> str:
    round_type = args[0].lower() if args else "behavioral"
    valid = {"dsa", "lld", "sysdesign", "behavioral"}
    if round_type not in valid:
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
        rounds = ", ".join(json.loads(i.round_types))
        scheduled = i.scheduled_for.strftime("%b %d") if i.scheduled_for else "TBD"
        lines.append(f"  • {i.company} — {i.role} | {rounds} | {scheduled}")
    return "\n".join(lines)


async def _handle_freeform(sender: str, body: str) -> str:
    """Route to the active MockSession, or end it if the user says 'end'."""
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

    if body.strip().lower() in {"end", "end mock", "stop", "quit"}:
        return await _orchestrator.end_session(active.id)

    return await _orchestrator.run_turn(active.id, body)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

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
    intent, args = _parse_intent(payload.Body)

    async with async_session_factory() as session:
        await WaWindowRepository(session).record_inbound(sender)

    # V2: get_user_context(sender_phone=sender) returns per-user config from DB.
    # V1: sender is passed but ignored — always returns owner context.
    _ctx = await get_user_context(sender_phone=sender)

    logger.info("twilio.intent", sender=sender, intent=intent, args=args)

    if intent == "prep":
        return await _handle_prep(sender, args)
    if intent == "mock":
        return await _handle_mock(sender, args)
    if intent == "done":
        return await _handle_done(sender, args)
    if intent == "status":
        return await _handle_status(sender)
    if intent == "link":
        return await _handle_link(sender, args)
    if intent == "freeform":
        return await _handle_freeform(sender, payload.Body)
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
            await _respond(to=payload.From, body=reply)
        except Exception as exc:
            logger.error("twilio.route.error", error=str(exc))
            await send_whatsapp(to=payload.From, body="Something went wrong. Try again.")

    asyncio.create_task(_bg())

    # Twilio expects a 200 with empty TwiML (we reply via API, not TwiML).
    return Response(content="<Response/>", media_type="application/xml")
