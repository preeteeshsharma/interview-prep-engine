from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WeakPattern


class WeakPatternRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, pattern: str, weight_bump: float, session_id: int | None = None) -> WeakPattern:
        result = await self._session.execute(
            select(WeakPattern).where(WeakPattern.pattern == pattern)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.weight += weight_bump
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        wp = WeakPattern(pattern=pattern, weight=weight_bump)
        self._session.add(wp)
        await self._session.commit()
        await self._session.refresh(wp)
        return wp

    async def top_patterns(self, limit: int = 10) -> list[WeakPattern]:
        result = await self._session.execute(
            select(WeakPattern).order_by(WeakPattern.weight.desc()).limit(limit)
        )
        return list(result.scalars().all())
