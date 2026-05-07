import asyncio

from github import Github

from app.config import settings

gh = Github(settings.github_token)


async def commit_file(path: str, content: str, message: str) -> str:
    """Upsert a file in the configured vault repo. Returns the commit SHA."""

    def _commit() -> str:
        repo = gh.get_repo(settings.github_vault_repo)
        try:
            existing = repo.get_contents(path)
            result = repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=existing.sha,
            )
        except Exception:
            # File does not exist yet — create it.
            result = repo.create_file(
                path=path,
                message=message,
                content=content,
            )
        return result["commit"].sha

    return await asyncio.to_thread(_commit)
