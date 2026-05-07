"""Tests for Twilio intent handlers — mocks DB repos and external calls."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes.webhooks.twilio import (
    _handle_done,
    _handle_link,
    _handle_mock,
    _handle_status,
)


# ---------------------------------------------------------------------------
# _handle_mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_requires_active_interview():
    """No active interview → clear error, no MockSession created."""
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_mock("whatsapp:+91999", ["lld"])

    assert "No active interview" in result
    assert "prep" in result.lower()


@pytest.mark.asyncio
async def test_mock_rejects_unknown_round_type():
    result = await _handle_mock("whatsapp:+91999", ["knitting"])
    assert "Unknown round" in result


@pytest.mark.asyncio
async def test_mock_defaults_to_behavioral_when_no_args():
    """No round arg → behavioral (not an error)."""
    mock_interview = MagicMock()
    mock_interview.id = 1
    mock_interview.company = "Stripe"
    mock_interview.role = "Backend Engineer"

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_interview_repo = AsyncMock()
        mock_interview_repo.list_active.return_value = [mock_interview]

        mock_session_repo = AsyncMock()
        mock_session_obj = MagicMock()
        mock_session_obj.id = 42
        mock_session_repo.create.return_value = mock_session_obj

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_interview_repo), \
             patch("app.routes.webhooks.twilio.MockSessionRepository", return_value=mock_session_repo), \
             patch("app.routes.webhooks.twilio._orchestrator") as mock_orch:
            mock_orch.start = AsyncMock(return_value="Tell me about yourself.")
            result = await _handle_mock("whatsapp:+91999", [])

    assert "behavioral" in result.lower() or "session" in result.lower()


# ---------------------------------------------------------------------------
# _handle_done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_done_rejects_invalid_rating():
    result = await _handle_done("whatsapp:+91999", ["amazing"])
    assert "Usage" in result
    assert "easy" in result


@pytest.mark.asyncio
async def test_done_no_args_rejects():
    result = await _handle_done("whatsapp:+91999", [])
    assert "Usage" in result


@pytest.mark.asyncio
async def test_done_no_active_interview():
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_done("whatsapp:+91999", ["hard"])

    assert "No active" in result


@pytest.mark.asyncio
async def test_done_no_pending_plan():
    mock_interview = MagicMock()
    mock_interview.id = 1

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [mock_interview]

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_done("whatsapp:+91999", ["easy"])

    assert "No pending" in result


# ---------------------------------------------------------------------------
# _handle_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_no_active_interviews():
    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = []

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_status("whatsapp:+91999")

    assert "No active" in result


@pytest.mark.asyncio
async def test_status_lists_active_interviews():
    import json

    mock_interview = MagicMock()
    mock_interview.company = "Zapier"
    mock_interview.role = "Backend Engineer"
    mock_interview.round_types = json.dumps(["DSA", "behavioral"])
    mock_interview.scheduled_for = None

    with patch("app.routes.webhooks.twilio.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = AsyncMock()
        mock_repo.list_active.return_value = [mock_interview]

        with patch("app.routes.webhooks.twilio.InterviewRepository", return_value=mock_repo):
            result = await _handle_status("whatsapp:+91999")

    assert "Zapier" in result
    assert "Backend Engineer" in result
    assert "DSA" in result


# ---------------------------------------------------------------------------
# _handle_link (V2 stub)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_link_no_email_returns_usage():
    result = await _handle_link("whatsapp:+91999", [])
    assert "Usage" in result


@pytest.mark.asyncio
async def test_link_with_email_returns_v2_message():
    result = await _handle_link("whatsapp:+91999", ["me@example.com"])
    assert "V2" in result or "owner" in result.lower()
