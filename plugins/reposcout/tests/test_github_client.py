"""Tests for GitHubClient — all HTTP calls mocked with pytest-httpx."""
from __future__ import annotations

import base64
import os
import re
import sys

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.clients.github_client import GitHubClient
from mcp_server.models.github import (
    CommitSummary,
    FileEntry,
    RateLimitExceeded,
    RepoDetails,
    RepoSearchResult,
)

# ── URL patterns (regex so query params are ignored) ─────────────────────────

_SEARCH = re.compile(r"https://api\.github\.com/search/repositories")
_REPO = re.compile(r"https://api\.github\.com/repos/owner/repo$")
_REPO_MISSING = re.compile(r"https://api\.github\.com/repos/owner/missing$")
_CONTRIBUTORS = re.compile(r"https://api\.github\.com/repos/owner/repo/contributors")
_README = re.compile(r"https://api\.github\.com/repos/owner/repo/readme")
_CONTENTS_ROOT = re.compile(r"https://api\.github\.com/repos/owner/repo/contents/?$")
_CONTENTS_SRC = re.compile(r"https://api\.github\.com/repos/owner/repo/contents/src$")
_LANGUAGES = re.compile(r"https://api\.github\.com/repos/owner/(repo|missing)/languages")
_COMMITS = re.compile(r"https://api\.github\.com/repos/owner/repo/commits")
_CONTENTS = re.compile(r"https://api\.github\.com/repos/owner/repo/contents/")

RATE_LIMIT_HEADERS = {
    "X-RateLimit-Remaining": "60",
    "X-RateLimit-Reset": "9999999999",
}

NOW = "2024-01-15T12:00:00Z"


def _repo_payload(full_name: str = "owner/repo") -> dict:
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "A test repo",
        "stargazers_count": 100,
        "forks_count": 20,
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "topics": ["python", "testing"],
        "updated_at": NOW,
        "pushed_at": NOW,
        "open_issues_count": 5,
        "size": 1024,
        "subscribers_count": 30,
        "network_count": 20,
        "has_wiki": True,
        "has_pages": False,
        "has_discussions": False,
        "archived": False,
        "default_branch": "main",
    }


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest_asyncio.fixture
async def client():
    async with GitHubClient(token="test-token") as c:
        yield c


# ── search_repositories ───────────────────────────────────────────────────────

class TestSearchRepositories:
    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [_repo_payload("alice/foo"), _repo_payload("bob/bar")], "total_count": 2},
            headers=RATE_LIMIT_HEADERS,
        )
        results = await client.search_repositories("fastapi")
        assert len(results) == 2
        assert isinstance(results[0], RepoSearchResult)
        assert results[0].full_name == "alice/foo"
        assert results[0].license_spdx == "MIT"

    async def test_empty_results(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [], "total_count": 0},
            headers=RATE_LIMIT_HEADERS,
        )
        results = await client.search_repositories("xyzzy-nonexistent-12345")
        assert results == []

    async def test_with_all_filters(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [_repo_payload()], "total_count": 1},
            headers=RATE_LIMIT_HEADERS,
        )
        results = await client.search_repositories(
            "saas",
            language="Python",
            min_stars=100,
            topics=["fastapi"],
            license_type="MIT",
            sort_by="stars",
            per_page=5,
        )
        assert len(results) == 1

    async def test_rate_limit_exhausted(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_SEARCH,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.search_repositories("test")

    async def test_403_rate_limit(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_SEARCH,
                status_code=403,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.search_repositories("test")

    async def test_no_license(self, client: GitHubClient, httpx_mock: HTTPXMock):
        payload = _repo_payload()
        payload["license"] = None
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [payload], "total_count": 1},
            headers=RATE_LIMIT_HEADERS,
        )
        results = await client.search_repositories("test")
        assert results[0].license_spdx is None


# ── get_repo_details ──────────────────────────────────────────────────────────

class TestGetRepoDetails:
    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_REPO,
            json=_repo_payload(),
            headers=RATE_LIMIT_HEADERS,
        )
        httpx_mock.add_response(
            url=_CONTRIBUTORS,
            json=[{"login": "alice"}, {"login": "bob"}],
            headers=RATE_LIMIT_HEADERS,
        )
        details = await client.get_repo_details("owner", "repo")
        assert isinstance(details, RepoDetails)
        assert details.full_name == "owner/repo"
        assert details.contributors_count == 2
        assert details.default_branch == "main"

    async def test_contributors_404(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_REPO,
            json=_repo_payload(),
            headers=RATE_LIMIT_HEADERS,
        )
        httpx_mock.add_response(
            url=_CONTRIBUTORS,
            status_code=404,
            headers=RATE_LIMIT_HEADERS,
        )
        details = await client.get_repo_details("owner", "repo")
        assert details.contributors_count is None

    async def test_repo_not_found(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_REPO_MISSING,
            status_code=404,
            headers=RATE_LIMIT_HEADERS,
        )
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.get_repo_details("owner", "missing")
        assert exc_info.value.response.status_code == 404

    async def test_rate_limit_on_details(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_REPO,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.get_repo_details("owner", "repo")

    async def test_archived_repo(self, client: GitHubClient, httpx_mock: HTTPXMock):
        payload = _repo_payload()
        payload["archived"] = True
        httpx_mock.add_response(url=_REPO, json=payload, headers=RATE_LIMIT_HEADERS)
        httpx_mock.add_response(url=_CONTRIBUTORS, json=[], headers=RATE_LIMIT_HEADERS)
        details = await client.get_repo_details("owner", "repo")
        assert details.archived is True


# ── get_repo_readme ───────────────────────────────────────────────────────────

class TestGetRepoReadme:
    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_README,
            json={"content": _b64("# Hello World\n\nThis is a test README.")},
            headers=RATE_LIMIT_HEADERS,
        )
        readme = await client.get_repo_readme("owner", "repo")
        assert readme == "# Hello World\n\nThis is a test README."

    async def test_no_readme(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_README, status_code=404, headers=RATE_LIMIT_HEADERS)
        readme = await client.get_repo_readme("owner", "repo")
        assert readme is None

    async def test_empty_readme(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_README,
            json={"content": _b64("")},
            headers=RATE_LIMIT_HEADERS,
        )
        readme = await client.get_repo_readme("owner", "repo")
        assert readme == ""

    async def test_rate_limit(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_README,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.get_repo_readme("owner", "repo")

    async def test_server_error_propagates(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_README, status_code=500, headers=RATE_LIMIT_HEADERS)
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_repo_readme("owner", "repo")


# ── get_repo_tree ─────────────────────────────────────────────────────────────

class TestGetRepoTree:
    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_CONTENTS_ROOT,
            json=[
                {"name": "src", "path": "src", "type": "dir", "size": 0},
                {"name": "README.md", "path": "README.md", "type": "file", "size": 512},
            ],
            headers=RATE_LIMIT_HEADERS,
        )
        tree = await client.get_repo_tree("owner", "repo")
        assert len(tree) == 2
        assert isinstance(tree[0], FileEntry)
        assert tree[0].type == "dir"
        assert tree[0].size is None
        assert tree[1].size == 512

    async def test_empty_repo_404(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_CONTENTS_ROOT,
            status_code=404,
            headers=RATE_LIMIT_HEADERS,
        )
        tree = await client.get_repo_tree("owner", "repo")
        assert tree == []

    async def test_sub_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_CONTENTS_SRC,
            json=[{"name": "main.py", "path": "src/main.py", "type": "file", "size": 200}],
            headers=RATE_LIMIT_HEADERS,
        )
        tree = await client.get_repo_tree("owner", "repo", path="src")
        assert tree[0].path == "src/main.py"

    async def test_single_file_response_returns_empty(
        self, client: GitHubClient, httpx_mock: HTTPXMock
    ):
        # GitHub returns a dict (not list) for a single-file path
        httpx_mock.add_response(
            url=_CONTENTS_ROOT,
            json={"name": "README.md", "type": "file", "size": 100},
            headers=RATE_LIMIT_HEADERS,
        )
        tree = await client.get_repo_tree("owner", "repo")
        assert tree == []

    async def test_rate_limit(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_CONTENTS_ROOT,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.get_repo_tree("owner", "repo")


# ── get_repo_languages ────────────────────────────────────────────────────────

class TestGetRepoLanguages:
    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_LANGUAGES,
            json={"Python": 45321, "Shell": 1200},
            headers=RATE_LIMIT_HEADERS,
        )
        langs = await client.get_repo_languages("owner", "repo")
        assert langs == {"Python": 45321, "Shell": 1200}

    async def test_empty_languages(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_LANGUAGES,
            json={},
            headers=RATE_LIMIT_HEADERS,
        )
        langs = await client.get_repo_languages("owner", "repo")
        assert langs == {}

    async def test_not_found(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_LANGUAGES,
            status_code=404,
            headers=RATE_LIMIT_HEADERS,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_repo_languages("owner", "missing")

    async def test_rate_limit(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_LANGUAGES,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.get_repo_languages("owner", "repo")


# ── get_recent_commits ────────────────────────────────────────────────────────

class TestGetRecentCommits:
    def _commit(self, sha: str, msg: str) -> dict:
        return {
            "sha": sha,
            "commit": {
                "message": msg,
                "author": {"name": "Alice", "date": NOW},
            },
        }

    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_COMMITS,
            json=[self._commit("abc123", "feat: add feature"), self._commit("def456", "fix: bug")],
            headers=RATE_LIMIT_HEADERS,
        )
        commits = await client.get_recent_commits("owner", "repo")
        assert len(commits) == 2
        assert isinstance(commits[0], CommitSummary)
        assert commits[0].sha == "abc123"
        assert commits[0].message == "feat: add feature"

    async def test_multiline_commit_message(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_COMMITS,
            json=[self._commit("sha1", "feat: title\n\nBody paragraph here.")],
            headers=RATE_LIMIT_HEADERS,
        )
        commits = await client.get_recent_commits("owner", "repo")
        assert commits[0].message == "feat: title"

    async def test_empty_commits(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_COMMITS, json=[], headers=RATE_LIMIT_HEADERS)
        commits = await client.get_recent_commits("owner", "repo")
        assert commits == []

    async def test_rate_limit(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for _ in range(4):
            httpx_mock.add_response(
                url=_COMMITS,
                status_code=429,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
            )
        with pytest.raises(RateLimitExceeded):
            await client.get_recent_commits("owner", "repo")

    async def test_custom_count(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_COMMITS,
            json=[self._commit(f"sha{i}", f"commit {i}") for i in range(5)],
            headers=RATE_LIMIT_HEADERS,
        )
        commits = await client.get_recent_commits("owner", "repo", count=5)
        assert len(commits) == 5


# ── get_dependency_files ──────────────────────────────────────────────────────

class TestGetDependencyFiles:
    _DEP_FILES = [
        "package.json", "pyproject.toml", "requirements.txt", "go.mod",
        "Cargo.toml", "pom.xml", "Gemfile", "build.gradle",
    ]

    def _dep_url(self, filename: str) -> re.Pattern:
        escaped = re.escape(filename)
        return re.compile(
            rf"https://api\.github\.com/repos/owner/repo/contents/{escaped}"
        )

    async def test_happy_path(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=self._dep_url("pyproject.toml"),
            json={"content": _b64('[project]\nname = "test"')},
            headers=RATE_LIMIT_HEADERS,
        )
        for f in self._DEP_FILES:
            if f != "pyproject.toml":
                httpx_mock.add_response(
                    url=self._dep_url(f),
                    status_code=404,
                    headers=RATE_LIMIT_HEADERS,
                )
        files = await client.get_dependency_files("owner", "repo")
        assert "pyproject.toml" in files
        assert "[project]" in files["pyproject.toml"]
        assert "package.json" not in files

    async def test_no_dependency_files(self, client: GitHubClient, httpx_mock: HTTPXMock):
        for f in self._DEP_FILES:
            httpx_mock.add_response(
                url=self._dep_url(f),
                status_code=404,
                headers=RATE_LIMIT_HEADERS,
            )
        files = await client.get_dependency_files("owner", "repo")
        assert files == {}

    async def test_multiple_files(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=self._dep_url("package.json"),
            json={"content": _b64('{"name": "test"}')},
            headers=RATE_LIMIT_HEADERS,
        )
        httpx_mock.add_response(
            url=self._dep_url("requirements.txt"),
            json={"content": _b64("fastapi\nhttpx\n")},
            headers=RATE_LIMIT_HEADERS,
        )
        for f in self._DEP_FILES:
            if f not in ("package.json", "requirements.txt"):
                httpx_mock.add_response(
                    url=self._dep_url(f),
                    status_code=404,
                    headers=RATE_LIMIT_HEADERS,
                )
        files = await client.get_dependency_files("owner", "repo")
        assert "package.json" in files
        assert "requirements.txt" in files
        assert len(files) == 2


# ── parse_owner_repo ──────────────────────────────────────────────────────────

class TestParseOwnerRepo:
    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo/", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("github.com/owner/repo", ("owner", "repo")),
        ("owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo/tree/main", ("owner", "repo")),
        ("  owner/repo  ", ("owner", "repo")),
    ])
    def test_valid_urls(self, url: str, expected: tuple[str, str]):
        assert GitHubClient.parse_owner_repo(url) == expected

    @pytest.mark.parametrize("url", [
        "",
        "not-a-url",
        "https://gitlab.com/owner/repo",
        "justonepart",
        "/",
    ])
    def test_invalid_urls(self, url: str):
        with pytest.raises(ValueError):
            GitHubClient.parse_owner_repo(url)

    def test_git_suffix_stripped(self):
        owner, repo = GitHubClient.parse_owner_repo("https://github.com/org/project.git")
        assert repo == "project"

    def test_trailing_slash_stripped(self):
        owner, repo = GitHubClient.parse_owner_repo("  owner/repo/  ")
        assert owner == "owner"
        assert repo == "repo"


# ── rate limit state tracking ─────────────────────────────────────────────────

class TestRateLimitTracking:
    async def test_low_rate_limit_tracked(self, client: GitHubClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [], "total_count": 0},
            headers={"X-RateLimit-Remaining": "5", "X-RateLimit-Reset": "9999999999"},
        )
        await client.search_repositories("test")
        assert client._rate_limit_remaining == 5

    async def test_retry_succeeds_on_third_attempt(
        self, client: GitHubClient, httpx_mock: HTTPXMock
    ):
        # Two 429s then success
        httpx_mock.add_response(
            url=_SEARCH,
            status_code=429,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
        )
        httpx_mock.add_response(
            url=_SEARCH,
            status_code=429,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
        )
        httpx_mock.add_response(
            url=_SEARCH,
            json={"items": [_repo_payload()], "total_count": 1},
            headers=RATE_LIMIT_HEADERS,
        )
        results = await client.search_repositories("test")
        assert len(results) == 1
