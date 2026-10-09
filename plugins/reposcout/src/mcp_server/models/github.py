"""Pydantic v2 models for all GitHub API data contracts used by the RepoScout MCP server."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RepoSearchResult(BaseModel):
    """A single repository returned from a GitHub search query."""

    full_name: str = Field(description="Owner and repo name in 'owner/repo' format")
    html_url: str = Field(description="URL to the repository on GitHub")
    description: str | None = Field(description="Short description provided by the repo owner")
    stargazers_count: int = Field(description="Number of GitHub stars")
    forks_count: int = Field(description="Number of times the repo has been forked")
    language: str | None = Field(description="Primary programming language detected by GitHub")
    license_spdx: str | None = Field(description="SPDX license identifier, e.g. 'MIT' or 'Apache-2.0'")
    topics: list[str] = Field(description="List of topic tags attached to the repository")
    updated_at: datetime = Field(description="Timestamp of the most recent push or metadata update")
    pushed_at: datetime = Field(description="Timestamp of the most recent commit push")
    open_issues_count: int = Field(description="Number of open issues and pull requests")
    size: int = Field(description="Repository size in kilobytes as reported by GitHub")


class RepoDetails(RepoSearchResult):
    """Extended repository details fetched from the single-repo endpoint."""

    subscribers_count: int = Field(description="Number of users watching (subscribing to) the repo")
    network_count: int = Field(description="Number of forks in the repository network")
    has_wiki: bool = Field(description="Whether the repository has a GitHub Wiki enabled")
    has_pages: bool = Field(description="Whether the repository has GitHub Pages enabled")
    has_discussions: bool = Field(description="Whether GitHub Discussions is enabled")
    archived: bool = Field(description="True if the repository is archived and read-only")
    default_branch: str = Field(description="Name of the default branch, e.g. 'main' or 'master'")
    contributors_count: int | None = Field(
        description="Total number of contributors; None if the endpoint was not called"
    )


class FileEntry(BaseModel):
    """A single entry in a repository's file tree."""

    name: str = Field(description="File or directory name (basename only)")
    path: str = Field(description="Full path relative to the repository root")
    type: Literal["file", "dir"] = Field(description="Whether this entry is a file or directory")
    size: int | None = Field(description="File size in bytes; None for directories")


class CommitSummary(BaseModel):
    """A condensed view of a single Git commit."""

    sha: str = Field(description="Full 40-character commit SHA")
    message: str = Field(description="The first line of the commit message")
    author_name: str = Field(description="Name of the commit author")
    authored_date: datetime = Field(description="UTC timestamp when the commit was authored")


class HealthScore(BaseModel):
    """Computed project-health score for a repository."""

    total_score: int = Field(ge=0, le=100, description="Overall health score from 0 (worst) to 100 (best)")
    breakdown: dict[str, int] = Field(
        description="Per-dimension scores, e.g. {'activity': 30, 'community': 20, 'docs': 10}"
    )
    flags: list[str] = Field(
        description="Human-readable warnings or positive signals, e.g. ['No CI detected', 'Active maintainer']"
    )
    verdict: Literal["Excellent", "Good", "Fair", "Risky", "Abandoned"] = Field(
        description="Qualitative label derived from the total score"
    )


class RepoAnalysis(BaseModel):
    """Full deep analysis of a single repository."""

    repo: RepoDetails = Field(description="Extended metadata for the analysed repository")
    readme_content: str | None = Field(description="Raw text of the README file, or None if absent")
    file_tree: list[FileEntry] = Field(description="Top-level file and directory listing")
    languages: dict[str, int] = Field(
        description="Language breakdown as bytes of code, e.g. {'Python': 45321, 'Shell': 1200}"
    )
    recent_commits: list[CommitSummary] = Field(description="Most recent commits, newest first")
    dependency_files: dict[str, str] = Field(
        description="Map of dependency filename to raw file content, e.g. {'requirements.txt': '...'}"
    )
    health: HealthScore = Field(description="Computed health score for this repository")
    detected_stack: list[str] = Field(
        description="Technology stack inferred from files, e.g. ['Python', 'FastAPI', 'PostgreSQL']"
    )


class ComparisonEntry(BaseModel):
    """Summary row for one repository inside a comparison report."""

    repo_url: str = Field(description="URL to the repository on GitHub")
    name: str = Field(description="Full repository name in 'owner/repo' format")
    stars: int = Field(description="Number of GitHub stars")
    health_score: int = Field(ge=0, le=100, description="Overall health score from 0 to 100")
    health_verdict: Literal["Excellent", "Good", "Fair", "Risky", "Abandoned"] = Field(
        description="Qualitative health label"
    )
    language: str | None = Field(description="Primary programming language")
    license: str | None = Field(description="SPDX license identifier")
    last_commit: datetime = Field(description="Timestamp of the most recent commit")
    has_tests: bool = Field(description="True if a test directory or test files were detected")
    has_ci: bool = Field(description="True if a CI configuration file was detected")
    detected_stack: list[str] = Field(description="Technology stack inferred from repository contents")


class ComparisonReport(BaseModel):
    """Side-by-side comparison of multiple repositories."""

    repos: list[ComparisonEntry] = Field(description="One entry per compared repository")
    recommendation: str = Field(
        description="Full name of the recommended repository, e.g. 'tiangolo/fastapi'"
    )
    reasoning: str = Field(description="Plain-English explanation of why this repository was chosen")


class ScaffoldResult(BaseModel):
    """Outcome of scaffolding a local project from a repository template."""

    target_dir: str = Field(description="Absolute path to the directory where files were written")
    files_count: int = Field(description="Number of files written to disk")
    detected_stack: list[str] = Field(description="Technology stack detected in the scaffolded project")
    suggested_next_steps: list[str] = Field(
        description="Ordered list of recommended actions after scaffolding, e.g. ['Run npm install', 'Copy .env.example']"
    )


class LicenseReport(BaseModel):
    """Licence compatibility and usage-rights analysis for a repository."""

    license_spdx: str | None = Field(description="SPDX identifier of the detected licence")
    license_name: str | None = Field(description="Human-readable licence name")
    is_permissive: bool = Field(description="True for permissive licences such as MIT, Apache-2.0, BSD")
    is_copyleft: bool = Field(description="True for copyleft licences such as GPL, AGPL, LGPL")
    commercial_use_allowed: bool = Field(description="Whether commercial use is permitted")
    modification_allowed: bool = Field(description="Whether modification of the source is permitted")
    distribution_allowed: bool = Field(description="Whether redistribution is permitted")
    compatibility_verdict: str = Field(
        description="Short verdict on licence compatibility for typical SaaS use, e.g. 'Safe for commercial use'"
    )
    warnings: list[str] = Field(
        description="Any licence-related warnings the developer should be aware of"
    )


class SearchResults(BaseModel):
    """Paginated search results returned to the MCP client."""

    query_used: str = Field(description="The exact GitHub search query string that was executed")
    total_found: int = Field(description="Total number of repositories GitHub found (may exceed results list)")
    results: list[RepoSearchResult] = Field(description="Repositories returned in this response page")
    health_scores: dict[str, HealthScore] = Field(
        description="Map of 'owner/repo' to its computed health score"
    )


class RateLimitExceeded(Exception):
    """Raised when the GitHub API rate limit has been hit.

    Attributes:
        reset_at: UTC datetime when the rate limit window resets.
        message: Human-readable explanation of the rate limit error.
    """

    def __init__(self, reset_at: datetime, message: str) -> None:
        self.reset_at: datetime = reset_at
        self.message: str = message
        super().__init__(message)
