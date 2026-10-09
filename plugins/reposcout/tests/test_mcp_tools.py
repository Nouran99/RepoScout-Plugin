"""Tests for the 5 RepoScout MCP tools.

GitHubClient is mocked entirely — no real HTTP calls are made.
LicenseChecker is mocked to control pass/block behaviour.
get_settings is mocked to control API-key presence.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.clients.github_client import GitHubClient as _RealGitHubClient
from mcp_server.middleware.license_check import LicenseChecker, LicenseError
from mcp_server.models.github import (
    CommitSummary,
    FileEntry,
    RateLimitExceeded,
    RepoDetails,
    RepoSearchResult,
)
from mcp_server.server import (
    analyze_repo,
    check_license_compatibility,
    clone_and_scaffold,
    compare_repos,
    search_repos,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
_OLD = datetime(2022, 1, 1, tzinfo=UTC)
_GITHUB_SEARCH_URL = re.compile(r"https://api\.github\.com/search/repositories.*")


# ── Fixture factories ──────────────────────────────────────────────────────────

def _search_result(name: str = "owner/repo", stars: int = 500) -> RepoSearchResult:
    return RepoSearchResult(
        full_name=name,
        html_url=f"https://github.com/{name}",
        description="A great starter project",
        stargazers_count=stars,
        forks_count=50,
        language="Python",
        license_spdx="MIT",
        topics=["python", "fastapi"],
        updated_at=_NOW,
        pushed_at=_NOW,
        open_issues_count=5,
        size=2048,
    )


def _repo_details(
    name: str = "owner/repo",
    license_spdx: str | None = "MIT",
    pushed_at: datetime | None = None,
) -> RepoDetails:
    sr = _search_result(name)
    _exclude = {"license_spdx", "pushed_at", "updated_at"}
    base = {k: v for k, v in sr.model_dump().items() if k not in _exclude}
    return RepoDetails(
        **base,
        pushed_at=pushed_at or _NOW,
        updated_at=pushed_at or _NOW,
        license_spdx=license_spdx,
        subscribers_count=30,
        network_count=100,
        has_wiki=True,
        has_pages=False,
        has_discussions=False,
        archived=False,
        default_branch="main",
        contributors_count=10,
    )


def _file_tree() -> list[FileEntry]:
    return [
        FileEntry(name=".github", path=".github", type="dir", size=None),
        FileEntry(name="tests", path="tests", type="dir", size=None),
        FileEntry(name="README.md", path="README.md", type="file", size=1200),
        FileEntry(name="pyproject.toml", path="pyproject.toml", type="file", size=800),
    ]


def _commit(days_ago: int = 5) -> CommitSummary:
    return CommitSummary(
        sha="a" * 40,
        message="feat: add feature",
        author_name="Alice",
        authored_date=_NOW - timedelta(days=days_ago),
    )


def _mock_client(
    search_results: list[RepoSearchResult] | None = None,
    details: RepoDetails | None = None,
) -> MagicMock:
    """Build a fully configured GitHubClient async-context-manager mock."""
    m = MagicMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    _sr = search_results if search_results is not None else [_search_result()]
    m.search_repositories = AsyncMock(return_value=_sr)
    m.get_repo_details = AsyncMock(return_value=details if details is not None else _repo_details())
    m.get_repo_readme = AsyncMock(return_value="# README\n\nA great project.")
    m.get_repo_tree = AsyncMock(return_value=_file_tree())
    m.get_repo_languages = AsyncMock(return_value={"Python": 45000, "Shell": 1000})
    m.get_recent_commits = AsyncMock(return_value=[_commit(i * 2) for i in range(20)])
    m.get_dependency_files = AsyncMock(
        return_value={
            "pyproject.toml": (
                '[tool.poetry]\nname = "app"\n'
                '[tool.poetry.dependencies]\nfastapi = "*"\npostgresql = "*"'
            )
        }
    )
    return m


def _mock_checker(blocked: bool = False) -> MagicMock:
    m = MagicMock()
    if blocked:
        m.check = AsyncMock(
            side_effect=LicenseError("Free tier limit reached (10 calls/day).")
        )
    else:
        m.check = AsyncMock(return_value={"allowed": True, "tier": "free"})
    m.log_usage = AsyncMock()
    m.increment_local_usage = MagicMock()
    return m


def _gh_class_mock(client: MagicMock) -> MagicMock:
    """Mock that replaces the GitHubClient *class*, preserving the real parse_owner_repo."""
    mock_cls = MagicMock(return_value=client)
    mock_cls.parse_owner_repo = _RealGitHubClient.parse_owner_repo
    return mock_cls


def _mock_settings(
    api_key: str | None = None,
    backend_url: str = "http://localhost:8000",
    fail_open: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.github_token = None
    m.reposcout_api_key = api_key
    m.reposcout_backend_url = backend_url
    m.reposcout_license_fail_open = fail_open
    return m


# ── Tool 1: search_repos ──────────────────────────────────────────────────────

class TestSearchRepos:
    async def test_happy_path_returns_results(self):
        results = [_search_result(f"owner/repo-{i}", stars=100 * i) for i in range(1, 6)]
        client = _mock_client(search_results=results)
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await search_repos(description="fastapi saas boilerplate")

        assert isinstance(result, dict)
        assert len(result["results"]) >= 1
        assert "health_scores" in result
        assert result["total_found"] >= 1
        checker.check.assert_awaited_once()
        checker.increment_local_usage.assert_called_once()

    async def test_empty_results_returns_empty_list(self):
        client = _mock_client(search_results=[])
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await search_repos(description="xyzzy-nonexistent-project-12345")

        assert result["results"] == []
        assert result["total_found"] == 0

    async def test_rate_limited_returns_empty_gracefully(self):
        reset = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
        client = _mock_client()
        client.search_repositories = AsyncMock(
            side_effect=RateLimitExceeded(reset_at=reset, message="Rate limit hit")
        )
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await search_repos(description="fastapi")

        # Per-query errors are logged; no results returned rather than crashing
        assert result["results"] == []

    async def test_license_check_blocks(self):
        checker = _mock_checker(blocked=True)
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError, match="Free tier limit"):
                await search_repos(description="saas boilerplate")

    async def test_pro_key_calls_log_usage(self):
        client = _mock_client(search_results=[_search_result()])
        checker = _mock_checker()
        settings = _mock_settings(api_key="nk_test_valid_key")

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            await search_repos(description="fastapi")

        checker.log_usage.assert_awaited_once()
        checker.increment_local_usage.assert_not_called()

    async def test_backend_outage_fails_open_and_tool_still_returns_results(self, httpx_mock: HTTPXMock):
        client = _mock_client(search_results=[_search_result()])
        settings = _mock_settings(
            api_key="nk_test_valid_key",
            backend_url="http://localhost:65530",
            fail_open=True,
        )
        validate_url = f"{settings.reposcout_backend_url}/api/v1/reposcout/validate-key"
        mocked_log_usage = AsyncMock()

        httpx_mock.add_exception(
            url=validate_url,
            exception=httpx.ConnectError("Connection refused"),
        )

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch.object(LicenseChecker, "log_usage", mocked_log_usage),
        ):
            result = await search_repos(description="fastapi")

        assert result["total_found"] >= 1
        assert len(result["results"]) >= 1
        mocked_log_usage.assert_awaited_once()

    async def test_backend_outage_fail_closed_blocks_tool(self, httpx_mock: HTTPXMock):
        client = _mock_client(search_results=[_search_result()])
        settings = _mock_settings(
            api_key="nk_test_valid_key",
            backend_url="http://localhost:65531",
            fail_open=False,
        )
        validate_url = f"{settings.reposcout_backend_url}/api/v1/reposcout/validate-key"

        httpx_mock.add_exception(
            url=validate_url,
            exception=httpx.ConnectError("Connection refused"),
        )

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError, match="temporarily unavailable"):
                await search_repos(description="fastapi")

    @pytest.mark.parametrize("status_code", [403, 429])
    async def test_real_github_client_rate_limit_returns_empty_after_bounded_retries(
        self,
        httpx_mock: HTTPXMock,
        status_code: int,
    ):
        checker = _mock_checker()
        settings = _mock_settings()
        mocked_sleep = AsyncMock()

        for _ in range(4):
            httpx_mock.add_response(
                url=_GITHUB_SEARCH_URL,
                status_code=status_code,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("mcp_server.server.QueryExpander.expand", return_value=[MagicMock(query="fastapi")]),
            patch("mcp_server.clients.github_client.asyncio.sleep", mocked_sleep),
        ):
            result = await search_repos(description="fastapi")

        assert result["results"] == []
        assert result["total_found"] == 0
        checker.check.assert_awaited_once()
        checker.increment_local_usage.assert_called_once()
        assert len(httpx_mock.get_requests()) == 4
        assert mocked_sleep.await_count == 3

    async def test_real_github_client_server_error_returns_empty_without_retry(self, httpx_mock: HTTPXMock):
        checker = _mock_checker()
        settings = _mock_settings()
        mocked_sleep = AsyncMock()

        httpx_mock.add_response(
            url=_GITHUB_SEARCH_URL,
            status_code=500,
        )

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("mcp_server.server.QueryExpander.expand", return_value=[MagicMock(query="fastapi")]),
            patch("mcp_server.clients.github_client.asyncio.sleep", mocked_sleep),
        ):
            result = await search_repos(description="fastapi")

        assert result["results"] == []
        assert result["total_found"] == 0
        checker.check.assert_awaited_once()
        checker.increment_local_usage.assert_called_once()
        assert len(httpx_mock.get_requests()) == 1
        mocked_sleep.assert_not_awaited()

    async def test_deduplicates_across_expanded_queries(self):
        # All expanded queries return the same repo — should appear once
        same_repo = _search_result("owner/same-repo", stars=200)
        client = _mock_client(search_results=[same_repo])
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await search_repos(description="saas")

        names = [r["full_name"] for r in result["results"]]
        assert len(names) == len(set(names)), "Duplicate repos in results"


# ── Tool 2: analyze_repo ──────────────────────────────────────────────────────

class TestAnalyzeRepo:
    async def test_happy_path_returns_full_analysis(self):
        client = _mock_client()
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await analyze_repo("https://github.com/owner/repo")

        assert result["repo"]["full_name"] == "owner/repo"
        assert "health" in result
        assert result["health"]["total_score"] >= 0
        assert "detected_stack" in result
        assert "Python" in result["detected_stack"]
        assert "FastAPI" in result["detected_stack"]

    async def test_no_readme_returns_none(self):
        client = _mock_client()
        client.get_repo_readme = AsyncMock(return_value=None)
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await analyze_repo("owner/repo")

        assert result["readme_content"] is None

    async def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            await analyze_repo("not-a-valid-url-no-slash")

    async def test_rate_limited_raises(self):
        reset = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
        client = _mock_client()
        client.get_repo_details = AsyncMock(
            side_effect=RateLimitExceeded(reset_at=reset, message="Rate limit")
        )
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(RateLimitExceeded):
                await analyze_repo("owner/repo")

    async def test_license_check_blocks(self):
        checker = _mock_checker(blocked=True)
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError):
                await analyze_repo("owner/repo")

    async def test_empty_file_tree_still_returns_score(self):
        client = _mock_client()
        client.get_repo_tree = AsyncMock(return_value=[])
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await analyze_repo("owner/repo")

        assert result["health"]["total_score"] >= 0
        assert result["file_tree"] == []


# ── Tool 3: compare_repos ──────────────────────────────────────────────────────

class TestCompareRepos:
    async def test_happy_path_two_repos(self):
        client = _mock_client()
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await compare_repos([
                "https://github.com/org/repo-a",
                "https://github.com/org/repo-b",
            ])

        assert len(result["repos"]) == 2
        assert result["recommendation"]
        assert result["reasoning"]

    async def test_recommends_higher_health_score(self):
        # repo-a has recent push; repo-b has stale push → repo-a wins
        details_a = _repo_details("org/repo-a", pushed_at=_NOW)
        details_b = _repo_details("org/repo-b", pushed_at=_OLD)

        call_idx = 0

        async def _details(owner: str, repo: str) -> RepoDetails:
            nonlocal call_idx
            call_idx += 1
            return details_a if repo == "repo-a" else details_b

        client = _mock_client()
        client.get_repo_details = AsyncMock(side_effect=_details)
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await compare_repos(["org/repo-a", "org/repo-b"])

        assert result["recommendation"] == "org/repo-a"

    async def test_too_few_urls_raises(self):
        with pytest.raises(ValueError, match="2 or 3"):
            await compare_repos(["https://github.com/owner/only-one"])

    async def test_too_many_urls_raises(self):
        with pytest.raises(ValueError, match="2 or 3"):
            await compare_repos(["a/b", "c/d", "e/f", "g/h"])

    async def test_rate_limited_raises(self):
        reset = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
        client = _mock_client()
        client.get_repo_details = AsyncMock(
            side_effect=RateLimitExceeded(reset_at=reset, message="Rate limit")
        )
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(RateLimitExceeded):
                await compare_repos(["owner/a", "owner/b"])

    async def test_license_check_blocks(self):
        checker = _mock_checker(blocked=True)
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError):
                await compare_repos(["owner/a", "owner/b"])

    async def test_three_repos_all_present(self):
        client = _mock_client()
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await compare_repos(["owner/a", "owner/b", "owner/c"])

        assert len(result["repos"]) == 3


# ── Tool 4: clone_and_scaffold ────────────────────────────────────────────────

class TestCloneAndScaffold:
    async def test_happy_path(self, tmp_path):
        target = tmp_path / "my-project"
        target.mkdir()
        (target / ".git").mkdir()
        (target / "package.json").write_text(
            '{"dependencies": {"react": "^18", "next": "^14"}}'
        )
        (target / "index.js").write_text("console.log('hello')")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)),
        ):
            result = await clone_and_scaffold(
                repo_url="owner/repo",
                target_dir=str(target),
            )

        assert result["target_dir"] == str(target.resolve())
        assert result["files_count"] >= 1
        assert not (target / ".git").exists()  # history stripped
        assert any(
            kw in result["detected_stack"] for kw in ("Next.js", "React", "JavaScript")
        )
        assert any("npm install" in step for step in result["suggested_next_steps"])

    async def test_git_clone_fails_raises(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"fatal: repository not found")
        )
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)),
        ):
            with pytest.raises(RuntimeError, match="git clone failed"):
                await clone_and_scaffold(
                    repo_url="owner/repo",
                    target_dir=str(tmp_path / "out"),
                )

    async def test_keep_git_history_when_flag_false(self, tmp_path):
        target = tmp_path / "proj"
        target.mkdir()
        (target / ".git").mkdir()
        (target / "app.py").write_text("print('hello')")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)),
        ):
            await clone_and_scaffold(
                repo_url="owner/repo",
                target_dir=str(target),
                remove_git_history=False,
            )

        assert (target / ".git").exists()

    async def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            await clone_and_scaffold(
                repo_url="not-a-repo-no-slash",
                target_dir="/some/dir",
            )

    async def test_license_check_blocks(self):
        checker = _mock_checker(blocked=True)
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError):
                await clone_and_scaffold(repo_url="owner/repo", target_dir="/tmp/x")

    async def test_python_project_suggests_pip_and_env(self, tmp_path):
        target = tmp_path / "pyproj"
        target.mkdir()
        (target / "requirements.txt").write_text("fastapi\nuvicorn\n")
        (target / "main.py").write_text("from fastapi import FastAPI")
        (target / ".env.example").write_text("DATABASE_URL=postgres://localhost/db")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)),
        ):
            result = await clone_and_scaffold(repo_url="owner/repo", target_dir=str(target))

        steps = " ".join(result["suggested_next_steps"]).lower()
        assert "pip install" in steps
        assert ".env" in steps


# ── Tool 5: check_license_compatibility ───────────────────────────────────────

class TestCheckLicenseCompatibility:
    async def test_mit_is_safe_for_commercial(self):
        client = _mock_client(details=_repo_details(license_spdx="MIT"))
        client.get_dependency_files = AsyncMock(return_value={})
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await check_license_compatibility("owner/repo")

        assert result["license_spdx"] == "MIT"
        assert result["is_permissive"] is True
        assert result["is_copyleft"] is False
        assert result["commercial_use_allowed"] is True
        assert result["warnings"] == []
        assert "Safe" in result["compatibility_verdict"]

    async def test_agpl_blocks_commercial_saas(self):
        client = _mock_client(details=_repo_details(license_spdx="AGPL-3.0"))
        client.get_dependency_files = AsyncMock(return_value={})
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await check_license_compatibility("owner/repo", intended_use="commercial")

        assert result["is_copyleft"] is True
        assert result["commercial_use_allowed"] is False
        assert len(result["warnings"]) >= 1

    async def test_no_license_warns_and_blocks(self):
        client = _mock_client(details=_repo_details(license_spdx=None))
        client.get_dependency_files = AsyncMock(return_value={})
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await check_license_compatibility("owner/repo")

        assert result["license_spdx"] is None
        assert result["commercial_use_allowed"] is False
        assert len(result["warnings"]) >= 1

    async def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            await check_license_compatibility("not-a-valid-url")

    async def test_license_check_blocks(self):
        checker = _mock_checker(blocked=True)
        settings = _mock_settings()

        with (
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            with pytest.raises(LicenseError):
                await check_license_compatibility("owner/repo")

    async def test_gpl_allows_modification(self):
        client = _mock_client(details=_repo_details(license_spdx="GPL-3.0"))
        client.get_dependency_files = AsyncMock(return_value={})
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await check_license_compatibility("owner/repo", intended_use="open_source")

        assert result["is_copyleft"] is True
        assert result["modification_allowed"] is True

    async def test_agpl_dep_triggers_transitive_warning(self):
        client = _mock_client(details=_repo_details(license_spdx="MIT"))
        client.get_dependency_files = AsyncMock(
            return_value={"requirements.txt": "agpl-licensed-pkg==1.0\nfastapi\n"}
        )
        checker = _mock_checker()
        settings = _mock_settings()

        with (
            patch("mcp_server.server.GitHubClient", _gh_class_mock(client)),
            patch("mcp_server.server.LicenseChecker", return_value=checker),
            patch("mcp_server.server.get_settings", return_value=settings),
        ):
            result = await check_license_compatibility("owner/repo", intended_use="commercial")

        # MIT repo but dep file contains "agpl" → transitive licence warning
        assert any("AGPL" in w or "agpl" in w.lower() for w in result["warnings"])
