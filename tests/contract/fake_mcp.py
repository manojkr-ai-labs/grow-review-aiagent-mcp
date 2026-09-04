"""In-process MCP stand-in used by contract tests (Phase 4 task 4.13).

The production client talks stdio; publishers talk a `ToolClient`. This fake
implements that protocol and records every call, which is what lets a test
assert payloads and idempotency without Google credentials or `npx`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reviewpulse.mcp.client import MCPToolError, ToolInfo


@dataclass
class FakeToolClient:
    """Minimal Docs or Gmail server: named tools, in-memory documents/drafts."""

    kind: str
    tools: dict[str, dict]
    store: dict = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    fail_next: str | None = None
    fail_message: str = "503 unavailable"

    def list_tools(self) -> list[ToolInfo]:
        return [ToolInfo(name=name, schema=schema) for name, schema in self.tools.items()]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if name not in self.tools:
            raise MCPToolError(f"unknown tool {name}")
        if self.fail_next == name:
            self.fail_next = None
            raise MCPToolError(self.fail_message)
        if self.kind == "docs":
            return self._docs(name, arguments)
        return self._gmail(name, arguments)

    def _docs(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        docs: dict[str, dict] = self.store.setdefault("docs", {})
        if name == "create_document":
            doc_id = f"doc-{len(docs) + 1}"
            docs[doc_id] = {
                "title": arguments.get("title") or arguments.get("name") or "",
                "text": "",
            }
            return {
                "document_id": doc_id,
                "url": f"https://docs.example.test/{doc_id}",
            }
        doc_id = (
            arguments.get("document_id")
            or arguments.get("documentId")
            or arguments.get("id")
        )
        if name in {"insert_text", "append_to_google_doc"}:
            docs.setdefault(doc_id, {"title": "", "text": ""})
            docs[doc_id]["text"] += arguments.get("text") or arguments.get("content") or ""
            return {
                "success": True,
                "data": {
                    "documentId": doc_id,
                    "title": docs[doc_id].get("title") or "",
                    "appendedCharacterCount": len(
                        arguments.get("text") or arguments.get("content") or ""
                    ),
                },
            }
        if name == "replace_text":
            docs.setdefault(doc_id, {"title": "", "text": ""})
            docs[doc_id]["text"] = arguments.get("text") or arguments.get("content") or ""
            return {"ok": True, "document_id": doc_id}
        if name == "search_documents":
            query = arguments.get("query") or arguments.get("title") or ""
            hits = [
                {"document_id": item_id, "title": item["title"]}
                for item_id, item in docs.items()
                if query and query in item["title"]
            ]
            return {"documents": hits}
        raise MCPToolError(f"unhandled docs tool {name}")

    def _gmail(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        drafts: dict[str, dict] = self.store.setdefault("drafts", {})
        if name == "send_email":
            sent: dict[str, dict] = self.store.setdefault("sent", {})
            msg_id = f"msg-{len(sent) + 1}"
            sent[msg_id] = {
                "to": arguments.get("to"),
                "subject": arguments.get("subject"),
                "body": arguments.get("body") or arguments.get("text"),
            }
            return {
                "success": True,
                "data": {"messageId": msg_id, "threadId": "t-1"},
            }
        if name in {"create_draft", "draft_email"}:
            draft_id = f"draft-{len(drafts) + 1}"
            drafts[draft_id] = {
                "to": arguments.get("to"),
                "subject": arguments.get("subject"),
                "body": arguments.get("body") or arguments.get("text"),
            }
            if name == "draft_email":
                return {
                    "success": True,
                    "data": {"draftId": draft_id, "messageId": f"msg-{draft_id}", "threadId": ""},
                }
            return {"draft_id": draft_id}
        draft_id = arguments.get("draft_id") or arguments.get("draftId") or arguments.get("id")
        if name == "update_draft":
            if draft_id not in drafts:
                raise MCPToolError("draft not found")
            drafts[draft_id].update(
                {
                    "to": arguments.get("to"),
                    "subject": arguments.get("subject"),
                    "body": arguments.get("body") or arguments.get("text"),
                }
            )
            return {"draft_id": draft_id}
        if name == "list_drafts":
            query = arguments.get("query") or arguments.get("subject") or ""
            hits = [
                {"draft_id": item_id, "subject": item.get("subject")}
                for item_id, item in drafts.items()
                if query and query in (item.get("subject") or "")
            ]
            return {"drafts": hits}
        raise MCPToolError(f"unhandled gmail tool {name}")


def docs_client(store: dict | None = None) -> FakeToolClient:
    schema = {"type": "object", "properties": {"title": {}, "text": {}, "document_id": {}, "query": {}}}
    return FakeToolClient(
        kind="docs",
        store=store if store is not None else {},
        tools={
            "create_document": schema,
            "insert_text": schema,
            "search_documents": schema,
            "replace_text": schema,
        },
    )


def hosted_docs_client(store: dict | None = None) -> FakeToolClient:
    """gmail-docs-mcp Docs surface: append only, camelCase schema."""
    schema = {
        "type": "object",
        "properties": {
            "documentId": {"type": "string"},
            "content": {"type": "string"},
            "prependNewline": {"type": "boolean"},
        },
    }
    return FakeToolClient(
        kind="docs",
        store=store if store is not None else {},
        tools={"append_to_google_doc": schema},
    )


def hosted_gmail_client(store: dict | None = None) -> FakeToolClient:
    """gmail-docs-mcp Gmail surface: draft_email + send_email."""
    draft_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "array"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
    }
    send_schema = dict(draft_schema)
    return FakeToolClient(
        kind="gmail",
        store=store if store is not None else {},
        tools={"draft_email": draft_schema, "send_email": send_schema},
    )


def gmail_client(store: dict | None = None) -> FakeToolClient:
    schema = {
        "type": "object",
        "properties": {"to": {}, "subject": {}, "body": {}, "draft_id": {}, "query": {}},
    }
    return FakeToolClient(
        kind="gmail",
        store=store if store is not None else {},
        tools={
            "create_draft": schema,
            "list_drafts": schema,
            "update_draft": schema,
        },
    )
