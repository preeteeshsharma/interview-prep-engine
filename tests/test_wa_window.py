from datetime import datetime, timedelta, timezone

from app.lib.wa_window import is_within_24h


def test_none_returns_false():
    assert is_within_24h(None) is False


def test_within_window():
    recent = datetime.now(timezone.utc) - timedelta(hours=12)
    assert is_within_24h(recent) is True


def test_outside_window():
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    assert is_within_24h(old) is False
