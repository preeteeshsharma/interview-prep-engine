from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WaWindowState
from app.lib.wa_window import is_within_24h


class WaWindowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_or_create(self, recipient_e164: str) -> WaWindowState:
        result = await self._session.execute(
            select(WaWindowState).where(WaWindowState.recipient_e164 == recipient_e164)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = WaWindowState(recipient_e164=recipient_e164)
            self._session.add(state)
            await self._session.flush()
        return state

    async def record_inbound(self, recipient_e164: str) -> WaWindowState:
        state = await self._get_or_create(recipient_e164)
        state.last_inbound_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(state)
        return state

    async def record_template_sent(self, recipient_e164: str) -> WaWindowState:
        state = await self._get_or_create(recipient_e164)
        state.last_template_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(state)
        return state

    async def is_within_window(self, recipient_e164: str) -> bool:
        """Return True if last_inbound_at is within 24 hours."""
        result = await self._session.execute(
            select(WaWindowState).where(WaWindowState.recipient_e164 == recipient_e164)
        )
        state = result.scalar_one_or_none()
        return is_within_24h(state.last_inbound_at if state else None)
