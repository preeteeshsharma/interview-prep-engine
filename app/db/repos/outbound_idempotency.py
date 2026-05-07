from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboundIdempotency


class OutboundIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, key: str, message_sid: str) -> OutboundIdempotency:
        record = OutboundIdempotency(
            idempotency_key=key,
            message_sid=message_sid,
            sent_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def exists(self, key: str) -> bool:
        result = await self._session.execute(
            select(OutboundIdempotency).where(OutboundIdempotency.idempotency_key == key)
        )
        return result.scalar_one_or_none() is not None
