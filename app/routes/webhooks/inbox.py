import asyncio
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db.repos.interviews import InterviewRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.session import async_session_factory
from app.integrations.github_client import commit_file
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.schemas.webhooks import MailgunInbound
from app.tools.generate_plan import generate_plan
from app.tools.parse_prep_intent import parse_prep_intent

router = APIRouter()
logger = get_logger(__name__)

_background_tasks: set[asyncio.Task] = set()

_REGISTRATION_SUBJECTS = {"register", "signup", "sign up", "sign-up"}


def _first_heading(plan_md: str) -> str | None:
    for line in plan_md.splitlines():
        if line.strip().startswith("### "):
            return line.strip().lstrip("# ").strip()
    return None


def _is_registration(payload: MailgunInbound) -> bool:
    return payload.subject.strip().lower() in _REGISTRATION_SUBJECTS


async def _handle_registration(payload: MailgunInbound) -> None:
    logger.info(
        "inbox.registration.not_implemented",
        sender=payload.sender,
        hint="V2: parse body for github_token + vault_repo, create User row",
    )


def _validate_mailgun_signature(timestamp: str, token: str, signature: str) -> None:
    computed = hmac.new(
        settings.mailgun_signing_key.encode(),
        (timestamp + token).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=403, detail="Invalid Mailgun signature")


async def _run_pipeline(payload: MailgunInbound) -> None:
    if _is_registration(payload):
        await _handle_registration(payload)
        return

    ctx = await get_user_context(email=payload.sender)

    raw = f"{payload.subject}\n\n{payload.body_plain[:2000]}"
    intent = await parse_prep_intent(raw)
    intent = intent.with_defaults()

    company = intent.company or "Unknown"
    role = intent.role or "Unknown"
    rounds = intent.rounds or []
    scheduled_for = None
    if intent.interview_date:
        from datetime import datetime, timezone
        try:
            scheduled_for = datetime.strptime(intent.interview_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    logger.info("inbox.parsed", company=company, role=role, rounds=rounds, sender=payload.sender)

    if not rounds:
        logger.warning("inbox.no_rounds_classified", company=company)
        return

    # Create one Interview per round — dedup by company+round so forwarding twice is idempotent.
    interviews: list = []
    for rt in rounds:
        async with async_session_factory() as session:
            existing = await InterviewRepository(session).find_active_by_company_round(company, rt)
            if existing:
                interviews.append(existing)
            else:
                created = await InterviewRepository(session).create(
                    company=company, role=role, round_type=rt, scheduled_for=scheduled_for,
                )
                interviews.append(created)

    if not interviews:
        return

    plan_md = await generate_plan(
        interview_id=interviews[0].id,
        company=company,
        role=role,
        round_types=rounds,
        days_until_interview=intent.days_until_interview or 7,
    )

    vault_path_str = f"plans/{company.lower().replace(' ', '-')}-{interviews[0].id}.md"
    committed_path: str | None = None
    try:
        sha = await commit_file(
            path=vault_path_str,
            content=plan_md,
            message=f"prep: {company} — {role}",
            github_token=ctx.github_token,
            vault_repo=ctx.vault_repo,
        )
        committed_path = vault_path_str
        logger.info("inbox.committed", path=vault_path_str, sha=sha)
    except Exception as exc:
        logger.warning("inbox.vault_commit_failed", path=vault_path_str, error=str(exc), exc_info=True)

    drill_label = _first_heading(plan_md)
    for interview in interviews:
        async with async_session_factory() as session:
            await PrepPlanRepository(session).create(
                interview_id=interview.id,
                vault_path=committed_path,
                drill_label=drill_label,
            )


async def _bg_pipeline(payload: MailgunInbound) -> None:
    try:
        await _run_pipeline(payload)
    except Exception as exc:
        logger.error("inbox.pipeline.failed", sender=payload.sender, error=str(exc), exc_info=True)


@router.post("/hooks/inbox")
async def inbox_webhook(request: Request) -> dict[str, str]:
    form = await request.form()
    body = dict(form)

    timestamp = body.get("timestamp", "")
    token = body.get("token", "")
    signature = body.get("signature", "")
    _validate_mailgun_signature(timestamp, token, signature)

    payload = MailgunInbound(
        sender=body.get("sender", ""),
        subject=body.get("subject", ""),
        body_plain=body.get("body-plain", ""),
    )
    logger.info("mailgun.inbound.received", sender=payload.sender, subject=payload.subject)

    _task = asyncio.create_task(_bg_pipeline(payload))
    _background_tasks.add(_task)
    _task.add_done_callback(_background_tasks.discard)

    return {"status": "queued"}
