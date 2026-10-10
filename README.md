# RepoScout — repository scouting for coding agents

RepoScout works with Claude Code, Codex, OpenCode, Qwen Code, and other agents
that support local MCP servers over stdio. This repository contains the shared
MCP server, Claude Code plugin, tests, marketplace metadata, and public
documentation. The RepoScout SaaS application, deployment configuration, and
private environment files are deliberately excluded.

The plugin connects to the SaaS only through the versioned HTTPS contract in
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Install for Codex, OpenCode, Qwen Code, or another MCP client

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/), then clone the public
repository and install its standalone MCP server:

```bash
git clone https://github.com/Nouran99/RepoScout-Plugin.git
cd RepoScout-Plugin
uv tool install ./plugins/reposcout
reposcout-mcp doctor
```

If `reposcout-mcp` is not found, run `uv tool update-shell`, reopen your terminal,
and try again. `doctor` checks a real local MCP connection, all five tools,
three workflow prompts, and input validation. It needs no credentials or network
and does not consume scouting quota. Success prints `"status": "ok"`.

Generate the configuration for your client:

| CLI | Generate configuration | Merge into | Verify after restarting |
| --- | --- | --- | --- |
| Codex | `reposcout-mcp config --client codex` | `~/.codex/config.toml` | `codex mcp list`, then `/mcp` |
| OpenCode | `reposcout-mcp config --client opencode` | `opencode.json` or `~/.config/opencode/opencode.json` | `opencode mcp list` |
| Qwen Code | `reposcout-mcp config --client qwen` | `~/.qwen/settings.json` or `.qwen/settings.json` | `qwen mcp list`; approve if prompted |
| Other stdio MCP clients | `reposcout-mcp config --client generic` | Your client's MCP configuration | Your client's MCP status view |

For example, for Codex:

```bash
reposcout-mcp config --client codex
```

Merge the printed fragment into the indicated file, preserving existing settings.
The command prints configuration; it does not register the server automatically.
It uses the installed Python interpreter's absolute path so it works from other
projects, including paths with spaces. Regenerate it if you move or reinstall
the tool environment. Avoid configuring RepoScout twice in the same client.

If Qwen Code reports **Pending approval**, review the generated command and run
`qwen mcp approve reposcout`, then `qwen mcp list` again. In an interactive
session, `/mcp` shows connection status. Approval is tied to the server's
configuration, so changing the command may require approving it again.

Restart your agent and ask: “Use RepoScout to find a maintained MIT-licensed
FastAPI starter.” This first real scouting call needs GitHub and the RepoScout
backend to be reachable and consumes quota. No RepoScout API key is needed for
anonymous free mode.

These instructions install the shared MCP server. Claude's native commands,
hooks, skill, and subagent use the Claude plugin installation below. Another
CLI must support starting local stdio MCP servers; clients that accept only
remote HTTP MCP endpoints need a separate bridge. The RepoScout backend URL is
a licensing API, not an MCP endpoint.

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

For a local checkout, validate and load the plugin with:

```bash
claude plugin validate ./plugins/reposcout
claude --plugin-dir ./plugins/reposcout
```

The plugin launcher selects its installed Python project explicitly, so it can
start from any project directory. Its first launch may download dependencies.

## Optional credentials

| Variable | Purpose |
| --- | --- |
| `GITHUB_TOKEN` | Increase GitHub API rate limits |
| `REPOSCOUT_API_KEY` | Use the plan attached to your RepoScout account |
| `REPOSCOUT_BACKEND_URL` | Override the default backend for development |

Set optional variables locally before launching the agent, then restart it.
Keep credentials out of committed client configuration. The default backend is
`https://reposcout-api.nouran-darwish-ai.dev`; do not set an empty override.

## Troubleshooting setup

- **Command not found:** check Python and uv, then run `uv tool update-shell`.
- **Server missing in the CLI:** merge the generated fragment into the correct
  user or trusted project configuration and restart the client.
- **Server fails to connect:** run `reposcout-mcp doctor`. Regenerate the client
  configuration if its interpreter path no longer exists. Check the client's
  workspace trust, MCP approval, and process permissions.
- **Local check passes but scouting fails:** check the backend and GitHub
  connection, credentials, quota, and rate limits. `doctor` does not test those
  external services, and backend outages fail closed.

## What is verified

The integration suite starts the generated Codex, OpenCode, Qwen Code, and generic
launchers through real MCP stdio sessions from unrelated directories. It also
tests the Claude manifest launcher from a fresh copy in a path with spaces,
tool and prompt discovery, and a tool validation error without consuming quota.
This verifies the shared protocol and package launchers; it does not simulate
every client's UI, model tool selection, or authenticated live scouting.

Manual checks on 2026-10-10 also confirmed MCP connections with Claude Code
2.1.286, OpenCode 1.18.35, and Qwen Code 0.25.0. Codex CLI 0.162.1 discovered
all five tools through its app-server MCP status API without a model request.
These checks used temporary client configurations or process-level overrides
and the launch commands documented above.

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
