import asyncio
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.db.repos.interviews import InterviewRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.session import async_session_factory
from app.integrations.anthropic_client import complete
from app.integrations.github_client import commit_file
from app.lib.logging import get_logger
from app.schemas.webhooks import MailgunInbound
from app.tools.classify_rounds import classify_rounds
from app.tools.generate_plan import generate_plan

router = APIRouter()
logger = get_logger(__name__)

_PARSE_SYSTEM = """Extract the company name and role from a forwarded interview invite email.
Return ONLY a JSON object: {"company": "...", "role": "..."}
If you cannot determine one of the values, use "Unknown".
"""


async def _parse_company_role(subject: str, body: str) -> tuple[str, str]:
    raw = await complete(
        messages=[{"role": "user", "content": f"Subject: {subject}\n\nBody:\n{body[:2000]}"}],
        system=_PARSE_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
    )
    try:
        parsed = json.loads(raw.strip())
        return parsed.get("company", "Unknown"), parsed.get("role", "Unknown")
    except Exception:
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
    """Classify → create DB record → generate plan → commit to vault."""
    company, role = await _parse_company_role(payload.subject, payload.body_plain)
    logger.info("inbox.parsed", company=company, role=role)

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
    sha = await commit_file(
        path=vault_path,
        content=plan_md,
        message=f"prep: {company} — {role} (interview #{interview_id})",
    )
    logger.info("inbox.committed", path=vault_path, sha=sha)


@router.post("/hooks/inbox")
async def inbox_webhook(request: Request) -> dict[str, str]:
    body = await request.json()

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

    # Run pipeline in background so webhook returns immediately.
    asyncio.create_task(_run_pipeline(payload))

    return {"status": "queued"}
