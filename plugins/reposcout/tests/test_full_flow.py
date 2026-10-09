"""
End-to-end integration tests for the 5 RepoScout MCP tools.

Every external I/O call is mocked (GitHub API, backend API, subprocess).
These tests exercise the full internal pipeline:
  query expansion → parallel GitHub search → deduplication → health scoring
  → response assembly → LicenseChecker enforcement → usage logging.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.clients.github_client import GitHubClient as _RealGitHubClient
from mcp_server.middleware.license_check import LicenseError
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

# ── Shared test constants ─────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# ── Fixture factories ─────────────────────────────────────────────────────────

def _sr(
    name: str = "owner/repo",
    stars: int = 500,
    license_spdx: str | None = "MIT",
    language: str = "Python",
) -> RepoSearchResult:
    """Build a minimal RepoSearchResult for use in tests."""
    return RepoSearchResult(
        full_name=name,
        html_url=f"https://github.com/{name}",
        description="A starter project",
        stargazers_count=stars,
        forks_count=max(1, stars // 10),
        language=language,
        license_spdx=license_spdx,
        topics=["python", "saas"],
        updated_at=_NOW,
        pushed_at=_NOW,
        open_issues_count=5,
        size=2048,
    )


def _details(
    name: str = "owner/repo",
    license_spdx: str | None = "MIT",
    pushed_at: datetime | None = None,
    stars: int = 500,
) -> RepoDetails:
    """Build a RepoDetails from a search result."""
    sr = _sr(name, stars=stars, license_spdx=license_spdx)
    _excl = {"license_spdx", "pushed_at", "updated_at"}
    base = {k: v for k, v in sr.model_dump().items() if k not in _excl}
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


def _tree(include_ci: bool = True, include_tests: bool = True) -> list[FileEntry]:
    entries = [
        FileEntry(name="README.md", path="README.md", type="file", size=1200),
        FileEntry(name="pyproject.toml", path="pyproject.toml", type="file", size=800),
    ]
    if include_ci:
        entries.append(FileEntry(name=".github", path=".github", type="dir", size=None))
    if include_tests:
        entries.append(FileEntry(name="tests", path="tests", type="dir", size=None))
    return entries


def _commits(n: int = 10) -> list[CommitSummary]:
    return [
        CommitSummary(
            sha="a" * 40,
            message=f"feat: commit {i}",
            author_name="Dev",
            authored_date=_NOW - timedelta(days=i * 3),
        )
        for i in range(n)
    ]


def _gh_client(
    search_results: list[RepoSearchResult] | None = None,
    repo_details: RepoDetails | None = None,
) -> MagicMock:
    """Build a fully configured async-context-manager mock of GitHubClient."""
    m = MagicMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    m.search_repositories = AsyncMock(
        return_value=search_results if search_results is not None else [_sr()]
    )
    m.get_repo_details = AsyncMock(
        return_value=repo_details if repo_details is not None else _details()
    )
    m.get_repo_readme = AsyncMock(return_value="# README\n\nA project.")
    m.get_repo_tree = AsyncMock(return_value=_tree())
    m.get_repo_languages = AsyncMock(return_value={"Python": 45000, "Shell": 1000})
    m.get_recent_commits = AsyncMock(return_value=_commits())
    m.get_dependency_files = AsyncMock(
        return_value={
            "pyproject.toml": (
                '[tool.poetry]\nname = "app"\n'
                '[tool.poetry.dependencies]\nfastapi = "*"\npostgresql = "*"\n'
            )
        }
    )
    return m


def _checker(blocked: bool = False) -> MagicMock:
    """Build a LicenseChecker mock. blocked=True makes check() raise LicenseError."""
    m = MagicMock()
    if blocked:
        m.check = AsyncMock(side_effect=LicenseError("Free tier limit reached (10 calls/day)."))
    else:
        m.check = AsyncMock(return_value={"allowed": True, "tier": "free"})
    m.log_usage = AsyncMock()
    m.increment_local_usage = MagicMock()
    return m


def _settings(api_key: str | None = None) -> MagicMock:
    """Build a settings mock."""
    m = MagicMock()
    m.github_token = None
    m.reposcout_api_key = api_key
    m.reposcout_backend_url = "http://localhost:8000"
    m.reposcout_license_fail_open = False
    return m


def _gh_cls(client: MagicMock) -> MagicMock:
    """Mock the GitHubClient CLASS, preserving the real parse_owner_repo static method."""
    mock_cls = MagicMock(return_value=client)
    mock_cls.parse_owner_repo = _RealGitHubClient.parse_owner_repo
    return mock_cls


# ── Test 1: Full search flow ──────────────────────────────────────────────────

async def test_full_search_flow():
    """Query expansion → parallel search → dedup → health scoring → sorted results."""
    # Two query batches, "owner/best" appears in both → must appear once in output
    results_q1 = [
        _sr("owner/best", stars=3000),
        _sr("owner/middle", stars=1000),
        _sr("owner/low", stars=200),
    ]
    results_q2 = [
        _sr("owner/best", stars=3000),    # duplicate full_name
        _sr("owner/another", stars=500),
    ]
    call_n = 0

    async def _search_side_effect(**_kwargs):
        nonlocal call_n
        call_n += 1
        return results_q1 if call_n == 1 else results_q2

    client = _gh_client()
    client.search_repositories = AsyncMock(side_effect=_search_side_effect)
    ck = _checker()
    s = _settings()

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        result = await search_repos("React dashboard with auth")

    # Basic structure
    assert isinstance(result, dict)
    assert "results" in result
    assert "health_scores" in result
    assert "query_used" in result
    assert result["total_found"] >= 1

    names = [r["full_name"] for r in result["results"]]

    # Deduplication: no duplicate full_name in output
    assert len(names) == len(set(names)), "Duplicate repos leaked through dedup"
    assert names.count("owner/best") == 1

    # Health scores present and valid for every returned result
    for name in names:
        assert name in result["health_scores"], f"{name} missing from health_scores"
        score = result["health_scores"][name]["total_score"]
        assert 0 <= score <= 100
        assert result["health_scores"][name]["verdict"] in (
            "Excellent", "Good", "Fair", "Risky", "Abandoned"
        )

    # Results sorted descending by health score
    scores = [result["health_scores"][n]["total_score"] for n in names]
    assert scores == sorted(scores, reverse=True), "Results not sorted by health score"

    # LicenseChecker called once; free-tier increment called once (no API key)
    ck.check.assert_awaited_once()
    ck.increment_local_usage.assert_called_once()


# ── Test 2: Search then analyze ───────────────────────────────────────────────

async def test_search_then_analyze():
    """Top result from search is passed to analyze_repo; full deep analysis is returned."""
    target = "tiangolo/fastapi"
    s = _settings()

    # Step 1 — search
    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(_gh_client(search_results=[_sr(target, stars=5000)]))),
        patch("mcp_server.server.LicenseChecker", return_value=_checker()),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        search_out = await search_repos("FastAPI REST API boilerplate Python")

    assert len(search_out["results"]) > 0
    top_repo = search_out["results"][0]["full_name"]
    assert top_repo == target

    # Step 2 — analyze
    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(_gh_client(repo_details=_details(target, stars=5000)))),
        patch("mcp_server.server.LicenseChecker", return_value=_checker()),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        analysis = await analyze_repo(top_repo)

    # Repo metadata
    assert analysis["repo"]["full_name"] == target

    # Health score is a valid score + verdict
    h = analysis["health"]
    assert 0 <= h["total_score"] <= 100
    assert h["verdict"] in ("Excellent", "Good", "Fair", "Risky", "Abandoned")
    assert isinstance(h["breakdown"], dict)
    assert len(h["breakdown"]) > 0

    # Stack detected from dep file content (fastapi + postgresql keywords present)
    assert isinstance(analysis["detected_stack"], list)
    assert len(analysis["detected_stack"]) > 0
    stack = analysis["detected_stack"]
    assert "Python" in stack or "FastAPI" in stack

    # All analysis fields populated
    assert analysis["readme_content"] is not None
    assert len(analysis["file_tree"]) > 0
    assert "Python" in analysis["languages"]
    assert len(analysis["recent_commits"]) > 0
    assert "pyproject.toml" in analysis["dependency_files"]


# ── Test 3: Search then compare ───────────────────────────────────────────────

async def test_search_then_compare():
    """Top 2 search results are compared; report contains recommendation and reasoning."""
    repo_a = "tiangolo/fastapi"
    repo_b = "pallets/flask"
    s = _settings()

    # Step 1 — search
    with (
        patch(
            "mcp_server.server.GitHubClient",
            _gh_cls(_gh_client(search_results=[_sr(repo_a, stars=5000), _sr(repo_b, stars=3000)])),
        ),
        patch("mcp_server.server.LicenseChecker", return_value=_checker()),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        search_out = await search_repos("Python web framework starter template")

    urls = [r["full_name"] for r in search_out["results"][:2]]
    assert len(urls) == 2

    # Step 2 — compare; each analyze call gets a distinct details object
    details_seq = [
        _details(repo_a, stars=5000),
        _details(repo_b, stars=3000),
    ]
    call_idx = 0

    async def _seq_details(owner, repo):
        nonlocal call_idx
        d = details_seq[call_idx % len(details_seq)]
        call_idx += 1
        return d

    cmp_client = _gh_client()
    cmp_client.get_repo_details = AsyncMock(side_effect=_seq_details)

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(cmp_client)),
        patch("mcp_server.server.LicenseChecker", return_value=_checker()),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        comparison = await compare_repos(urls)

    # Structure
    assert "repos" in comparison
    assert "recommendation" in comparison
    assert "reasoning" in comparison
    assert len(comparison["repos"]) == 2

    # Recommendation is one of the two repos; reasoning mentions it
    repo_names = [e["name"] for e in comparison["repos"]]
    assert comparison["recommendation"] in repo_names
    assert comparison["recommendation"] in comparison["reasoning"]
    assert len(comparison["reasoning"]) > 0

    # Each comparison entry has all required fields
    for entry in comparison["repos"]:
        assert 0 <= entry["health_score"] <= 100
        assert entry["health_verdict"] in ("Excellent", "Good", "Fair", "Risky", "Abandoned")
        assert "stars" in entry
        assert "language" in entry
        assert isinstance(entry["has_tests"], bool)
        assert isinstance(entry["has_ci"], bool)
        assert isinstance(entry["detected_stack"], list)


# ── Test 4: Clone and scaffold ────────────────────────────────────────────────

async def test_clone_and_scaffold(tmp_path):
    """Mocked git clone produces correct file count, stack detection, and next-step hints."""
    repo_dir = tmp_path / "my-project"
    repo_dir.mkdir()

    # Simulate a cloned Python/FastAPI project
    (repo_dir / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "app"\n[tool.poetry.dependencies]\nfastapi = "*"\n'
    )
    (repo_dir / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (repo_dir / ".git").mkdir()
    (repo_dir / ".env.example").write_text("DATABASE_URL=postgresql://\nSECRET_KEY=\n")
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_ok(): pass\n")

    # Mock subprocess: returncode=0, no output
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    ck = _checker()
    s = _settings()

    with (
        patch(
            "mcp_server.server.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        ),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        result = await clone_and_scaffold("owner/repo", str(repo_dir))

    # .git directory removed (remove_git_history=True by default)
    assert not (repo_dir / ".git").exists(), ".git was not stripped"

    # File count: pyproject.toml + app.py + .env.example + tests/test_app.py = 4
    assert result["files_count"] == 4

    # Stack: Python (by extension) + FastAPI (from pyproject.toml content)
    assert "Python" in result["detected_stack"]
    assert "FastAPI" in result["detected_stack"]

    # Suggested next steps
    steps_text = " ".join(result["suggested_next_steps"])
    assert "pip install" in steps_text or "uv sync" in steps_text   # pyproject.toml present
    assert ".env" in steps_text                                       # .env.example present
    assert "git init" in steps_text                                   # always suggested


# ── Test 5: License check — permissive (MIT) ─────────────────────────────────

async def test_license_check_permissive():
    """MIT-licensed repo: commercial_use=True, is_permissive=True, no warnings."""
    client = _gh_client(repo_details=_details("owner/mit-repo", license_spdx="MIT"))
    ck = _checker()
    s = _settings()

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        result = await check_license_compatibility("owner/mit-repo")

    assert result["license_spdx"] == "MIT"
    assert result["is_permissive"] is True
    assert result["is_copyleft"] is False
    assert result["commercial_use_allowed"] is True
    assert result["modification_allowed"] is True
    assert result["distribution_allowed"] is True
    assert result["warnings"] == []
    assert "commercial" in result["compatibility_verdict"].lower()


# ── Test 6: License check — copyleft (GPL-3.0) ───────────────────────────────

async def test_license_check_copyleft():
    """GPL-3.0 repo: is_copyleft=True, commercial-distribution warnings present."""
    client = _gh_client(repo_details=_details("owner/gpl-repo", license_spdx="GPL-3.0"))
    ck = _checker()
    s = _settings()

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        result = await check_license_compatibility("owner/gpl-repo", intended_use="commercial")

    assert result["license_spdx"] == "GPL-3.0"
    assert result["is_copyleft"] is True
    assert result["is_permissive"] is False
    # GPL still allows commercial use (requires source disclosure on distribution)
    assert result["commercial_use_allowed"] is True
    # At least two warnings: one about source disclosure, one about commercial distribution
    assert len(result["warnings"]) >= 2
    warning_text = " ".join(result["warnings"]).lower()
    assert "gpl" in warning_text or "source code" in warning_text
    assert "commercial" in warning_text
    # Verdict explains the copyleft requirement
    assert "copyleft" in result["compatibility_verdict"].lower()


# ── Test 7: Free-tier daily limit ─────────────────────────────────────────────

async def test_free_tier_limit(tmp_path):
    """First 10 searches succeed; the 11th is blocked by the free-tier daily cap."""
    usage_file = tmp_path / "usage.json"
    usage_file.write_text("{}")   # start with empty usage

    client = _gh_client()
    s = _settings(api_key=None)   # no API key → free tier

    with (
        patch("mcp_server.middleware.license_check._USAGE_FILE", usage_file),
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        # Calls 1–10 should all succeed
        for i in range(10):
            result = await search_repos(f"test query {i}")
            assert "results" in result, f"Call {i + 1} should have succeeded"

        # 11th call must be blocked
        with pytest.raises(LicenseError, match="Free tier limit reached"):
            await search_repos("test query over limit")

    # Usage file should record exactly 10 calls for today
    data = json.loads(usage_file.read_text())
    today = str(date.today())
    assert data.get(today, 0) == 10


# ── Test 8: Pro key — high-volume search ──────────────────────────────────────

async def test_pro_key_unlimited():
    """With a Pro API key, 20 consecutive searches all succeed without hitting a limit."""
    client = _gh_client()
    ck = _checker()                                  # always allows
    s = _settings(api_key="rs_pro_test_key_abc123")

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        for i in range(20):
            result = await search_repos(f"saas boilerplate query {i}")
            assert "results" in result, f"Search {i + 1} unexpectedly failed"

    # Checker invoked once per call; pro tier uses log_usage (not local increment)
    assert ck.check.await_count == 20
    assert ck.log_usage.await_count == 20
    assert ck.increment_local_usage.call_count == 0


# ── Test 9: GitHub rate-limit — partial results ───────────────────────────────

async def test_github_rate_limit_partial_results():
    """Rate limit on one expanded query doesn't crash the tool — other queries' results survive."""
    good_results = [_sr(f"owner/repo-{i}", stars=200 * i) for i in range(1, 4)]
    call_n = 0

    async def _mixed_search(**_kwargs):
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            raise RateLimitExceeded(
                reset_at=datetime.now(UTC) + timedelta(minutes=1),
                message="Rate limit exceeded on first query",
            )
        return good_results

    client = _gh_client()
    client.search_repositories = AsyncMock(side_effect=_mixed_search)
    ck = _checker()
    s = _settings()

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.LicenseChecker", return_value=ck),
        patch("mcp_server.server.get_settings", return_value=s),
    ):
        # Description that expands to multiple queries so at least one succeeds
        result = await search_repos("saas dashboard auth stripe payments")

    # Must return results from the queries that succeeded — not crash
    assert "results" in result
    assert result["total_found"] > 0
    assert len(result["results"]) > 0
    # Health scores present for all returned results
    for r in result["results"]:
        assert r["full_name"] in result["health_scores"]


# ── Test 10: Backend unreachable — fail closed by default ─────────────────────

async def test_backend_unreachable_fails_closed_by_default(httpx_mock):
    """A production-style settings object must block calls when licensing is unavailable."""
    # Both the validate-key and the usage-logging POST will fail with ConnectError
    httpx_mock.add_exception(
        httpx.ConnectError("Connection refused"),
        url=re.compile(r"http://localhost:8000/api/v1/reposcout/validate-key"),
    )
    client = _gh_client()
    # Real LicenseChecker (not mocked) to exercise the production-safe default.
    s = _settings(api_key="rs_real_key_backend_down")

    with (
        patch("mcp_server.server.GitHubClient", _gh_cls(client)),
        patch("mcp_server.server.get_settings", return_value=s),
        pytest.raises(LicenseError),
    ):
        await search_repos("python saas starter")
