from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import PrepPlan
from app.db.repos.interviews import InterviewRepository
from app.db.repos.outbound_idempotency import OutboundIdempotencyRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.repos.wa_window import WaWindowRepository
from app.db.repos.weak_patterns import WeakPatternRepository
from app.db.session import async_session_factory
from app.integrations.github_client import commit_file
from app.integrations.twilio_client import send_whatsapp
from app.lib.chunker import chunk_message
from app.lib.idempotency import make_key
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.tools.generate_plan import generate_plan

logger = get_logger(__name__)

# Weight bump when a drill is skipped (no reply by next morning).
_SKIP_WEIGHT_BUMP = 2.0


async def _get_active_users() -> list[tuple[str, object]]:
    """Return (whatsapp_phone, UserContext) for every user to drill.

    V1: single owner from settings.
    V2: replace body — query User table, return one entry per registered user:
        async with async_session_factory() as session:
            users = await UserRepository(session).list_all()
        return [
            (user.whatsapp_phone, UserContext(user.email, user.github_token, user.vault_repo))
            for user in users if user.whatsapp_phone
        ]
    """
    from app.config import settings
    ctx = await get_user_context()
    return [(settings.twilio_to_whatsapp, ctx)]


async def run_morning_drill() -> None:
    """7am IST daily cron. For each active interview:
    1. Mark yesterday's uncompleted plan as skipped (and bump weak_patterns).
    2. Generate today's drill plan.
    3. Idempotency check — skip if already sent today.
    4. Respect 24h WhatsApp window — freeform if inside, template nudge if outside.
    5. Send WhatsApp message and commit plan to prep-vault.
    """
    logger.info("morning_drill.started")
    today = date.today().isoformat()

    for recipient, ctx in await _get_active_users():
        # V2: pass user_email=ctx.email to filter interviews per user.
        async with async_session_factory() as session:
            interviews = await InterviewRepository(session).list_active()

        if not interviews:
            logger.info("morning_drill.no_active_interviews", recipient=recipient)
            continue

        for interview in interviews:
            try:
                await _process_interview(
                    interview_id=interview.id,
                    company=interview.company,
                    role=interview.role,
                    round_type=interview.round_type,
                    recipient=recipient,
                    today=today,
                    github_token=ctx.github_token,
                    vault_repo=ctx.vault_repo,
                )
            except Exception as exc:
                logger.error(
                    "morning_drill.interview_failed",
                    interview_id=interview.id,
                    company=interview.company,
                    error=str(exc),
                    exc_info=True,
                )

    logger.info("morning_drill.done")


async def _process_interview(
    interview_id: int,
    company: str,
    role: str,
    round_type: str | None,
    recipient: str,
    today: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> None:
    round_types = [round_type] if round_type else []
    # Step 1: mark yesterday's uncompleted plan as skipped.
    await _mark_yesterday_skipped(interview_id)

    # Step 2: idempotency check — skip if already sent today for this interview.
    # Must come before generate_plan so a redeploy mid-day doesn't write a duplicate PrepPlan row.
    idempotency_key = make_key(today, recipient, str(interview_id))
    async with async_session_factory() as session:
        already_sent = await OutboundIdempotencyRepository(session).exists(idempotency_key)

    if already_sent:
        logger.info("morning_drill.already_sent", interview_id=interview_id)
        return

    # Step 3: generate today's plan (uses weak_patterns from DB).
    async with async_session_factory() as session:
        wp_repo = WeakPatternRepository(session)
        top_patterns = await wp_repo.top_patterns(limit=5)
        weak_pattern_labels = [p.pattern for p in top_patterns]

        recent_plans = await PrepPlanRepository(session).recent_completed(
            interview_id=interview_id, days=7
        )
        exclude_recent = [p.drill_label for p in recent_plans if p.drill_label]

    plan_md = await generate_plan(
        interview_id=interview_id,
        company=company,
        role=role,
        round_types=round_types,
        weak_patterns=weak_pattern_labels,
        exclude_recent=exclude_recent,
    )

    # Step 4: commit to prep-vault, then save plan to DB with vault path.
    vault_path_str = f"plans/{company.lower().replace(' ', '-')}-{today}.md"
    committed_path: str | None = None
    try:
        await commit_file(
            path=vault_path_str,
            content=plan_md,
            message=f"drill: {company} — {today}",
            github_token=github_token,
            vault_repo=vault_repo,
        )
        committed_path = vault_path_str
    except Exception as exc:
        logger.warning("morning_drill.vault_commit_failed", path=vault_path_str, error=str(exc), exc_info=True)

    async with async_session_factory() as session:
        plan = await PrepPlanRepository(session).create(
            interview_id=interview_id,
            vault_path=committed_path,
            drill_label=_first_heading(plan_md),
        )
        plan_id = plan.id

    # Step 6: check 24h WhatsApp window and send.
    async with async_session_factory() as session:
        within_window = await WaWindowRepository(session).is_within_window(recipient)

    preview = plan_md[:400].rstrip() + "…"
    message = (
        f"Good morning! Today's prep — {company} ({round_type or 'general'}):\n\n"
        f"{preview}\n\n"
        "Reply done easy / done medium / done hard when finished."
    )

    sid = None
    try:
        if within_window:
            chunks = chunk_message(message)
            for chunk in chunks:
                sid = await send_whatsapp(to=recipient, body=chunk)
        else:
            # Outside 24h window — send a template nudge.
            # Using freeform with a shorter message; production should use an approved template SID.
            # Twilio Sandbox accepts freeform regardless of window for sandbox numbers.
            sid = await send_whatsapp(
                to=recipient,
                body=f"Your {company} prep drill is ready in prep-vault. Reply 'done easy/medium/hard' when finished.",
            )
    except Exception as exc:
        logger.error("morning_drill.send_failed", interview_id=interview_id, error=str(exc), exc_info=True)

    # Step 7: record idempotency. Use status='send_failed' so a transient send error
    # doesn't permanently block the next cron run from retrying.
    try:
        async with async_session_factory() as session:
            await OutboundIdempotencyRepository(session).record(
                key=idempotency_key,
                status="sent" if sid else "send_failed",
            )
    except Exception as exc:
        logger.error("morning_drill.idempotency_record_failed", key=idempotency_key, error=str(exc), exc_info=True)

    logger.info(
        "morning_drill.sent",
        interview_id=interview_id,
        company=company,
        plan_id=plan_id,
        within_window=within_window,
    )


async def _mark_yesterday_skipped(interview_id: int) -> None:
    """Find yesterday's uncompleted plan and mark it skipped, bumping weak_patterns."""
    yesterday_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    yesterday_end = yesterday_start + timedelta(days=1)

    async with async_session_factory() as session:
        result = await session.execute(
            select(PrepPlan).where(
                PrepPlan.interview_id == interview_id,
                PrepPlan.generated_at >= yesterday_start,
                PrepPlan.generated_at < yesterday_end,
                PrepPlan.completed_at.is_(None),
                PrepPlan.skipped.is_(False),
            )
        )
        plans = list(result.scalars().all())

        for plan in plans:
            plan.skipped = True
            pattern = plan.drill_label
            if pattern:
                await WeakPatternRepository(session).upsert(
                    pattern=f"{pattern} (skipped)",
                    weight_bump=_SKIP_WEIGHT_BUMP,
                    session_id=None,
                )
                logger.info("morning_drill.plan_skipped", plan_id=plan.id, pattern=pattern)
        await session.commit()


def _first_heading(plan_md: str) -> str | None:
    """Extract the first ### heading from a plan as a label for weak_patterns."""
    for line in plan_md.splitlines():
        if line.strip().startswith("### "):
            return line.strip().lstrip("# ").strip()
    return None
