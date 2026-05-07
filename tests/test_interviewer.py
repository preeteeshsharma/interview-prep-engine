"""Tests for Interviewer agent — validates the no-duplicate-user-message fix."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.interviewer import Interviewer, _transcript_to_messages


# ---------------------------------------------------------------------------
# _transcript_to_messages
# ---------------------------------------------------------------------------

def test_transcript_to_messages_maps_roles():
    transcript = [
        {"role": "interviewer", "content": "Tell me about yourself.", "turn": 0},
        {"role": "candidate", "content": "Sure, I've been...", "turn": 1},
        {"role": "interviewer", "content": "What was the hardest part?", "turn": 2},
    ]
    messages = _transcript_to_messages(transcript)
    assert messages[0] == {"role": "assistant", "content": "Tell me about yourself."}
    assert messages[1] == {"role": "user", "content": "Sure, I've been..."}
    assert messages[2] == {"role": "assistant", "content": "What was the hardest part?"}


def test_transcript_to_messages_no_extra_user_append():
    """Regression: next_turn must NOT append the candidate's message again.

    The transcript already contains the candidate turn at the end.
    _transcript_to_messages converts it to role=user. next_turn must not
    also call messages.append({"role": "user", ...}) or the API receives
    two consecutive user messages and returns an error.
    """
    transcript = [
        {"role": "interviewer", "content": "What is a deadlock?", "turn": 0},
        {"role": "candidate", "content": "A deadlock happens when...", "turn": 1},
    ]
    messages = _transcript_to_messages(transcript)
    # Last message must be role=user (candidate), not another appended user message.
    assert messages[-1]["role"] == "user"
    assert len(messages) == 2  # exactly one message per transcript turn


def test_no_consecutive_same_roles():
    """Messages must alternate assistant/user — no two consecutive same roles."""
    transcript = [
        {"role": "interviewer", "content": "Q1", "turn": 0},
        {"role": "candidate", "content": "A1", "turn": 1},
        {"role": "interviewer", "content": "Q2", "turn": 2},
        {"role": "candidate", "content": "A2", "turn": 3},
    ]
    messages = _transcript_to_messages(transcript)
    for i in range(len(messages) - 1):
        assert messages[i]["role"] != messages[i + 1]["role"], (
            f"Consecutive same roles at positions {i} and {i+1}: {messages[i]['role']}"
        )


# ---------------------------------------------------------------------------
# Interviewer.start_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_session_returns_question():
    raw = json.dumps({
        "question": "Design a parking lot system.",
        "follow_up_hints": [],
        "missing_justifications": [],
    })
    with patch("app.agents.interviewer.complete", new=AsyncMock(return_value=raw)):
        result = await Interviewer().start_session("lld", "Stripe", "Backend Engineer")
    assert result == "Design a parking lot system."


@pytest.mark.asyncio
async def test_start_session_falls_back_on_bad_json():
    with patch("app.agents.interviewer.complete", new=AsyncMock(return_value="Let's start.")):
        result = await Interviewer().start_session("behavioral", "Zapier", "SWE")
    assert result == "Let's start."


# ---------------------------------------------------------------------------
# Interviewer.next_turn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_next_turn_no_user_reply_param():
    """next_turn signature must not accept user_reply — confirm the blocker fix."""
    import inspect
    sig = inspect.signature(Interviewer.next_turn)
    assert "user_reply" not in sig.parameters, (
        "user_reply param was re-added to next_turn — this causes duplicate user messages"
    )


@pytest.mark.asyncio
async def test_next_turn_passes_transcript_messages_without_duplication():
    """Messages sent to the API must not duplicate the final candidate turn."""
    transcript = [
        {"role": "interviewer", "content": "What is a mutex?", "turn": 0},
        {"role": "candidate", "content": "It's a lock that...", "turn": 1},
    ]
    captured = {}

    async def mock_complete(**kwargs):
        captured["messages"] = kwargs["messages"]
        return json.dumps({
            "question": "Follow-up question",
            "follow_up_hints": [],
            "missing_justifications": [],
        })

    with patch("app.agents.interviewer.complete", new=mock_complete):
        await Interviewer().next_turn(transcript, "dsa")

    msgs = captured["messages"]
    assert len(msgs) == 2
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "It's a lock that..."
    # Crucially: no second user message appended after
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
async def test_next_turn_returns_turn_output():
    raw = json.dumps({
        "question": "What about time complexity?",
        "follow_up_hints": ["think two-pointer"],
        "missing_justifications": ["space complexity not addressed"],
    })
    transcript = [
        {"role": "interviewer", "content": "Explain BFS.", "turn": 0},
        {"role": "candidate", "content": "BFS uses a queue...", "turn": 1},
    ]
    with patch("app.agents.interviewer.complete", new=AsyncMock(return_value=raw)):
        result = await Interviewer().next_turn(transcript, "dsa")

    assert result.question == "What about time complexity?"
    assert result.follow_up_hints == ["think two-pointer"]
    assert result.missing_justifications == ["space complexity not addressed"]


@pytest.mark.asyncio
async def test_next_turn_falls_back_on_bad_json():
    transcript = [
        {"role": "interviewer", "content": "Q", "turn": 0},
        {"role": "candidate", "content": "A", "turn": 1},
    ]
    with patch("app.agents.interviewer.complete", new=AsyncMock(return_value="Not JSON")):
        result = await Interviewer().next_turn(transcript, "behavioral")
    assert result.question == "Not JSON"
    assert result.follow_up_hints == []
