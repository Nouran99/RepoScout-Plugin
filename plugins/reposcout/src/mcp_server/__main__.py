"""Entry point — run the RepoScout MCP server over stdio transport."""
from mcp_server.server import mcp

mcp.run(transport="stdio")
