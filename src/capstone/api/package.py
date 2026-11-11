"""Weekly package HTTP. Assemble does not call MCP.

Publish uses the pulse publisher and the pulse state file. A desk case id
is refused. Send is called only when the stored approval says send.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from capstone.assemble import run as assemble_run
from capstone.contracts import WeeklyPackageManifest
from capstone.log import LogStore
from capstone.package import package_hash
from reviewpulse.mcp.client import ToolClient
from supportdesk.approval import ApprovalRecord, approval_matches
from supportdesk.enums import ApprovalDecision
from supportdesk.facts import RetrievalBundle
from supportdesk.ids import SHA256_PATTERN, is_case_id

router = APIRouter(prefix="/api/capstone")

_PACKAGE_CASE = "case_" + "0" * 32
_APPROVAL_NAME = "package-approval.json"


class PackageDecisionBody(BaseModel):
    """Approve or reject the current package hash."""

    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    approver_ref: str
    action: str = "draft"


class PackagePublishBody(BaseModel):
    """Hash the caller wants published. Send stays off unless the approval said so."""

    model_config = ConfigDict(extra="forbid")

    package_hash: str = Field(pattern=SHA256_PATTERN)
    action: str = "draft"


@dataclass
class PackageDeps:
    """Run directory, log, and the pulse publisher inputs tests can replace."""

    store: LogStore
    clock: datetime
    retriever: Callable[[str], RetrievalBundle]
    runs_dir: Path
    publish_state_path: Path
    desk_state_path: Path
    docs: ToolClient | None = None
    gmail: ToolClient | None = None


def package_deps() -> PackageDeps:
    """Defaults. Tests override this dependency."""
    return PackageDeps(
        store=LogStore(),
        clock=datetime.now(timezone.utc),
        retriever=_missing,
        runs_dir=Path("runs"),
        publish_state_path=Path("data/publish-state.json"),
        desk_state_path=Path("data/supportdesk-publish-state.json"),
    )


def _missing(question: str) -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])


@router.post("/runs/{run_id}/assemble")
def assemble(
    run_id: str,
    deps: PackageDeps = Depends(package_deps),
) -> dict[str, object]:
    """Build the package. This route does not call a publisher."""
    if is_case_id(run_id):
        raise HTTPException(status_code=409, detail="a desk case is not a weekly package")
    result = assemble_run(
        run_id,
        store=deps.store,
        clock=deps.clock,
        retriever=deps.retriever,
        runs_dir=deps.runs_dir,
    )
    if not result.assembled:
        raise HTTPException(status_code=409, detail={"codes": result.codes})
    return result.model_dump(mode="json")


@router.get("/runs/{run_id}/package")
def read_package(
    run_id: str,
    deps: PackageDeps = Depends(package_deps),
) -> dict[str, object]:
    """Note, explainer, signals, hash, and the week's ledger rows."""
    run_dir = _run_dir(deps, run_id)
    manifest = _manifest(run_dir)
    explainer = _json(run_dir / "explainer.json")
    week_id = str(explainer.get("week_id") or "")
    ledger = [row.model_dump(mode="json") for row in deps.store.list_ledger(week_id)]
    return {
        "note": (run_dir / "note.md").read_text(encoding="utf-8"),
        "explainer": explainer,
        "signals": _json(run_dir / "support_signals.json"),
        "package_hash": manifest.package_hash,
        "fee_theme": manifest.fee_theme,
        "ledger": ledger,
        "approval": _approval_view(run_dir),
    }


@router.post("/runs/{run_id}/decision")
def decide_package(
    run_id: str,
    body: PackageDecisionBody,
    deps: PackageDeps = Depends(package_deps),
) -> dict[str, object]:
    """Store the decision beside ``package.json``. Does not write a state file."""
    if is_case_id(run_id):
        raise HTTPException(status_code=409, detail="a desk case is not a weekly package")
    if body.action not in {"append", "draft", "send"}:
        raise HTTPException(status_code=422, detail="action must be append, draft, or send")
    run_dir = _run_dir(deps, run_id)
    digest = _current_hash(run_dir)
    record = _record(body.decision, digest, body.approver_ref, deps.clock)
    payload = record.model_dump(mode="json")
    payload["action"] = body.action
    (run_dir / _APPROVAL_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


@router.post("/runs/{run_id}/publish")
def publish_package(
    run_id: str,
    body: PackagePublishBody,
    deps: PackageDeps = Depends(package_deps),
) -> dict[str, object]:
    """Pulse tools only, and only for the approved hash."""
    if is_case_id(run_id):
        raise HTTPException(status_code=409, detail="a desk case is not a weekly package")
    run_dir = _run_dir(deps, run_id)
    approval = _approval(run_dir)
    current = _current_hash(run_dir)
    if not approval_matches(approval, body.package_hash) or not approval_matches(approval, current):
        raise HTTPException(status_code=409, detail="approval does not match this package hash")
    action = _action(run_dir)
    send = action == "send" and body.action == "send"
    if body.action == "send" and not send:
        raise HTTPException(status_code=409, detail="send was not approved")
    _publish_with_pulse(run_dir, deps, send=send, action=body.action)
    return {"ok": True, "package_hash": current, "action": "send" if send else body.action}


def _run_dir(deps: PackageDeps, run_id: str) -> Path:
    path = deps.runs_dir / run_id
    if not (path / "package.json").is_file() and not (path / "note.md").is_file():
        raise HTTPException(status_code=404, detail="run not found")
    return path


def _manifest(run_dir: Path) -> WeeklyPackageManifest:
    path = run_dir / "package.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="package not found")
    return WeeklyPackageManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _json(path: Path) -> object:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _current_hash(run_dir: Path) -> str:
    return package_hash(
        (run_dir / "note.md").read_bytes(),
        (run_dir / "explainer.json").read_bytes(),
        (run_dir / "support_signals.json").read_bytes(),
    )


def _record(
    decision: ApprovalDecision,
    digest: str,
    approver_ref: str,
    clock: datetime,
) -> ApprovalRecord:
    try:
        return ApprovalRecord(
            case_id=_PACKAGE_CASE,
            decision=decision,
            content_hash=digest,
            decided_at=clock,
            approver_ref=approver_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _approval_view(run_dir: Path) -> dict[str, object] | None:
    """Whether the stored decision still matches the files on disk."""
    path = run_dir / _APPROVAL_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    stored = payload.get("content_hash")
    decision = payload.get("decision")
    action = payload.get("action")
    current = _current_hash(run_dir)
    return {
        "decision": decision if isinstance(decision, str) else None,
        "content_hash": stored if isinstance(stored, str) else None,
        "action": action if isinstance(action, str) else "draft",
        "matches": decision == "approve" and stored == current,
    }


def _approval(run_dir: Path) -> ApprovalRecord:
    path = run_dir / _APPROVAL_NAME
    if not path.is_file():
        raise HTTPException(status_code=409, detail="package has no approval")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=409, detail="package approval is unreadable")
    stored = {key: payload.get(key) for key in ApprovalRecord.model_fields}
    return ApprovalRecord.model_validate(stored)


def _action(run_dir: Path) -> str:
    payload = json.loads((run_dir / _APPROVAL_NAME).read_text(encoding="utf-8"))
    action = payload.get("action") if isinstance(payload, dict) else None
    return action if isinstance(action, str) else "draft"


def _publish_with_pulse(run_dir: Path, deps: PackageDeps, *, send: bool, action: str) -> None:
    """Call the existing pulse publisher. Send follows the stored approval."""
    from reviewpulse.api.catalog import pulse_note_from_run
    from reviewpulse.config import Settings
    from reviewpulse.publish.mcp import build_mcp_publisher

    rendered = (run_dir / "note.md").read_text(encoding="utf-8")
    try:
        note = pulse_note_from_run(run_dir, rendered)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="note cannot be published") from exc
    publisher = build_mcp_publisher(
        Settings(),
        run_dir,
        gdocs=deps.docs,
        gmail=deps.gmail,
        state_path=deps.publish_state_path,
        send=send,
    )
    key = note.window_end.isoformat()
    doc = publisher.publish_doc(note, rendered, key)
    if action in {"draft", "send"}:
        publisher.create_draft(note, rendered, doc, key)
