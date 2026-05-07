import asyncio
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.lib.logging import get_logger
from app.lib.prep_pipeline import execute_prep
from app.schemas.webhooks import MailgunInbound
from app.tools.parse_prep_intent import parse_prep_intent

router = APIRouter()
logger = get_logger(__name__)

_background_tasks: set[asyncio.Task] = set()

_REGISTRATION_SUBJECTS = {"register", "signup", "sign up", "sign-up"}


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

    raw = f"{payload.subject}\n\n{payload.body_plain[:2000]}"
    intent = await parse_prep_intent(raw)
    logger.info(
        "inbox.parsed",
        company=intent.company,
        role=intent.role,
        rounds=intent.rounds,
        date=intent.interview_date,
        sender=payload.sender,
    )

    if not intent.rounds:
        logger.warning("inbox.no_rounds_classified", company=intent.company)
        return

    result = await execute_prep(intent)
    logger.info("inbox.pipeline.done", result_preview=result[:100])


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
