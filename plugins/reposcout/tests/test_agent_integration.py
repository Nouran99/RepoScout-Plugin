"""Exercise installed launchers and client configs through real MCP stdio sessions."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_server.cli import client_config, main

_TOOLS = {
    "search_repos", "analyze_repo", "compare_repos", "clone_and_scaffold",
    "check_license_compatibility",
}


@pytest.mark.parametrize("client", ["codex", "opencode", "qwen", "generic"])
def test_config_is_parseable_and_does_not_embed_credentials(client, monkeypatch, capsys):
    executable = "C:\\Coding tools\\مستكشف 🔎\\python.exe"
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setenv("REPOSCOUT_API_KEY", "rs-never-embed-this")
    main(["config", "--client", client])
    output = capsys.readouterr().out
    assert "rs-never-embed-this" not in output
    assert "CLAUDE_PLUGIN_ROOT" not in output
    if client == "codex":
        server = tomllib.loads(output)["mcp_servers"]["reposcout"]
        assert server["command"] == executable
        assert server["args"] == ["-m", "mcp_server"]
        assert "REPOSCOUT_API_KEY" in server["env_vars"]
    elif client == "opencode":
        server = json.loads(output)["mcp"]["reposcout"]
        assert server["command"] == [executable, "-m", "mcp_server"]
        assert server["type"] == "local"
    else:
        server = json.loads(output)["mcpServers"]["reposcout"]
        assert server["command"] == executable
        assert server["args"] == ["-m", "mcp_server"]


def test_logging_never_writes_to_protocol_stdout(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", (
            "from mcp_server.cli import configure_logging; "
            "configure_logging(); import structlog; "
            "structlog.get_logger().info('tool_completed', count=1)"
        )],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"event": "tool_completed", "count": 1}


@pytest.mark.parametrize("launcher", [
    "codex", "opencode", "qwen", "generic", "console", "module-server", "claude",
])
async def test_launchers_discover_and_call_mcp_from_another_directory(launcher, tmp_path):
    env = {"GITHUB_TOKEN": "", "REPOSCOUT_API_KEY": ""}
    if launcher == "claude":
        plugin_root = Path(__file__).resolve().parents[1]
        # Relocate the actual package to exercise plugin-root expansion, uv
        # project selection, and fresh installation from a path with spaces.
        installed_root = tmp_path / "installed plugin with spaces"
        shutil.copytree(plugin_root, installed_root, ignore=shutil.ignore_patterns(
            ".venv", "tests", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ))
        server = json.loads((installed_root / ".mcp.json").read_text())["mcpServers"]["reposcout"]
        command = server["command"]
        args = [arg.replace("${CLAUDE_PLUGIN_ROOT}", str(installed_root)) for arg in server["args"]]
    elif launcher == "console":
        executable = Path(sys.executable).parent / (
            "reposcout-mcp.exe" if sys.platform == "win32" else "reposcout-mcp"
        )
        command, args = str(executable), ["serve"]
    elif launcher == "module-server":
        command, args = sys.executable, ["-m", "mcp_server.server"]
    elif launcher == "codex":
        server = tomllib.loads(client_config(launcher))["mcp_servers"]["reposcout"]
        command, args = server["command"], server["args"]
    elif launcher == "opencode":
        server = json.loads(client_config(launcher))["mcp"]["reposcout"]
        command, *args = server["command"]
    else:
        server = json.loads(client_config(launcher))["mcpServers"]["reposcout"]
        command, args = server["command"], server["args"]

    # This directory contains neither source files nor a pyproject.toml. Empty
    # credentials keep discovery independent of the developer's account.
    cwd = tmp_path / "unrelated project with spaces"
    cwd.mkdir()
    parameters = StdioServerParameters(
        command=command, args=args, cwd=cwd,
        env=env,
    )
    async with asyncio.timeout(60 if launcher == "claude" else 20):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "reposcout"
                assert "absolute target directory" in initialized.instructions
                assert "untrusted data" in initialized.instructions
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == _TOOLS
                prompts = await session.list_prompts()
                assert {prompt.name for prompt in prompts.prompts} == {"find", "analyze", "compare"}
                for name, arguments, expected in [
                    ("find", {"description": "FastAPI starter"}, "search_repos"),
                    ("analyze", {"repo_url": "owner/repo"}, "analyze_repo"),
                    ("compare", {"repo_urls": "owner/a owner/b"}, "compare_repos"),
                ]:
                    prompt = await session.get_prompt(name, arguments=arguments)
                    content = prompt.messages[0].content
                    assert content.type == "text"
                    assert expected in content.text
                    assert next(iter(arguments.values())) in content.text
                # Invalid input fails before quota/network access and exercises
                # real tools/call error serialization without spending quota.
                result = await session.call_tool("compare_repos", {"repo_urls": []})
                assert result.isError
                assert any("exactly 2 or 3" in item.text for item in result.content if item.type == "text")


def test_doctor_checks_real_stdio_without_credentials_or_network(tmp_path):
    executable = Path(sys.executable).parent / "reposcout-mcp"
    if sys.platform == "win32":
        executable = executable.with_suffix(".exe")
    result = subprocess.run(
        [str(executable), "doctor"], cwd=tmp_path,
        capture_output=True, text=True, check=True, timeout=40,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert set(report["tools"]) == _TOOLS
    assert report["prompts"] == ["analyze", "compare", "find"]
    assert report["network_checked"] is False
