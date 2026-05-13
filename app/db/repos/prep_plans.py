from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PrepPlan


class PrepPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        interview_id: int,
        vault_path: str | None = None,
        drill_label: str | None = None,
    ) -> PrepPlan:
        # Supersede any existing pending plans for this interview — one active plan per interview.
        await self._session.execute(
            update(PrepPlan)
            .where(
                PrepPlan.interview_id == interview_id,
                PrepPlan.completed_at.is_(None),
                PrepPlan.skipped.is_(False),
            )
            .values(skipped=True)
        )
        plan = PrepPlan(
            interview_id=interview_id,
            vault_path=vault_path,
            drill_label=drill_label,
            generated_at=datetime.now(timezone.utc),
        )
        self._session.add(plan)
        await self._session.commit()
        await self._session.refresh(plan)
        return plan

    async def get_pending(self, interview_id: int) -> PrepPlan | None:
        result = await self._session.execute(
            select(PrepPlan)
            .where(
                PrepPlan.interview_id == interview_id,
                PrepPlan.completed_at.is_(None),
                PrepPlan.skipped.is_(False),
            )
            .order_by(PrepPlan.generated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_complete(self, id: int, rating: str) -> PrepPlan:
        result = await self._session.execute(select(PrepPlan).where(PrepPlan.id == id))
        plan = result.scalar_one()
        plan.completed_at = datetime.now(timezone.utc)
        plan.self_rating = rating
        await self._session.commit()
        await self._session.refresh(plan)
        return plan

    async def mark_skipped(self, id: int) -> PrepPlan:
        result = await self._session.execute(select(PrepPlan).where(PrepPlan.id == id))
        plan = result.scalar_one()
        plan.skipped = True
        await self._session.commit()
        await self._session.refresh(plan)
        return plan

    async def get_structured(self, interview_id: int) -> PrepPlan | None:
        """Return the earliest PrepPlan with a 3-segment vault_path (company/round/epoch-plan.md).

        Daily drill plans use a 2-segment path (plans/company-date.md). This finds the
        original structured plan committed during `prep`, which holds the correct round slug
        and the generation date needed to compute Day N.
        """
        result = await self._session.execute(
            select(PrepPlan)
            .where(
                PrepPlan.interview_id == interview_id,
                PrepPlan.vault_path.like("%/%/%"),
            )
            .order_by(PrepPlan.generated_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def recent_completed(self, interview_id: int, days: int = 7, user_email: str | None = None) -> list[PrepPlan]:
        # user_email filter added in V2 after migration.
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=days)
        result = await self._session.execute(
            select(PrepPlan).where(
                PrepPlan.interview_id == interview_id,
                PrepPlan.completed_at.is_not(None),
                PrepPlan.completed_at >= cutoff,
            )
        )
        return list(result.scalars().all())
