"""Tests for llm_client fast tier and DB-driven provider switching.

Covers:
- complete_fast: uses fast provider, falls back on failure
- complete_fast_with_tools: same fallback contract
- _primary() / _fast(): get_config("llm.*_provider") controls which provider is selected
- Both tiers: fallback failure is re-raised (not swallowed)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# complete_fast — uses fast provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_fast_uses_fast_provider(monkeypatch):
    import app.integrations.llm_client as facade

    mock_fast = MagicMock()
    mock_fast.complete = AsyncMock(return_value="fast answer")
    mock_slow = MagicMock()
    mock_slow.complete = AsyncMock(return_value="slow answer")

    monkeypatch.setattr(facade, "_gemini", mock_fast)
    monkeypatch.setattr(facade, "_anthropic", mock_slow)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete_fast([{"role": "user", "content": "hi"}], "sys")

    assert result == "fast answer"
    mock_fast.complete.assert_awaited_once()
    mock_slow.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_fast_falls_back_on_primary_failure(monkeypatch):
    import app.integrations.llm_client as facade

    mock_fast = MagicMock()
    mock_fast.complete = AsyncMock(side_effect=RuntimeError("quota exceeded"))
    mock_fallback = MagicMock()
    mock_fallback.complete = AsyncMock(return_value="fallback answer")

    monkeypatch.setattr(facade, "_gemini", mock_fast)
    monkeypatch.setattr(facade, "_anthropic", mock_fallback)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete_fast([{"role": "user", "content": "hi"}], "sys")

    assert result == "fallback answer"
    mock_fallback.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_fast_raises_when_both_providers_fail(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(side_effect=RuntimeError("gemini down"))
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(side_effect=RuntimeError("anthropic down"))

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        with pytest.raises(RuntimeError, match="anthropic down"):
            await facade.complete_fast([{"role": "user", "content": "hi"}], "sys")


# ---------------------------------------------------------------------------
# complete_fast_with_tools — same fallback contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_fast_with_tools_uses_fast_provider(monkeypatch):
    import app.integrations.llm_client as facade

    mock_fast = MagicMock()
    mock_fast.complete_with_tools = AsyncMock(return_value="fast tools answer")
    mock_slow = MagicMock()
    mock_slow.complete_with_tools = AsyncMock(return_value="slow tools answer")

    monkeypatch.setattr(facade, "_gemini", mock_fast)
    monkeypatch.setattr(facade, "_anthropic", mock_slow)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete_fast_with_tools(
            [{"role": "user", "content": "search"}],
            "sys",
            [{"type": "web_search_20250305", "name": "web_search"}],
        )

    assert result == "fast tools answer"
    mock_fast.complete_with_tools.assert_awaited_once()
    mock_slow.complete_with_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_fast_with_tools_falls_back_on_failure(monkeypatch):
    import app.integrations.llm_client as facade

    mock_fast = MagicMock()
    mock_fast.complete_with_tools = AsyncMock(side_effect=RuntimeError("fast down"))
    mock_fallback = MagicMock()
    mock_fallback.complete_with_tools = AsyncMock(return_value="fallback tools")

    monkeypatch.setattr(facade, "_gemini", mock_fast)
    monkeypatch.setattr(facade, "_anthropic", mock_fallback)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete_fast_with_tools(
            [{"role": "user", "content": "hi"}], "sys", []
        )

    assert result == "fallback tools"


# ---------------------------------------------------------------------------
# DB-driven provider switching via get_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_primary_provider_uses_gemini_when_config_says_gemini(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(return_value="gemini response")
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic response")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "gemini response"
    mock_gemini.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_primary_provider_uses_anthropic_when_config_says_anthropic(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(return_value="gemini response")
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic response")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="anthropic")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "anthropic response"
    mock_anthropic.complete.assert_awaited_once()
    mock_gemini.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_primary_provider_falls_back_to_anthropic_when_gemini_none(monkeypatch):
    """Even if config says 'gemini', if _gemini is None (not configured) use anthropic."""
    import app.integrations.llm_client as facade

    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic only")

    monkeypatch.setattr(facade, "_gemini", None)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        result = await facade.complete([{"role": "user", "content": "hi"}], "sys")

    assert result == "anthropic only"


@pytest.mark.asyncio
async def test_fast_provider_uses_anthropic_when_config_says_anthropic(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(return_value="gemini fast")
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(return_value="anthropic fast")

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="anthropic")):
        result = await facade.complete_fast([{"role": "user", "content": "hi"}], "sys")

    assert result == "anthropic fast"
    mock_anthropic.complete.assert_awaited_once()
    mock_gemini.complete.assert_not_awaited()


# ---------------------------------------------------------------------------
# complete() fallback logs and re-raises when both fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_raises_when_both_providers_fail(monkeypatch):
    import app.integrations.llm_client as facade

    mock_gemini = MagicMock()
    mock_gemini.complete = AsyncMock(side_effect=RuntimeError("gemini down"))
    mock_anthropic = MagicMock()
    mock_anthropic.complete = AsyncMock(side_effect=RuntimeError("anthropic down"))

    monkeypatch.setattr(facade, "_gemini", mock_gemini)
    monkeypatch.setattr(facade, "_anthropic", mock_anthropic)

    with patch("app.integrations.llm_client.get_config", new=AsyncMock(return_value="gemini")):
        with pytest.raises(RuntimeError, match="anthropic down"):
            await facade.complete([{"role": "user", "content": "hi"}], "sys")
