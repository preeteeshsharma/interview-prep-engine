"""Shared prep execution logic used by both the WhatsApp webhook and the email inbox."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from app.agents.researcher import research as run_research
from app.db.repos.interviews import InterviewRepository
from app.db.repos.prep_plans import PrepPlanRepository
from app.db.session import async_session_factory
from app.integrations.github_client import commit_file
from app.lib.logging import get_logger
from app.lib.user_context import get_user_context
from app.tools.generate_plan import generate_plan
from app.tools.parse_prep_intent import PrepIntent

logger = get_logger(__name__)


def _first_heading(plan_md: str) -> str | None:
    for line in plan_md.splitlines():
        if line.strip().startswith("### "):
            return line.strip().lstrip("# ").strip()
    return None


async def commit_plan_to_vault(
    interview_id: int,
    company: str,
    plan_md: str,
    research: str = "",
    round_label: str | None = None,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> str | None:
    """Commit plan (and research) to vault. Returns plan path on success, None on failure."""
    try:
        company_slug = company.lower().replace(" ", "-")
        round_slug = (round_label or "general").lower().replace(" ", "-")
        epoch = int(time.time())
        base = f"{company_slug}/{round_slug}/{epoch}"
        plan_path = f"{base}-plan.md"
        await commit_file(
            path=plan_path,
            content=plan_md,
            message=f"plan: {company} — {round_label or 'general'} #{interview_id}",
            github_token=github_token,
            vault_repo=vault_repo,
        )
        if research:
            await commit_file(
                path=f"{base}-research.md",
                content=research,
                message=f"research: {company} — {round_label or 'general'} #{interview_id}",
                github_token=github_token,
                vault_repo=vault_repo,
            )
        return plan_path
    except Exception as exc:
        logger.warning("prep.vault_commit_failed", interview_id=interview_id, error=str(exc), exc_info=True)
        return None


async def execute_prep(intent: PrepIntent, refresh: bool = False, user_research: str = "") -> str:
    """Research + plan for a resolved PrepIntent. Used by WhatsApp prep and email inbox."""
    final = intent.with_defaults()
    company = final.company or "Unknown"
    role = final.role
    round_types = final.rounds
    round_label = (final.round_labels or [None])[0]
    single_round_type = round_types[0] if len(round_types) == 1 else None

    if not final.interview_date:
        return "Interview date is required."
    try:
        scheduled_for = datetime.strptime(final.interview_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return f"Couldn't parse date '{final.interview_date}'."

    # Find or create one Interview per round; check idempotency.
    interviews_to_run: list[tuple] = []
    for rt in round_types:
        async with async_session_factory() as session:
            interview = await InterviewRepository(session).find_or_create(
                company=company, role=role, round_type=rt, scheduled_for=scheduled_for,
            )
            pending = await PrepPlanRepository(session).get_pending(interview.id)

        date_changed = (
            interview.scheduled_for
            and interview.scheduled_for.date().isoformat() != final.interview_date
        )
        if pending and not date_changed and not refresh:
            if len(round_types) == 1:
                return (
                    f"Active plan for {interview.company} ({rt}) already exists.\n"
                    f"Send 'done {company.lower()} {rt.lower()} easy/medium/hard' to complete it, "
                    f"or 'prep {company.lower()} {rt.lower()} {final.interview_date} refresh' to regenerate."
                )
            continue
        interviews_to_run.append((interview, rt))

    if not interviews_to_run:
        return f"All rounds for {company} already have active plans. Send 'done' when finished."

    ctx = await get_user_context()
    first_interview = interviews_to_run[0][0]
    effective_role = first_interview.role if first_interview.role != "Unknown" else role

    if user_research:
        research = user_research
        logger.info("execute_prep.user_research", company=company, chars=len(research))
    else:
        research = await run_research(company, effective_role, round_type=single_round_type, round_label=round_label)
    plan_md = await generate_plan(
        interview_id=first_interview.id,
        company=company,
        role=effective_role,
        round_types=round_types,
        research_context=research,
        days_until_interview=final.days_until_interview or 7,
    )
    vault_path = await commit_plan_to_vault(
        first_interview.id, company, plan_md, research,
        round_label=round_label or single_round_type,
        github_token=ctx.github_token,
        vault_repo=ctx.vault_repo,
    )
    drill_label = _first_heading(plan_md)

    for interview, _ in interviews_to_run:
        async with async_session_factory() as session:
            await PrepPlanRepository(session).create(
                interview_id=interview.id,
                vault_path=vault_path,
                drill_label=drill_label,
            )

    date_str = f" on {final.interview_date}" if final.interview_date else ""
    rounds_str = " + ".join(round_types)
    return f"Plan for {company} ({role}) — {rounds_str}{date_str}:\n\n{plan_md[:1200]}…\n\n(Full plan + sources in prep-vault)"
