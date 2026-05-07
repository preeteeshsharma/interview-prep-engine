from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PrepPlan


class PrepPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        interview_id: int,
        plan_md: str,
        time_budget_min: int,
    ) -> PrepPlan:
        plan = PrepPlan(
            interview_id=interview_id,
            plan_md=plan_md,
            time_budget_min=time_budget_min,
            generated_at=datetime.now(timezone.utc),
        )
        self._session.add(plan)
        await self._session.commit()
        await self._session.refresh(plan)
        return plan

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
