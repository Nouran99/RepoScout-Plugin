# RepoScout Claude Plugin

RepoScout is a Claude Code plugin that helps users find strong open-source repos
to bootstrap new products. It bundles:

- MCP tools for search, analysis, comparison, and scaffolding
- Claude commands in `commands/`
- A project scouting skill in `skills/project-scout/`
- A repo analyst subagent in `agents/`

## Before Submission

Use this checklist before submitting to the Anthropic marketplace:

1. Keep the plugin self-contained inside this directory.
2. Bump `.claude-plugin/plugin.json` with a semantic version.
3. Verify `homepage`, `repository`, and `license` metadata are correct.
4. Confirm the production `REPOSCOUT_BACKEND_URL` to document for users.
5. Test local install with `claude --plugin-dir /absolute/path/to/RepoScout-plugin-community/plugins/reposcout`.
6. Have at least one external tester install and use the plugin.

## Prerequisites

- Claude Code installed and authenticated
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
4. Set any optional credentials in the same shell that launches Claude Code:

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
uv sync --dev
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
      "args": ["run", "python", "-m", "mcp_server.server"]
    }
  }
}
```

That means marketplace users need a working Python 3.12+ and `uv` install unless
you later switch to a bundled launcher.

## Trust and license scope

RepoScout provides automated repository-health and license signals for triage. Its license output is not legal advice, does not replace review of the repository and dependency licenses, and must not be treated as a guarantee that a project is safe to ship. Users remain responsible for obtaining professional legal advice for commercial distribution, copyleft obligations, and third-party notices.

## Submission

Submit through one of Anthropic's official forms:

- `https://claude.ai/settings/plugins/submit`
- `https://platform.claude.com/plugins/submit`
