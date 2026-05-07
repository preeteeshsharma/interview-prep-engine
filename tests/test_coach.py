"""Tests for Coach agent — quote_offset validation and retry logic."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.coach import Coach, _MAX_RETRIES
from app.schemas.agent_io import Critique, RubricScore


RUBRIC = RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)

TRANSCRIPT = [
    {"role": "interviewer", "content": "Design a URL shortener.", "turn": 0},
    {"role": "candidate", "content": "I'd use a hash function...", "turn": 1},
    {"role": "interviewer", "content": "What about collisions?", "turn": 2},
    {"role": "candidate", "content": "We can use base62 encoding...", "turn": 3},
]


def _valid_response(quote_offset: int = 1) -> str:
    return json.dumps({
        "entries": [{"quote_offset": quote_offset, "issue": "Vague on hashing", "suggestion": "Name the algorithm"}],
        "overall_summary": "Good attempt but missed collision handling.",
    })


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_critique_returns_valid_entries():
    with patch("app.agents.coach.complete", new=AsyncMock(return_value=_valid_response(1))):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)
    assert isinstance(result, Critique)
    assert len(result.entries) == 1
    assert result.entries[0].quote_offset == 1
    assert result.entries[0].issue == "Vague on hashing"
    assert "collision" in result.overall_summary.lower()


@pytest.mark.asyncio
async def test_critique_accepts_all_valid_offsets():
    """Every turn index 0–3 is a valid quote_offset for a 4-turn transcript."""
    raw = json.dumps({
        "entries": [
            {"quote_offset": 0, "issue": "i0", "suggestion": "s0"},
            {"quote_offset": 3, "issue": "i3", "suggestion": "s3"},
        ],
        "overall_summary": "Summary.",
    })
    with patch("app.agents.coach.complete", new=AsyncMock(return_value=raw)):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)
    assert len(result.entries) == 2


# ---------------------------------------------------------------------------
# quote_offset validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_offset_filtered_and_retried():
    """An out-of-range quote_offset triggers a retry on the first attempt."""
    bad = json.dumps({
        "entries": [{"quote_offset": 99, "issue": "bad offset", "suggestion": "fix"}],
        "overall_summary": "Summary.",
    })
    good = _valid_response(2)
    call_count = 0

    async def mock_complete(**kwargs):
        nonlocal call_count
        call_count += 1
        return bad if call_count == 1 else good

    with patch("app.agents.coach.complete", new=mock_complete):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)

    assert call_count == 2
    assert len(result.entries) == 1
    assert result.entries[0].quote_offset == 2


@pytest.mark.asyncio
async def test_invalid_offset_on_final_attempt_returns_valid_subset():
    """On the last retry, valid entries are kept even if some are still invalid."""
    mixed = json.dumps({
        "entries": [
            {"quote_offset": 1, "issue": "valid", "suggestion": "ok"},
            {"quote_offset": 50, "issue": "invalid", "suggestion": "bad"},
        ],
        "overall_summary": "Mixed.",
    })
    # Both attempts return the same mixed response — last attempt keeps valid entries.
    with patch("app.agents.coach.complete", new=AsyncMock(return_value=mixed)):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)

    assert len(result.entries) == 1
    assert result.entries[0].quote_offset == 1


@pytest.mark.asyncio
async def test_negative_offset_is_invalid():
    bad = json.dumps({
        "entries": [{"quote_offset": -1, "issue": "neg", "suggestion": "fix"}],
        "overall_summary": "Summary.",
    })
    good = _valid_response(0)
    responses = iter([bad, good])

    with patch("app.agents.coach.complete", new=AsyncMock(side_effect=responses)):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)

    assert all(e.quote_offset >= 0 for e in result.entries)


# ---------------------------------------------------------------------------
# Retry exhaustion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exhausted_retries_returns_empty_critique():
    """If all attempts fail JSON parse, return empty critique rather than crashing."""
    with patch("app.agents.coach.complete", new=AsyncMock(return_value="not json at all")):
        result = await Coach().critique(TRANSCRIPT, RUBRIC)
    assert result.entries == []
    assert "could not" in result.overall_summary.lower()


@pytest.mark.asyncio
async def test_max_retries_constant():
    assert _MAX_RETRIES == 2
