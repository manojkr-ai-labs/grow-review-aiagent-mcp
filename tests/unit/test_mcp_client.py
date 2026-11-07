"""MCP client helpers (Phase 4 stdio + Phase 5 hosted HTTP)."""

from __future__ import annotations

import pytest

from reviewpulse.config import EXAMPLE_SETTINGS_PATH, McpSettings, normalize_document_id, load_settings
from reviewpulse.mcp.client import (
    MCPAuthError,
    MCPConfigError,
    flatten_tool_payload,
    hosted_health_url,
    inspect_publish_servers,
    is_auth_error,
    is_retryable,
    mcp_probe_status,
    refuse_send_tool,
    unwrap_tool_result,
    verify_publish_servers,
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


def test_mcp_client_send_respects_allow_send(monkeypatch: pytest.MonkeyPatch) -> None:
    from reviewpulse.config import McpServerSettings
    from reviewpulse.mcp.client import MCPClient

    blocked = MCPClient(McpServerSettings(), name="gmail", allow_send=False)
    with pytest.raises(MCPConfigError, match="drafts only"):
        blocked.call_tool("send_email", {"to": "pm@example.com"})

    allowed = MCPClient(
        McpServerSettings(url="https://example.com/mcp"),
        name="gmail",
        allow_send=True,
    )

    def boom():
        raise RuntimeError("session-opened")

    monkeypatch.setattr(allowed, "_session", boom)
    with pytest.raises(Exception, match="session-opened"):
        allowed.call_tool("send_email", {"to": "pm@example.com"})


def test_normalize_document_id_accepts_url_or_bare_id() -> None:
    bare = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    url = f"https://docs.google.com/document/d/{bare}/edit"
    assert normalize_document_id(url) == bare
    assert normalize_document_id(bare) == bare
    assert normalize_document_id("  ") == ""


def test_hosted_health_url_strips_mcp_path() -> None:
    assert (
        hosted_health_url("https://mcp-gmail-google-docs-connect-production.up.railway.app/mcp")
        == "https://mcp-gmail-google-docs-connect-production.up.railway.app/health"
    )


def test_mcp_probe_empty_settings_is_not_configured() -> None:
    status = mcp_probe_status(McpSettings())
    assert status["ok"] is False
    assert status["label"] == "NOT_CONFIGURED"


def test_inspect_http_does_not_require_document_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from reviewpulse.config import McpServerSettings, McpToolNames
    from reviewpulse.mcp.client import ToolInfo

    url = "https://mcp-gmail-google-docs-connect-production.up.railway.app/mcp"
    settings = McpSettings(
        url=url,
        auth_token="test-token",
        gdocs=McpServerSettings(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            tools=McpToolNames(append="append_to_google_doc"),
        ),
        gmail=McpServerSettings(
            url=url,
            headers={"Authorization": "Bearer test-token"},
            tools=McpToolNames(create_draft="draft_email", send="send_email"),
        ),
    )

    class Fake:
        def verify(self, required):
            assert "append_to_google_doc" in required
            assert "draft_email" in required
            return [
                ToolInfo(name="append_to_google_doc"),
                ToolInfo(name="draft_email"),
                ToolInfo(name="send_email"),
            ]

    monkeypatch.setattr("reviewpulse.mcp.client.make_mcp_client", lambda *args, **kwargs: Fake())
    info = inspect_publish_servers(settings)
    assert info["publish_ready"] is False
    assert "append_to_google_doc" in info["tools"]
    status = mcp_probe_status(settings)
    assert status["ok"] is True
    assert status["label"] == "CONNECTED"
    assert "Google Doc" in (status["detail"] or "")
    with pytest.raises(MCPConfigError, match="document_id"):
        verify_publish_servers(settings)


def test_env_overlays_document_id_and_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token-value")
    monkeypatch.setenv("MCP_DOCUMENT_ID", "https://docs.google.com/document/d/abcDEF123xyz/edit")
    monkeypatch.setenv("GMAIL_RECIPIENT", "manojk.eci07@gmail.com")
    settings = load_settings(EXAMPLE_SETTINGS_PATH)
    assert settings.mcp.gdocs.document_id == "abcDEF123xyz"
    assert settings.pulse.recipient_alias == "manojk.eci07@gmail.com"
    assert settings.mcp.configured is True
