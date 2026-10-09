---
description: Interactively find an open-source GitHub project to use as a base for your new build
---

You are running the `/reposcout:find` command. Your job is to help the user find the perfect open-source starter project on GitHub for their new build.

**User's initial input:** $ARGUMENTS

---

## Step 1 — Gather Requirements

If the user's input is empty or too vague, ask exactly these three questions (all at once, in a single message — do not ask them one by one):

1. **What are you building?** (e.g. "a SaaS dashboard with payments", "a RAG chatbot", "an e-commerce store")
2. **What language or framework do you prefer?** (e.g. Next.js, FastAPI, Django — or "no preference")
3. **Any must-haves?** (e.g. minimum stars, specific licence, must include Docker/Postgres)

If the user has already provided enough detail in `$ARGUMENTS`, skip directly to Step 2.

---

## Step 2 — Search

Call the `search_repos` MCP tool with the gathered information:
- `description`: the user's project description
- `language`: the preferred language/framework (if any)
- `min_stars`: derived from must-haves (default: no minimum)
- `topics`: any specific topic tags mentioned
- `license_type`: if a licence was requested

---

## Step 3 — Present Top 5

Show the top 5 results from the search as a formatted table. For each repo include:

| # | Repository | Stars | Health | Verdict | Language | Licence | Last Push |
|---|-----------|-------|--------|---------|----------|---------|-----------|

Under the table, add one sentence per repo summarising why it appeared (e.g. "Matches saas + stripe + nextjs").

Then ask:

> Would you like to:
> - **[number]** — drill into a specific repo for full analysis
> - **compare [n] [n]** — compare two or three repos side-by-side
> - **clone [number]** — scaffold a repo directly into a local directory
> - **refine** — adjust the search filters
> - **skip** — none of these match, let me describe again

---

## Step 4 — Drill Down (if requested)

If the user selects a number, call `analyze_repo` on that repo's URL and present:

### Health Score: {score}/100 — {verdict}

**Breakdown**
| Dimension | Score |
|-----------|-------|
| Recency   | x/25  |
| Activity  | x/20  |
| Community | x/15  |
| Docs      | x/15  |
| Code Quality | x/15 |
| Licence   | x/10  |

**Flags:** list any warnings (No CI, Archived, etc.)

**Tech Stack:** detected stack tags

**Recent Activity:** last 3 commit messages with dates

**README preview:** first 400 characters

Then ask: *"Want to clone this into a directory, compare it with another, or check licence compatibility?"*

---

## Step 5 — Compare (if requested)

If the user says "compare 1 3" (or similar), call `compare_repos` with those repo URLs and present the result as a side-by-side markdown table, then state the recommendation and reasoning clearly.

---

## Step 6 — Clone (if requested)

If the user wants to clone:
1. Ask: *"Where should I create the project directory? (e.g. `~/projects/my-app`)"*
2. Confirm the path with the user before proceeding.
3. Call `clone_and_scaffold` with `remove_git_history: true`.
4. Present the result: directory, file count, detected stack.
5. List the suggested next steps as a numbered checklist.

---

## Behaviour Rules

- Never fabricate repository names, stars, or scores — only use data returned by the MCP tools.
- If a tool call fails with a rate-limit error, tell the user and suggest retrying in a minute.
- If the licence check middleware blocks the call, show the upgrade message returned in the error.
- Keep responses concise — tables over paragraphs, bullets over prose.
- Do not run `clone_and_scaffold` without explicit user confirmation of the target directory.
