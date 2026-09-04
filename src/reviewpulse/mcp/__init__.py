"""MCP client — stdio or Streamable HTTP to Docs and Gmail (Phase 4–5)."""

from reviewpulse.mcp.client import (
    MCPAuthError,
    MCPClient,
    MCPConfigError,
    MCPError,
    MCPToolError,
    MCPToolMismatchError,
    MCPTransportError,
    StdioMCPClient,
    make_mcp_client,
    refuse_send_tool,
    inspect_publish_servers,
    verify_publish_servers,
)

__all__ = [
    "MCPAuthError",
    "MCPClient",
    "MCPConfigError",
    "MCPError",
    "MCPToolError",
    "MCPToolMismatchError",
    "MCPTransportError",
    "StdioMCPClient",
    "make_mcp_client",
    "refuse_send_tool",
    "inspect_publish_servers",
    "verify_publish_servers",
]
