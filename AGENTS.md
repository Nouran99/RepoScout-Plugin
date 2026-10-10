# RepoScout Plugin Operating Guide

This public repository is the single source of truth for the RepoScout Claude
Code plugin. The SaaS website and API live in `Nouran99/RepoScout`.

## Ownership

- `plugins/reposcout/src/` — MCP runtime and GitHub clients.
- `plugins/reposcout/commands/` — slash commands.
- `plugins/reposcout/skills/` — plugin skills.
- `plugins/reposcout/agents/` — plugin agents.
- `plugins/reposcout/tests/` — unit and integration tests.
- `.claude-plugin/marketplace.json` — public marketplace catalog.

Do not add SaaS frontend or backend implementation here. The repositories connect
through the HTTPS contract documented in `docs/API_CONTRACT.md`.

## Validation

From `plugins/reposcout`:

```bash
uv sync --all-groups
uv run pytest
uv run ruff check src tests
uv run mypy src
```

From the repository root, run the marketplace preflight before release.
