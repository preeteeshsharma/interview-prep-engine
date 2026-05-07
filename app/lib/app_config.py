"""Runtime config backed by app_config table. Cached with 60s TTL.

Update values directly in Supabase dashboard — changes propagate within 60s.

Keys:
  llm.primary_provider  anthropic | gemini   (quality calls)
  llm.fast_provider     gemini | anthropic    (classification/parsing calls)
"""
from __future__ import annotations

import time
from sqlalchemy import text

from app.db.session import async_session_factory
from app.lib.logging import get_logger

logger = get_logger(__name__)

_TTL = 60  # seconds

_cache: dict[str, str] = {}
_cache_loaded_at: float = 0.0

_DEFAULTS: dict[str, str] = {
    "llm.primary_provider": "anthropic",
    "llm.fast_provider": "gemini",
}


async def get(key: str) -> str:
    global _cache, _cache_loaded_at

    if time.monotonic() - _cache_loaded_at > _TTL:
        try:
            async with async_session_factory() as session:
                rows = await session.execute(text("SELECT key, value FROM app_config"))
                _cache = {row.key: row.value for row in rows}
                _cache_loaded_at = time.monotonic()
        except Exception as exc:
            logger.warning("app_config.load_failed", error=str(exc))
            # Keep stale cache or use defaults — never crash on config read

    return _cache.get(key) or _DEFAULTS.get(key, "")
