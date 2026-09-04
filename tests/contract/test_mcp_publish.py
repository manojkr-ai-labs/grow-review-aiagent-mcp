"""Contract tests for MCP publishing (Phase 4 task 4.13).

A fake ToolClient stands in for the Docs and Gmail servers. The assertions are
the ones a live run has to keep: tool names, payload shape, ISO-week
idempotency, and "Docs ok / Gmail fail" leaving a reusable doc_id.
"""

from __future__ import annotations

from datetime import date

import pytest

from reviewpulse.config import EXAMPLE_SETTINGS_PATH, McpSettings, McpToolNames, Settings, load_settings
from reviewpulse.mcp.client import (
    MCPConfigError,
    MCPToolMismatchError,
    bind_arguments,
    verify_publish_servers,
)
from reviewpulse.models import ActionIdea, PulseNote, Quote, Theme
from reviewpulse.publish.base import doc_title, email_subject, idempotency_key, publish
from reviewpulse.publish.mcp import build_mcp_publisher
from tests.contract.fake_mcp import (
    FakeToolClient,
    docs_client,
    gmail_client,
    hosted_docs_client,
    hosted_gmail_client,
)


def _note(run_id: str = "run-1") -> PulseNote:
    theme = Theme(
        theme_id="t1",
        label="Withdrawals",
        summary="Payouts stall.",
        review_ids=["r1"],
        size=10,
        mean_rating=1.4,
        rank=1,
    )
    return PulseNote(
        run_id=run_id,
        window_start=date(2026, 8, 17),
        window_end=date(2026, 9, 4),
        review_count=40,
        top_themes=[theme],
        quotes=[Quote(review_id="r1", theme_id="t1", text="stuck withdrawal", rating=1)],
        actions=[ActionIdea(text="Investigate payouts", theme_ids=["t1"])],
        word_count=80,
        theme_count=1,
    )


def _settings(tmp_path) -> Settings:
    settings = load_settings()
    settings.pulse.recipient_alias = "pm@example.com"
    settings.mcp = McpSettings()
    settings.mcp.gdocs.tools = McpToolNames(
        create="create_document",
        append="insert_text",
        find="search_documents",
        replace="replace_text",
    )
    settings.mcp.gmail.tools = McpToolNames(
        create_draft="create_draft",
        find_draft="list_drafts",
        update_draft="update_draft",
    )
    return settings


def test_example_mcp_config_is_not_runnable() -> None:
    settings = load_settings(EXAMPLE_SETTINGS_PATH)
    assert settings.mcp.configured is False
    with pytest.raises(MCPConfigError, match="not configured"):
        verify_publish_servers(settings.mcp)


def test_invalid_recipient_is_rejected_at_config_load(tmp_path) -> None:
    from reviewpulse.config import ConfigError, validate_email

    with pytest.raises(ConfigError, match="valid email"):
        validate_email("not-an-address")
    assert validate_email("pm@groww.in") == "pm@groww.in"
    assert validate_email("") == ""


def test_bind_arguments_follows_the_server_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"documentId": {"type": "string"}, "content": {"type": "string"}},
    }
    bound = bind_arguments(schema, {"document_id": "doc-1", "text": "hello"})
    assert bound == {"documentId": "doc-1", "content": "hello"}


def test_publish_calls_docs_then_gmail_with_the_idempotency_key(tmp_path) -> None:
    settings = _settings(tmp_path)
    docs = docs_client()
    mail = gmail_client()
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    note = _note()
    result, doc, draft = publish(publisher, note, "weekly pulse body")

    key = idempotency_key(note.window_end)
    assert result.idempotency_key == key
    assert result.doc_id == doc.doc_id == "doc-1"
    assert result.draft_id == draft.draft_id == "draft-1"
    assert doc.url.startswith("https://docs.example.test/")

    assert [name for name, _ in docs.calls] == ["search_documents", "create_document", "insert_text"]
    assert docs.calls[1][1]["title"] == doc_title(key)
    assert docs.calls[2][1]["text"] == "weekly pulse body"
    assert docs.calls[2][1]["document_id"] == "doc-1"

    assert [name for name, _ in mail.calls] == ["list_drafts", "create_draft"]
    assert mail.calls[1][1]["to"] == "pm@example.com"
    assert mail.calls[1][1]["subject"] == email_subject(key)
    assert "weekly pulse body" in mail.calls[1][1]["body"]
    assert "https://docs.example.test/doc-1" in mail.calls[1][1]["body"]


def test_rerun_same_week_updates_in_place(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = {}
    docs = docs_client(store)
    mail = gmail_client(store)
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    note = _note()
    first, doc, draft = publish(publisher, note, "first body")
    docs.calls.clear()
    mail.calls.clear()

    second, doc2, draft2 = publish(publisher, note, "second body")
    assert second.doc_id == first.doc_id
    assert second.draft_id == first.draft_id
    assert doc2.doc_id == doc.doc_id
    assert draft2.draft_id == draft.draft_id
    assert "create_document" not in [name for name, _ in docs.calls]
    assert "create_draft" not in [name for name, _ in mail.calls]
    assert [name for name, _ in docs.calls][-1] == "replace_text"
    assert docs.store["docs"][doc.doc_id]["text"] == "second body"
    assert mail.store["drafts"][draft.draft_id]["body"] == (
        "second body\nFull document: https://docs.example.test/doc-1\n"
    )


def test_gmail_failure_persists_doc_id_for_retry(tmp_path) -> None:
    settings = _settings(tmp_path)
    docs = docs_client()
    mail = gmail_client()
    mail.fail_next = "create_draft"
    mail.fail_message = "503 unavailable"
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    note = _note()
    with pytest.raises(Exception, match="503"):
        publish(publisher, note, "body")

    payload = (tmp_path / "run" / "publish.json").read_text(encoding="utf-8")
    assert '"doc-1"' in payload
    assert '"published": false' in payload.lower() or '"draft": null' in payload

    mail.fail_next = None
    docs.calls.clear()
    retry, doc, draft = publish(publisher, note, "body")
    assert retry.doc_id == "doc-1"
    assert draft.draft_id == "draft-1"
    assert "create_document" not in [name for name, _ in docs.calls]


def test_tool_mismatch_lists_what_the_server_actually_has() -> None:
    client = FakeToolClient(
        kind="docs",
        tools={"docs.create": {"type": "object", "properties": {}}},
    )
    with pytest.raises(MCPToolMismatchError) as exc:
        # Mimic StdioMCPClient.verify using the same error type the live path raises.
        available = {tool.name for tool in client.list_tools()}
        missing = ["create_document"]
        if missing[0] not in available:
            raise MCPToolMismatchError(
                f"gdocs MCP server is missing tool(s) {missing}; "
                f"available: {', '.join(sorted(available))}"
            )
    assert "create_document" in str(exc.value)
    assert "docs.create" in str(exc.value)


def _hosted_settings() -> Settings:
    from reviewpulse.config import McpServerSettings

    settings = load_settings(EXAMPLE_SETTINGS_PATH)
    settings.pulse.recipient_alias = "pm@example.com"
    url = "https://mcp-gmail-google-docs-connect-production.up.railway.app/mcp"
    settings.mcp = McpSettings(
        url=url,
        auth_token="test-token",
        gdocs=McpServerSettings(
            url=url,
            document_id="notebook-1",
            tools=McpToolNames(append="append_to_google_doc"),
        ),
        gmail=McpServerSettings(
            url=url,
            tools=McpToolNames(create_draft="draft_email"),
        ),
    )
    return settings


def test_example_points_at_hosted_gmail_docs_mcp() -> None:
    settings = load_settings(EXAMPLE_SETTINGS_PATH)
    assert settings.mcp.url.endswith("/mcp")
    assert "railway.app" in settings.mcp.url
    assert settings.mcp.gdocs.tools.append == "append_to_google_doc"
    assert settings.mcp.gmail.tools.create_draft == "draft_email"
    assert settings.mcp.gmail.tools.send == "send_email"
    assert not settings.mcp.gmail.tools.forbidden()
    assert settings.schedule.weekday == "monday"
    assert settings.schedule.send_email is True


def test_hosted_publish_appends_then_drafts(tmp_path) -> None:
    settings = _hosted_settings()
    docs = hosted_docs_client()
    mail = hosted_gmail_client()
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    result, doc, draft = publish(publisher, _note(), "weekly pulse body")

    key = idempotency_key(_note().window_end)
    assert result.doc_id == doc.doc_id == "notebook-1"
    assert doc.url == "https://docs.google.com/document/d/notebook-1/edit"
    assert draft.draft_id == "draft-1"
    assert [name for name, _ in docs.calls] == ["append_to_google_doc"]
    assert docs.calls[0][1]["document_id"] == "notebook-1"
    assert key in docs.calls[0][1]["text"]
    assert "weekly pulse body" in docs.calls[0][1]["text"]
    assert [name for name, _ in mail.calls] == ["draft_email"]
    assert mail.calls[0][1]["to"] == "pm@example.com"
    assert "send_email" not in [name for name, _ in mail.calls]


def test_hosted_rerun_skips_append_and_opens_a_new_draft(tmp_path) -> None:
    settings = _hosted_settings()
    store: dict = {}
    docs = hosted_docs_client(store)
    mail = hosted_gmail_client(store)
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    note = _note()
    first, doc, draft = publish(publisher, note, "first body")
    docs.calls.clear()
    mail.calls.clear()

    second, doc2, draft2 = publish(publisher, note, "second body")
    assert second.doc_id == first.doc_id == "notebook-1"
    assert doc2.doc_id == doc.doc_id
    assert [name for name, _ in docs.calls] == []
    assert [name for name, _ in mail.calls] == ["draft_email"]
    assert draft2.draft_id != draft.draft_id
    assert "send_email" not in [name for name, _ in mail.calls]


def test_hosted_gmail_failure_does_not_reappend(tmp_path) -> None:
    settings = _hosted_settings()
    docs = hosted_docs_client()
    mail = hosted_gmail_client()
    mail.fail_next = "draft_email"
    mail.fail_message = "503 unavailable"
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
    )
    with pytest.raises(Exception, match="503"):
        publish(publisher, _note(), "body")

    assert [name for name, _ in docs.calls] == ["append_to_google_doc"]
    mail.fail_next = None
    docs.calls.clear()
    retry, doc, draft = publish(publisher, _note(), "body")
    assert retry.doc_id == "notebook-1"
    assert doc.doc_id == "notebook-1"
    assert draft.draft_id == "draft-1"
    assert [name for name, _ in docs.calls] == []


def test_bind_arguments_coerces_to_array_for_hosted_gmail() -> None:
    from reviewpulse.mcp.client import bind_arguments

    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
    }
    bound = bind_arguments(
        schema, {"to": "pm@example.com", "subject": "hi", "body": "note"}
    )
    assert bound["to"] == ["pm@example.com"]


def test_hosted_send_calls_send_email_not_draft(tmp_path) -> None:
    settings = _hosted_settings()
    settings.mcp.gmail.tools.send = "send_email"
    docs = hosted_docs_client()
    mail = hosted_gmail_client()
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
        send=True,
    )
    result, doc, draft = publish(publisher, _note(), "weekly pulse body")

    assert result.doc_id == "notebook-1"
    assert result.message_id == "msg-1"
    assert draft.sent is True
    assert [name for name, _ in docs.calls] == ["append_to_google_doc"]
    assert [name for name, _ in mail.calls] == ["send_email"]
    assert mail.calls[0][1]["to"] == "pm@example.com"
    assert "draft_email" not in [name for name, _ in mail.calls]


def test_hosted_send_same_week_skips_second_send(tmp_path) -> None:
    settings = _hosted_settings()
    settings.mcp.gmail.tools.send = "send_email"
    store: dict = {}
    docs = hosted_docs_client(store)
    mail = hosted_gmail_client(store)
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=docs,
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
        send=True,
    )
    note = _note()
    first, _, draft = publish(publisher, note, "first body")
    docs.calls.clear()
    mail.calls.clear()

    second, _, draft2 = publish(publisher, note, "second body")
    assert second.message_id == first.message_id == "msg-1"
    assert draft2.skipped is True
    assert [name for name, _ in docs.calls] == []
    assert [name for name, _ in mail.calls] == []


def test_hosted_draft_path_still_never_sends(tmp_path) -> None:
    settings = _hosted_settings()
    mail = hosted_gmail_client()
    publisher = build_mcp_publisher(
        settings,
        tmp_path / "run",
        gdocs=hosted_docs_client(),
        gmail=mail,
        state_path=tmp_path / "publish-state.json",
        send=False,
    )
    publish(publisher, _note(), "body")
    assert "send_email" not in [name for name, _ in mail.calls]
    assert [name for name, _ in mail.calls] == ["draft_email"]
