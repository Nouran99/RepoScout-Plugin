"""Agent-independent launcher and client configuration for RepoScout."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
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


async def check_installation() -> dict[str, object]:
    """Check the installed server over stdio without credentials or network calls."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    expected_tools = {
        "search_repos", "analyze_repo", "compare_repos",
        "check_license_compatibility", "clone_and_scaffold",
    }
    with tempfile.TemporaryDirectory(prefix="reposcout connection check ") as directory:
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "mcp_server"], cwd=directory,
            env={"GITHUB_TOKEN": "", "REPOSCOUT_API_KEY": ""},
        )
        async with asyncio.timeout(30):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    prompts = await session.list_prompts()
                    if initialized.serverInfo.name != "reposcout":
                        raise RuntimeError("Unexpected MCP server")
                    if {tool.name for tool in tools.tools} != expected_tools:
                        raise RuntimeError("Incomplete tool discovery")
                    if {prompt.name for prompt in prompts.prompts} != {"find", "analyze", "compare"}:
                        raise RuntimeError("Incomplete prompt discovery")
                    # Invalid input is rejected before backend/quota access.
                    result = await session.call_tool("compare_repos", {"repo_urls": []})
                    if not result.isError:
                        raise RuntimeError("Tool validation failed")
    return {
        "status": "ok", "server": initialized.serverInfo.name,
        "tools": sorted(expected_tools),
        "prompts": sorted(prompt.name for prompt in prompts.prompts),
        "tool_call": "invalid input rejected",
        "network_checked": False,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RepoScout MCP server for coding agents")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Run the stdio MCP server (the default)")
    commands.add_parser("doctor", help="Check local MCP discovery and tool calls without using quota")
    config = commands.add_parser("config", help="Print a client config fragment; no files are changed")
    config.add_argument("--client", required=True, choices=["codex", "opencode", "qwen", "generic"])
    options = parser.parse_args(argv)
    if options.command == "config":
        print(client_config(options.client))
        return
    if options.command == "doctor":
        try:
            report = asyncio.run(check_installation())
        except Exception as exc:
            parser.exit(1, f"RepoScout connection check failed ({type(exc).__name__}).\n")
        print(json.dumps(report, indent=2))
        return

    configure_logging()
    from mcp_server.server import mcp

    mcp.run(transport="stdio")
