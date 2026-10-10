---
description: Configure RepoScout and verify its connection in anonymous or authenticated mode.
---

# RepoScout setup

Help the user complete this checklist without requesting or echoing secret values in chat.

1. Confirm that Claude Code is running with the RepoScout plugin and that Python 3.12+ and `uv` are installed.
2. Explain that no API key is required for anonymous free mode. If the user wants to use an existing paid plan, they can create a RepoScout API key at `https://nouran-darwish-ai.dev/reposcout/settings/api-keys` and set `REPOSCOUT_API_KEY` locally; never ask them to paste the key into the conversation.
3. Confirm `REPOSCOUT_BACKEND_URL` points to `https://reposcout-api.nouran-darwish-ai.dev` for production, or `http://localhost:8000` for local development. Explain that `GITHUB_TOKEN` is optional but increases GitHub API limits.
4. Ask the user to restart Claude Code after changing environment variables.
5. Discover the five RepoScout tools first. Run one small `search_repos` call, such as `Find a well-maintained MIT-licensed FastAPI starter`, in the user's selected anonymous or authenticated mode. Explain that this consumes scouting quota, and summarize the result count and any quota information returned without exposing credentials.
6. If setup fails, report only the HTTP status and safe error message. Recommend checking the backend URL, API-key status, email verification, quota, and service status in that order.

Explain that RepoScout's health and license output is automated triage, not legal advice, and direct the user to review the repository's actual license and dependency notices before shipping.
