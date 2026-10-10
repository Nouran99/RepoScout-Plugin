# RepoScout marketplace checklist

## Required

- [ ] `plugins/reposcout/` is self-contained.
- [ ] Plugin metadata and Python package versions match.
- [ ] `.mcp.json` starts from a clean environment.
- [ ] No secrets or local checkout paths are committed.
- [ ] The production backend default is intentional.

## Validation

- [ ] `uv sync --all-groups --locked` succeeds.
- [ ] `uv run pytest` passes.
- [ ] `uv run ruff check src tests` passes.
- [ ] `uv run mypy src` passes.
- [ ] `python scripts/marketplace_preflight.py --plugin-dir plugins/reposcout` passes.
- [ ] A clean Claude Code install loads `/reposcout:setup`.

## Production exercise

- [ ] Anonymous free mode completes a search.
- [ ] A production API key validates successfully.
- [ ] `/reposcout:find`, `/reposcout:analyze` and `/reposcout:compare` work.
- [ ] Quota denial is clear and blocks execution.
- [ ] License output retains the legal-review disclaimer.
