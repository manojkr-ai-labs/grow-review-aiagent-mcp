"""Google Docs publisher over MCP (Phase 4 tasks 4.6, 4.9; Phase 5 hosted append)."""

from __future__ import annotations

from reviewpulse.config import McpToolNames, google_doc_url
from reviewpulse.mcp.client import MCPConfigError, ToolClient, extract_id, extract_url
from reviewpulse.publish.base import DocRef, doc_title

INSERT_CHUNK = 3500


def publish_document(
    client: ToolClient,
    tools: McpToolNames,
    *,
    rendered: str,
    key: str,
    existing_id: str | None = None,
    existing_url: str | None = None,
    notebook_id: str | None = None,
) -> DocRef:
    """Create or update the weekly doc whose title carries `key`.

    The hosted gmail-docs-mcp server can only *append* to an existing document.
    When `notebook_id` is set, that ID is the rolling pulse notebook: the first
    publish of an ISO week appends a headed section; a re-run of the same week
    skips the append so a Gmail retry cannot duplicate the note.
    """
    title = doc_title(key)
    names = {tool.name for tool in client.list_tools()}
    notebook_id = (notebook_id or "").strip() or None

    if notebook_id:
        return _append_to_notebook(
            client,
            tools,
            names=names,
            rendered=rendered,
            title=title,
            notebook_id=notebook_id,
            existing_id=existing_id,
            existing_url=existing_url,
        )

    doc_id = existing_id or _find_doc(client, tools, title, key)

    if doc_id and tools.replace and tools.replace in names:
        client.call_tool(
            tools.replace,
            {"document_id": doc_id, "text": rendered, "title": title},
        )
        return DocRef(doc_id=doc_id, url=existing_url)

    if not doc_id:
        if not tools.create or tools.create not in names:
            raise MCPConfigError(
                "no existing Google Doc id and the MCP server has no create tool. "
                "Set mcp.gdocs.document_id to a Doc the authorized account can edit."
            )
        created = client.call_tool(tools.create, {"title": title})
        doc_id = (
            extract_id(
                created,
                "document_id",
                "documentId",
                "doc_id",
                "docId",
                "fileId",
                "file_id",
                "id",
            )
            or f"doc:{key}"
        )
        url = extract_url(created) or existing_url
        if tools.append and tools.append in names:
            _insert(client, tools.append, doc_id, rendered)
        return DocRef(doc_id=doc_id, url=url)

    if tools.append and tools.append in names:
        _insert(client, tools.append, doc_id, rendered)
    return DocRef(doc_id=doc_id, url=existing_url)


def _append_to_notebook(
    client: ToolClient,
    tools: McpToolNames,
    *,
    names: set[str],
    rendered: str,
    title: str,
    notebook_id: str,
    existing_id: str | None,
    existing_url: str | None,
) -> DocRef:
    url = existing_url or google_doc_url(notebook_id)
    if existing_id == notebook_id:
        # Same ISO week already appended (or Docs succeeded and Gmail failed).
        return DocRef(doc_id=notebook_id, url=url)
    if not tools.append or tools.append not in names:
        raise MCPConfigError(
            f"hosted Docs publish needs append tool {tools.append!r}; "
            f"available: {', '.join(sorted(names)) or '(none)'}"
        )
    section = f"{title}\n\n{rendered}".rstrip() + "\n"
    result = client.call_tool(
        tools.append,
        {
            "document_id": notebook_id,
            "text": section,
            "prepend_newline": True,
        },
    )
    returned_id = (
        extract_id(result, "document_id", "documentId", "doc_id", "id")
        or notebook_id
    )
    return DocRef(doc_id=returned_id, url=extract_url(result) or url)


def _find_doc(client: ToolClient, tools: McpToolNames, title: str, key: str) -> str | None:
    if not tools.find:
        return None
    names = {tool.name for tool in client.list_tools()}
    if tools.find not in names:
        return None
    found = client.call_tool(tools.find, {"query": key, "title": title})
    for item in _iter_records(found):
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("title", "name", "subject", "text", "id")
        )
        if key in haystack or title in haystack:
            return extract_id(
                item, "document_id", "documentId", "doc_id", "id", "fileId", "file_id"
            )
    return extract_id(
        found, "document_id", "documentId", "doc_id", "id", "fileId", "file_id"
    )


def _insert(client: ToolClient, tool: str, doc_id: str, rendered: str) -> None:
    if len(rendered) <= INSERT_CHUNK:
        client.call_tool(tool, {"document_id": doc_id, "text": rendered})
        return
    for start in range(0, len(rendered), INSERT_CHUNK):
        client.call_tool(
            tool,
            {"document_id": doc_id, "text": rendered[start : start + INSERT_CHUNK]},
        )


def _iter_records(payload: dict) -> list[dict]:
    for key in ("documents", "files", "items", "results", "drafts"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload] if payload else []
