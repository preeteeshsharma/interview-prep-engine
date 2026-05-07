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


async def load_vault_context(
    company_slug: str,
    round_slug: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (research_md, plan_md) for company/round from vault.

    Latest research and latest plan are picked independently by epoch — if one
    run produced only a plan (research failed), we still get the best of each.
    Returns (None, None) if the directory doesn't exist.
    """
    token = github_token or settings.github_token
    repo_name = vault_repo or settings.github_vault_repo
    path = f"{company_slug}/{round_slug}"

    def _epoch(filename: str) -> int:
        try:
            return int(filename.split("-")[0])
        except (ValueError, IndexError):
            return 0

    def _load() -> tuple[str | None, str | None]:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        try:
            items = repo.get_contents(path)
        except GithubException as exc:
            if exc.status == 404:
                return None, None
            raise
        if not isinstance(items, list):
            items = [items]
        files = {item.name: item for item in items if item.type == "file"}

        research_files = sorted(
            [n for n in files if n.endswith("-research.md")], key=_epoch, reverse=True
        )
        plan_files = sorted(
            [n for n in files if n.endswith("-plan.md")], key=_epoch, reverse=True
        )

        research = files[research_files[0]].decoded_content.decode("utf-8") if research_files else None
        plan = files[plan_files[0]].decoded_content.decode("utf-8") if plan_files else None
        return research, plan

    return await asyncio.to_thread(_load)


async def list_vault_rounds(
    company_slug: str,
    github_token: str | None = None,
    vault_repo: str | None = None,
) -> list[str]:
    """Return round subdirectory names under company_slug/ in vault. Returns [] if not found."""
    token = github_token or settings.github_token
    repo_name = vault_repo or settings.github_vault_repo

    def _list() -> list[str]:
        gh = Github(token)
        repo = gh.get_repo(repo_name)
        try:
            items = repo.get_contents(company_slug)
        except GithubException as exc:
            if exc.status == 404:
                return []
            raise
        if not isinstance(items, list):
            items = [items]
        return [item.name for item in items if item.type == "dir"]

    return await asyncio.to_thread(_list)
