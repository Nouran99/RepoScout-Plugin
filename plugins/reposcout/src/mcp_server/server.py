"""FastMCP server — 5 RepoScout tools exposed over stdio transport."""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_server.clients.github_client import GitHubClient
from mcp_server.config import get_settings
from mcp_server.middleware.license_check import LicenseChecker, LicenseError  # noqa: F401
from mcp_server.models.github import (
    ComparisonEntry,
    ComparisonReport,
    LicenseReport,
    RateLimitExceeded,  # noqa: F401 — re-exported so callers can catch it
    RepoAnalysis,
    RepoDetails,
    RepoSearchResult,
    ScaffoldResult,
    SearchResults,
)
from mcp_server.scoring.health_scorer import HealthScorer
from mcp_server.search.query_expander import QueryExpander

logger = structlog.get_logger(__name__)
mcp = FastMCP("reposcout")


# ── License classification tables ─────────────────────────────────────────────

_PERMISSIVE_SPDX: set[str] = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD",
}
_WEAK_COPYLEFT_SPDX: set[str] = {"LGPL-2.0", "LGPL-2.1", "LGPL-3.0", "MPL-2.0"}
_COPYLEFT_SPDX: set[str] = {
    "GPL-2.0", "GPL-3.0", "GPL-2.0-only", "GPL-3.0-only",
    "GPL-2.0-or-later", "GPL-3.0-or-later",
}
_STRONG_COPYLEFT_SPDX: set[str] = {"AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0"}

_LICENSE_NAMES: dict[str, str] = {
    "MIT": "MIT License",
    "Apache-2.0": "Apache License 2.0",
    "BSD-2-Clause": "BSD 2-Clause License",
    "BSD-3-Clause": "BSD 3-Clause License",
    "ISC": "ISC License",
    "Unlicense": "The Unlicense",
    "0BSD": "Zero-Clause BSD",
    "GPL-2.0": "GNU GPL v2",
    "GPL-3.0": "GNU GPL v3",
    "LGPL-2.1": "GNU LGPL v2.1",
    "LGPL-3.0": "GNU LGPL v3",
    "AGPL-3.0": "GNU AGPL v3",
    "MPL-2.0": "Mozilla Public License 2.0",
    "SSPL-1.0": "Server Side Public License v1",
}

# ── Stack detection hints ──────────────────────────────────────────────────────
# Each tuple is (substring to search in dep-file content, display name).
# Ordered so longer/more specific strings match before shorter substrings.

_FRAMEWORK_HINTS: list[tuple[str, str]] = [
    # Python web frameworks
    ("fastapi", "FastAPI"),
    ("django", "Django"),
    ("flask", "Flask"),
    ("starlette", "Starlette"),
    ("litestar", "Litestar"),
    ("sqlalchemy", "SQLAlchemy"),
    ("alembic", "Alembic"),
    ("celery", "Celery"),
    # JS/TS frameworks (use quoted form to reduce false positives)
    ('"@nestjs/core"', "NestJS"),
    ('"next"', "Next.js"),
    ('"react"', "React"),
    ('"vue"', "Vue"),
    ('"nuxt"', "Nuxt"),
    ('"svelte"', "Svelte"),
    ('"express"', "Express"),
    ('"remix"', "Remix"),
    ('"astro"', "Astro"),
    ('"hono"', "Hono"),
    ('"elysia"', "Elysia"),
    ('"tailwindcss"', "Tailwind CSS"),
    # Databases
    ("asyncpg", "PostgreSQL"),
    ("psycopg", "PostgreSQL"),
    ("postgresql", "PostgreSQL"),
    ("mysqlclient", "MySQL"),
    ("pymysql", "MySQL"),
    ("motor", "MongoDB"),
    ("pymongo", "MongoDB"),
    ("redis", "Redis"),
    ("prisma", "Prisma"),
    ("drizzle-orm", "Drizzle ORM"),
    ("supabase", "Supabase"),
    # Auth / billing
    ("nextauth", "NextAuth"),
    ("authjs", "Auth.js"),
    ('"stripe"', "Stripe"),
    ("paddle", "Paddle"),
    # AI / ML
    ("langchain", "LangChain"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("llamaindex", "LlamaIndex"),
    ("huggingface", "HuggingFace"),
    # UI
    ('"@radix-ui"', "Radix UI"),
    ('"@chakra-ui"', "Chakra UI"),
    ('"@mui"', "Material UI"),
    # Infra
    ("docker", "Docker"),
    ("kubernetes", "Kubernetes"),
    ("terraform", "Terraform"),
]

# CI / test directory names — duplicated here to avoid importing private symbols
_CI_FILES = {".github", ".travis.yml", ".circleci", "Jenkinsfile", ".gitlab-ci.yml"}
_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__"}

_DEP_MANIFEST_NAMES = [
    "package.json", "pyproject.toml", "requirements.txt",
    "go.mod", "Cargo.toml", "pom.xml", "Gemfile", "build.gradle",
]

# File extensions → language names for local scaffold scanning
_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
    ".cpp": "C++", ".c": "C",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def detect_stack(
    dependency_files: dict[str, str],
    languages: dict[str, int],
) -> list[str]:
    """Infer the technology stack from dependency manifests and language byte counts.

    Args:
        dependency_files: Map of filename → raw file content.
        languages: Map of language name → bytes of code (GitHub API format).

    Returns:
        Up to 10 detected technology names, languages first then frameworks.
    """
    stack: list[str] = []

    # Top languages by byte count (up to 3)
    for lang in sorted(languages, key=lambda k: languages[k], reverse=True)[:3]:
        if lang not in stack:
            stack.append(lang)

    # Frameworks from dep file contents
    combined = "\n".join(dependency_files.values()).lower()
    for hint, name in _FRAMEWORK_HINTS:
        if hint.lower() in combined and name not in stack:
            stack.append(name)

    return stack[:10]


def _make_minimal_details(result: RepoSearchResult) -> RepoDetails:
    """Wrap a search result as a minimal RepoDetails so it can be health-scored."""
    return RepoDetails(
        **result.model_dump(),
        subscribers_count=0,
        network_count=0,
        has_wiki=False,
        has_pages=False,
        has_discussions=False,
        archived=False,
        default_branch="main",
        contributors_count=None,
    )


async def _analyze_internal(
    client: GitHubClient,
    owner: str,
    repo: str,
) -> RepoAnalysis:
    """Fetch all repository data in parallel and return a full RepoAnalysis.

    Args:
        client: Open GitHubClient instance.
        owner: Repository owner login.
        repo: Repository name.

    Returns:
        RepoAnalysis with health score, detected stack, and all fetched data.
    """
    details, readme, tree, languages, commits, dep_files = await asyncio.gather(
        client.get_repo_details(owner, repo),
        client.get_repo_readme(owner, repo),
        client.get_repo_tree(owner, repo),
        client.get_repo_languages(owner, repo),
        client.get_recent_commits(owner, repo, count=90),
        client.get_dependency_files(owner, repo),
    )
    health = HealthScorer.score(
        repo=details,
        commits=commits,
        dependency_files=dep_files,
        file_tree=tree,
    )
    stack = detect_stack(dep_files, languages)
    return RepoAnalysis(
        repo=details,
        readme_content=readme,
        file_tree=tree,
        languages=languages,
        recent_commits=commits,
        dependency_files=dep_files,
        health=health,
        detected_stack=stack,
    )


# ── Tool 1: search_repos ──────────────────────────────────────────────────────

@mcp.tool()
async def search_repos(
    description: str,
    language: str | None = None,
    min_stars: int | None = None,
    topics: list[str] | None = None,
    license_type: str | None = None,
) -> dict[str, Any]:
    """Find open-source GitHub repositories matching a natural-language description.

    Expands the description into up to 5 synonym/template variants, searches them
    in parallel, deduplicates results, health-scores the top 15, and returns the
    10 best-scoring matches.

    Args:
        description: What kind of project you want, e.g. 'fastapi saas boilerplate'.
        language: Optional programming language or framework, e.g. 'Python' or 'nextjs'.
        min_stars: Minimum GitHub star count filter; None means no minimum.
        topics: List of GitHub topic tags to require, e.g. ['docker', 'postgres'].
        license_type: SPDX licence identifier to filter by, e.g. 'MIT' or 'Apache-2.0'.

    Returns:
        SearchResults with up to 10 repositories, their health scores, and the
        primary query string that was executed.
    """
    settings = get_settings()
    checker = LicenseChecker(
        api_key=settings.reposcout_api_key,
        backend_url=settings.reposcout_backend_url,
        fail_open=settings.reposcout_license_fail_open,
    )
    request_id = uuid.uuid4().hex
    license_result = await checker.check(idempotency_key=request_id)

    expanded = QueryExpander.expand(description, language=language, min_stars=min_stars)
    if not expanded:
        empty = SearchResults(
            query_used=description,
            total_found=0,
            results=[],
            health_scores={},
        )
        return empty.model_dump(mode="json")

    async with GitHubClient(token=settings.github_token) as client:
        raw_results = await asyncio.gather(
            *[
                client.search_repositories(
                    query=eq.query,
                    topics=topics,
                    license_type=license_type,
                    per_page=15,
                )
                for eq in expanded
            ],
            return_exceptions=True,
        )

    # Deduplicate across all query results
    seen: set[str] = set()
    deduplicated: list[RepoSearchResult] = []
    for batch in raw_results:
        if isinstance(batch, BaseException):
            logger.warning("search_query_failed", error=str(batch))
            continue
        for r in batch:
            if r.full_name not in seen:
                seen.add(r.full_name)
                deduplicated.append(r)

    # Health-score up to 15 candidates (no extra API calls — use search data)
    candidates = deduplicated[:15]
    health_scores = {
        r.full_name: HealthScorer.score(
            repo=_make_minimal_details(r),
            commits=[],
            dependency_files={},
            file_tree=[],
        )
        for r in candidates
    }

    # Sort by health score desc, return top 10
    top10 = sorted(candidates, key=lambda r: health_scores[r.full_name].total_score, reverse=True)[
        :10
    ]

    result = SearchResults(
        query_used=expanded[0].query,
        total_found=len(deduplicated),
        results=top10,
        health_scores={r.full_name: health_scores[r.full_name] for r in top10},
    )

    if settings.reposcout_api_key:
        await checker.log_usage(
            "search_repos",
            description,
            len(top10),
            None,
            reservation_id=license_result.get("reservation_id"),
            idempotency_key=request_id,
        )
    else:
        checker.increment_local_usage()

    logger.info("search_repos_complete", query=description, returned=len(top10))
    return result.model_dump(mode="json")


# ── Tool 2: analyze_repo ──────────────────────────────────────────────────────

@mcp.tool()
async def analyze_repo(repo_url: str) -> dict[str, Any]:
    """Perform a deep analysis of a single GitHub repository.

    Fetches metadata, README, file tree, languages, recent commits, and dependency
    manifests all in parallel, then computes a 0-100 health score and detects the
    technology stack.

    Args:
        repo_url: GitHub repository URL (https://github.com/owner/repo) or
                  'owner/repo' slug.

    Returns:
        RepoAnalysis containing the health score, detected stack, README text,
        file tree, language breakdown, recent commits, and dependency manifests.
    """
    owner, repo = GitHubClient.parse_owner_repo(repo_url)
    settings = get_settings()
    checker = LicenseChecker(
        api_key=settings.reposcout_api_key,
        backend_url=settings.reposcout_backend_url,
        fail_open=settings.reposcout_license_fail_open,
    )
    request_id = uuid.uuid4().hex
    license_result = await checker.check(idempotency_key=request_id)

    async with GitHubClient(token=settings.github_token) as client:
        analysis = await _analyze_internal(client, owner, repo)

    if settings.reposcout_api_key:
        await checker.log_usage(
            "analyze_repo",
            repo_url,
            1,
            analysis.repo.full_name,
            reservation_id=license_result.get("reservation_id"),
            idempotency_key=request_id,
        )
    else:
        checker.increment_local_usage()

    logger.info(
        "analyze_repo_complete",
        repo=f"{owner}/{repo}",
        score=analysis.health.total_score,
        verdict=analysis.health.verdict,
    )
    return analysis.model_dump(mode="json")


# ── Tool 3: compare_repos ──────────────────────────────────────────────────────

@mcp.tool()
async def compare_repos(repo_urls: list[str]) -> dict[str, Any]:
    """Compare 2 or 3 GitHub repositories side-by-side and recommend the best one.

    Analyses all repositories in parallel and produces a structured comparison
    table. The recommendation is based on health score and community signals.

    Args:
        repo_urls: List of exactly 2 or 3 GitHub repository URLs or 'owner/repo'
                   slugs. Fewer than 2 or more than 3 raises a ValueError.

    Returns:
        ComparisonReport with per-repo summary rows, a recommended repository
        name, and a plain-English reasoning for the recommendation.
    """
    if not 2 <= len(repo_urls) <= 3:
        raise ValueError(
            f"compare_repos requires exactly 2 or 3 repository URLs, got {len(repo_urls)}."
        )

    parsed = [GitHubClient.parse_owner_repo(url) for url in repo_urls]
    settings = get_settings()
    checker = LicenseChecker(
        api_key=settings.reposcout_api_key,
        backend_url=settings.reposcout_backend_url,
        fail_open=settings.reposcout_license_fail_open,
    )
    request_id = uuid.uuid4().hex
    license_result = await checker.check(idempotency_key=request_id)

    async with GitHubClient(token=settings.github_token) as client:
        analyses = await asyncio.gather(
            *[_analyze_internal(client, owner, repo) for owner, repo in parsed]
        )

    entries: list[ComparisonEntry] = []
    for analysis in analyses:
        tree_names = {e.name.lower() for e in analysis.file_tree}
        entries.append(
            ComparisonEntry(
                repo_url=analysis.repo.html_url,
                name=analysis.repo.full_name,
                stars=analysis.repo.stargazers_count,
                health_score=analysis.health.total_score,
                health_verdict=analysis.health.verdict,
                language=analysis.repo.language,
                license=analysis.repo.license_spdx,
                last_commit=analysis.repo.pushed_at,
                has_tests=bool(tree_names & _TEST_DIRS),
                has_ci=bool(tree_names & _CI_FILES),
                detected_stack=analysis.detected_stack,
            )
        )

    best = max(entries, key=lambda e: (e.health_score, e.stars))
    others = sorted(
        [e for e in entries if e.name != best.name],
        key=lambda e: e.health_score,
        reverse=True,
    )

    parts = [
        f"{best.name} scores highest at {best.health_score}/100 ({best.health_verdict})."
    ]
    if best.stars > 0:
        parts.append(f"It has {best.stars:,} GitHub stars.")
    if others:
        parts.append(
            f"Runner-up is {others[0].name} with a health score of {others[0].health_score}."
        )

    report = ComparisonReport(
        repos=entries,
        recommendation=best.name,
        reasoning=" ".join(parts),
    )

    if settings.reposcout_api_key:
        await checker.log_usage(
            "compare_repos",
            ", ".join(repo_urls),
            len(entries),
            best.name,
            reservation_id=license_result.get("reservation_id"),
            idempotency_key=request_id,
        )
    else:
        checker.increment_local_usage()

    logger.info("compare_repos_complete", recommendation=best.name, count=len(entries))
    return report.model_dump(mode="json")


# ── Tool 4: clone_and_scaffold ────────────────────────────────────────────────

@mcp.tool()
async def clone_and_scaffold(
    repo_url: str,
    target_dir: str,
    remove_git_history: bool = True,
) -> dict[str, Any]:
    """Clone a GitHub repository locally and set it up as a new project scaffold.

    Performs a shallow clone (--depth 1) to keep it fast, optionally strips the
    .git directory, counts the resulting files, detects the technology stack from
    the dependency manifests on disk, and suggests initial setup steps.

    Args:
        repo_url: GitHub repository URL or 'owner/repo' slug.
        target_dir: Local path where the project should be created. The directory
                    must not already exist (git clone will create it).
        remove_git_history: Remove the .git directory after cloning so the project
                            can be initialised as a fresh repository. Default True.

    Returns:
        ScaffoldResult with the resolved target path, file count, detected stack,
        and an ordered list of suggested next steps.
    """
    owner, repo = GitHubClient.parse_owner_repo(repo_url)
    settings = get_settings()
    checker = LicenseChecker(
        api_key=settings.reposcout_api_key,
        backend_url=settings.reposcout_backend_url,
        fail_open=settings.reposcout_license_fail_open,
    )
    request_id = uuid.uuid4().hex
    license_result = await checker.check(idempotency_key=request_id)

    clone_url = f"https://github.com/{owner}/{repo}.git"
    target_path = Path(target_dir)

    process = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", clone_url, str(target_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            f"git clone failed: {stderr.decode(errors='replace').strip()}"
        )

    if remove_git_history:
        git_dir = target_path / ".git"
        if git_dir.exists():
            shutil.rmtree(str(git_dir))

    # Count all files in the cloned project
    files_count = sum(len(files) for _, _, files in os.walk(str(target_path)))

    # Read dependency manifests from disk for stack detection
    dep_files: dict[str, str] = {}
    for fname in _DEP_MANIFEST_NAMES:
        fpath = target_path / fname
        if fpath.exists():
            try:
                dep_files[fname] = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

    # Infer language distribution from file extensions
    lang_counts: dict[str, int] = {}
    for _, _, files in os.walk(str(target_path)):
        for f in files:
            lang = _EXT_TO_LANG.get(os.path.splitext(f)[1].lower())
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

    stack = detect_stack(dep_files, lang_counts)

    # Suggested next steps based on detected manifests
    next_steps: list[str] = []
    if "package.json" in dep_files:
        next_steps.append("Run: npm install  (or pnpm install / yarn)")
    if "requirements.txt" in dep_files or "pyproject.toml" in dep_files:
        next_steps.append("Run: pip install -r requirements.txt  (or: uv sync)")
    if "go.mod" in dep_files:
        next_steps.append("Run: go mod download")
    if "Cargo.toml" in dep_files:
        next_steps.append("Run: cargo build")
    if (target_path / ".env.example").exists():
        next_steps.append("Copy .env.example → .env and fill in secrets")
    if not next_steps:
        next_steps.append("Review the README for setup instructions")
    next_steps.append(
        "Initialise a new git repo: git init && git add . && git commit -m 'initial commit'"
    )

    result = ScaffoldResult(
        target_dir=str(target_path.resolve()),
        files_count=files_count,
        detected_stack=stack,
        suggested_next_steps=next_steps,
    )

    if settings.reposcout_api_key:
        await checker.log_usage(
            "clone_and_scaffold",
            repo_url,
            files_count,
            f"{owner}/{repo}",
            reservation_id=license_result.get("reservation_id"),
            idempotency_key=request_id,
        )
    else:
        checker.increment_local_usage()

    logger.info(
        "scaffold_complete",
        repo=f"{owner}/{repo}",
        target=target_dir,
        files=files_count,
    )
    return result.model_dump(mode="json")


# ── Tool 5: check_license_compatibility ───────────────────────────────────────

@mcp.tool()
async def check_license_compatibility(
    repo_url: str,
    intended_use: str = "commercial",
) -> dict[str, Any]:
    """Analyse the licence of a GitHub repository and assess compatibility with your use case.

    Fetches repository metadata and dependency manifests, classifies the licence,
    and reports whether commercial use, modification, and redistribution are
    permitted — with explicit warnings for copyleft or missing licences.

    Args:
        repo_url: GitHub repository URL or 'owner/repo' slug.
        intended_use: How you plan to use the project — 'commercial' (default),
                      'internal', or 'open_source'. Affects whether copyleft
                      licences are flagged as incompatible.

    Returns:
        LicenseReport with the SPDX identifier, classification flags,
        a compatibility verdict, and a list of warnings.
    """
    owner, repo = GitHubClient.parse_owner_repo(repo_url)
    settings = get_settings()
    checker = LicenseChecker(
        api_key=settings.reposcout_api_key,
        backend_url=settings.reposcout_backend_url,
        fail_open=settings.reposcout_license_fail_open,
    )
    request_id = uuid.uuid4().hex
    license_result = await checker.check(idempotency_key=request_id)

    async with GitHubClient(token=settings.github_token) as client:
        details, dep_files = await asyncio.gather(
            client.get_repo_details(owner, repo),
            client.get_dependency_files(owner, repo),
        )

    spdx = details.license_spdx
    license_name = _LICENSE_NAMES.get(spdx or "", spdx)
    is_permissive = spdx in _PERMISSIVE_SPDX
    is_weak_copyleft = spdx in _WEAK_COPYLEFT_SPDX
    is_copyleft_flag = spdx in _COPYLEFT_SPDX
    is_strong_copyleft = spdx in _STRONG_COPYLEFT_SPDX
    warnings: list[str] = []

    if spdx is None:
        commercial_use = False
        modification_allowed = False
        distribution_allowed = False
        verdict = (
            "No licence detected — all rights reserved by default. "
            "Do not use this code without explicit permission from the author."
        )
        warnings.append(
            "No licence file found. Contact the repository owner before using this code."
        )
    elif is_permissive:
        commercial_use = True
        modification_allowed = True
        distribution_allowed = True
        verdict = "Safe for commercial use. Attribution is typically required."
    elif is_weak_copyleft:
        commercial_use = True
        modification_allowed = True
        distribution_allowed = True
        verdict = "Usable commercially, but modifications to the licensed library must be shared."
        warnings.append(
            f"{spdx}: modifications to this specific library must be released under the same licence."
        )
    elif is_copyleft_flag:
        commercial_use = True
        modification_allowed = True
        distribution_allowed = True
        verdict = "Copyleft: distributing binaries requires releasing your full source code."
        warnings.append(
            f"{spdx}: if you distribute this software you must also provide the source code."
        )
        if intended_use == "commercial":
            warnings.append(
                "Commercial distribution of GPL-licensed software requires careful legal review."
            )
    elif is_strong_copyleft:
        commercial_use = False
        modification_allowed = True
        distribution_allowed = True
        verdict = (
            "Strong copyleft: offering this software over a network (SaaS) "
            "triggers the source-disclosure requirement."
        )
        warnings.append(
            f"{spdx}: running this software as a service requires releasing your source code."
        )
        warnings.append(
            "This licence is generally incompatible with closed-source commercial SaaS."
        )
    else:
        commercial_use = False
        modification_allowed = True
        distribution_allowed = False
        verdict = f"Unknown or non-standard licence ({spdx}). Review manually before use."
        warnings.append("Licence compatibility could not be determined automatically.")

    # Heuristic: scan dep file contents for AGPL/SSPL transitive dependencies
    combined_deps = "\n".join(dep_files.values()).lower()
    if any(kw in combined_deps for kw in ("agpl", "sspl")) and intended_use == "commercial":
        warnings.append(
            "Dependency manifests reference AGPL/SSPL packages — "
            "review transitive licences before shipping."
        )

    report = LicenseReport(
        license_spdx=spdx,
        license_name=license_name,
        is_permissive=is_permissive,
        is_copyleft=is_copyleft_flag or is_strong_copyleft,
        commercial_use_allowed=commercial_use,
        modification_allowed=modification_allowed,
        distribution_allowed=distribution_allowed,
        compatibility_verdict=verdict,
        warnings=warnings,
    )

    if settings.reposcout_api_key:
        await checker.log_usage(
            "check_license_compatibility",
            repo_url,
            1,
            f"{owner}/{repo}",
            reservation_id=license_result.get("reservation_id"),
            idempotency_key=request_id,
        )
    else:
        checker.increment_local_usage()

    logger.info(
        "license_check_complete",
        repo=f"{owner}/{repo}",
        spdx=spdx,
        commercial_use=commercial_use,
    )
    return report.model_dump(mode="json")

