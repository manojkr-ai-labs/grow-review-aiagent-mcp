"""FastAPI application for the ReviewPulse operator console (Phase 7)."""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from reviewpulse import __version__
from reviewpulse.api.catalog import (
    key_for_run,
    list_run_dirs,
    load_manifest,
    membership,
    note_path_for,
    pulse_dto,
    pulse_note_from_run,
    publish_summary,
    resolve_run_dir,
    run_detail,
    run_summary,
    theme_detail,
    themes_for_run,
    window_dto,
)
from reviewpulse.api.context import ApiContext, get_context, reset_default_context
from reviewpulse.api.dto import (
    JobDTO,
    McpStatusDTO,
    PipelineRunRequest,
    PublishActionRequest,
    PublishActionResult,
    PublishSummaryDTO,
    PulseDTO,
    ReviewDTO,
    ReviewListDTO,
    RunDetailDTO,
    RunSummaryDTO,
    SettingsDTO,
    SettingsPatch,
    StatusDTO,
    ThemeDTO,
    ThemeDetailDTO,
)
from reviewpulse.api.cors import cors_origins
from reviewpulse.api.jobs import JOBS, LockHeldError
from reviewpulse.api.settings import apply_settings_patch, settings_dto
from reviewpulse.config import google_doc_url
from reviewpulse.mcp.client import MCPError, inspect_publish_servers
from reviewpulse.publish.base import DocRef
from reviewpulse.publish.mcp import build_mcp_publisher
from reviewpulse.publish.state import load_state, record_for
from reviewpulse.schedule.lock import lock_is_held

_mcp_cache: tuple[float, McpStatusDTO] = (0.0, McpStatusDTO(ok=False, label="UNKNOWN"))
_mcp_lock = threading.Lock()
_mcp_inflight = False
MCP_TTL = 15.0

app = FastAPI(title="ReviewPulse Console API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _job_dto(job) -> JobDTO:
    return JobDTO(
        job_id=job.job_id,
        status=job.status,
        dry_run=job.dry_run,
        send=job.send,
        window_weeks=job.window_weeks,
        error=job.error,
        run_id=job.run_id,
        started_at=job.started_at,
        finished_at=job.finished_at,
        log_lines=len(job.logs),
    )


def _probe_mcp(ctx: ApiContext) -> McpStatusDTO:
    global _mcp_cache, _mcp_inflight
    settings = ctx.settings.mcp
    try:
        if not settings.url and not settings.gdocs.configured and not settings.gmail.configured:
            result = McpStatusDTO(ok=False, label="UNREACHABLE", detail="MCP not configured")
        else:
            try:
                info = inspect_publish_servers(settings)
                result = McpStatusDTO(
                    ok=True,
                    label="CONNECTED",
                    url=info.get("url") or settings.url,
                    document_id=info.get("document_id") or settings.gdocs.document_id,
                    cached=False,
                )
            except MCPError as exc:
                result = McpStatusDTO(ok=False, label="UNREACHABLE", detail=str(exc))
            except Exception as exc:
                result = McpStatusDTO(ok=False, label="UNREACHABLE", detail=str(exc))
        _mcp_cache = (time.monotonic(), result)
        return result
    finally:
        with _mcp_lock:
            _mcp_inflight = False


def _mcp_status(ctx: ApiContext, *, force: bool = False) -> McpStatusDTO:
    global _mcp_inflight
    now = time.monotonic()
    cached_at, cached = _mcp_cache
    fresh = now - cached_at < MCP_TTL and cached.label not in {"UNKNOWN", "CHECKING"}
    if not force and fresh:
        cached.cached = True
        return cached
    if force:
        with _mcp_lock:
            _mcp_inflight = True
        return _probe_mcp(ctx)
    with _mcp_lock:
        if not _mcp_inflight:
            _mcp_inflight = True
            threading.Thread(target=_probe_mcp, args=(ctx,), name="reviewpulse-mcp-ping", daemon=True).start()
    if cached.label not in {"UNKNOWN", "CHECKING"}:
        cached.cached = True
        return cached
    return McpStatusDTO(ok=False, label="CHECKING", detail="MCP ping in progress", cached=True)


def _state_entry(ctx: ApiContext, run_dir) -> dict[str, Any]:
    if run_dir is None:
        return {}
    key = key_for_run(run_dir)
    return record_for(ctx.publish_state_path, key)


def _require_run(ctx: ApiContext, run_id: str | None):
    run_dir = resolve_run_dir(ctx.runs_dir, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="no runs found")
    return run_dir


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {"ok": True, "name": "reviewpulse-console", "version": __version__}


@app.get("/api/v1/status", response_model=StatusDTO)
def status(ctx: ApiContext = Depends(get_context)) -> StatusDTO:
    latest = resolve_run_dir(ctx.runs_dir, None)
    manifest = load_manifest(latest) if latest else {}
    store_count = 0
    try:
        store_count = ctx.store().count()
    except Exception:
        store_count = 0
    running = JOBS.current_running()
    return StatusDTO(
        package_id=ctx.settings.package_id,
        operator_initials=ctx.settings.console.operator_initials,
        iso_week=None if not latest else __iso(latest, manifest),
        last_run_id=None if latest is None else latest.name,
        last_run_at=manifest.get("timestamp"),
        window=window_dto(manifest, weeks_fallback=ctx.settings.default_window_weeks) if manifest else None,
        mcp=_mcp_status(ctx),
        lock_held=lock_is_held(
            ctx.lock_path,
            timeout_minutes=ctx.settings.schedule.lock_timeout_minutes,
        ),
        store_count=store_count,
        pipeline=_job_dto(running) if running else None,
    )


def __iso(run_dir, manifest: dict[str, Any]) -> str | None:
    from reviewpulse.api.catalog import iso_week_of

    return iso_week_of(manifest)


@app.get("/api/v1/pulse", response_model=PulseDTO)
def pulse(run_id: str | None = None, ctx: ApiContext = Depends(get_context)) -> PulseDTO:
    run_dir = _require_run(ctx, run_id)
    return pulse_dto(
        run_dir,
        recipient=ctx.settings.pulse.recipient_alias,
        state_entry=_state_entry(ctx, run_dir),
        weeks_fallback=ctx.settings.default_window_weeks,
    )


@app.get("/api/v1/themes", response_model=list[ThemeDTO])
def themes(run_id: str | None = None, ctx: ApiContext = Depends(get_context)) -> list[ThemeDTO]:
    run_dir = _require_run(ctx, run_id)
    return themes_for_run(run_dir)


@app.get("/api/v1/themes/{theme_id}", response_model=ThemeDetailDTO)
def theme(
    theme_id: str,
    run_id: str | None = None,
    ctx: ApiContext = Depends(get_context),
) -> ThemeDetailDTO:
    run_dir = _require_run(ctx, run_id)
    detail = theme_detail(run_dir, theme_id, ctx.store())
    if detail is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return detail


@app.get("/api/v1/reviews", response_model=ReviewListDTO)
def reviews(
    q: str | None = None,
    rating: int | None = Query(default=None, ge=1, le=5),
    theme_id: str | None = None,
    scrubbed: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    run_id: str | None = None,
    ctx: ApiContext = Depends(get_context),
) -> ReviewListDTO:
    run_dir = resolve_run_dir(ctx.runs_dir, run_id)
    window_start = window_end = None
    counts_window = clustered = dropped = 0
    flag_counts: dict[str, int] = {}
    member: dict[str, tuple[str, str]] = {}
    review_ids = None
    if run_dir is not None:
        manifest = load_manifest(run_dir)
        window = manifest.get("window") or {}
        try:
            if window.get("actual_start"):
                window_start = date.fromisoformat(str(window["actual_start"])[:10])
            if window.get("actual_end"):
                window_end = date.fromisoformat(str(window["actual_end"])[:10])
        except ValueError:
            window_start = window_end = None
        counts = manifest.get("counts") or {}
        counts_window = int(counts.get("window_reviews") or 0)
        clustered = int(counts.get("clustered") or 0)
        dropped = int(counts.get("dropped_low_signal") or 0)
        flag_counts = {
            str(k): int(v)
            for k, v in ((manifest.get("pulse") or {}).get("scrub_flags") or {}).items()
        }
        member = membership(run_dir)
        if theme_id:
            from reviewpulse.api.catalog import clusters_by_id

            theme = clusters_by_id(run_dir).get(theme_id)
            if theme is None:
                return ReviewListDTO(
                    items=[],
                    next_cursor=None,
                    total=0,
                    window_reviews=counts_window,
                    clustered=clustered,
                    dropped_low_signal=dropped,
                    scrub_flag_counts=flag_counts,
                )
            review_ids = [str(rid) for rid in (theme.get("review_ids") or [])]
    items, next_cursor, total = ctx.store().query_reviews(
        q=q,
        rating=rating,
        review_ids=review_ids,
        window_start=window_start,
        window_end=window_end,
        scrubbed=scrubbed,
        cursor=cursor,
        limit=limit,
    )
    dto_items = []
    for review in items:
        theme_info = member.get(review.review_id)
        payload = ReviewDTO(
            review_id=review.review_id,
            source=review.source,
            rating=review.rating,
            text_clean=review.text_clean,
            date=review.date.isoformat(),
            lang=review.lang,
            scrub_flags=list(review.scrub_flags),
            theme_id=theme_info[0] if theme_info else None,
            theme_label=theme_info[1] if theme_info else None,
        )
        dto_items.append(payload)
    return ReviewListDTO(
        items=dto_items,
        next_cursor=next_cursor,
        total=total,
        window_reviews=counts_window,
        clustered=clustered,
        dropped_low_signal=dropped,
        scrub_flag_counts=flag_counts,
    )


@app.get("/api/v1/reviews/{review_id}", response_model=ReviewDTO)
def review_one(
    review_id: str,
    run_id: str | None = None,
    ctx: ApiContext = Depends(get_context),
) -> ReviewDTO:
    review = ctx.store().get_by_id(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not found")
    theme_info = None
    run_dir = resolve_run_dir(ctx.runs_dir, run_id)
    if run_dir is not None:
        theme_info = membership(run_dir).get(review.review_id)
    return ReviewDTO(
        review_id=review.review_id,
        source=review.source,
        rating=review.rating,
        text_clean=review.text_clean,
        date=review.date.isoformat(),
        lang=review.lang,
        scrub_flags=list(review.scrub_flags),
        theme_id=theme_info[0] if theme_info else None,
        theme_label=theme_info[1] if theme_info else None,
    )


@app.get("/api/v1/runs", response_model=list[RunSummaryDTO])
def runs(ctx: ApiContext = Depends(get_context)) -> list[RunSummaryDTO]:
    current = resolve_run_dir(ctx.runs_dir, None)
    current_id = current.name if current else None
    return [
        run_summary(
            path,
            current_id=current_id,
            weeks_fallback=ctx.settings.default_window_weeks,
        )
        for path in list_run_dirs(ctx.runs_dir)
    ]


@app.get("/api/v1/runs/{run_id}", response_model=RunDetailDTO)
def run_one(run_id: str, ctx: ApiContext = Depends(get_context)) -> RunDetailDTO:
    run_dir = _require_run(ctx, run_id)
    return run_detail(
        run_dir,
        recipient=ctx.settings.pulse.recipient_alias,
        state_entry=_state_entry(ctx, run_dir),
        weeks_fallback=ctx.settings.default_window_weeks,
    )


@app.get("/api/v1/runs/{run_id}/note")
def run_note(run_id: str, ctx: ApiContext = Depends(get_context)) -> PlainTextResponse:
    run_dir = _require_run(ctx, run_id)
    path = note_path_for(run_dir)
    if path is None:
        raise HTTPException(status_code=404, detail="note not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/api/v1/publish", response_model=PublishSummaryDTO)
def publish_get(run_id: str | None = None, ctx: ApiContext = Depends(get_context)) -> PublishSummaryDTO:
    run_dir = resolve_run_dir(ctx.runs_dir, run_id)
    if run_dir is None:
        state = load_state(ctx.publish_state_path)
        latest_key = next(iter(reversed(list(state.keys()))), None) if state else None
        entry = state.get(latest_key or "", {})
        return PublishSummaryDTO(
            mode="none",
            doc_id=entry.get("doc_id"),
            doc_url=entry.get("doc_url") or google_doc_url(ctx.settings.mcp.gdocs.document_id),
            draft_id=entry.get("draft_id"),
            message_id=entry.get("message_id"),
            recipient=ctx.settings.pulse.recipient_alias or None,
            idempotency_key=latest_key,
        )
    return publish_summary(
        run_dir,
        load_manifest(run_dir),
        state_entry=_state_entry(ctx, run_dir),
        recipient=ctx.settings.pulse.recipient_alias,
    )


@app.get("/api/v1/settings", response_model=SettingsDTO)
def settings_get(ctx: ApiContext = Depends(get_context)) -> SettingsDTO:
    return settings_dto(ctx.settings)


@app.patch("/api/v1/settings", response_model=SettingsDTO)
def settings_patch(patch: SettingsPatch, ctx: ApiContext = Depends(get_context)) -> SettingsDTO:
    try:
        updated = apply_settings_patch(patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reset_default_context()
    ctx.settings = updated
    return settings_dto(updated)


@app.post("/api/v1/mcp/check", response_model=McpStatusDTO)
def mcp_check(ctx: ApiContext = Depends(get_context)) -> McpStatusDTO:
    return _mcp_status(ctx, force=True)


@app.post("/api/v1/pipeline/run", response_model=JobDTO)
def pipeline_run(body: PipelineRunRequest, ctx: ApiContext = Depends(get_context)) -> JobDTO:
    if body.send and body.dry_run:
        raise HTTPException(status_code=400, detail="send and dry_run cannot be combined")
    weeks = body.window_weeks or ctx.settings.default_window_weeks
    if weeks < 1 or weeks > 52:
        raise HTTPException(status_code=400, detail="window_weeks must be 1–52")
    try:
        job = JOBS.start(ctx, window_weeks=weeks, dry_run=body.dry_run, send=body.send)
    except LockHeldError as exc:
        raise HTTPException(status_code=409, detail="lock_held") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _job_dto(job)


@app.get("/api/v1/pipeline/jobs/{job_id}", response_model=JobDTO)
def pipeline_job(job_id: str) -> JobDTO:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dto(job)


@app.get("/api/v1/pipeline/jobs/{job_id}/log")
async def pipeline_log(job_id: str) -> StreamingResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def events():
        import asyncio

        last = 0
        yield ": connected\n\n"
        while True:
            current = JOBS.get(job_id)
            if current is None:
                yield "event: error\ndata: not found\n\n"
                return
            while last < len(current.logs):
                line = current.logs[last]
                last += 1
                yield f"data: {json.dumps(line)}\n\n"
            if current.status in {"succeeded", "failed"}:
                yield f"event: done\ndata: {json.dumps({'status': current.status, 'error': current.error, 'run_id': current.run_id})}\n\n"
                return
            yield ": ping\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _publisher(ctx: ApiContext, run_dir, *, send: bool = False):
    return build_mcp_publisher(ctx.settings, run_dir, state_path=ctx.publish_state_path, send=send)


@app.post("/api/v1/publish/append", response_model=PublishActionResult)
def publish_append(
    body: PublishActionRequest,
    ctx: ApiContext = Depends(get_context),
) -> PublishActionResult:
    run_dir = _require_run(ctx, body.run_id)
    path = note_path_for(run_dir)
    if path is None or path.name == "note.rejected.md":
        raise HTTPException(status_code=409, detail="no passing note to append")
    rendered = path.read_text(encoding="utf-8")
    note = pulse_note_from_run(run_dir, rendered)
    key = key_for_run(run_dir)
    try:
        publisher = _publisher(ctx, run_dir, send=False)
        doc = publisher.publish_doc(note, rendered, key)
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    skipped = doc.doc_id == ctx.settings.mcp.gdocs.document_id and bool(
        record_for(ctx.publish_state_path, key).get("doc_id")
    )
    return PublishActionResult(
        ok=True,
        skipped=skipped,
        detail="append skipped (same ISO week)" if skipped else "appended to notebook",
        publish=publish_summary(
            run_dir,
            load_manifest(run_dir),
            state_entry=record_for(ctx.publish_state_path, key),
            recipient=ctx.settings.pulse.recipient_alias,
        ),
    )


@app.post("/api/v1/publish/draft", response_model=PublishActionResult)
def publish_draft(
    body: PublishActionRequest,
    ctx: ApiContext = Depends(get_context),
) -> PublishActionResult:
    run_dir = _require_run(ctx, body.run_id)
    path = note_path_for(run_dir)
    if path is None or path.name == "note.rejected.md":
        raise HTTPException(status_code=409, detail="no passing note to draft")
    rendered = path.read_text(encoding="utf-8")
    note = pulse_note_from_run(run_dir, rendered)
    key = key_for_run(run_dir)
    state = record_for(ctx.publish_state_path, key)
    doc = DocRef(
        doc_id=state.get("doc_id") or ctx.settings.mcp.gdocs.document_id or f"doc:{key}",
        url=state.get("doc_url") or google_doc_url(ctx.settings.mcp.gdocs.document_id),
    )
    try:
        publisher = _publisher(ctx, run_dir, send=False)
        draft = publisher.create_draft(note, rendered, doc, key)
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PublishActionResult(
        ok=True,
        skipped=False,
        detail=f"draft {draft.draft_id}",
        publish=publish_summary(
            run_dir,
            load_manifest(run_dir),
            state_entry=record_for(ctx.publish_state_path, key),
            recipient=ctx.settings.pulse.recipient_alias,
        ),
    )


@app.post("/api/v1/publish/send", response_model=PublishActionResult)
def publish_send(
    body: PublishActionRequest,
    ctx: ApiContext = Depends(get_context),
) -> PublishActionResult:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm required to send")
    run_dir = _require_run(ctx, body.run_id)
    path = note_path_for(run_dir)
    if path is None or path.name == "note.rejected.md":
        raise HTTPException(status_code=409, detail="no passing note to send")
    rendered = path.read_text(encoding="utf-8")
    note = pulse_note_from_run(run_dir, rendered)
    key = key_for_run(run_dir)
    state = record_for(ctx.publish_state_path, key)
    if state.get("message_id"):
        return PublishActionResult(
            ok=True,
            skipped=True,
            detail="send skipped (message_id already stored for this ISO week)",
            publish=publish_summary(
                run_dir,
                load_manifest(run_dir),
                state_entry=state,
                recipient=ctx.settings.pulse.recipient_alias,
            ),
        )
    doc = DocRef(
        doc_id=state.get("doc_id") or ctx.settings.mcp.gdocs.document_id or f"doc:{key}",
        url=state.get("doc_url") or google_doc_url(ctx.settings.mcp.gdocs.document_id),
    )
    try:
        publisher = _publisher(ctx, run_dir, send=True)
        draft = publisher.create_draft(note, rendered, doc, key)
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PublishActionResult(
        ok=True,
        skipped=bool(draft.skipped),
        detail="sent" if not draft.skipped else "send skipped",
        publish=publish_summary(
            run_dir,
            load_manifest(run_dir),
            state_entry=record_for(ctx.publish_state_path, key),
            recipient=ctx.settings.pulse.recipient_alias,
        ),
    )
