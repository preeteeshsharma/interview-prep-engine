from datetime import datetime, timedelta, timezone


def is_within_24h(dt: datetime | None) -> bool:
    """Return True if dt is within the last 24 hours (UTC), False if None or older."""
    if dt is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # Ensure dt is timezone-aware before comparing.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > cutoff
