"""Tests for github_client — validates 404-only exception handling fix."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github import GithubException


# ---------------------------------------------------------------------------
# commit_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_creates_file_when_not_exists():
    """get_contents raises 404 → create_file is called."""
    mock_repo = MagicMock()
    mock_repo.get_contents.side_effect = GithubException(404, "Not Found", {})
    mock_repo.create_file.return_value = {"commit": MagicMock(sha="abc123")}

    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch("app.integrations.github_client.Github", return_value=mock_gh), \
         patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        from app.integrations.github_client import commit_file
        sha = await commit_file("plans/test.md", "content", "message")

    mock_repo.create_file.assert_called_once()
    mock_repo.update_file.assert_not_called()
    assert sha == "abc123"


@pytest.mark.asyncio
async def test_updates_file_when_exists():
    """get_contents returns existing file → update_file is called with sha."""
    existing = MagicMock()
    existing.sha = "existingsha"

    mock_repo = MagicMock()
    mock_repo.get_contents.return_value = existing
    mock_repo.update_file.return_value = {"commit": MagicMock(sha="newsha")}

    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch("app.integrations.github_client.Github", return_value=mock_gh), \
         patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        from app.integrations.github_client import commit_file
        sha = await commit_file("plans/test.md", "new content", "update message")

    mock_repo.update_file.assert_called_once_with(
        path="plans/test.md",
        message="update message",
        content="new content",
        sha="existingsha",
    )
    mock_repo.create_file.assert_not_called()
    assert sha == "newsha"


@pytest.mark.asyncio
async def test_non_404_exception_propagates():
    """A 401 auth error must NOT be swallowed — it should propagate."""
    mock_repo = MagicMock()
    mock_repo.get_contents.side_effect = GithubException(401, "Unauthorized", {})

    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo

    with patch("app.integrations.github_client.Github", return_value=mock_gh), \
         patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        from app.integrations.github_client import commit_file
        with pytest.raises(GithubException) as exc_info:
            await commit_file("plans/test.md", "content", "message")

    assert exc_info.value.status == 401
    mock_repo.create_file.assert_not_called()


@pytest.mark.asyncio
async def test_uses_per_user_token_when_provided():
    """V2 path: explicit github_token and vault_repo override settings."""
    existing = MagicMock(sha="sha1")
    mock_repo = MagicMock()
    mock_repo.get_contents.return_value = existing
    mock_repo.update_file.return_value = {"commit": MagicMock(sha="sha2")}

    captured = {}
    def mock_github_init(token):
        captured["token"] = token
        gh = MagicMock()
        gh.get_repo.return_value = mock_repo
        return gh

    with patch("app.integrations.github_client.Github", side_effect=mock_github_init), \
         patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn: fn())):
        from app.integrations.github_client import commit_file
        await commit_file(
            "plans/test.md", "content", "msg",
            github_token="ghp_custom",
            vault_repo="other/vault",
        )

    assert captured["token"] == "ghp_custom"
