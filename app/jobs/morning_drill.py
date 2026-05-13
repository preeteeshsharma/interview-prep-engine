from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import PrepPlan
from app.db.repos.interviews import InterviewRepository
from app.db.repos.outbound_idempotency import OutboundIdempotencyRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.repos.wa_window import WaWindowRepository
from app.db.repos.weak_patterns import WeakPatternRepository
from app.db.session import async_session_factory
from app.integrations.github_client import load_vault_context
from app.integrations.twilio_client import send_whatsapp
from app.lib.chunker import chunk_message
from app.lib.idempotency import make_key
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.tools.generate_plan import generate_plan

logger = get_logger(__name__)

_SKIP_WEIGHT_BUMP = 2.0


async def _get_active_users() -> list[tuple[str, object]]:
    """Return (whatsapp_phone, UserContext) for every user to drill.

    V1: single owner from settings.
    V2: replace body — query User table, return one entry per registered user.
    """
    from app.config import settings
    ctx = await get_user_context()
    return [(settings.twilio_to_whatsapp, ctx)]


async def run_morning_drill() -> None:
    """7am IST daily cron. Groups interviews by company and sends one message per company."""
    logger.info("morning_drill.started")
    today = date.today().isoformat()

    for recipient, ctx in await _get_active_users():
        async with async_session_factory() as session:
            interviews = await InterviewRepository(session).list_active()

        if not interviews:
            logger.info("morning_drill.no_active_interviews", recipient=recipient)
            continue

        by_company: dict[str, list] = defaultdict(list)
        for interview in interviews:
            by_company[interview.company].append(interview)

        for company, company_interviews in by_company.items():
            try:
                await _process_company(
                    company=company,
                    interviews=company_interviews,
                    recipient=recipient,
                    today=today,
                    github_token=ctx.github_token,
                    vault_repo=ctx.vault_repo,
                )
            except Exception as exc:
                logger.error(
                    "morning_drill.company_failed",
                    company=company,
                    error=str(exc),
                    exc_info=True,
                )

    logger.info("morning_drill.done")


async def _process_company(
    company: str,
    interviews: list,
    recipient: str,
    today: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> None:
    """Generate and send the daily drill for all rounds of one company in a single message."""
    # Idempotency key is per-company so multiple round rows don't fire duplicate messages.
    idempotency_key = make_key(today, recipient, company.lower())
    async with async_session_factory() as session:
        already_sent = await OutboundIdempotencyRepository(session).exists(idempotency_key)

    if already_sent:
        logger.info("morning_drill.already_sent", company=company)
        return

    # Mark yesterday's uncompleted plans as skipped for all rounds.
    for interview in interviews:
        await _mark_yesterday_skipped(interview.id)

    # Collect weak patterns and recent completions across all rounds for this company.
    async with async_session_factory() as session:
        wp_repo = WeakPatternRepository(session)
        top_patterns = await wp_repo.top_patterns(limit=5)
        weak_pattern_labels = [p.pattern for p in top_patterns]

    # Build daily content per round, then combine into one message.
    sections: list[str] = []
    plan_ids: list[int] = []
    all_round_types: list[str] = []

    for interview in interviews:
        round_type = interview.round_type
        if round_type:
            all_round_types.append(round_type)

        section_md, plan_id = await _build_round_section(
            interview=interview,
            company=company,
            today=today,
            weak_pattern_labels=weak_pattern_labels,
            github_token=github_token,
            vault_repo=vault_repo,
        )
        if section_md:
            sections.append(section_md)
        if plan_id:
            plan_ids.append(plan_id)

    if not sections:
        logger.warning("morning_drill.no_content", company=company)
        return

    combined_plan_md = "\n\n---\n\n".join(sections)
    rounds_str = " + ".join(all_round_types) if all_round_types else "general"

    async with async_session_factory() as session:
        within_window = await WaWindowRepository(session).is_within_window(recipient)

    preview = combined_plan_md[:400].rstrip() + "…"
    message = (
        f"Good morning! Today's prep — {company} ({rounds_str}):\n\n"
        f"{preview}\n\n"
        "Reply done easy / done medium / done hard when finished."
    )

    sid = None
    try:
        if within_window:
            for chunk in chunk_message(message):
                sid = await send_whatsapp(to=recipient, body=chunk)
        else:
            sid = await send_whatsapp(
                to=recipient,
                body=f"Your {company} prep drill is ready in prep-vault. Reply 'done easy/medium/hard' when finished.",
            )
    except Exception as exc:
        logger.error("morning_drill.send_failed", company=company, error=str(exc), exc_info=True)

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
        company=company,
        plan_ids=plan_ids,
        within_window=within_window,
    )


async def _build_round_section(
    interview,
    company: str,
    today: str,
    weak_pattern_labels: list[str],
    github_token: str | None,
    vault_repo: str | None,
) -> tuple[str | None, int | None]:
    """Return (plan_md_section, plan_id) for one interview/round.

    Tries to extract Day N from the structured vault plan. Falls back to generate_plan
    with vault context if the vault plan is exhausted or missing.
    """
    interview_id = interview.id
    round_type = interview.round_type
    role = interview.role

    days_until = _days_until(interview.scheduled_for)

    # Attempt to serve Day N from the vault plan committed during `prep`.
    async with async_session_factory() as session:
        structured = await PrepPlanRepository(session).get_structured(interview_id)

    plan_md: str | None = None
    vault_research: str | None = None

    if structured and structured.vault_path:
        parts = structured.vault_path.split("/")
        if len(parts) == 3:
            company_slug, round_slug = parts[0], parts[1]
            try:
                vault_research, vault_plan = await load_vault_context(
                    company_slug, round_slug,
                    github_token=github_token, vault_repo=vault_repo,
                )
                if vault_plan:
                    day_number = (date.today() - structured.generated_at.date()).days + 1
                    plan_md = _extract_day_section(vault_plan, day_number)
                    if plan_md:
                        logger.info(
                            "morning_drill.vault_day_extracted",
                            interview_id=interview_id, day=day_number,
                        )
            except Exception as exc:
                logger.warning(
                    "morning_drill.vault_load_failed",
                    interview_id=interview_id, error=str(exc), exc_info=True,
                )

    if not plan_md:
        # Vault plan exhausted or missing — generate fresh using vault research as context.
        async with async_session_factory() as session:
            recent_plans = await PrepPlanRepository(session).recent_completed(
                interview_id=interview_id, days=7
            )
        exclude_recent = [p.drill_label for p in recent_plans if p.drill_label]

        plan_md = await generate_plan(
            interview_id=interview_id,
            company=company,
            role=role,
            round_types=[round_type] if round_type else [],
            weak_patterns=weak_pattern_labels,
            exclude_recent=exclude_recent,
            days_until_interview=days_until,
            research_context=vault_research or "",
        )

    # Record a PrepPlan row for completion tracking. Point at the structured plan so
    # _get_vault_round always receives a 3-segment vault path.
    vault_path_for_db = structured.vault_path if structured else None

    async with async_session_factory() as session:
        plan = await PrepPlanRepository(session).create(
            interview_id=interview_id,
            vault_path=vault_path_for_db,
            drill_label=_first_heading(plan_md),
        )

    return plan_md, plan.id


def _days_until(scheduled_for: datetime | None) -> int:
    if not scheduled_for:
        return 7
    return max(0, (scheduled_for.date() - date.today()).days)


def _extract_day_section(plan_md: str, day_number: int) -> str | None:
    """Extract the '## Day N' section from a vault plan. Returns None if not found."""
    pattern = re.compile(r"^## Day \d+", re.MULTILINE)
    matches = list(pattern.finditer(plan_md))

    target_header = f"## Day {day_number}"
    for i, match in enumerate(matches):
        if plan_md[match.start():match.start() + len(target_header)] == target_header:
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_md)
            return plan_md[start:end].strip()

    return None


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
    for line in plan_md.splitlines():
        if line.strip().startswith("### "):
            return line.strip().lstrip("# ").strip()
    return None
