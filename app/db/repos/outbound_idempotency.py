from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboundIdempotency


class OutboundIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, key: str, message_sid: str, status: str = "sent") -> OutboundIdempotency:
        record = OutboundIdempotency(
            idempotency_key=key,
            message_sid=message_sid,
            sent_at=datetime.now(timezone.utc),
            status=status,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def exists(self, key: str) -> bool:
        """Return True only if a successful send was recorded (status='sent').

        A 'send_failed' record does NOT block retry — the next cron run will attempt again.
        """
        result = await self._session.execute(
            select(OutboundIdempotency).where(
                OutboundIdempotency.idempotency_key == key,
                OutboundIdempotency.status == "sent",
            )
        )
        return result.scalar_one_or_none() is not None
