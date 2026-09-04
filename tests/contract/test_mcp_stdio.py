"""stdio contract: the native MCP client against the fake server."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from reviewpulse.config import McpServerSettings
from reviewpulse.mcp.client import MCPToolMismatchError, StdioMCPClient

SERVER = Path(__file__).resolve().parent / "fake_mcp_server.py"


def _settings(kind: str, state: Path) -> McpServerSettings:
    return McpServerSettings(
        command=sys.executable,
        args=[str(SERVER), kind],
        env={"FAKE_MCP_STATE": str(state)},
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def test_stdio_client_lists_and_calls_configured_tools(tmp_path) -> None:
    client = StdioMCPClient(_settings("docs", tmp_path / "state.json"), name="gdocs")
    tools = client.verify(["create_document", "insert_text"])
    names = {tool.name for tool in tools}
    assert {"create_document", "insert_text", "replace_text", "search_documents"} <= names

    created = client.call_tool("create_document", {"title": "Groww Weekly Review Pulse [groww:2026-W36]"})
    assert created["document_id"].startswith("doc-")
    inserted = client.call_tool(
        "insert_text",
        {"document_id": created["document_id"], "text": "hello"},
    )
    assert inserted["ok"] is True


def test_stdio_client_fails_fast_on_tool_mismatch(tmp_path) -> None:
    client = StdioMCPClient(_settings("mismatch", tmp_path / "state.json"), name="gdocs")
    with pytest.raises(MCPToolMismatchError, match="create_document"):
        client.verify(["create_document"])
