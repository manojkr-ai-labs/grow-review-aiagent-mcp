"""MCP publisher: Docs first, then Gmail (Phase 4).

Partial failure is the realistic case. `publish_doc` writes the doc id to the
idempotency store *before* `create_draft` runs, so a retry for the same ISO
week updates that document instead of minting a second one. The run manifest
is only marked published after both calls succeed; a failed Gmail call still
leaves `publish.json` with the doc id for the next attempt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reviewpulse.config import McpSettings, Settings
from reviewpulse.mcp.client import ToolClient, make_mcp_client
from reviewpulse.models import PublishResult, PulseNote
from reviewpulse.publish.base import (
    PUBLISH_FILENAME,
    DraftRef,
    DocRef,
    NOTE_FILENAME,
)
from reviewpulse.publish.gdocs import publish_document
from reviewpulse.publish.gmail import create_or_update_draft, send_pulse_email
from reviewpulse.publish.state import record_for, save_record


@dataclass
class McpPublisher:
    """Live Publisher. Same protocol as DryRunPublisher; talks to MCP servers."""

    run_dir: Path
    recipient: str
    gdocs: ToolClient
    gmail: ToolClient
    mcp: McpSettings
    state_path: Path
    send_email: bool = False
    calls: list[dict] = field(default_factory=list)
    mode: str = "mcp"

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def note_path(self) -> Path:
        return self.run_dir / NOTE_FILENAME

    @property
    def publish_path(self) -> Path:
        return self.run_dir / PUBLISH_FILENAME

    def publish_doc(self, note: PulseNote, rendered: str, key: str) -> DocRef:
        self.note_path.write_text(rendered, encoding="utf-8")
        prior = record_for(self.state_path, key)
        doc = publish_document(
            self.gdocs,
            self.mcp.gdocs.tools,
            rendered=rendered,
            key=key,
            existing_id=prior.get("doc_id"),
            existing_url=prior.get("doc_url"),
            notebook_id=self.mcp.gdocs.document_id,
        )
        save_record(
            self.state_path,
            key,
            doc_id=doc.doc_id,
            doc_url=doc.url,
        )
        self.calls.append(
            {
                "target": "gdocs",
                "operation": "create_or_update",
                "idempotency_key": key,
                "doc_id": doc.doc_id,
                "doc_url": doc.url,
            }
        )
        self._write_partial(note, key, doc=doc, draft=None)
        return doc

    def create_draft(
        self, note: PulseNote, rendered: str, doc: DocRef, key: str
    ) -> DraftRef:
        prior = record_for(self.state_path, key)
        if self.send_email:
            return self._send(note, rendered, doc, key, prior)
        draft = create_or_update_draft(
            self.gmail,
            self.mcp.gmail.tools,
            note=note,
            rendered=rendered,
            doc=doc,
            key=key,
            recipient=self.recipient,
            existing_id=prior.get("draft_id"),
        )
        save_record(self.state_path, key, draft_id=draft.draft_id)
        self.calls.append(
            {
                "target": "gmail",
                "operation": "create_draft",
                "idempotency_key": key,
                "draft_id": draft.draft_id,
                "to": draft.recipient,
                "doc_id": doc.doc_id,
            }
        )
        return draft

    def _send(
        self,
        note: PulseNote,
        rendered: str,
        doc: DocRef,
        key: str,
        prior: dict,
    ) -> DraftRef:
        existing = prior.get("message_id")
        if existing:
            draft = DraftRef(
                draft_id=prior.get("draft_id") or "",
                recipient=self.recipient,
                message_id=existing,
                sent=True,
                skipped=True,
            )
            self.calls.append(
                {
                    "target": "gmail",
                    "operation": "skip_send",
                    "idempotency_key": key,
                    "message_id": existing,
                    "to": self.recipient,
                    "doc_id": doc.doc_id,
                }
            )
            return draft
        draft = send_pulse_email(
            self.gmail,
            self.mcp.gmail.tools,
            note=note,
            rendered=rendered,
            doc=doc,
            key=key,
            recipient=self.recipient,
        )
        save_record(self.state_path, key, message_id=draft.message_id)
        self.calls.append(
            {
                "target": "gmail",
                "operation": "send_email",
                "idempotency_key": key,
                "message_id": draft.message_id,
                "to": draft.recipient,
                "doc_id": doc.doc_id,
            }
        )
        return draft

    def write_manifest_entry(
        self,
        note: PulseNote,
        doc: DocRef,
        draft: DraftRef,
        key: str,
    ) -> PublishResult:
        result = PublishResult(
            doc_id=doc.doc_id,
            doc_url=doc.url,
            draft_id=draft.draft_id or None,
            message_id=draft.message_id,
            idempotency_key=key,
        )
        self._write_partial(note, key, doc=doc, draft=draft, published=True)
        return result

    def _write_partial(
        self,
        note: PulseNote,
        key: str,
        *,
        doc: DocRef | None,
        draft: DraftRef | None,
        published: bool = False,
    ) -> None:
        payload = {
            "run_id": note.run_id,
            "mode": self.mode,
            "published": published,
            "idempotency_key": key,
            "doc": asdict(doc) if doc else None,
            "draft": asdict(draft) if draft else None,
            "calls": self.calls,
            "artifacts": {"note": str(self.note_path)},
        }
        self.publish_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def build_mcp_publisher(
    settings: Settings,
    run_dir: Path,
    *,
    gdocs: ToolClient | None = None,
    gmail: ToolClient | None = None,
    state_path: Path | None = None,
    send: bool = False,
) -> McpPublisher:
    state = Path(state_path or (settings.db_path.parent / "publish-state.json"))
    return McpPublisher(
        run_dir=run_dir,
        recipient=settings.pulse.recipient_alias,
        gdocs=gdocs
        or make_mcp_client(
            settings.mcp.gdocs,
            name="gmail-docs" if settings.mcp.transport == "http" else "gdocs",
        ),
        gmail=gmail
        or make_mcp_client(
            settings.mcp.gmail,
            name="gmail-docs" if settings.mcp.transport == "http" else "gmail",
            allow_send=send,
        ),
        mcp=settings.mcp,
        state_path=state,
        send_email=send,
    )
