"""stdio MCP fake used to prove the native client, not just the publisher."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

KIND = sys.argv[1] if len(sys.argv) > 1 else "docs"
STATE_PATH = Path(os.environ.get("FAKE_MCP_STATE", "fake-mcp-state.json"))

server = FastMCP(f"fake-{KIND}")


def _load() -> dict:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"docs": {}, "drafts": {}}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


if KIND == "docs":

    @server.tool()
    def create_document(title: str) -> dict:
        state = _load()
        doc_id = f"doc-{len(state['docs']) + 1}"
        state["docs"][doc_id] = {"title": title, "text": ""}
        _save(state)
        return {"document_id": doc_id, "url": f"https://docs.example.test/{doc_id}"}

    @server.tool()
    def insert_text(document_id: str, text: str) -> dict:
        state = _load()
        state["docs"].setdefault(document_id, {"title": "", "text": ""})
        state["docs"][document_id]["text"] += text
        _save(state)
        return {"ok": True, "document_id": document_id}

    @server.tool()
    def replace_text(document_id: str, text: str) -> dict:
        state = _load()
        state["docs"].setdefault(document_id, {"title": "", "text": ""})
        state["docs"][document_id]["text"] = text
        _save(state)
        return {"ok": True, "document_id": document_id}

    @server.tool()
    def search_documents(query: str) -> dict:
        state = _load()
        hits = [
            {"document_id": doc_id, "title": item["title"]}
            for doc_id, item in state["docs"].items()
            if query in item["title"]
        ]
        return {"documents": hits}

elif KIND == "gmail":

    @server.tool()
    def create_draft(to: str, subject: str, body: str) -> dict:
        state = _load()
        draft_id = f"draft-{len(state['drafts']) + 1}"
        state["drafts"][draft_id] = {"to": to, "subject": subject, "body": body}
        _save(state)
        return {"draft_id": draft_id}

    @server.tool()
    def list_drafts(query: str = "") -> dict:
        state = _load()
        hits = [
            {"draft_id": draft_id, "subject": item.get("subject")}
            for draft_id, item in state["drafts"].items()
            if query in (item.get("subject") or "")
        ]
        return {"drafts": hits}

    @server.tool()
    def update_draft(draft_id: str, to: str = "", subject: str = "", body: str = "") -> dict:
        state = _load()
        if draft_id not in state["drafts"]:
            raise ValueError("draft not found")
        state["drafts"][draft_id] = {"to": to, "subject": subject, "body": body}
        _save(state)
        return {"draft_id": draft_id}

else:

    @server.tool()
    def docs_create(title: str) -> dict:
        return {"id": "unexpected"}


if __name__ == "__main__":
    server.run()
