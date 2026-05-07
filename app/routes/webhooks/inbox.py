import asyncio
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db.repos.interviews import InterviewRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.session import async_session_factory
from app.integrations.llm_client import complete_fast as complete
from app.integrations.github_client import commit_file
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.schemas.webhooks import MailgunInbound
from app.tools.classify_rounds import classify_rounds
from app.tools.generate_plan import generate_plan

router = APIRouter()
logger = get_logger(__name__)

_background_tasks: set[asyncio.Task] = set()

_PARSE_SYSTEM = """Extract the company name and role from a forwarded interview invite email.
Return ONLY a JSON object: {"company": "...", "role": "..."}
If you cannot determine one of the values, use "Unknown".
"""

_REGISTRATION_SUBJECTS = {"register", "signup", "sign up", "sign-up"}


def _is_registration(payload: MailgunInbound) -> bool:
    """Return True if this email is a registration request, not an interview forward.

    V2: user emails subject "register" with github_token + vault_repo in body.
    V1: always False — registration not yet implemented.
    """
    return payload.subject.strip().lower() in _REGISTRATION_SUBJECTS


async def _handle_registration(payload: MailgunInbound) -> None:
    """Handle a registration email from a new user.

    V2 implementation: parse github_token + vault_repo from body,
    create User row keyed by payload.sender email, reply via Mailgun API.

    V1: log and no-op — single owner only.
    """
    logger.info(
        "inbox.registration.not_implemented",
        sender=payload.sender,
        hint="V2: parse body for github_token + vault_repo, create User row",
    )


async def _parse_company_role(subject: str, body: str) -> tuple[str, str]:
    raw = await complete(
        messages=[{"role": "user", "content": f"Subject: {subject}\n\nBody:\n{body[:2000]}"}],
        system=_PARSE_SYSTEM,
        max_tokens=64,
    )
    try:
        parsed = json.loads(raw.strip())
        return parsed.get("company", "Unknown"), parsed.get("role", "Unknown")
    except Exception as exc:
        logger.warning("inbox.parse_company_role.failed", error=str(exc), exc_info=True)
        return "Unknown", "Unknown"


def _validate_mailgun_signature(timestamp: str, token: str, signature: str) -> None:
    computed = hmac.new(
        settings.mailgun_signing_key.encode(),
        (timestamp + token).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=403, detail="Invalid Mailgun signature")


async def _run_pipeline(payload: MailgunInbound) -> None:
    """Route inbound email: registration or interview forward."""
    if _is_registration(payload):
        await _handle_registration(payload)
        return

    # V2: get_user_context(email=payload.sender) returns per-user GitHub config.
    # V1: sender email is passed but ignored — always returns owner context.
    ctx = await get_user_context(email=payload.sender)

    company, role = await _parse_company_role(payload.subject, payload.body_plain)
    logger.info("inbox.parsed", company=company, role=role, sender=payload.sender)

    jd_text = f"{payload.subject}\n\n{payload.body_plain}"
    rounds = await classify_rounds(jd_text)
    logger.info("inbox.classified", rounds=rounds)

    async with async_session_factory() as session:
        interview = await InterviewRepository(session).create(
            company=company,
            role=role,
            round_types=rounds,
        )
        interview_id = interview.id

    plan_md = await generate_plan(
        interview_id=interview_id,
        company=company,
        role=role,
        round_types=rounds,
    )

    async with async_session_factory() as session:
        await PrepPlanRepository(session).create(
            interview_id=interview_id,
            plan_md=plan_md,
            time_budget_min=120,
        )

    vault_path = f"plans/{company.lower().replace(' ', '-')}-{interview_id}.md"
    try:
        sha = await commit_file(
            path=vault_path,
            content=plan_md,
            message=f"prep: {company} — {role} (interview #{interview_id})",
            github_token=ctx.github_token,
            vault_repo=ctx.vault_repo,
        )
        logger.info("inbox.committed", path=vault_path, sha=sha)
    except Exception as exc:
        logger.warning("inbox.vault_commit_failed", path=vault_path, error=str(exc), exc_info=True)


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
