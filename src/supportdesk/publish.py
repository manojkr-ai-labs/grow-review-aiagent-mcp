"""Approval-gated Docs append and Gmail draft.

The pulse helpers `publish_document` and `create_or_update_draft` write a
weekly review note and a weekly subject. A support case uses the same MCP
tool names and the same argument binding, with `allow_send=False`, and its
own state file. `send_email` is never called.

An uncertain timeout is stored as uncertain and is not retried. A later call
retries only an action whose saved status says it did not complete.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from supportdesk.approval import mcp_idempotency_key
from supportdesk.contracts import McpActionRequest, McpActionResult, WorkflowRun
from supportdesk.decisions import DeskCase, content_digest
from supportdesk.enums import McpActionKind, McpActionStatus, WorkflowState
from supportdesk.reviewer import content_has_pii
from supportdesk.workflow import ContractError, assert_mcp_permitted, transition
from reviewpulse.config import HOSTED_APPEND_TOOL, HOSTED_DRAFT_TOOL
from reviewpulse.mcp.client import (
    MCPError,
    ToolClient,
    bind_arguments,
    extract_id,
    refuse_send_tool,
)

DEFAULT_STATE_NAME = "supportdesk-publish-state.json"


class PublishOutcome(BaseModel):
    """Workflow run plus the Docs and Gmail results. No message body is stored."""

    model_config = ConfigDict(extra="forbid")

    run: WorkflowRun
    actions: list[McpActionResult]


def publish_case(
    case: DeskCase,
    *,
    docs: ToolClient,
    gmail: ToolClient,
    document_id: str,
    recipient: str,
    state_path: Path,
) -> PublishOutcome:
    """Append the approved case and draft an email. Does not send."""
    if case.run.state is WorkflowState.COMPLETED:
        return _replay(case, state_path)
    _require_approved(case)
    if not document_id.strip() or not recipient.strip():
        raise ContractError("document id and recipient are required")
    if content_has_pii(case.result):
        raise ContractError("approved content matched a PII pattern")
    run = case.run
    if run.state is WorkflowState.APPROVED:
        run = transition(run, WorkflowState.MCP_ACTIONS)
    elif run.state is WorkflowState.PARTIAL_FAILURE:
        run = transition(run, WorkflowState.MCP_ACTIONS)
    elif run.state is not WorkflowState.MCP_ACTIONS:
        raise ContractError("MCP actions are not permitted from this state")

    digest = content_digest(case.result)
    docs_key = mcp_idempotency_key(case.run.case_id, digest, McpActionKind.DOCS_APPEND)
    draft_key = mcp_idempotency_key(case.run.case_id, digest, McpActionKind.GMAIL_DRAFT)
    _requests(case, digest, docs_key, draft_key)
    body = _case_body(case)
    docs_action = _append(
        docs,
        document_id=document_id.strip(),
        body=body,
        key=docs_key,
        state_path=state_path,
    )
    actions = [docs_action]
    if docs_action.status is McpActionStatus.SUCCEEDED or docs_action.status is McpActionStatus.SKIPPED_DUPLICATE:
        actions.append(
            _draft(
                gmail,
                recipient=recipient.strip(),
                body=body,
                case_id=case.run.case_id,
                key=draft_key,
                state_path=state_path,
            )
        )
    run = transition(
        run,
        WorkflowState.COMPLETED if _finished(actions) else WorkflowState.PARTIAL_FAILURE,
    )
    return PublishOutcome(run=run, actions=actions)


def _replay(case: DeskCase, state_path: Path) -> PublishOutcome:
    """Return saved ids for a finished case. Does not call a tool."""
    digest = content_digest(case.result)
    actions: list[McpActionResult] = []
    for kind in (McpActionKind.DOCS_APPEND, McpActionKind.GMAIL_DRAFT):
        key = mcp_idempotency_key(case.run.case_id, digest, kind)
        prior = _load(state_path).get(key) or {}
        status = _saved_status(prior)
        if status is not McpActionStatus.SUCCEEDED:
            raise ContractError("completed case has no saved MCP result")
        actions.append(
            _result(kind, McpActionStatus.SKIPPED_DUPLICATE, key, prior.get("external_id"))
        )
    return PublishOutcome(run=case.run, actions=actions)


def _require_approved(case: DeskCase) -> None:
    try:
        assert_mcp_permitted(case.run)
    except ContractError:
        raise
    if content_digest(case.result) != case.run.content_hash:
        raise ContractError("MCP actions require approval of this exact content")


def _requests(case: DeskCase, digest: str, docs_key: str, draft_key: str) -> None:
    approval = case.run.approval
    if approval is None:
        raise ContractError("MCP actions require approval of this exact content")
    McpActionRequest(
        case_id=case.run.case_id,
        kind=McpActionKind.DOCS_APPEND,
        content_hash=digest,
        approval=approval,
        idempotency_key=docs_key,
    )
    McpActionRequest(
        case_id=case.run.case_id,
        kind=McpActionKind.GMAIL_DRAFT,
        content_hash=digest,
        approval=approval,
        idempotency_key=draft_key,
    )


def _append(
    client: ToolClient,
    *,
    document_id: str,
    body: str,
    key: str,
    state_path: Path,
) -> McpActionResult:
    prior = _load(state_path).get(key) or {}
    status = _saved_status(prior)
    if status is McpActionStatus.SUCCEEDED:
        return _result(McpActionKind.DOCS_APPEND, McpActionStatus.SKIPPED_DUPLICATE, key, prior.get("external_id"))
    if status is McpActionStatus.UNCERTAIN:
        return _result(McpActionKind.DOCS_APPEND, McpActionStatus.UNCERTAIN, key, None, "timed out")
    try:
        payload = _call(
            client,
            HOSTED_APPEND_TOOL,
            {
                "document_id": document_id,
                "text": body,
                "prepend_newline": True,
            },
        )
    except Exception as exc:
        outcome = _classify(exc)
        _save(state_path, key, outcome, None)
        return _result(McpActionKind.DOCS_APPEND, outcome, key, None, _error_text(outcome))
    external_id = (
        extract_id(payload, "document_id", "documentId", "doc_id", "id") or document_id
    )
    _save(state_path, key, McpActionStatus.SUCCEEDED, external_id)
    return _result(McpActionKind.DOCS_APPEND, McpActionStatus.SUCCEEDED, key, external_id)


def _draft(
    client: ToolClient,
    *,
    recipient: str,
    body: str,
    case_id: str,
    key: str,
    state_path: Path,
) -> McpActionResult:
    prior = _load(state_path).get(key) or {}
    status = _saved_status(prior)
    if status is McpActionStatus.SUCCEEDED:
        return _result(McpActionKind.GMAIL_DRAFT, McpActionStatus.SKIPPED_DUPLICATE, key, prior.get("external_id"))
    if status is McpActionStatus.UNCERTAIN:
        return _result(McpActionKind.GMAIL_DRAFT, McpActionStatus.UNCERTAIN, key, None, "timed out")
    try:
        payload = _call(
            client,
            HOSTED_DRAFT_TOOL,
            {
                "to": recipient,
                "subject": f"Support desk {case_id}",
                "body": body,
            },
        )
    except Exception as exc:
        outcome = _classify(exc)
        _save(state_path, key, outcome, None)
        return _result(McpActionKind.GMAIL_DRAFT, outcome, key, None, _error_text(outcome))
    external_id = extract_id(payload, "draft_id", "draftId", "id")
    _save(state_path, key, McpActionStatus.SUCCEEDED, external_id)
    return _result(McpActionKind.GMAIL_DRAFT, McpActionStatus.SUCCEEDED, key, external_id)


def _call(client: ToolClient, tool_name: str, semantic: dict[str, Any]) -> dict[str, Any]:
    refuse_send_tool(tool_name, allow_send=False)
    tools = {tool.name: tool for tool in client.list_tools()}
    tool = tools.get(tool_name)
    if tool is None:
        raise ContractError(f"MCP server has no tool {tool_name}")
    return client.call_tool(tool_name, bind_arguments(tool.schema, semantic))


def _classify(exc: Exception) -> McpActionStatus:
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return McpActionStatus.UNCERTAIN
    return McpActionStatus.FAILED


def _error_text(status: McpActionStatus) -> str:
    if status is McpActionStatus.UNCERTAIN:
        return "timed out"
    return MCPError.__name__


def _finished(actions: list[McpActionResult]) -> bool:
    if len(actions) < 2:
        return False
    return all(
        item.status in {McpActionStatus.SUCCEEDED, McpActionStatus.SKIPPED_DUPLICATE}
        for item in actions
    )


def _result(
    kind: McpActionKind,
    status: McpActionStatus,
    key: str,
    external_id: object,
    error: str | None = None,
) -> McpActionResult:
    return McpActionResult(
        kind=kind,
        status=status,
        idempotency_key=key,
        external_id=external_id if isinstance(external_id, str) and external_id else None,
        error=error,
    )


def _case_body(case: DeskCase) -> str:
    note = case.result.routing_note
    citations = ", ".join(note.citation_refs) or "none"
    return "\n".join(
        [
            f"Support case {case.run.case_id}",
            case.result.reply.text,
            f"Citations: {citations}",
            f"Pattern: {note.pattern_signal.value} count {note.matching_count}",
            f"Team: {note.team} priority {note.priority.value}",
        ]
    )


def _saved_status(record: object) -> McpActionStatus | None:
    if not isinstance(record, dict):
        return None
    raw = record.get("status")
    try:
        return McpActionStatus(str(raw))
    except ValueError:
        return None


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(
    path: Path,
    key: str,
    status: McpActionStatus,
    external_id: str | None,
) -> None:
    state = _load(path)
    entry: dict[str, Any] = {"status": status.value, "kind": key.rsplit(":", 1)[-1]}
    if external_id:
        entry["external_id"] = external_id
    state[key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
