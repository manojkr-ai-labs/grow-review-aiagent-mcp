"""Publisher protocol and the dry-run implementation (Phase 3 task 3.9).

`DryRunPublisher` writes the artifacts a real publish would send — the rendered
body and the payload shapes — to `runs/<run_id>/`. Phase 4's `McpPublisher`
implements the same protocol, so the only thing that changes when publishing
goes live is which object the orchestrator constructs.

The idempotency key is defined here rather than in Phase 4 because the dry-run
artifact should already carry the identity a re-run would collide on.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from reviewpulse.models import PublishResult, PulseNote
from reviewpulse.pulse.render import render_email_body

NOTE_FILENAME = "note.md"
PUBLISH_FILENAME = "publish.json"


@dataclass
class DocRef:
    doc_id: str
    url: str | None = None


@dataclass
class DraftRef:
    draft_id: str
    recipient: str | None = None
    message_id: str | None = None
    sent: bool = False
    skipped: bool = False


def idempotency_key(window_end: date, prefix: str = "groww") -> str:
    """`groww:<ISO year>-W<week>` — one artifact per ISO week, per §8.4."""
    iso_year, iso_week, _ = window_end.isocalendar()
    return f"{prefix}:{iso_year}-W{iso_week:02d}"


def doc_title(key: str) -> str:
    return f"Groww Weekly Review Pulse [{key}]"


def email_subject(key: str) -> str:
    return f"Groww weekly review pulse [{key}]"


class Publisher(Protocol):
    def publish_doc(self, note: PulseNote, rendered: str, key: str) -> DocRef: ...

    def create_draft(
        self, note: PulseNote, rendered: str, doc: DocRef, key: str
    ) -> DraftRef: ...


class DryRunPublisher:
    """Writes what would have been published; makes no network calls."""

    mode = "dry_run"

    def __init__(self, run_dir: Path, *, recipient: str = "") -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.recipient = recipient
        self.calls: list[dict] = []

    @property
    def note_path(self) -> Path:
        return self.run_dir / NOTE_FILENAME

    @property
    def publish_path(self) -> Path:
        return self.run_dir / PUBLISH_FILENAME

    def publish_doc(self, note: PulseNote, rendered: str, key: str) -> DocRef:
        self.note_path.write_text(rendered, encoding="utf-8")
        self.calls.append(
            {
                "target": "gdocs",
                "operation": "create_or_update",
                "title": doc_title(key),
                "idempotency_key": key,
                "body_chars": len(rendered),
                "artifact": str(self.note_path),
            }
        )
        return DocRef(doc_id=f"dry-run-doc:{key}", url=None)

    def create_draft(
        self, note: PulseNote, rendered: str, doc: DocRef, key: str
    ) -> DraftRef:
        body = render_email_body(note, rendered, doc.url)
        self.calls.append(
            {
                "target": "gmail",
                "operation": "create_draft",
                "subject": email_subject(key),
                "to": self.recipient,
                "idempotency_key": key,
                "doc_id": doc.doc_id,
                "body_chars": len(body),
            }
        )
        return DraftRef(draft_id=f"dry-run-draft:{key}", recipient=self.recipient)

    def write_manifest_entry(
        self,
        note: PulseNote,
        doc: DocRef,
        draft: DraftRef,
        key: str,
    ) -> PublishResult:
        """Persist `publish.json` and return the result the orchestrator records."""
        result = PublishResult(
            doc_id=doc.doc_id,
            doc_url=doc.url,
            draft_id=draft.draft_id or None,
            message_id=draft.message_id,
            idempotency_key=key,
        )
        payload = {
            "run_id": note.run_id,
            "mode": "dry_run",
            "idempotency_key": key,
            "doc": asdict(doc),
            "draft": asdict(draft),
            "calls": self.calls,
            "artifacts": {"note": str(self.note_path)},
        }
        self.publish_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result


def publish(
    publisher: Publisher,
    note: PulseNote,
    rendered: str,
    *,
    key: str | None = None,
) -> tuple[PublishResult, DocRef, DraftRef]:
    """Docs first, then Gmail — the order Phase 4's partial-failure retry needs."""
    key = key or idempotency_key(note.window_end)
    doc = publisher.publish_doc(note, rendered, key)
    draft = publisher.create_draft(note, rendered, doc, key)
    if hasattr(publisher, "write_manifest_entry"):
        return publisher.write_manifest_entry(note, doc, draft, key), doc, draft
    return (
        PublishResult(
            doc_id=doc.doc_id,
            doc_url=doc.url,
            draft_id=draft.draft_id or None,
            message_id=draft.message_id,
            idempotency_key=key,
        ),
        doc,
        draft,
    )
