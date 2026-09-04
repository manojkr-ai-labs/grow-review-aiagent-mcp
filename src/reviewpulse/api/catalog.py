"""Scan `runs/` manifests and serialize pulse / theme / run views."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reviewpulse.api.dto import (
    ActionDTO,
    CountsDTO,
    GateDTO,
    PublishSummaryDTO,
    PulseDTO,
    QuoteDTO,
    RunDetailDTO,
    RunSummaryDTO,
    StageDTO,
    ThemeDetailDTO,
    ThemeDTO,
    WindowDTO,
)
from reviewpulse.models import ActionIdea, PulseNote, Quote, Theme
from reviewpulse.publish.base import email_subject, idempotency_key
from reviewpulse.pulse.validate import GATE_NAMES
from reviewpulse.store.sqlite import ReviewStore

PULSE_GATES = GATE_NAMES


def list_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    dirs = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    dirs.sort(key=lambda path: path.name, reverse=True)
    return dirs


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_manifest(run_dir: Path) -> dict[str, Any]:
    return load_json(run_dir / "manifest.json")


def resolve_run_dir(runs_dir: Path, run_id: str | None) -> Path | None:
    dirs = list_run_dirs(runs_dir)
    if not dirs:
        return None
    if run_id:
        match = next((path for path in dirs if path.name == run_id), None)
        if match is None:
            return None
        return match
    return latest_successful(dirs) or dirs[0]


def latest_successful(dirs: list[Path]) -> Path | None:
    for path in dirs:
        manifest = load_manifest(path)
        if _all_pulse_gates_passed(manifest) and not _is_rejected(path, manifest):
            return path
    for path in dirs:
        if "pulse" in (load_manifest(path).get("stages") or []):
            return path
    return None


def _is_rejected(run_dir: Path, manifest: dict[str, Any] | None = None) -> bool:
    if (run_dir / "note.rejected.md").is_file() and not (run_dir / "note.md").is_file():
        return True
    manifest = manifest or load_manifest(run_dir)
    return not _all_pulse_gates_passed(manifest) and bool(manifest.get("gates"))


def _all_pulse_gates_passed(manifest: dict[str, Any]) -> bool:
    gates = _gate_map(manifest)
    if not gates:
        return False
    return all(gates.get(name, False) for name in PULSE_GATES)


def _gate_map(manifest: dict[str, Any]) -> dict[str, bool]:
    gates = manifest.get("gates")
    if isinstance(gates, list) and gates:
        return {
            str(item.get("gate")): bool(item.get("passed"))
            for item in gates
            if isinstance(item, dict) and item.get("gate")
        }
    checks = manifest.get("checks")
    if isinstance(checks, dict):
        return {str(key): bool(value) for key, value in checks.items()}
    return {}


def window_dto(manifest: dict[str, Any], *, weeks_fallback: int = 12) -> WindowDTO:
    window = manifest.get("window") or {}
    weeks = int(manifest.get("window_weeks") or weeks_fallback)
    return WindowDTO(
        weeks=weeks,
        requested_start=window.get("requested_start"),
        requested_end=window.get("requested_end"),
        actual_start=window.get("actual_start"),
        actual_end=window.get("actual_end"),
        actual_weeks=window.get("actual_weeks"),
    )


def iso_week_of(manifest: dict[str, Any]) -> str | None:
    publish = manifest.get("publish") or {}
    key = str(publish.get("idempotency_key") or "")
    if ":" in key:
        return key.split(":", 1)[1]
    window = manifest.get("window") or {}
    end = window.get("actual_end") or window.get("requested_end")
    if not end:
        return None
    try:
        parsed = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def counts_dto(manifest: dict[str, Any]) -> CountsDTO:
    counts = manifest.get("counts") or {}
    themes = manifest.get("themes") or []
    negative = 0
    for theme in themes:
        if isinstance(theme, dict):
            negative += int(round(float(theme.get("size") or 0) * float(theme.get("neg_share") or 0)))
    return CountsDTO(
        window_reviews=int(counts.get("window_reviews") or 0),
        clustered=int(counts.get("clustered") or 0),
        dropped_low_signal=int(counts.get("dropped_low_signal") or 0),
        themes=int(counts.get("themes") or len(themes)),
        negative=negative,
    )


def publish_mode(manifest: dict[str, Any], publish_file: dict[str, Any] | None = None) -> str:
    gates = manifest.get("gates") or []
    gates_ok = True
    if isinstance(gates, list) and gates:
        gates_ok = all(item.get("passed") for item in gates if isinstance(item, dict))
    blob = publish_file or {}
    draft = blob.get("draft") or {}
    publish = manifest.get("publish") or {}
    if draft.get("sent") or publish.get("message_id") or blob.get("message_id") or draft.get("message_id"):
        return "sent"
    if not gates_ok and not publish.get("published"):
        return "gated"
    mode = str(publish.get("mode") or blob.get("mode") or "")
    if mode == "dry_run":
        return "dry-run"
    if publish.get("draft_id") or draft.get("draft_id"):
        return "draft"
    if mode == "mcp":
        return "draft"
    return mode or "none"


def publish_summary(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    state_entry: dict[str, Any] | None = None,
    recipient: str = "",
) -> PublishSummaryDTO:
    blob = load_json(run_dir / "publish.json")
    publish = manifest.get("publish") or {}
    draft = blob.get("draft") or {}
    doc = blob.get("doc") or {}
    key = publish.get("idempotency_key") or blob.get("idempotency_key")
    state_entry = state_entry or {}
    doc_id = (
        publish.get("doc_id")
        or doc.get("doc_id")
        or state_entry.get("doc_id")
    )
    doc_url = (
        publish.get("doc_url")
        or doc.get("url")
        or state_entry.get("doc_url")
    )
    draft_id = (
        publish.get("draft_id")
        or draft.get("draft_id")
        or state_entry.get("draft_id")
    )
    message_id = (
        publish.get("message_id")
        or draft.get("message_id")
        or state_entry.get("message_id")
    )
    skipped_append = bool(doc_id and state_entry.get("doc_id") == doc_id)
    skipped_send = bool(draft.get("skipped") or (message_id and state_entry.get("message_id")))
    return PublishSummaryDTO(
        mode=publish_mode(manifest, blob),
        published=bool(publish.get("published") or blob.get("published")),
        idempotency_key=key,
        doc_id=doc_id,
        doc_url=doc_url,
        draft_id=draft_id,
        message_id=message_id,
        recipient=draft.get("recipient") or recipient or None,
        skipped_append=skipped_append,
        skipped_send=bool(skipped_send and message_id),
        subject=email_subject(key) if key else None,
    )


def _theme_dto(raw: dict[str, Any], *, in_note: bool, extra: dict[str, Any] | None = None) -> ThemeDTO:
    extra = extra or {}
    return ThemeDTO(
        theme_id=str(raw.get("theme_id") or extra.get("theme_id") or ""),
        rank=int(raw.get("rank") or extra.get("rank") or 0),
        label=str(raw.get("label") or ""),
        summary=str(raw.get("summary") or extra.get("summary") or ""),
        line=raw.get("line"),
        size=int(raw.get("size") or 0),
        mean_rating=raw.get("mean_rating"),
        neg_share=float(raw.get("neg_share") or 0),
        priority=float(raw.get("priority") or 0),
        trend=raw.get("trend"),
        emerging=bool(raw.get("emerging")),
        in_note=in_note,
        keywords=list(raw.get("keywords") or extra.get("keywords") or []),
        top_terms=list(extra.get("top_terms") or raw.get("top_terms") or []),
        label_source=raw.get("label_source") or extra.get("label_source"),
    )


def clusters_by_id(run_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(run_dir / "clusters.json")
    themes = payload.get("themes") or []
    return {
        str(item["theme_id"]): item
        for item in themes
        if isinstance(item, dict) and item.get("theme_id")
    }


def debug_by_rank(run_dir: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(run_dir / "cluster_debug.json")
    clusters = payload.get("clusters") or []
    return {
        int(item["rank"]): item
        for item in clusters
        if isinstance(item, dict) and item.get("rank") is not None
    }


def membership(run_dir: Path) -> dict[str, tuple[str, str]]:
    """review_id → (theme_id, label)."""
    mapping: dict[str, tuple[str, str]] = {}
    for theme_id, theme in clusters_by_id(run_dir).items():
        label = str(theme.get("label") or theme_id)
        for review_id in theme.get("review_ids") or []:
            mapping[str(review_id)] = (theme_id, label)
    return mapping


def themes_for_run(run_dir: Path, manifest: dict[str, Any] | None = None) -> list[ThemeDTO]:
    manifest = manifest or load_manifest(run_dir)
    clustered = clusters_by_id(run_dir)
    debug = debug_by_rank(run_dir)
    pulse = manifest.get("pulse") or {}
    in_note = {
        str(item.get("theme_id"))
        for item in (pulse.get("top_themes") or [])
        if isinstance(item, dict)
    }
    source = clustered.values() or (manifest.get("themes") or [])
    themes: list[ThemeDTO] = []
    for raw in source:
        if not isinstance(raw, dict):
            continue
        rank = int(raw.get("rank") or 0)
        extra = debug.get(rank) or {}
        clustered_row = clustered.get(str(raw.get("theme_id")), {})
        merged = {**raw, **clustered_row}
        theme_id = str(merged.get("theme_id") or "")
        themes.append(
            _theme_dto(
                merged,
                in_note=theme_id in in_note or int(merged.get("rank") or 0) <= 3,
                extra=extra,
            )
        )
    themes.sort(key=lambda item: item.rank)
    return themes


def pulse_dto(
    run_dir: Path,
    *,
    recipient: str = "",
    state_entry: dict[str, Any] | None = None,
    weeks_fallback: int = 12,
) -> PulseDTO:
    manifest = load_manifest(run_dir)
    pulse = manifest.get("pulse") or {}
    counts = counts_dto(manifest)
    gate_items = []
    gate_lookup = {item.get("gate"): item for item in (manifest.get("gates") or []) if isinstance(item, dict)}
    for name in PULSE_GATES:
        row = gate_lookup.get(name) or {}
        passed = bool(row.get("passed", _gate_map(manifest).get(name, False)))
        detail = str(row.get("detail") or "")
        if name == "word_count" and pulse.get("word_count") is not None:
            detail = detail or f"{pulse.get('word_count')}/{pulse.get('max_words', 250)}"
        gate_items.append(GateDTO(gate=name, passed=passed, detail=detail))
    passed_n = sum(1 for item in gate_items if item.passed)
    quotes = [
        QuoteDTO(
            review_id=str(item.get("review_id") or ""),
            theme_id=str(item.get("theme_id") or ""),
            text=str(item.get("text") or ""),
            rating=item.get("rating"),
            words=item.get("words"),
        )
        for item in (pulse.get("quotes") or [])
        if isinstance(item, dict)
    ]
    actions = [
        ActionDTO(
            text=str(item.get("text") or ""),
            theme_ids=[str(tid) for tid in (item.get("theme_ids") or [])],
        )
        for item in (pulse.get("actions") or [])
        if isinstance(item, dict)
    ]
    top = []
    clustered = clusters_by_id(run_dir)
    debug = debug_by_rank(run_dir)
    for item in pulse.get("top_themes") or []:
        if not isinstance(item, dict):
            continue
        extra = clustered.get(str(item.get("theme_id")), {})
        rank_debug = debug.get(int(item.get("rank") or extra.get("rank") or 0), {})
        top.append(_theme_dto({**extra, **item}, in_note=True, extra=rank_debug))
    rejected = _is_rejected(run_dir, manifest)
    note_ok = (run_dir / "note.md").is_file()
    clustering = manifest.get("clustering") or {}
    return PulseDTO(
        run_id=run_dir.name,
        iso_week=iso_week_of(manifest),
        window=window_dto(manifest, weeks_fallback=weeks_fallback),
        counts=counts,
        mean_rating=pulse.get("mean_rating"),
        word_count=int(pulse.get("word_count") or 0),
        max_words=int(pulse.get("max_words") or 250),
        compose_source=pulse.get("compose_source"),
        compose_provider=pulse.get("compose_provider"),
        compose_model=pulse.get("compose_model"),
        top_themes=top,
        quotes=quotes,
        actions=actions,
        gates=gate_items,
        gates_passed=passed_n,
        gates_total=len(PULSE_GATES),
        all_gates_passed=passed_n == len(PULSE_GATES) and not rejected,
        rejected=rejected,
        publish=publish_summary(run_dir, manifest, state_entry=state_entry, recipient=recipient),
        stages=_stages(manifest, clustering),
        note_available=note_ok,
        clustering={
            "mode": clustering.get("mode"),
            "strategy": clustering.get("strategy") or clustering.get("linkage"),
            "embedding_model": clustering.get("embedding_model"),
            "linkage": clustering.get("linkage"),
        },
    )


def _stages(manifest: dict[str, Any], clustering: dict[str, Any]) -> list[StageDTO]:
    counts = manifest.get("counts") or {}
    pulse = manifest.get("pulse") or {}
    ingest = manifest.get("ingest") or {}
    fetch = manifest.get("fetch") or {}
    downloaded = fetch.get("fetched_count") or ingest.get("parsed_count")
    stages_present = set(manifest.get("stages") or [])
    passed = _all_pulse_gates_passed(manifest)
    publish = manifest.get("publish") or {}

    def status_for(done: bool) -> str:
        return "ok" if done else "idle"

    return [
        StageDTO(
            id="fetch",
            label="Fetch Play reviews",
            status=status_for(bool(downloaded) or "ingest" in stages_present or bool(counts)),
            detail=f"{downloaded} downloaded" if downloaded else "SQLite window already populated",
        ),
        StageDTO(
            id="ingest",
            label="Ingest & cleanse",
            status=status_for(bool(counts.get("window_reviews"))),
            detail=(
                f"{counts.get('window_reviews', 0)} in window · "
                f"{counts.get('dropped_low_signal', 0)} low-signal dropped · SQLite"
            ),
        ),
        StageDTO(
            id="cluster",
            label="Cluster",
            status=status_for("cluster" in stages_present or bool(counts.get("themes"))),
            detail=(
                f"{counts.get('clustered', 0)} clustered · "
                f"{clustering.get('linkage') or clustering.get('strategy') or 'ward'} · "
                f"{clustering.get('embedding_model') or 'MiniLM'}"
            ),
        ),
        StageDTO(
            id="pulse",
            label="Pulse synthesis",
            status=status_for("pulse" in stages_present or bool(pulse)),
            detail=(
                f"{pulse.get('word_count', 0)} words · "
                f"{pulse.get('compose_provider') or pulse.get('compose_source') or 'heuristic'}"
            ),
        ),
        StageDTO(
            id="validate",
            label="Validate",
            status="ok" if passed else ("failed" if manifest.get("gates") else "idle"),
            detail="7/7 gates" if passed else "gates pending or failed",
        ),
        StageDTO(
            id="publish",
            label="Publish & dispatch",
            status=status_for(bool(publish)),
            detail=str(publish.get("mode") or "not published"),
        ),
    ]


def theme_detail(run_dir: Path, theme_id: str, store: ReviewStore) -> ThemeDetailDTO | None:
    manifest = load_manifest(run_dir)
    themes = themes_for_run(run_dir, manifest)
    theme = next((item for item in themes if item.theme_id == theme_id), None)
    if theme is None:
        return None
    clustered = clusters_by_id(run_dir).get(theme_id) or {}
    review_ids = [str(rid) for rid in (clustered.get("review_ids") or [])]
    histogram = {int(k): int(v) for k, v in store.rating_histogram(review_ids).items()}
    pulse = manifest.get("pulse") or {}
    in_note = theme_id in {
        str(item.get("theme_id"))
        for item in (pulse.get("top_themes") or [])
        if isinstance(item, dict)
    }
    return ThemeDetailDTO(
        run_id=run_dir.name,
        theme=theme,
        rating_histogram=histogram,
        member_count=len(review_ids) or theme.size,
        in_note=in_note or theme.in_note,
    )


def run_summary(
    run_dir: Path,
    *,
    current_id: str | None = None,
    weeks_fallback: int = 12,
) -> RunSummaryDTO:
    manifest = load_manifest(run_dir)
    pulse = manifest.get("pulse") or {}
    artifacts = []
    for name in ("note.md", "note.rejected.md", "manifest.json", "clusters.json", "publish.json"):
        if (run_dir / name).is_file():
            artifacts.append(name)
    return RunSummaryDTO(
        run_id=run_dir.name,
        iso_week=iso_week_of(manifest),
        timestamp=manifest.get("timestamp"),
        window=window_dto(manifest, weeks_fallback=weeks_fallback),
        counts=counts_dto(manifest),
        word_count=pulse.get("word_count"),
        theme_count=counts_dto(manifest).themes,
        gates_passed=_all_pulse_gates_passed(manifest),
        rejected=_is_rejected(run_dir, manifest),
        publish_mode=publish_mode(manifest, load_json(run_dir / "publish.json")),
        artifacts=artifacts,
        current=run_dir.name == current_id,
    )


def run_detail(
    run_dir: Path,
    *,
    recipient: str = "",
    state_entry: dict[str, Any] | None = None,
    weeks_fallback: int = 12,
) -> RunDetailDTO:
    manifest = load_manifest(run_dir)
    note_path = run_dir / "note.md"
    rejected_path = run_dir / "note.rejected.md"
    preview = None
    if note_path.is_file():
        preview = note_path.read_text(encoding="utf-8")[:4000]
    elif rejected_path.is_file():
        preview = rejected_path.read_text(encoding="utf-8")[:4000]
    return RunDetailDTO(
        summary=run_summary(run_dir, current_id=run_dir.name, weeks_fallback=weeks_fallback),
        note_preview=preview,
        rejected=_is_rejected(run_dir, manifest),
        manifest_checks=manifest.get("checks") or {},
        publish=publish_summary(
            run_dir, manifest, state_entry=state_entry, recipient=recipient
        ),
    )


def note_path_for(run_dir: Path) -> Path | None:
    note = run_dir / "note.md"
    if note.is_file():
        return note
    rejected = run_dir / "note.rejected.md"
    if rejected.is_file():
        return rejected
    return None


def pulse_note_from_run(run_dir: Path, rendered: str) -> PulseNote:
    """Rebuild a PulseNote so MCP publish helpers can run on an existing artifact."""
    manifest = load_manifest(run_dir)
    pulse = manifest.get("pulse") or {}
    window = manifest.get("window") or {}
    clustered = clusters_by_id(run_dir)
    top_themes: list[Theme] = []
    for item in pulse.get("top_themes") or []:
        if not isinstance(item, dict):
            continue
        extra = clustered.get(str(item.get("theme_id")), {})
        top_themes.append(
            Theme(
                theme_id=str(item.get("theme_id")),
                label=str(item.get("label") or extra.get("label") or item.get("theme_id")),
                summary=str(extra.get("summary") or item.get("line") or ""),
                review_ids=[str(rid) for rid in (extra.get("review_ids") or [])],
                size=int(item.get("size") or extra.get("size") or 0),
                mean_rating=item.get("mean_rating"),
                rank=int(item.get("rank") or 0),
                neg_share=float(item.get("neg_share") or extra.get("neg_share") or 0),
                priority=float(item.get("priority") or extra.get("priority") or 0),
                trend=item.get("trend"),
                emerging=bool(item.get("emerging")),
            )
        )
    quotes = [
        Quote(
            review_id=str(item.get("review_id")),
            theme_id=str(item.get("theme_id")),
            text=str(item.get("text") or ""),
            rating=item.get("rating"),
        )
        for item in (pulse.get("quotes") or [])
        if isinstance(item, dict)
    ]
    actions = [
        ActionIdea(
            text=str(item.get("text") or ""),
            theme_ids=[str(tid) for tid in (item.get("theme_ids") or [])],
        )
        for item in (pulse.get("actions") or [])
        if isinstance(item, dict)
    ]
    start = date.fromisoformat(str(window.get("actual_start") or window.get("requested_start")))
    end = date.fromisoformat(str(window.get("actual_end") or window.get("requested_end")))
    return PulseNote(
        run_id=run_dir.name,
        window_start=start,
        window_end=end,
        review_count=int((manifest.get("counts") or {}).get("clustered") or 0),
        top_themes=top_themes,
        quotes=quotes,
        actions=actions,
        word_count=int(pulse.get("word_count") or 0),
        mean_rating=pulse.get("mean_rating"),
        theme_count=int((manifest.get("counts") or {}).get("themes") or len(top_themes)),
        compose_source=pulse.get("compose_source") or "heuristic",
    )


def key_for_run(run_dir: Path) -> str:
    manifest = load_manifest(run_dir)
    publish = manifest.get("publish") or {}
    if publish.get("idempotency_key"):
        return str(publish["idempotency_key"])
    window = manifest.get("window") or {}
    end = window.get("actual_end") or window.get("requested_end")
    if end:
        return idempotency_key(date.fromisoformat(str(end)[:10]))
    return idempotency_key(datetime.now().date())
