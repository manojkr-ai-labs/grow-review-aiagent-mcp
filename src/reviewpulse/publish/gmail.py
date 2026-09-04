"""Gmail draft / send publisher over MCP (Phase 4 + Phase 6)."""

from __future__ import annotations

from reviewpulse.config import HOSTED_SEND_TOOL, McpToolNames
from reviewpulse.mcp.client import MCPConfigError, MCPToolError, ToolClient, extract_id, refuse_send_tool
from reviewpulse.models import PulseNote
from reviewpulse.publish.base import DraftRef, DocRef, email_subject
from reviewpulse.pulse.render import render_email_body


def create_or_update_draft(
    client: ToolClient,
    tools: McpToolNames,
    *,
    note: PulseNote,
    rendered: str,
    doc: DocRef,
    key: str,
    recipient: str,
    existing_id: str | None = None,
) -> DraftRef:
    """Create (or refresh) the draft whose subject carries `key`. Never sends."""
    if not recipient:
        raise MCPToolError(
            "gmail.recipient_alias is empty; set it in config/settings.toml "
            "before a live publish"
        )
    refuse_send_tool(tools.create_draft)
    subject = email_subject(key)
    body = render_email_body(note, rendered, doc.url)
    names = {tool.name for tool in client.list_tools()}
    if tools.create_draft not in names:
        raise MCPConfigError(
            f"Gmail MCP server has no draft tool {tools.create_draft!r}; "
            f"available: {', '.join(sorted(names)) or '(none)'}"
        )
    draft_id = existing_id or _find_draft(client, tools, names, subject, key)

    if draft_id and tools.update_draft and tools.update_draft in names:
        try:
            updated = client.call_tool(
                tools.update_draft,
                {
                    "draft_id": draft_id,
                    "to": recipient,
                    "subject": subject,
                    "body": body,
                },
            )
            return DraftRef(
                draft_id=extract_id(updated, "draft_id", "draftId", "id") or draft_id,
                recipient=recipient,
            )
        except MCPToolError:
            draft_id = None

    created = client.call_tool(
        tools.create_draft,
        {"to": recipient, "subject": subject, "body": body},
    )
    return DraftRef(
        draft_id=extract_id(created, "draft_id", "draftId", "id") or f"draft:{key}",
        recipient=recipient,
    )


def send_pulse_email(
    client: ToolClient,
    tools: McpToolNames,
    *,
    note: PulseNote,
    rendered: str,
    doc: DocRef,
    key: str,
    recipient: str,
) -> DraftRef:
    """Send the pulse via MCP `send_email`. Same subject/body as the draft path."""
    if not recipient:
        raise MCPToolError(
            "gmail.recipient_alias is empty; set it in config/settings.toml "
            "before a live publish"
        )
    send_name = tools.send or HOSTED_SEND_TOOL
    refuse_send_tool(send_name, allow_send=True)
    subject = email_subject(key)
    body = render_email_body(note, rendered, doc.url)
    names = {tool.name for tool in client.list_tools()}
    if send_name not in names:
        raise MCPConfigError(
            f"Gmail MCP server has no send tool {send_name!r}; "
            f"available: {', '.join(sorted(names)) or '(none)'}"
        )
    sent = client.call_tool(
        send_name,
        {"to": recipient, "subject": subject, "body": body},
    )
    message_id = (
        extract_id(sent, "message_id", "messageId", "id") or f"msg:{key}"
    )
    return DraftRef(
        draft_id="",
        recipient=recipient,
        message_id=message_id,
        sent=True,
    )


def _find_draft(
    client: ToolClient,
    tools: McpToolNames,
    names: set[str],
    subject: str,
    key: str,
) -> str | None:
    if not tools.find_draft or tools.find_draft not in names:
        return None
    found = client.call_tool(tools.find_draft, {"query": key, "subject": subject})
    for item in _iter_drafts(found):
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("subject", "title", "id", "snippet")
        )
        if key in haystack or subject in haystack:
            return extract_id(item, "draft_id", "draftId", "id")
    return extract_id(found, "draft_id", "draftId", "id")


def _iter_drafts(payload: dict) -> list[dict]:
    for key in ("drafts", "items", "results", "messages"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload] if payload else []
