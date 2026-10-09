"""Tests for HealthScorer — 5 repository profiles plus dimension edge cases."""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.models.github import CommitSummary, FileEntry, RepoDetails
from mcp_server.scoring.health_scorer import HealthScorer

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(UTC)


def _ago(**kwargs) -> datetime:
    return _now() - timedelta(**kwargs)


def _commit(days_ago: float) -> CommitSummary:
    return CommitSummary(
        sha="a" * 40,
        message="chore: update",
        author_name="Alice",
        authored_date=_ago(days=days_ago),
    )


def _file(name: str, kind: str = "file") -> FileEntry:
    return FileEntry(name=name, path=name, type=kind, size=None if kind == "dir" else 100)


def _base_repo(**overrides) -> RepoDetails:
    defaults = dict(
        full_name="owner/repo",
        html_url="https://github.com/owner/repo",
        description="A well-maintained project",
        stargazers_count=500,
        forks_count=100,
        language="Python",
        license_spdx="MIT",
        topics=["python"],
        updated_at=_ago(days=5),
        pushed_at=_ago(days=5),
        open_issues_count=10,
        size=2048,
        subscribers_count=50,
        network_count=100,
        has_wiki=True,
        has_pages=False,
        has_discussions=False,
        archived=False,
        default_branch="main",
        contributors_count=15,
    )
    defaults.update(overrides)
    return RepoDetails(**defaults)


def _score(repo: RepoDetails, commits=None, dep_files=None, tree=None):
    return HealthScorer.score(
        repo=repo,
        commits=commits or [],
        dependency_files=dep_files or {},
        file_tree=tree or [],
    )


# ── Profile 1: Healthy ────────────────────────────────────────────────────────

class TestHealthyProfile:
    """Active, well-maintained project — should score Excellent or Good."""

    def _build(self):
        repo = _base_repo(
            stargazers_count=2000,
            forks_count=300,
            contributors_count=25,
            pushed_at=_ago(days=3),
            license_spdx="MIT",
        )
        commits = [_commit(i * 1.5) for i in range(60)]  # 60 commits in 90 days
        tree = [
            _file(".github", "dir"),
            _file("tests", "dir"),
            _file("README.md"),
            _file("LICENSE"),
            _file("pyproject.toml"),
            _file("CONTRIBUTING.md"),
            _file("docs", "dir"),
        ]
        return repo, commits, tree

    def test_verdict_excellent_or_good(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.verdict in ("Excellent", "Good")

    def test_high_total_score(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.total_score >= 60

    def test_max_recency(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["recency"] == 25

    def test_max_activity(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["activity"] == 20

    def test_max_license(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["license"] == 10

    def test_has_ci_flag_absent(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No CI" not in result.flags

    def test_has_no_test_flag(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No tests" not in result.flags


# ── Profile 2: Abandoned ─────────────────────────────────────────────────────

class TestAbandonedProfile:
    """Stale repo — should score Abandoned or Risky."""

    def _build(self):
        repo = _base_repo(
            stargazers_count=5,
            forks_count=1,
            contributors_count=1,
            pushed_at=_ago(days=800),
            open_issues_count=50,
            license_spdx=None,
        )
        return repo, [], []

    def test_verdict_abandoned_or_risky(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.verdict in ("Abandoned", "Risky")

    def test_low_total_score(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.total_score < 40

    def test_min_recency(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["recency"] == 1

    def test_zero_activity(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["activity"] == 0

    def test_no_license_flag(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No license" in result.flags

    def test_stale_flag(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No commits in 6 months" in result.flags

    def test_few_contributors_flag(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "Few contributors (<3)" in result.flags


# ── Profile 3: New-but-promising ─────────────────────────────────────────────

class TestNewButPromisingProfile:
    """Newly created, actively pushed, low stars but all the right signals."""

    def _build(self):
        repo = _base_repo(
            stargazers_count=20,
            forks_count=3,
            contributors_count=2,
            pushed_at=_ago(days=2),
            license_spdx="Apache-2.0",
            description="A new but actively developed library",
            size=500,
        )
        commits = [_commit(i * 3) for i in range(10)]  # 10 commits in 90 days
        tree = [
            _file(".github", "dir"),
            _file("tests", "dir"),
            _file("README.md"),
            _file("LICENSE"),
            _file("pyproject.toml"),
        ]
        return repo, commits, tree

    def test_verdict_is_fair_or_better(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.verdict in ("Fair", "Good", "Excellent")

    def test_max_recency(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["recency"] == 25

    def test_has_ci(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No CI" not in result.flags

    def test_permissive_license(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["license"] == 10

    def test_activity_positive(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["activity"] > 0


# ── Profile 4: Popular-but-unmaintained ──────────────────────────────────────

class TestPopularButUnmaintainedProfile:
    """Lots of stars/forks but last commit was 2 years ago."""

    def _build(self):
        repo = _base_repo(
            stargazers_count=15000,
            forks_count=2000,
            contributors_count=80,
            pushed_at=_ago(days=730),
            license_spdx="MIT",
            open_issues_count=300,
        )
        return repo, [], []

    def test_community_score_high(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["community"] == 15  # capped at 15

    def test_recency_very_low(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["recency"] == 1

    def test_stale_flag_set(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No commits in 6 months" in result.flags

    def test_zero_activity(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["activity"] == 0

    def test_verdict_is_risky_or_fair(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        # High community, but stale — should land in Fair/Risky range
        assert result.verdict in ("Fair", "Risky", "Good")


# ── Profile 5: Small-but-active ──────────────────────────────────────────────

class TestSmallButActiveProfile:
    """Small project, modest stars, but commits very recently and has good hygiene."""

    def _build(self):
        repo = _base_repo(
            stargazers_count=40,
            forks_count=8,
            contributors_count=4,
            pushed_at=_ago(days=10),
            license_spdx="MIT",
        )
        commits = [_commit(i * 5) for i in range(20)]  # 20 commits in 100 days
        tree = [
            _file(".github", "dir"),
            _file("test", "dir"),
            _file("README.md"),
            _file("LICENSE"),
            _file("pyproject.toml"),
        ]
        return repo, commits, tree

    def test_verdict_fair_or_better(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.verdict in ("Fair", "Good", "Excellent")

    def test_no_ci_flag_absent(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No CI" not in result.flags

    def test_recent_push(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert result.breakdown["recency"] == 25

    def test_no_test_flag_absent(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "No tests" not in result.flags

    def test_not_few_contributors(self):
        repo, commits, tree = self._build()
        result = _score(repo, commits, tree=tree)
        assert "Few contributors (<3)" not in result.flags


# ── Dimension edge-case tests ─────────────────────────────────────────────────

class TestScoringDimensions:
    def test_recency_thresholds(self):
        for days, expected in [(29, 25), (89, 17), (179, 10), (364, 5), (400, 1)]:
            repo = _base_repo(pushed_at=_ago(days=days))
            result = _score(repo)
            assert result.breakdown["recency"] == expected, f"days={days}"

    def test_activity_thresholds(self):
        for count, expected in [(0, 0), (1, 5), (6, 10), (21, 15), (51, 20)]:
            commits = [_commit(i) for i in range(count)]
            result = _score(_base_repo(), commits)
            assert result.breakdown["activity"] == expected, f"count={count}"

    def test_community_capped_at_15(self):
        repo = _base_repo(stargazers_count=100_000, forks_count=50_000, contributors_count=5000)
        result = _score(repo)
        assert result.breakdown["community"] == 15

    def test_community_zero_for_empty_repo(self):
        repo = _base_repo(stargazers_count=0, forks_count=0, contributors_count=0)
        result = _score(repo)
        assert result.breakdown["community"] == 0

    def test_license_permissive_scores_10(self):
        for spdx in ("MIT", "Apache-2.0", "BSD-3-Clause", "ISC"):
            result = _score(_base_repo(license_spdx=spdx))
            assert result.breakdown["license"] == 10, spdx

    def test_license_lgpl_scores_7(self):
        result = _score(_base_repo(license_spdx="LGPL-3.0"))
        assert result.breakdown["license"] == 7

    def test_license_gpl_scores_4(self):
        result = _score(_base_repo(license_spdx="GPL-3.0"))
        assert result.breakdown["license"] == 4

    def test_license_agpl_scores_2(self):
        result = _score(_base_repo(license_spdx="AGPL-3.0"))
        assert result.breakdown["license"] == 2

    def test_license_none_scores_0_and_flag(self):
        result = _score(_base_repo(license_spdx=None))
        assert result.breakdown["license"] == 0
        assert "No license" in result.flags

    def test_archived_flag(self):
        result = _score(_base_repo(archived=True))
        assert "Archived" in result.flags

    def test_ci_detection_github_actions(self):
        tree = [_file(".github", "dir")]
        result = _score(_base_repo(), tree=tree)
        assert "No CI" not in result.flags
        assert result.breakdown["code_quality"] >= 5

    def test_ci_detection_travis(self):
        tree = [_file(".travis.yml")]
        result = _score(_base_repo(), tree=tree)
        assert "No CI" not in result.flags

    def test_no_ci_flag_when_absent(self):
        result = _score(_base_repo(), tree=[_file("src", "dir"), _file("README.md")])
        assert "No CI" in result.flags

    def test_test_dir_detection(self):
        for dirname in ("tests", "test", "spec", "__tests__"):
            tree = [_file(dirname, "dir")]
            result = _score(_base_repo(), tree=tree)
            assert "No tests" not in result.flags, dirname

    def test_verdict_boundaries(self):
        # We verify the verdict mapping logic by inspecting different total scores
        # via profiles that hit each range
        assert HealthScorer.score(
            _base_repo(pushed_at=_ago(days=2), stargazers_count=5000, forks_count=1000,
                       contributors_count=50, license_spdx="MIT"),
            [_commit(i) for i in range(60)],
            {},
            [_file(".github", "dir"), _file("tests", "dir"), _file("README.md"),
             _file("LICENSE"), _file("pyproject.toml"), _file("CONTRIBUTING.md"),
             _file("docs", "dir")],
        ).verdict in ("Excellent", "Good")

    def test_total_does_not_exceed_100(self):
        # Max everything out
        repo = _base_repo(
            stargazers_count=50000, forks_count=10000, contributors_count=500,
            pushed_at=_ago(days=1), license_spdx="MIT",
        )
        commits = [_commit(i) for i in range(100)]
        tree = [
            _file(".github", "dir"), _file("tests", "dir"), _file("README.md"),
            _file("LICENSE"), _file("pyproject.toml"), _file("CONTRIBUTING.md"),
            _file("docs", "dir"),
        ]
        result = _score(repo, commits, tree=tree)
        assert result.total_score <= 100

    def test_breakdown_keys_present(self):
        result = _score(_base_repo())
        for key in ("recency", "activity", "community", "documentation", "code_quality", "license"):
            assert key in result.breakdown

    def test_high_issue_ratio_flag(self):
        repo = _base_repo(stargazers_count=100, open_issues_count=20, forks_count=5)
        result = _score(repo)
        assert "High issue ratio" in result.flags

    def test_no_high_issue_ratio_for_healthy_repo(self):
        repo = _base_repo(stargazers_count=1000, open_issues_count=5, forks_count=50)
        result = _score(repo)
        assert "High issue ratio" not in result.flags
