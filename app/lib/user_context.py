from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass
class UserContext:
    email: str
    github_token: str
    vault_repo: str


async def get_user_context(
    sender_phone: str | None = None,
    email: str | None = None,
) -> UserContext:
    """Return the UserContext for a given sender (WhatsApp phone or email).

    V1 — single owner: both params accepted but ignored. Always returns owner
         from settings.

    V2 — replace this body only. All callers already pass the right identifier.
         Lookup order: phone → email → raise UnregisteredUserError.

         async with async_session_factory() as session:
             repo = UserRepository(session)
             user = (
                 await repo.get_by_phone(sender_phone) if sender_phone
                 else await repo.get_by_email(email)
             )
             if not user:
                 raise UnregisteredUserError(sender_phone or email)
             return UserContext(
                 email=user.email,
                 github_token=user.github_token,
                 vault_repo=user.vault_repo,
             )
    """
    return UserContext(
        email=settings.owner_email,
        github_token=settings.github_token,
        vault_repo=settings.github_vault_repo,
    )
