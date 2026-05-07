"""Tests for Mailgun HMAC signature validation — security-critical path."""
import hashlib
import hmac
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.routes.webhooks.inbox import _validate_mailgun_signature, _is_registration
from app.schemas.webhooks import MailgunInbound

SIGNING_KEY = "test_signing_key"  # matches conftest.py


def _make_signature(timestamp: str, token: str, key: str = SIGNING_KEY) -> str:
    return hmac.new(
        key.encode(),
        (timestamp + token).encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# _validate_mailgun_signature
# ---------------------------------------------------------------------------

def test_valid_signature_passes():
    ts = str(int(time.time()))
    token = "abc123token"
    sig = _make_signature(ts, token)
    # Should not raise
    _validate_mailgun_signature(ts, token, sig)


def test_invalid_signature_raises_403():
    ts = str(int(time.time()))
    token = "abc123token"
    with pytest.raises(HTTPException) as exc_info:
        _validate_mailgun_signature(ts, token, "badsignature")
    assert exc_info.value.status_code == 403


def test_wrong_key_raises_403():
    ts = str(int(time.time()))
    token = "abc123token"
    sig = _make_signature(ts, token, key="wrong_key")
    with pytest.raises(HTTPException) as exc_info:
        _validate_mailgun_signature(ts, token, sig)
    assert exc_info.value.status_code == 403


def test_tampered_token_raises_403():
    ts = str(int(time.time()))
    token = "abc123token"
    sig = _make_signature(ts, token)
    with pytest.raises(HTTPException) as exc_info:
        _validate_mailgun_signature(ts, "tampered_token", sig)
    assert exc_info.value.status_code == 403


def test_tampered_timestamp_raises_403():
    ts = str(int(time.time()))
    token = "abc123token"
    sig = _make_signature(ts, token)
    with pytest.raises(HTTPException) as exc_info:
        _validate_mailgun_signature("9999999999", token, sig)
    assert exc_info.value.status_code == 403


def test_empty_signature_raises_403():
    ts = str(int(time.time()))
    token = "abc123token"
    with pytest.raises(HTTPException) as exc_info:
        _validate_mailgun_signature(ts, token, "")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# _is_registration
# ---------------------------------------------------------------------------

def test_is_registration_detects_register_subject():
    payload = MailgunInbound(sender="user@example.com", subject="register", body_plain="")
    assert _is_registration(payload) is True


def test_is_registration_case_insensitive():
    payload = MailgunInbound(sender="user@example.com", subject="REGISTER", body_plain="")
    assert _is_registration(payload) is True


def test_is_registration_with_whitespace():
    payload = MailgunInbound(sender="user@example.com", subject="  sign up  ", body_plain="")
    assert _is_registration(payload) is True


def test_is_registration_false_for_normal_email():
    payload = MailgunInbound(
        sender="recruiting@zapier.com",
        subject="Interview invite — Backend Engineer",
        body_plain="We'd like to schedule...",
    )
    assert _is_registration(payload) is False


def test_is_registration_false_for_empty_subject():
    payload = MailgunInbound(sender="user@example.com", subject="", body_plain="")
    assert _is_registration(payload) is False
