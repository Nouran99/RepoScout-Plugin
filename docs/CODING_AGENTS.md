# Use RepoScout with coding agents

RepoScout exposes five tools through the standard MCP stdio transport. It does
not depend on a particular model or AI provider. A client must support starting
a local MCP process; a CLI that only supports remote HTTP MCP needs a separate
bridge and cannot use this launcher directly. The RepoScout licensing API is
not a remote MCP endpoint.

## Install once

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From a checkout of this repository:

```bash
uv tool install ./plugins/reposcout
reposcout-mcp --help
```

Make sure uv's tool executable directory is on your `PATH` (`uv tool update-shell`
can help). This installs a dedicated environment without requiring Claude Code.
The instructions use this checkout; they do not assume a PyPI release exists.

`reposcout-mcp config --client CLIENT` prints a fragment containing the absolute
Python interpreter of this installation and `-m mcp_server`. It works from any
agent working directory, including paths with spaces. It never reads or embeds
credentials and does not edit files. Merge the fragment with your existing
configuration. Regenerate it after moving or reinstalling the environment.

## Codex

```bash
reposcout-mcp config --client codex
```

Merge the TOML output into `~/.codex/config.toml` (or a trusted project's
`.codex/config.toml`). The fragment includes `env_vars` so Codex forwards the
optional RepoScout and GitHub variables from its environment. Restart Codex,
then use `codex mcp list` and `/mcp` to inspect the connection.

The configuration follows the [official Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## OpenCode

```bash
reposcout-mcp config --client opencode
```

Merge the JSON output into your project's `opencode.json`, or your global
`~/.config/opencode/opencode.json`. RepoScout is configured under `mcp` as a
`local` server with a command array. Restart OpenCode and run `opencode mcp list`
to inspect it. The generated config allows 30 seconds for initial discovery.

See the [official OpenCode MCP documentation](https://opencode.ai/docs/mcp-servers/).

## Qwen Code

```bash
reposcout-mcp config --client qwen
```

Merge the JSON output into `~/.qwen/settings.json` for all projects, or
`.qwen/settings.json` for one project. Restart Qwen Code and use `/mcp` to
inspect RepoScout. Review any workspace trust or tool confirmation prompts.

See the [official Qwen Code MCP documentation](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/).

## Other MCP clients

```bash
reposcout-mcp config --client generic
```

The output is a conventional `mcpServers.reposcout` object with `command` and
`args`. Use your client's documented configuration location. If its schema
differs, copy the command and argument values into the equivalent stdio server
fields. Do not copy the Claude plugin's `.mcp.json`: its plugin-root variable
and environment interpolation are Claude-specific.

## Credentials and usage

Anonymous free mode works without credentials but still needs the RepoScout
backend and GitHub API. Optional environment variables:

| Variable | Purpose |
| --- | --- |
| `GITHUB_TOKEN` | Increase GitHub API limits |
| `REPOSCOUT_API_KEY` | Use the plan attached to your RepoScout account |
| `REPOSCOUT_BACKEND_URL` | Override the production backend for development |

Set variables locally before launching the coding agent and restart it after
changes. OpenCode and Qwen Code launch local servers with their process
environment; Codex's generated config explicitly forwards these variable names.
If another client filters inherited variables, use its documented environment
settings. Keep keys out of committed configuration and conversations. The
backend defaults to `https://reposcout-api.nouran-darwish-ai.dev`; do not set an
empty backend override. Existing quota enforcement is shared across clients.

Try these requests in any connected agent:

- “Use RepoScout to find a maintained MIT-licensed FastAPI SaaS starter.”
- “Use RepoScout to analyze tiangolo/fastapi.”
- “Use RepoScout to compare tiangolo/fastapi and litestar-org/litestar.”
- “Use RepoScout to check the license compatibility of owner/repo.”

The tools are `search_repos`, `analyze_repo`, `compare_repos`,
`check_license_compatibility`, and `clone_and_scaffold`. Cloning writes local
files; explicitly provide and confirm the repository and absolute target path.
The directory must not already exist. License results are automated triage and
do not replace review of the actual project and dependency licenses.

Server instructions describe the workflow to agents that consume MCP
instructions. Clients with MCP prompt support can also discover `find`
(`description`), `analyze` (`repo_url`), and `compare` (`repo_urls`, a
space-separated string). Prompt display and invocation depend on the client;
plain-language requests work through the tools without prompt support. Claude's
`/reposcout:*` commands, hooks, skills, and subagent are native Claude assets
and are not installed by these MCP configurations.

## Development without a tool installation

From the repository root:

```bash
uv sync --project plugins/reposcout --all-groups
uv run --project plugins/reposcout reposcout-mcp config --client codex
```

The generated config points to the checkout's virtual environment. To configure
a client manually with uv, use command `uv` and the following separate arguments,
replacing the path with your absolute plugin directory:

```json
["run", "--project", "/absolute/path/to/RepoScout-plugin-community/plugins/reposcout", "--no-dev", "reposcout-mcp"]
```

`--project` locates the Python project without changing the agent's working
directory. All launchers reserve stdout for MCP protocol messages and send logs
to stderr. Tool and prompt discovery need no network calls or API keys; actual
scouting calls need GitHub and the licensing backend. If discovery fails, check
that the configured interpreter still exists and the package is installed in
that environment. If tools fail after discovery, check connectivity, credentials,
quota, and GitHub rate limits.
