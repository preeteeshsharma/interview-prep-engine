import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Interview


class InterviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        company: str,
        role: str,
        round_types: list[str],
        scheduled_for: datetime | None = None,
    ) -> Interview:
        interview = Interview(
            company=company,
            role=role,
            round_types=json.dumps(round_types),
            scheduled_for=scheduled_for,
            status="active",
        )
        self._session.add(interview)
        await self._session.commit()
        await self._session.refresh(interview)
        return interview

    async def list_active(self, user_email: str | None = None) -> list[Interview]:
        # user_email filter added in V2 after adding user_email FK column + migration.
        query = select(Interview).where(Interview.status == "active")
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get(self, id: int) -> Interview | None:
        result = await self._session.execute(select(Interview).where(Interview.id == id))
        return result.scalar_one_or_none()
