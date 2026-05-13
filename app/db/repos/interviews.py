from datetime import datetime
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Interview


class InterviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        company: str,
        role: str,
        round_type: str | None = None,
        scheduled_for: datetime | None = None,
    ) -> Interview:
        interview = Interview(
            company=company,
            role=role,
            round_type=round_type,
            scheduled_for=scheduled_for,
        )
        self._session.add(interview)
        await self._session.commit()
        await self._session.refresh(interview)
        return interview

    async def find_active_by_company_round(
        self, company: str, round_type: str | None
    ) -> Interview | None:
        conditions = [func.lower(Interview.company) == company.lower()]
        if round_type is not None:
            conditions.append(func.lower(Interview.round_type) == round_type.lower())
        else:
            conditions.append(Interview.round_type.is_(None))
        result = await self._session.execute(
            select(Interview).where(*conditions).order_by(Interview.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Interview]:
        result = await self._session.execute(
            select(Interview).where(
                or_(
                    Interview.scheduled_for.is_(None),
                    Interview.scheduled_for >= func.current_date(),
                )
            )
        )
        return list(result.scalars().all())

    async def update_scheduled_for(self, id: int, scheduled_for: datetime) -> Interview:
        result = await self._session.execute(select(Interview).where(Interview.id == id))
        interview = result.scalar_one()
        interview.scheduled_for = scheduled_for
        await self._session.commit()
        await self._session.refresh(interview)
        return interview

    async def find_or_create(
        self,
        company: str,
        role: str,
        round_type: str | None,
        scheduled_for: datetime | None,
    ) -> Interview:
        existing = await self.find_active_by_company_round(company, round_type)
        if existing:
            return existing
        return await self.create(company=company, role=role, round_type=round_type, scheduled_for=scheduled_for)

    async def get(self, id: int) -> Interview | None:
        result = await self._session.execute(select(Interview).where(Interview.id == id))
        return result.scalar_one_or_none()
