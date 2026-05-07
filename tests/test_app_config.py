"""Tests for app_config — TTL cache, DB failure fallback, stampede prevention."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reset(module):
    """Reset module-level cache state between tests."""
    module._cache = {}
    module._cache_loaded_at = 0.0


# ---------------------------------------------------------------------------
# Cache miss — fresh load from DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_db_value_on_cache_miss():
    import app.lib.app_config as cfg
    _reset(cfg)

    mock_row = MagicMock()
    mock_row.key = "llm.primary_provider"
    mock_row.value = "gemini"

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=[mock_row])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.primary_provider")

    assert result == "gemini"


# ---------------------------------------------------------------------------
# Cache hit — no DB query within TTL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_skips_db_query():
    import app.lib.app_config as cfg
    _reset(cfg)

    cfg._cache = {"llm.primary_provider": "anthropic"}
    cfg._cache_loaded_at = time.monotonic()  # just loaded

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.primary_provider")

    mock_session.execute.assert_not_awaited()
    assert result == "anthropic"


# ---------------------------------------------------------------------------
# Cache miss after TTL expiry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_refreshed_after_ttl():
    import app.lib.app_config as cfg
    _reset(cfg)

    cfg._cache = {"llm.primary_provider": "anthropic"}
    cfg._cache_loaded_at = time.monotonic() - cfg._TTL - 1  # expired

    mock_row = MagicMock()
    mock_row.key = "llm.primary_provider"
    mock_row.value = "gemini"

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=[mock_row])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.primary_provider")

    assert result == "gemini"
    mock_session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# DB failure — falls back to hardcoded defaults
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_falls_back_to_default_when_db_fails():
    import app.lib.app_config as cfg
    _reset(cfg)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB unreachable"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.primary_provider")

    assert result == "anthropic"  # hardcoded default


@pytest.mark.asyncio
async def test_falls_back_to_default_for_fast_provider_when_db_fails():
    import app.lib.app_config as cfg
    _reset(cfg)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB unreachable"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.fast_provider")

    assert result == "gemini"


# ---------------------------------------------------------------------------
# Critical: _cache_loaded_at advances even on DB failure (stampede prevention)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_loaded_at_advances_on_db_failure():
    """DB failure must still advance _cache_loaded_at so the next call doesn't retry immediately."""
    import app.lib.app_config as cfg
    _reset(cfg)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    before = time.monotonic()
    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        await cfg.get("llm.primary_provider")

    # Timestamp must have been set to a value after `before`.
    assert cfg._cache_loaded_at >= before


@pytest.mark.asyncio
async def test_single_db_query_despite_concurrent_calls():
    """Multiple concurrent calls during a cache miss must produce exactly one DB query."""
    import asyncio
    import app.lib.app_config as cfg
    _reset(cfg)

    query_count = 0

    async def _fake_execute(*_args, **_kwargs):
        nonlocal query_count
        await asyncio.sleep(0)  # yield so concurrent coroutines can pile up
        query_count += 1
        row = MagicMock()
        row.key = "llm.primary_provider"
        row.value = "anthropic"
        return [row]

    mock_session = AsyncMock()
    mock_session.execute = _fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        results = await asyncio.gather(*[cfg.get("llm.primary_provider") for _ in range(10)])

    assert query_count == 1
    assert all(r == "anthropic" for r in results)


# ---------------------------------------------------------------------------
# Stale cache preserved on DB failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_cache_kept_on_db_failure():
    """If DB fails after TTL, the stale cached value is returned (not the default)."""
    import app.lib.app_config as cfg
    _reset(cfg)

    cfg._cache = {"llm.primary_provider": "gemini"}
    cfg._cache_loaded_at = time.monotonic() - cfg._TTL - 1  # expired

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB gone"))
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.lib.app_config.async_session_factory", return_value=mock_session):
        result = await cfg.get("llm.primary_provider")

    # Stale "gemini" beats the "anthropic" hardcoded default.
    assert result == "gemini"


# ---------------------------------------------------------------------------
# Unknown key returns empty string (not KeyError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_key_returns_empty_string():
    import app.lib.app_config as cfg
    _reset(cfg)
    cfg._cache = {}
    cfg._cache_loaded_at = time.monotonic()  # fresh, no DB call

    result = await cfg.get("llm.nonexistent_key")
    assert result == ""
