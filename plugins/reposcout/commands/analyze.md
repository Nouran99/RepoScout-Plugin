---
description: Deep-analyze a GitHub repository — health score, tech stack, README, recent commits
---

You are running the `/reposcout:analyze` command.

**Target repository:** $ARGUMENTS

---

## Step 1 — Validate Input

If `$ARGUMENTS` is empty, ask the user:
> Please provide a GitHub repository URL or `owner/repo` slug. For example:
> `/reposcout:analyze tiangolo/fastapi`

If `$ARGUMENTS` is provided, proceed immediately.

---

## Step 2 — Fetch Analysis

Call the `analyze_repo` MCP tool with the URL from `$ARGUMENTS`.

If the tool raises a `RateLimitExceeded` error, tell the user:
> GitHub rate limit reached. Please wait a minute and try again.

If the tool raises a `LicenseError`, display the error message as-is — it contains upgrade instructions.

If the URL cannot be parsed, ask the user to provide a full GitHub URL (e.g. `https://github.com/owner/repo`) or an `owner/repo` slug.

---

## Step 3 — Present Full Analysis

Format the results as follows:

---

### {full_name}

> {description}

**{html_url}**

---

#### Health Score: {total_score}/100 — {verdict}

| Dimension    | Score  | Max |
|--------------|--------|-----|
| Recency      | x      | 25  |
| Activity     | x      | 20  |
| Community    | x      | 15  |
| Documentation| x      | 15  |
| Code Quality | x      | 15  |
| Licence      | x      | 10  |

**Flags:** {flags — or "None" if empty}

---

#### Repository Stats

| Stat             | Value              |
|------------------|--------------------|
| Stars            | {stargazers_count} |
| Forks            | {forks_count}      |
| Contributors     | {contributors_count or "unknown"} |
| Open Issues      | {open_issues_count}|
| Primary Language | {language}         |
| Licence          | {license_spdx}     |
| Default Branch   | {default_branch}   |
| Last Push        | {pushed_at}        |
| Archived         | {archived}         |

---

#### Tech Stack

{detected_stack as comma-separated tags}

---

#### Language Breakdown

Show the top 5 languages as a simple list with percentage of total bytes:
- Python: 87.3%
- Shell: 12.7%

---

#### Recent Commits (last 5)

| Date | Author | Message |
|------|--------|---------|

---

#### README Preview

> {first 600 characters of readme_content, or "No README found."}

---

#### Dependency Files Found

List the dependency manifest files present (e.g. `pyproject.toml`, `package.json`). If none: "None detected."

---

## Step 4 — Follow-Up Options

After presenting the analysis, offer:

> What next?
> - **`/reposcout:compare`** — compare this with another repo
> - **clone** — scaffold this repo locally (tell me your target directory)
> - **licence** — run a full licence compatibility check
> - **done** — nothing, thanks

If the user says "clone", ask for the target directory, confirm it, then call `clone_and_scaffold`.

If the user says "licence", call `check_license_compatibility` with `intended_use: "commercial"` and present the `LicenseReport` result clearly, including all warnings.
