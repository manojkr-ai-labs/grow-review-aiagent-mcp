"""Local idempotency store for MCP publish (Phase 4 tasks 4.8–4.10).

The MCP servers do not share a standard search API, so the publisher also
records the last `doc_id` / `draft_id` for each ISO-week key. That is what
lets a Gmail failure reuse the Docs artifact instead of creating a second one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reviewpulse.config import default_state_path


def load_state(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or default_state_path())
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def record_for(path: Path | None, key: str) -> dict[str, Any]:
    entry = load_state(path).get(key)
    return dict(entry) if isinstance(entry, dict) else {}


def save_record(
    path: Path | None,
    key: str,
    *,
    doc_id: str | None = None,
    doc_url: str | None = None,
    draft_id: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Merge one key's identifiers. Existing values win unless a new one is given."""
    path = Path(path or default_state_path())
    state = load_state(path)
    entry = dict(state.get(key) or {})
    if doc_id:
        entry["doc_id"] = doc_id
    if doc_url:
        entry["doc_url"] = doc_url
    if draft_id:
        entry["draft_id"] = draft_id
    if message_id:
        entry["message_id"] = message_id
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    state[key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry
