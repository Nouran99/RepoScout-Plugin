# RepoScout MCP server and Claude Code plugin

RepoScout helps coding agents find strong open-source repos to bootstrap new
products. Its standard stdio MCP server works with Codex, OpenCode, Qwen Code,
and other MCP clients. It also bundles a native Claude Code plugin:

- MCP tools for search, analysis, comparison, and scaffolding
- Claude commands in `commands/`
- A project scouting skill in `skills/project-scout/`
- A repo analyst subagent in `agents/`

## Other coding agents

Install the standalone server from this directory:

```bash
uv tool install .
reposcout-mcp doctor
reposcout-mcp config --client codex
```

Merge the output into `~/.codex/config.toml`, preserving existing settings.
Use `--client opencode` for `opencode.json`, `--client qwen` for
`~/.qwen/settings.json`, or `--client generic` for other clients that accept
`mcpServers` JSON. Restart the agent, then ask it to use RepoScout.

The launcher also works as `python -m mcp_server` in an environment with this
package installed. `reposcout-mcp` (or `reposcout-mcp serve`) runs the MCP server;
`config` only prints configuration and never changes your agent's files.
`doctor` verifies local MCP initialization, five tools, three workflow prompts,
and tool input validation from an unrelated directory. It needs no keys or
network and consumes no quota; it does not check live backend availability.

See [the full agent setup guide](../../docs/CODING_AGENTS.md). Claude's slash
commands, hooks, and subagent are specific to Claude Code; other clients receive
the same five tools, server instructions, and optional MCP workflow prompts.

## Before Submission

Use this checklist before submitting to the Anthropic marketplace:

1. Keep the plugin self-contained inside this directory.
2. Bump `.claude-plugin/plugin.json` with a semantic version.
3. Verify `homepage`, `repository`, and `license` metadata are correct.
4. Confirm the production `REPOSCOUT_BACKEND_URL` to document for users.
5. Test local install with `claude --plugin-dir /absolute/path/to/RepoScout-plugin-community/plugins/reposcout`.
6. Have at least one external tester install and use the plugin.

## Prerequisites

- Your coding agent installed and authenticated, with local stdio MCP support
- Python 3.12+
- `uv`

## Production installation

Add the official RepoScout marketplace, then install the plugin:

```bash
claude plugin marketplace add Nouran99/RepoScout-Plugin
claude plugin install reposcout@reposcout-marketplace
```

Restart Claude Code or run `/reload-plugins`, then run `/reposcout:setup`.

The plugin works in anonymous free mode without credentials. A GitHub token is
optional and only raises GitHub API rate limits; a RepoScout API key unlocks the
plan attached to your RepoScout account.

## Production configuration

1. Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and authenticate it.
2. Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
3. Optionally create a RepoScout API key in the RepoScout dashboard at `https://nouran-darwish-ai.dev/reposcout/settings/api-keys`.
4. Set any optional credentials in the same shell that launches your coding agent:

```bash
export REPOSCOUT_API_KEY="rs_..."
export GITHUB_TOKEN="ghp_..." # optional, raises GitHub API limits
```

The production backend is the default. Override it only for local development:

```bash
export REPOSCOUT_BACKEND_URL="http://localhost:8000"
```

To test a checked-out plugin directly:

```bash
claude --plugin-dir /absolute/path/to/RepoScout-plugin-community/plugins/reposcout
```

The plugin makes one server-authoritative quota reservation per billable tool call and fails closed when the licensing backend is unreachable. Keep `REPOSCOUT_API_KEY` private, rotate it from the dashboard if it is exposed, and do not commit it to a repository or shell history. `REPOSCOUT_LICENSE_FAIL_OPEN=true` is reserved for local development and must not be used in production.

## Environment Variables

Optional variables used by the MCP server:

- `GITHUB_TOKEN`: raises GitHub API limits
- `REPOSCOUT_API_KEY`: enables RepoScout Pro or Team limits
- `REPOSCOUT_BACKEND_URL`: backend base URL, defaults to `https://reposcout-api.nouran-darwish-ai.dev`

## Local Development

From this directory:

```bash
uv sync --all-groups
claude --plugin-dir /absolute/path/to/RepoScout-plugin-community/plugins/reposcout
```

Claude loads:

- plugin metadata from `.claude-plugin/plugin.json`
- MCP server config from `.mcp.json`
- commands from `commands/`
- skills from `skills/`
- agents from `agents/`
- hooks from `hooks/hooks.json`

Run `/reposcout:setup` first to verify configuration and connectivity. The main
workflows are `/reposcout:find`, `/reposcout:analyze`, and
`/reposcout:compare`.

## Packaging Notes

This plugin starts its MCP server with:

```json
{
  "mcpServers": {
    "reposcout": {
      "command": "uv",
      "args": ["run", "--project", "${CLAUDE_PLUGIN_ROOT}", "--no-dev", "reposcout-mcp"]
    }
  }
}
```

Marketplace users need Python 3.12+ and `uv`. Other agents use the installed
`reposcout-mcp` launcher or the generated configuration; they do not need
`CLAUDE_PLUGIN_ROOT`. Both launch paths use the same MCP tools and backend.
Explicit project selection lets the Claude plugin start from other directories,
including paths with spaces. The first launch may download Python dependencies.

## Trust and license scope

RepoScout provides automated repository-health and license signals for triage. Its license output is not legal advice, does not replace review of the repository and dependency licenses, and must not be treated as a guarantee that a project is safe to ship. Users remain responsible for obtaining professional legal advice for commercial distribution, copyleft obligations, and third-party notices.

## Submission

Submit through one of Anthropic's official forms:

- `https://claude.ai/settings/plugins/submit`
- `https://platform.claude.com/plugins/submit`
