import os

# Set required env vars before any app module is imported.
# Values are placeholders — tests mock external calls so no real API is hit.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACtest")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_auth_token")
os.environ.setdefault("TWILIO_FROM_WHATSAPP", "whatsapp:+14155238886")
os.environ.setdefault("TWILIO_TO_WHATSAPP", "whatsapp:+910000000000")
os.environ.setdefault("MAILGUN_SIGNING_KEY", "test_signing_key")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test")
os.environ.setdefault("GITHUB_VAULT_REPO", "test/prep-vault")
os.environ.setdefault("OWNER_EMAIL", "test@example.com")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
