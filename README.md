# RepoScout — repository scouting for coding agents

RepoScout works with Claude Code, Codex, OpenCode, Qwen Code, and other agents
that support local MCP servers over stdio. This repository contains the shared
MCP server, Claude Code plugin, tests, marketplace metadata, and public
documentation. The RepoScout SaaS application, deployment configuration, and
private environment files are deliberately excluded.

The plugin connects to the SaaS only through the versioned HTTPS contract in
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Install for Codex, OpenCode, Qwen Code, or another MCP client

With Python 3.12+ and [uv](https://docs.astral.sh/uv/) installed, run from this
repository's root:

```bash
uv tool install ./plugins/reposcout
reposcout-mcp config --client codex
```

Merge the printed configuration into `~/.codex/config.toml`. For OpenCode use
`--client opencode` and merge into `opencode.json`; for Qwen Code use
`--client qwen` and merge into `~/.qwen/settings.json`. Use `--client generic`
for a conventional `mcpServers` JSON fragment. Existing settings should be kept.

Restart your agent and ask: “Use RepoScout to find a maintained MIT-licensed
FastAPI starter.” No RepoScout API key is needed for anonymous free mode.

See [the coding-agent setup guide](docs/CODING_AGENTS.md) for configuration,
credentials, development launchers, and compatibility details.

## Install for Claude Code

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
uv sync --all-groups
uv run pytest
uv run ruff check src tests
uv run mypy src
cd ../..
python scripts/marketplace_preflight.py --plugin-dir plugins/reposcout
```

Please report security issues using the private process in [SECURITY.md](SECURITY.md),
not a public issue.
