from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_whatsapp: str  # e.g. whatsapp:+14155238886
    twilio_to_whatsapp: str  # Preeteesh's personal number
    mailgun_signing_key: str
    github_token: str
    github_vault_repo: str
    owner_email: str = "owner@example.com"  # V1 single-user identity — replaced by User table in V2
    database_url: str = "postgresql+asyncpg://user:password@host:5432/dbname"
    env: str = "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
