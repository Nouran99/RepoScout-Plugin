---
description: Compare 2 or 3 GitHub repositories side-by-side and get a recommendation
---

You are running the `/reposcout:compare` command.

**Input:** $ARGUMENTS

---

## Step 1 — Parse Repository URLs

Extract 2 or 3 GitHub repository references from `$ARGUMENTS`. Each can be:
- A full URL: `https://github.com/owner/repo`
- An `owner/repo` slug: `tiangolo/fastapi`

**Examples of valid input:**
```
/reposcout:compare tiangolo/fastapi litestar-org/litestar
/reposcout:compare https://github.com/trpc/trpc https://github.com/t3-oss/create-t3-app
/reposcout:compare vercel/next.js nuxt/nuxt sveltejs/kit
```

If `$ARGUMENTS` is empty, ask the user:
> Please provide 2 or 3 GitHub repository URLs or `owner/repo` slugs, separated by spaces.

If fewer than 2 or more than 3 repositories are identified, tell the user:
> `/reposcout:compare` requires exactly 2 or 3 repositories. You provided {n}.

---

## Step 2 — Run Comparison

Call the `compare_repos` MCP tool with the list of URLs.

If the tool raises a `RateLimitExceeded` error:
> GitHub rate limit reached. Please wait a minute and try again.

If the tool raises a `LicenseError`, display the message — it contains upgrade instructions.

---

## Step 3 — Present Comparison Table

Display the results as a markdown table. One column per repository:

| Metric            | {repo A}   | {repo B}   | {repo C}   |
|-------------------|-----------|-----------|-----------|
| Health Score      | x/100     | x/100     | x/100     |
| Verdict           | Excellent | Good      | Fair      |
| Stars             | 12,345    | 4,567     | 890       |
| Language          | Python    | TypeScript| Go        |
| Licence           | MIT       | Apache-2.0| GPL-3.0   |
| Last Commit       | 3d ago    | 2w ago    | 6m ago    |
| Has Tests         | ✓         | ✓         | ✗         |
| Has CI            | ✓         | ✗         | ✓         |
| Stack             | FastAPI…  | Next.js…  | Gin…      |

---

## Step 4 — Recommendation

After the table, present the recommendation clearly:

---

### Recommendation: **{recommendation}**

{reasoning}

---

## Step 5 — Follow-Up Options

After presenting the comparison, offer:

> What next?
> - **drill [name]** — full deep analysis of one of these repos
> - **clone [name]** — scaffold one of these repos locally
> - **licence [name]** — check licence compatibility for a specific repo
> - **search again** — go back to `/reposcout:find` with different criteria

Handle each option:
- **drill**: call `analyze_repo` and present the full analysis (same format as `/reposcout:analyze`)
- **clone**: ask for target directory, confirm, call `clone_and_scaffold`
- **licence**: call `check_license_compatibility` with `intended_use: "commercial"` and present the full report
