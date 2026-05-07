import asyncio

from github import Github, GithubException

from app.config import settings


async def commit_file(
    path: str,
    content: str,
    message: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> str:
    """Upsert a file in the vault repo. Returns the commit SHA.

    V1: token and repo default to settings (single owner).
    V2: pass per-user token and repo from UserContext.
    """
    token = github_token or settings.github_token
    repo_name = vault_repo or settings.github_vault_repo

    def _commit() -> str:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        try:
            existing = repo.get_contents(path)
            result = repo.update_file(
                path=path,
                message=message,
                content=content,
                sha=existing.sha,
            )
        except GithubException as exc:
            if exc.status != 404:
                raise
            result = repo.create_file(
                path=path,
                message=message,
                content=content,
            )
        return result["commit"].sha

    return await asyncio.to_thread(_commit)


async def read_file(
    path: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> str:
    """Read a file from the vault repo. Raises GithubException(404) if not found."""
    token = github_token or settings.github_token
    repo_name = vault_repo or settings.github_vault_repo

    def _read() -> str:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        contents = repo.get_contents(path)
        return contents.decoded_content.decode("utf-8")

    return await asyncio.to_thread(_read)


async def list_directory(
    path: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> list[str]:
    """List file paths in a directory (non-recursive). Returns [] if path doesn't exist."""
    token = github_token or settings.github_token
    repo_name = vault_repo or settings.github_vault_repo

    def _list() -> list[str]:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        try:
            items = repo.get_contents(path)
            if not isinstance(items, list):
                items = [items]
            return [item.path for item in items if item.type == "file"]
        except GithubException as exc:
            if exc.status == 404:
                return []
            raise

    return await asyncio.to_thread(_list)
