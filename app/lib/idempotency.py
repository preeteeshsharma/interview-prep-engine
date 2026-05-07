import hashlib


def make_key(*parts: str) -> str:
    """Join parts with ':' and return the SHA256 hex digest."""
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()
