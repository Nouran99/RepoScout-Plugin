"""Project health scorer — produces a 0-100 HealthScore from repo metadata."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from mcp_server.models.github import (
    CommitSummary,
    FileEntry,
    HealthScore,
    RepoDetails,
)

# ── License tiers ─────────────────────────────────────────────────────────────
_PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD"}
_WEAK_COPYLEFT = {"LGPL-2.0", "LGPL-2.1", "LGPL-3.0", "MPL-2.0", "EUPL-1.1", "EUPL-1.2"}
_COPYLEFT = {"GPL-2.0", "GPL-3.0", "GPL-2.0-only", "GPL-3.0-only", "GPL-2.0-or-later",
             "GPL-3.0-or-later"}
_STRONG_COPYLEFT = {"AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0"}

# ── CI / linter / type-check file patterns ───────────────────────────────────
_CI_FILES = {
    ".github",          # GitHub Actions workflows directory
    ".travis.yml",
    ".circleci",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
    ".drone.yml",
    "circle.yml",
}
_LINTER_FILES = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
    ".pylintrc", "ruff.toml", ".ruff.toml", "pyproject.toml",  # pyproject counts if present
    ".flake8", "setup.cfg", ".rubocop.yml", "golangci.yml", ".golangci.yml",
}
_TYPE_CHECK_FILES = {
    "mypy.ini", ".mypy.ini", "pyrightconfig.json", "tsconfig.json",
    ".tsbuildinfo", "pyproject.toml",  # mypy section in pyproject counts
}
_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "test_", "e2e"}
_DOCS_DIRS = {"docs", "doc", "documentation", "wiki"}
_CONTRIBUTING_FILES = {"contributing.md", "contributing.rst", "contributing"}
_LICENSE_FILES = {"license", "license.md", "license.txt", "licence", "copying"}


def _now() -> datetime:
    return datetime.now(UTC)


def _days_since(dt: datetime) -> float:
    """Return days elapsed since *dt* (timezone-aware)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (_now() - dt).total_seconds() / 86400


class HealthScorer:
    """Compute a HealthScore from repository metadata."""

    @staticmethod
    def score(
        repo: RepoDetails,
        commits: list[CommitSummary],
        dependency_files: dict[str, str],
        file_tree: list[FileEntry],
    ) -> HealthScore:
        """Compute a 0-100 health score for a repository.

        Args:
            repo: Extended repository metadata.
            commits: Recent commits (used for recency and activity).
            dependency_files: Map of filename → content for manifest files.
            file_tree: Top-level file/directory listing.

        Returns:
            HealthScore with total, per-dimension breakdown, flags, and verdict.
        """
        names_lower = {e.name.lower() for e in file_tree}
        breakdown: dict[str, int] = {}
        flags: list[str] = []

        # ── 1. Recency (25) ───────────────────────────────────────────────────
        days = _days_since(repo.pushed_at)
        if days < 30:
            recency = 25
        elif days < 90:
            recency = 17
        elif days < 180:
            recency = 10
        elif days < 365:
            recency = 5
        else:
            recency = 1
            flags.append("No commits in 6 months")
        breakdown["recency"] = recency

        # ── 2. Activity (20) ─────────────────────────────────────────────────
        cutoff = _now().timestamp() - 90 * 86400
        recent_count = sum(
            1 for c in commits
            if (c.authored_date.replace(tzinfo=UTC)
                if c.authored_date.tzinfo is None
                else c.authored_date).timestamp() >= cutoff
        )
        if recent_count > 50:
            activity = 20
        elif recent_count > 20:
            activity = 15
        elif recent_count > 5:
            activity = 10
        elif recent_count > 0:
            activity = 5
        else:
            activity = 0
        breakdown["activity"] = activity

        # ── 3. Community (15) ────────────────────────────────────────────────
        contributors = repo.contributors_count or 0
        raw = (repo.stargazers_count + repo.forks_count * 2 + contributors * 3) / 1000
        community = round(min(raw, 1.0) * 15)
        if contributors < 3:
            flags.append("Few contributors (<3)")
        breakdown["community"] = community

        # ── 4. Documentation (15) ────────────────────────────────────────────
        docs = 0
        # README scoring determined by file content length heuristic via tree size
        # We can't easily know README length without fetching it, so we check presence
        # and use the repo description as a proxy for having some docs.
        # If the caller has a README, they can pass it via a richer API; here we
        # detect the file and estimate quality from repo description + size.
        has_readme = any(n.startswith("readme") for n in names_lower)
        if has_readme:
            # Assume >500 chars if repo has description and is non-trivial size
            if repo.description and len(repo.description) > 20 and repo.size > 10:
                docs += 6
            else:
                docs += 3
        has_contributing = any(n in _CONTRIBUTING_FILES for n in names_lower)
        if has_contributing:
            docs += 3
        has_docs_dir = any(
            e.type == "dir" and e.name.lower() in _DOCS_DIRS for e in file_tree
        )
        if has_docs_dir:
            docs += 3
        has_license_file = any(n in _LICENSE_FILES for n in names_lower)
        if has_license_file:
            docs += 3
        breakdown["documentation"] = min(docs, 15)

        # ── 5. Code quality (15) ─────────────────────────────────────────────
        quality = 0
        has_ci = bool(names_lower & _CI_FILES)
        if has_ci:
            quality += 5
        else:
            flags.append("No CI")
        has_tests = any(
            (e.type == "dir" and e.name.lower() in _TEST_DIRS)
            or (e.type == "file" and (
                e.name.lower().startswith("test_")
                or e.name.lower().endswith("_test.py")
                or e.name.lower().endswith(".test.js")
                or e.name.lower().endswith(".spec.js")
                or e.name.lower().endswith(".test.ts")
                or e.name.lower().endswith(".spec.ts")
            ))
            for e in file_tree
        )
        if has_tests:
            quality += 4
        else:
            flags.append("No tests")
        has_linter = bool(names_lower & _LINTER_FILES)
        if has_linter:
            quality += 3
        has_type_check = bool(names_lower & _TYPE_CHECK_FILES)
        if has_type_check:
            quality += 3
        breakdown["code_quality"] = min(quality, 15)

        # ── 6. License (10) ──────────────────────────────────────────────────
        spdx = (repo.license_spdx or "").strip()
        if spdx in _PERMISSIVE:
            license_score = 10
        elif spdx in _WEAK_COPYLEFT:
            license_score = 7
        elif spdx in _COPYLEFT:
            license_score = 4
        elif spdx in _STRONG_COPYLEFT:
            license_score = 2
        else:
            license_score = 0
            flags.append("No license")
        breakdown["license"] = license_score

        # ── Extra flags ───────────────────────────────────────────────────────
        if repo.archived:
            flags.append("Archived")
        open_issues = repo.open_issues_count
        if open_issues > 0 and repo.forks_count > 0:
            ratio = open_issues / max(repo.stargazers_count, 1)
            if ratio > 0.1:
                flags.append("High issue ratio")

        # ── Total & verdict ───────────────────────────────────────────────────
        total = sum(breakdown.values())
        verdict: Literal["Excellent", "Good", "Fair", "Risky", "Abandoned"]
        if total >= 80:
            verdict = "Excellent"
        elif total >= 60:
            verdict = "Good"
        elif total >= 40:
            verdict = "Fair"
        elif total >= 20:
            verdict = "Risky"
        else:
            verdict = "Abandoned"

        return HealthScore(
            total_score=total,
            breakdown=breakdown,
            flags=flags,
            verdict=verdict,
        )
