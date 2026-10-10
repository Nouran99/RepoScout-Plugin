"""Validate RepoScout plugin packaging before marketplace submission."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class MarketplaceError(ValueError):
    """Raised when a marketplace package is incomplete or unsafe to submit."""


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MarketplaceError(f"Missing required file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MarketplaceError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MarketplaceError(f"Expected an object in {path}")
    return value


def require_https_url(value: Any, field: str) -> None:
    if not isinstance(value, str) or urlparse(value).scheme != "https":
        raise MarketplaceError(f"{field} must be an https URL")
    if "example.com" in value or "localhost" in value:
        raise MarketplaceError(f"{field} contains a placeholder/local URL")


def validate(plugin_dir: Path) -> None:
    metadata = read_json(plugin_dir / ".claude-plugin" / "plugin.json")
    for field in ("name", "description", "version", "author", "license"):
        if not metadata.get(field):
            raise MarketplaceError(f"plugin.json is missing {field}")
    if metadata["name"] != "reposcout":
        raise MarketplaceError("plugin name must be reposcout")
    if metadata["license"] != "MIT":
        raise MarketplaceError("plugin license must be MIT")
    require_https_url(metadata.get("homepage"), "plugin homepage")
    require_https_url(metadata.get("repository"), "plugin repository")

    pyproject_path = plugin_dir / "pyproject.toml"
    if not pyproject_path.is_file():
        raise MarketplaceError(f"Missing required file: {pyproject_path}")
    with pyproject_path.open("rb") as handle:
        project = tomllib.load(handle).get("project") or {}
    if project.get("name") != "reposcout-plugin":
        raise MarketplaceError("pyproject.toml project name must be reposcout-plugin")
    if project.get("version") != metadata["version"]:
        raise MarketplaceError("plugin version mismatch between pyproject.toml and plugin.json")

    marketplace = read_json(plugin_dir.parents[1] / ".claude-plugin" / "marketplace.json")
    plugins = marketplace.get("plugins") or []
    if not any(
        isinstance(item, dict)
        and item.get("name") == "reposcout"
        and item.get("source") == "./plugins/reposcout"
        for item in plugins
    ):
        raise MarketplaceError("marketplace.json must register ./plugins/reposcout")

    mcp = read_json(plugin_dir / ".mcp.json")
    server = (mcp.get("mcpServers") or {}).get("reposcout")
    if not isinstance(server, dict):
        raise MarketplaceError(".mcp.json must define mcpServers.reposcout")
    if server.get("command") != "uv":
        raise MarketplaceError("RepoScout MCP launcher must use uv")
    if server.get("cwd") != "${CLAUDE_PLUGIN_ROOT}/src":
        raise MarketplaceError("RepoScout MCP launcher cwd must be ${CLAUDE_PLUGIN_ROOT}/src")
    if "mcp_server.server" not in (server.get("args") or []):
        raise MarketplaceError("RepoScout MCP launcher must start mcp_server.server")

    required_paths = (
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "commands/setup.md",
        "skills/project-scout",
        "agents",
        "hooks/hooks.json",
        "src/mcp_server/server.py",
        "tests",
    )
    for relative in required_paths:
        if not (plugin_dir / relative).exists():
            raise MarketplaceError(f"Missing marketplace asset: {relative}")

    readme = (plugin_dir / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "Production installation",
        "REPOSCOUT_BACKEND_URL",
        "REPOSCOUT_API_KEY",
        "license output is not legal advice",
        "/reposcout:setup",
    ):
        if phrase not in readme:
            raise MarketplaceError(f"README.md is missing required onboarding text: {phrase}")

    for relative in (".mcp.json", "README.md", "commands/setup.md"):
        text = (plugin_dir / relative).read_text(encoding="utf-8")
        if any(marker in text for marker in ("/home/", "reposcout-audit", "\\\\")):
            raise MarketplaceError(f"{relative} contains a checkout-dependent path")

    build_dir = Path(tempfile.mkdtemp(prefix="reposcout-marketplace-build-"))
    try:
        result = subprocess.run(
            ["uv", "build", "--out-dir", str(build_dir)],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MarketplaceError(f"isolated plugin build failed: {result.stderr.strip()[-800:]}")
        if not list(build_dir.glob("*.whl")):
            raise MarketplaceError("isolated plugin build did not produce a wheel")
        dist_dir = plugin_dir / "dist"
        dist_dir.mkdir(exist_ok=True)
        for artifact in build_dir.iterdir():
            shutil.copy2(artifact, dist_dir / artifact.name)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-dir", type=Path, default=Path("plugins/reposcout"))
    args = parser.parse_args()
    try:
        validate(args.plugin_dir.resolve())
    except MarketplaceError as exc:
        print(f"Marketplace preflight rejected package: {exc}", file=sys.stderr)
        return 1
    print(f"Marketplace preflight passed: {args.plugin_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
