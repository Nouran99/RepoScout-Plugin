# RepoScout Plugin Marketplace

This repository is the public distribution surface for the RepoScout Claude Code
plugin. It contains only the plugin, its tests, marketplace metadata, and public
documentation. The RepoScout SaaS application, deployment configuration, and
private environment files are deliberately excluded.

## Install

Add the official marketplace, then install RepoScout:

```bash
claude plugin marketplace add Nouran99/RepoScout-Plugin
claude plugin install reposcout@reposcout-marketplace
```

Restart Claude Code or run `/reload-plugins`, then use `/reposcout:setup` to
check the optional credentials and production API connection.

## What the plugin can do

- Search GitHub and rank repositories by health
- Analyze architecture, maintenance, licensing, and project fit
- Compare candidate repositories
- Clone a selected public GitHub repository into a user-confirmed local path

The plugin runs locally with the current user's permissions. Review the source
under `plugins/reposcout/` before installing it, especially the
`clone_and_scaffold` tool, which writes to a path explicitly supplied by the
user.

## Development and validation

```bash
claude plugin validate .
cd plugins/reposcout
uv sync --dev
uv run pytest
uv run ruff check src tests
uv run mypy src
```

Please report security issues using the private process in [SECURITY.md](SECURITY.md),
not a public issue.
