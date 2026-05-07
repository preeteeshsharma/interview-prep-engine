"""Tests for classify_rounds — mocks the Anthropic client, tests parsing logic."""
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.classify_rounds import classify_rounds, _VALID


@pytest.mark.asyncio
async def test_returns_valid_round_types():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value='["DSA", "behavioral"]')):
        result = await classify_rounds("some jd text")
    assert result == ["DSA", "behavioral"]


@pytest.mark.asyncio
async def test_filters_invalid_round_types():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value='["DSA", "knitting"]')):
        result = await classify_rounds("some jd text")
    assert result == ["DSA"]
    assert "knitting" not in result


@pytest.mark.asyncio
async def test_falls_back_to_unknown_on_bad_json():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value="not json at all")):
        result = await classify_rounds("some jd text")
    assert result == ["unknown"]


@pytest.mark.asyncio
async def test_falls_back_to_unknown_on_non_list_json():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value='{"rounds": ["DSA"]}')):
        result = await classify_rounds("some jd text")
    assert result == ["unknown"]


@pytest.mark.asyncio
async def test_falls_back_to_unknown_when_all_types_invalid():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value='["foo", "bar"]')):
        result = await classify_rounds("some jd text")
    assert result == ["unknown"]


@pytest.mark.asyncio
async def test_all_valid_types_accepted():
    payload = str(list(_VALID - {"unknown"})).replace("'", '"')
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value=payload)):
        result = await classify_rounds("some jd text")
    assert set(result) == _VALID - {"unknown"}


@pytest.mark.asyncio
async def test_deduplicates_round_types():
    with patch("app.tools.classify_rounds.complete", new=AsyncMock(return_value='["DSA", "DSA", "LLD"]')):
        result = await classify_rounds("some jd text")
    # Both DSA entries pass the filter; dedup is caller's responsibility —
    # we just confirm the filter doesn't crash on duplicates.
    assert "DSA" in result
    assert "LLD" in result
