from datetime import datetime
from sqlalchemy import func, select
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
            conditions.append(Interview.round_type == round_type)
        else:
            conditions.append(Interview.round_type.is_(None))
        result = await self._session.execute(
            select(Interview).where(*conditions).order_by(Interview.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Interview]:
        result = await self._session.execute(select(Interview))
        return list(result.scalars().all())

    async def get(self, id: int) -> Interview | None:
        result = await self._session.execute(select(Interview).where(Interview.id == id))
        return result.scalar_one_or_none()
