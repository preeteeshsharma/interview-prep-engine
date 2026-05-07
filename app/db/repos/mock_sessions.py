from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MockSession


class MockSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, interview_id: int, round_type: str) -> MockSession:
        mock = MockSession(
            interview_id=interview_id,
            round_type=round_type,
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(mock)
        await self._session.commit()
        await self._session.refresh(mock)
        return mock

    async def update_transcript(self, id: int, transcript_json: str) -> MockSession:
        result = await self._session.execute(select(MockSession).where(MockSession.id == id))
        session = result.scalar_one()
        session.transcript_json = transcript_json
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def finalize(
        self, id: int, rubric_json: str, critique_json: str
    ) -> MockSession:
        result = await self._session.execute(select(MockSession).where(MockSession.id == id))
        session = result.scalar_one()
        session.ended_at = datetime.now(timezone.utc)
        session.rubric_json = rubric_json
        session.critique_json = critique_json
        await self._session.commit()
        await self._session.refresh(session)
        return session
