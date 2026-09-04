"""MCP client helpers (Phase 4 stdio + Phase 5 hosted HTTP)."""

from __future__ import annotations

import pytest

from reviewpulse.config import normalize_document_id
from reviewpulse.mcp.client import (
    MCPAuthError,
    MCPConfigError,
    flatten_tool_payload,
    is_auth_error,
    is_retryable,
    refuse_send_tool,
    unwrap_tool_result,
)


class _Result:
    def __init__(self, *, is_error: bool, text: str = "", structured=None) -> None:
        self.isError = is_error
        self.structuredContent = structured
        self.content = [type("C", (), {"text": text})()]


def test_auth_errors_are_not_retried() -> None:
    assert is_auth_error("invalid_grant: token expired")
    assert is_auth_error("AUTH_REQUIRED")
    assert not is_retryable("invalid_grant: token expired")
    result = _Result(is_error=True, text="OAuth token expired; re-auth the MCP server")
    try:
        unwrap_tool_result(result)
    except MCPAuthError as exc:
        assert "OAuth" in str(exc)
    else:
        raise AssertionError("expected MCPAuthError")


def test_hosted_auth_envelope_is_mcp_auth_error() -> None:
    payload = {
        "success": False,
        "error": {"code": "AUTH_REQUIRED", "message": "Run npm run auth"},
    }
    result = _Result(is_error=True, text=__import__("json").dumps(payload))
    with pytest.raises(MCPAuthError, match="AUTH_REQUIRED"):
        unwrap_tool_result(result)


def test_unavailable_errors_are_retried() -> None:
    assert is_retryable("503 unavailable")
    assert is_retryable("gateway timeout")
    assert is_retryable("RATE_LIMITED")
    assert not is_retryable("unknown tool create_document")


def test_hosted_success_envelope_flattens_ids() -> None:
    flat = flatten_tool_payload(
        {"success": True, "data": {"draftId": "r-1", "messageId": "m-1", "threadId": "t-1"}}
    )
    assert flat["draftId"] == "r-1"
    result = _Result(
        is_error=False,
        text='{"success":true,"data":{"documentId":"doc-9","title":"Pulse"}}',
    )
    unwrapped = unwrap_tool_result(result)
    assert unwrapped["documentId"] == "doc-9"


def test_refuse_send_email() -> None:
    with pytest.raises(MCPConfigError, match="drafts only"):
        refuse_send_tool("send_email")
    refuse_send_tool("draft_email")
    refuse_send_tool("send_email", allow_send=True)


def test_normalize_document_id_accepts_url_or_bare_id() -> None:
    bare = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    url = f"https://docs.google.com/document/d/{bare}/edit"
    assert normalize_document_id(url) == bare
    assert normalize_document_id(bare) == bare
    assert normalize_document_id("  ") == ""
