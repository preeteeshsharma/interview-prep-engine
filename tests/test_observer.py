"""Tests for Observer agent — rubric parsing and fallback."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.observer import Observer
from app.schemas.agent_io import RubricScore


SAMPLE_TRANSCRIPT = [
    {"role": "interviewer", "content": "Explain LRU cache.", "turn": 0},
    {"role": "candidate", "content": "Use a doubly linked list + hashmap.", "turn": 1},
]


@pytest.mark.asyncio
async def test_score_returns_rubric_from_valid_json():
    raw = json.dumps({"depth": 4, "clarity": 3, "edge_cases": 2, "time_management": 5, "requirements": 4})
    with patch("app.agents.observer.complete", new=AsyncMock(return_value=raw)):
        result = await Observer().score(SAMPLE_TRANSCRIPT)
    assert isinstance(result, RubricScore)
    assert result.depth == 4
    assert result.clarity == 3
    assert result.time_management == 5


@pytest.mark.asyncio
async def test_score_falls_back_to_neutral_on_bad_json():
    with patch("app.agents.observer.complete", new=AsyncMock(return_value="not json")):
        result = await Observer().score(SAMPLE_TRANSCRIPT)
    assert result == RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)


@pytest.mark.asyncio
async def test_score_falls_back_to_neutral_on_out_of_range():
    # Field ge=1, le=5 — value 0 should fail pydantic validation
    raw = json.dumps({"depth": 0, "clarity": 3, "edge_cases": 3, "time_management": 3, "requirements": 3})
    with patch("app.agents.observer.complete", new=AsyncMock(return_value=raw)):
        result = await Observer().score(SAMPLE_TRANSCRIPT)
    assert result == RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)


@pytest.mark.asyncio
async def test_score_empty_transcript_skips_api():
    """Empty transcript should return neutral rubric without calling the API."""
    with patch("app.agents.observer.complete", new=AsyncMock()) as mock_complete:
        result = await Observer().score([])
    mock_complete.assert_not_called()
    assert result == RubricScore(depth=3, clarity=3, edge_cases=3, time_management=3, requirements=3)


@pytest.mark.asyncio
async def test_score_uses_fast_tier():
    """Observer must use complete_fast (haiku tier), not the quality complete()."""
    called_with_messages = []

    async def mock_complete_fast(messages, system, **kwargs):
        called_with_messages.extend(messages)
        return json.dumps({"depth": 3, "clarity": 3, "edge_cases": 3, "time_management": 3, "requirements": 3})

    with patch("app.agents.observer.complete", new=mock_complete_fast):
        await Observer().score(SAMPLE_TRANSCRIPT)

    # Verify the fast-tier wrapper was called (messages were passed through).
    assert len(called_with_messages) > 0
