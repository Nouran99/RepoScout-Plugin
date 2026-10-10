"""Agent-independent launcher and client configuration for RepoScout."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import structlog

_ENV_VARS = ["GITHUB_TOKEN", "REPOSCOUT_API_KEY", "REPOSCOUT_BACKEND_URL"]


def client_config(client: str) -> str:
    """Render a config fragment using this installation's Python interpreter.

    No credentials are read or embedded. Absolute executable paths and module
    loading let clients start the installed server from any working directory.
    """
    command = sys.executable
    args = ["-m", "mcp_server"]
    if client == "codex":
        # JSON strings/arrays are also valid TOML basic strings/arrays. Escape
        # non-ASCII characters literally because TOML has no JSON surrogate pairs.
        return "\n".join([
            "[mcp_servers.reposcout]",
            f"command = {json.dumps(command, ensure_ascii=False)}",
            f"args = {json.dumps(args)}",
            f"env_vars = {json.dumps(_ENV_VARS)}",
            "startup_timeout_sec = 30",
        ])
    if client == "opencode":
        return json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "mcp": {"reposcout": {
                "type": "local",
                "command": [command, *args],
                "enabled": True,
                "timeout": 30000,
            }},
        }, indent=2)
    if client in {"qwen", "generic"}:
        return json.dumps({
            "mcpServers": {"reposcout": {"command": command, "args": args}},
        }, indent=2)
    raise ValueError(f"Unsupported MCP client: {client}")


def configure_logging() -> None:
    """Reserve stdout for MCP JSON-RPC messages, including during tool calls."""
    structlog.configure(
        processors=[structlog.processors.JSONRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RepoScout MCP server for coding agents")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Run the stdio MCP server (the default)")
    config = commands.add_parser("config", help="Print a client config fragment; no files are changed")
    config.add_argument("--client", required=True, choices=["codex", "opencode", "qwen", "generic"])
    options = parser.parse_args(argv)
    if options.command == "config":
        print(client_config(options.client))
        return

    configure_logging()
    from mcp_server.server import mcp

    mcp.run(transport="stdio")
