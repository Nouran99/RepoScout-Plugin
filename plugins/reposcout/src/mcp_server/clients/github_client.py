"""GitHub API client — all GitHub HTTP calls go through this class."""
from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from mcp_server.models.github import (
    CommitSummary,
    FileEntry,
    RateLimitExceeded,
    RepoDetails,
    RepoSearchResult,
)

logger = structlog.get_logger(__name__)

_DEPENDENCY_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "Gemfile",
    "build.gradle",
]

_RETRY_DELAYS = [1.0, 2.0, 4.0]  # seconds for exponential backoff


class GitHubClient:
    """Async GitHub API client with rate-limit tracking and exponential backoff."""

    def __init__(self, token: str | None = None) -> None:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=30.0,
        )
        self._rate_limit_remaining: int | None = None
        self._rate_limit_reset: datetime | None = None

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    # ── Core request method ───────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an authenticated request with rate-limit tracking and retry logic.

        Args:
            method: HTTP method (GET, POST, …).
            path: Path relative to https://api.github.com.
            **kwargs: Extra arguments forwarded to httpx.

        Returns:
            The httpx.Response on success.

        Raises:
            RateLimitExceeded: When all retries are exhausted due to 403/429.
            httpx.HTTPStatusError: For other non-2xx responses.
        """
        last_exc: Exception | None = None

        for attempt, delay in enumerate([0.0] + _RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)

            response = await self._client.request(method, path, **kwargs)
            self._update_rate_limit(response)

            if response.status_code in (403, 429):
                reset_at = self._rate_limit_reset or datetime.now(UTC)
                msg = (
                    f"GitHub rate limit hit (attempt {attempt + 1}/4). "
                    f"Resets at {reset_at.isoformat()}"
                )
                logger.warning("github_rate_limit", attempt=attempt + 1, reset_at=reset_at)
                last_exc = RateLimitExceeded(reset_at=reset_at, message=msg)
                continue

            response.raise_for_status()
            return response

        raise last_exc  # type: ignore[misc]

    def _update_rate_limit(self, response: httpx.Response) -> None:
        """Parse rate-limit headers and warn if running low."""
        remaining_str = response.headers.get("X-RateLimit-Remaining")
        reset_str = response.headers.get("X-RateLimit-Reset")

        if remaining_str is not None:
            self._rate_limit_remaining = int(remaining_str)
        if reset_str is not None:
            self._rate_limit_reset = datetime.fromtimestamp(int(reset_str), tz=UTC)

        if self._rate_limit_remaining is not None and self._rate_limit_remaining < 10:
            logger.warning(
                "github_rate_limit_low",
                remaining=self._rate_limit_remaining,
                reset_at=self._rate_limit_reset,
            )

    # ── Public API methods ────────────────────────────────────────────────────

    async def search_repositories(
        self,
        query: str,
        language: str | None = None,
        min_stars: int | None = None,
        topics: list[str] | None = None,
        license_type: str | None = None,
        sort_by: str = "stars",
        per_page: int = 10,
    ) -> list[RepoSearchResult]:
        """Search GitHub repositories and return structured results.

        Args:
            query: Free-text search query.
            language: Filter by programming language.
            min_stars: Minimum star count filter.
            topics: List of topic tags to require.
            license_type: SPDX license identifier to filter by.
            sort_by: Sort field — 'stars', 'forks', 'updated', or 'best-match'.
            per_page: Number of results to return (max 100).

        Returns:
            List of RepoSearchResult ordered by sort_by.
        """
        parts = [query]
        if language:
            parts.append(f"language:{language}")
        if min_stars is not None:
            parts.append(f"stars:>={min_stars}")
        if topics:
            for topic in topics:
                parts.append(f"topic:{topic}")
        if license_type:
            parts.append(f"license:{license_type}")

        full_query = " ".join(parts)
        response = await self._request(
            "GET",
            "/search/repositories",
            params={"q": full_query, "sort": sort_by, "per_page": per_page},
        )
        items: list[dict[str, Any]] = response.json().get("items", [])
        return [_parse_search_result(item) for item in items]

    async def get_repo_details(self, owner: str, repo: str) -> RepoDetails:
        """Fetch extended metadata for a single repository.

        Args:
            owner: Repository owner login.
            repo: Repository name.

        Returns:
            RepoDetails with full metadata including subscriber and network counts.
        """
        response = await self._request("GET", f"/repos/{owner}/{repo}")
        data: dict[str, Any] = response.json()

        contributors_count: int | None = None
        try:
            contrib_resp = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contributors",
                params={"per_page": 1, "anon": "false"},
            )
            # GitHub returns Link header for pagination; use list length as fallback
            link = contrib_resp.headers.get("Link", "")
            if 'rel="last"' in link:
                # Extract page number from last link
                import re
                match = re.search(r'page=(\d+)>; rel="last"', link)
                contributors_count = int(match.group(1)) if match else len(contrib_resp.json())
            else:
                contributors_count = len(contrib_resp.json())
        except (httpx.HTTPStatusError, httpx.TimeoutException):
            pass

        return _parse_repo_details(data, contributors_count)

    async def get_repo_readme(self, owner: str, repo: str) -> str | None:
        """Fetch the decoded README content for a repository.

        Args:
            owner: Repository owner login.
            repo: Repository name.

        Returns:
            Plain text README content, or None if no README exists.
        """
        try:
            response = await self._request("GET", f"/repos/{owner}/{repo}/readme")
            data: dict[str, Any] = response.json()
            content_b64 = data.get("content", "")
            return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def get_repo_tree(self, owner: str, repo: str, path: str = "") -> list[FileEntry]:
        """List the file tree at the given path (non-recursive).

        Args:
            owner: Repository owner login.
            repo: Repository name.
            path: Sub-path within the repo to list; empty string for root.

        Returns:
            List of FileEntry items at the specified path.
        """
        endpoint = f"/repos/{owner}/{repo}/contents/{path}".rstrip("/")
        try:
            response = await self._request("GET", endpoint)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        entries: list[dict[str, Any]] = response.json()
        if not isinstance(entries, list):
            return []
        return [
            FileEntry(
                name=e["name"],
                path=e["path"],
                type="dir" if e["type"] == "dir" else "file",
                size=e.get("size") if e["type"] != "dir" else None,
            )
            for e in entries
        ]

    async def get_repo_languages(self, owner: str, repo: str) -> dict[str, int]:
        """Return the language breakdown for a repository.

        Args:
            owner: Repository owner login.
            repo: Repository name.

        Returns:
            Mapping of language name to bytes of code.
        """
        response = await self._request("GET", f"/repos/{owner}/{repo}/languages")
        return dict(response.json())

    async def get_recent_commits(
        self, owner: str, repo: str, count: int = 10
    ) -> list[CommitSummary]:
        """Fetch the most recent commits on the default branch.

        Args:
            owner: Repository owner login.
            repo: Repository name.
            count: Maximum number of commits to return.

        Returns:
            List of CommitSummary ordered newest-first.
        """
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits",
            params={"per_page": count},
        )
        commits: list[dict[str, Any]] = response.json()
        results = []
        for c in commits:
            commit_data = c.get("commit", {})
            author = commit_data.get("author") or {}
            results.append(
                CommitSummary(
                    sha=c["sha"],
                    message=commit_data.get("message", "").split("\n")[0],
                    author_name=author.get("name", "Unknown"),
                    authored_date=author.get("date", datetime.now(UTC).isoformat()),
                )
            )
        return results

    async def get_dependency_files(self, owner: str, repo: str) -> dict[str, str]:
        """Fetch common dependency manifest files in parallel.

        Args:
            owner: Repository owner login.
            repo: Repository name.

        Returns:
            Mapping of filename to decoded file content for files that exist.
        """
        async def _fetch_file(filename: str) -> tuple[str, str | None]:
            try:
                response = await self._request(
                    "GET", f"/repos/{owner}/{repo}/contents/{filename}"
                )
                data: dict[str, Any] = response.json()
                content_b64 = data.get("content", "")
                text = base64.b64decode(
                    content_b64.replace("\n", "")
                ).decode("utf-8", errors="replace")
                return filename, text
            except (httpx.HTTPStatusError, httpx.TimeoutException):
                return filename, None

        results = await asyncio.gather(*(_fetch_file(f) for f in _DEPENDENCY_FILES))
        return {name: content for name, content in results if content is not None}

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def parse_owner_repo(url: str) -> tuple[str, str]:
        """Parse a GitHub URL or 'owner/repo' string into (owner, repo).

        Args:
            url: A GitHub repository URL or 'owner/repo' slug.

        Returns:
            Tuple of (owner, repo).

        Raises:
            ValueError: If the input cannot be parsed as a valid repo reference.
        """
        cleaned = url.strip().rstrip("/")
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]

        # Already an owner/repo slug (no scheme)
        if "github.com" not in cleaned and "/" in cleaned and "://" not in cleaned:
            parts = cleaned.split("/")
            if len(parts) == 2 and all(parts):
                return parts[0], parts[1]

        # Full URL
        if "github.com" in cleaned:
            parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) >= 2:
                return path_parts[0], path_parts[1]

        raise ValueError(
            f"Cannot parse {url!r} as a GitHub repository. "
            "Expected 'owner/repo' or a github.com URL."
        )


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_search_result(data: dict[str, Any]) -> RepoSearchResult:
    license_info = data.get("license") or {}
    return RepoSearchResult(
        full_name=data["full_name"],
        html_url=data["html_url"],
        description=data.get("description"),
        stargazers_count=data.get("stargazers_count", 0),
        forks_count=data.get("forks_count", 0),
        language=data.get("language"),
        license_spdx=license_info.get("spdx_id"),
        topics=data.get("topics", []),
        updated_at=data["updated_at"],
        pushed_at=data["pushed_at"],
        open_issues_count=data.get("open_issues_count", 0),
        size=data.get("size", 0),
    )


def _parse_repo_details(data: dict[str, Any], contributors_count: int | None) -> RepoDetails:
    license_info = data.get("license") or {}
    return RepoDetails(
        full_name=data["full_name"],
        html_url=data["html_url"],
        description=data.get("description"),
        stargazers_count=data.get("stargazers_count", 0),
        forks_count=data.get("forks_count", 0),
        language=data.get("language"),
        license_spdx=license_info.get("spdx_id"),
        topics=data.get("topics", []),
        updated_at=data["updated_at"],
        pushed_at=data["pushed_at"],
        open_issues_count=data.get("open_issues_count", 0),
        size=data.get("size", 0),
        subscribers_count=data.get("subscribers_count", 0),
        network_count=data.get("network_count", 0),
        has_wiki=data.get("has_wiki", False),
        has_pages=data.get("has_pages", False),
        has_discussions=data.get("has_discussions", False),
        archived=data.get("archived", False),
        default_branch=data.get("default_branch", "main"),
        contributors_count=contributors_count,
    )
