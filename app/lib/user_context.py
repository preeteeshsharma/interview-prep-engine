from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass
class UserContext:
    email: str
    github_token: str
    vault_repo: str


async def get_user_context(sender_phone: str | None = None) -> UserContext:
    """Return the UserContext for a given WhatsApp sender.

    V1 — single owner: always returns the owner configured in settings.
         sender_phone is accepted but ignored.

    V2 — multi-user: look up User table by sender_phone; raise if not registered.
         Replace this function body only — all callers stay unchanged.

    ## V2 migration steps (this function is the only seam to change):
    1. Add User table (email PK, whatsapp_phone, github_token, vault_repo)
    2. Add Alembic migration
    3. Replace body below with:
           async with async_session_factory() as session:
               user = await UserRepository(session).get_by_phone(sender_phone)
               if not user:
                   raise UnregisteredUserError(sender_phone)
               return UserContext(
                   email=user.email,
                   github_token=user.github_token,
                   vault_repo=user.vault_repo,
               )
    4. Add register + link intents to Twilio router
    5. Add inbox registration flow (email with subject "register")
    """
    return UserContext(
        email=settings.owner_email,
        github_token=settings.github_token,
        vault_repo=settings.github_vault_repo,
    )
