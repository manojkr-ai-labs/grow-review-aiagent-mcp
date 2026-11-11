"""Desk queue, decision, and publish routes.

Questions are sanitized, orchestrated, reviewed, and recorded. Refine and
decision call the desk functions. Publish calls ``publish_case`` only after
the workflow and approval checks. This router does not assemble a package
and has no send switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from capstone.log import LogStore
from capstone.record import record_case
from reviewpulse.mcp.client import ToolClient
from supportdesk.approval import approval_matches
from supportdesk.compliance import ComplianceSession
from supportdesk.decisions import DeskCase, content_digest, decide, refine
from supportdesk.enums import ApprovalDecision, WorkflowState
from supportdesk.facts import Retriever
from supportdesk.ids import new_case_id
from supportdesk.orchestrate import orchestrate
from supportdesk.publish import publish_case
from supportdesk.reviewer import review_case
from supportdesk.workflow import ContractError, assert_mcp_permitted

router = APIRouter(prefix="/api/desk")


class QuestionBody(BaseModel):
    """Operator question. ``citation`` and ``count`` are accepted and ignored."""

    model_config = ConfigDict(extra="ignore")

    text: str
    citation: str | None = None
    count: int | None = None


@dataclass
class DeskDeps:
    """Store and the deterministic desk inputs tests can replace."""

    store: LogStore
    retriever: Retriever | None = None
    clock: datetime | None = None
    run_dir: Path | None = None
    csv_path: Path | None = None
    docs: ToolClient | None = None
    gmail: ToolClient | None = None
    document_id: str = "doc-desk"
    recipient: str = "desk@example.com"
    state_path: Path | None = None


def desk_deps() -> DeskDeps:
    """Default store. Tests override this dependency."""
    return DeskDeps(store=LogStore())


@router.post("/questions")
async def submit_question(
    body: QuestionBody,
    deps: DeskDeps = Depends(desk_deps),
) -> JSONResponse:
    """Sanitize, orchestrate, review, and store the case."""
    case_id = new_case_id()
    session = ComplianceSession()
    inspection = session.inspect(body.text, case_id=case_id, received_at=deps.clock)
    outcome = await orchestrate(
        body.text,
        session=session,
        case_id=case_id,
        retriever=deps.retriever,
        run_dir=deps.run_dir,
        csv_path=deps.csv_path,
    )
    reviewed = review_case(outcome)
    try:
        recorded = record_case(
            reviewed,
            inspection.request,
            store=deps.store,
            clock=deps.clock,
        )
    except (ContractError, ValueError):
        recorded = None
    if recorded is None or not recorded.recorded or recorded.case_id is None:
        if reviewed.run.state is WorkflowState.BLOCKED and reviewed.result is not None:
            blocked = DeskCase(
                run=reviewed.run,
                result=reviewed.result,
                reviews=list(reviewed.reviews),
            )
            deps.store.save_case(
                blocked.model_dump(mode="json"),
                updated_at=_when(deps),
            )
            return JSONResponse(deps.store.fetch_case(reviewed.run.case_id))
        return JSONResponse(
            status_code=422,
            content={"recorded": False, "case": reviewed.model_dump(mode="json")},
        )
    stored = deps.store.fetch_case(recorded.case_id)
    return JSONResponse(stored)


@router.get("/queue")
def queue(deps: DeskDeps = Depends(desk_deps)) -> list[dict[str, object]]:
    """Sanitized queue rows. Pending, blocked, and rejected cases stay listed."""
    rows: list[dict[str, object]] = []
    for case_id in deps.store.list_case_ids():
        log_row = deps.store.fetch(case_id)
        payload = deps.store.fetch_case(case_id)
        if log_row is None or payload is None:
            continue
        rows.append(_queue_row(log_row.sanitized_text, payload, log_row.theme_id))
    return rows


@router.get("/cases/{case_id}")
def case_detail(case_id: str, deps: DeskDeps = Depends(desk_deps)) -> dict[str, object]:
    """Draft, routing note, timings, claims, and reviewer findings."""
    payload = deps.store.fetch_case(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="case not found")
    view = _case_view(payload)
    run = _mapping(payload.get("run"))
    view["state"] = run.get("state")
    view["content_hash"] = run.get("content_hash") or payload.get("accepted_hash")
    view["document_id"] = deps.document_id
    view["recipient"] = deps.recipient
    return view


class RefineBody(BaseModel):
    """One operator instruction. The reply is used when no agent is named."""

    model_config = ConfigDict(extra="forbid")

    instruction: str
    message: str | None = None
    reply: str | None = None


class DecisionBody(BaseModel):
    """Approve or reject the stored hash."""

    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    approver_ref: str


class PublishBody(BaseModel):
    """Publish has no field that can turn sending on."""

    model_config = ConfigDict(extra="forbid")


@router.post("/cases/{case_id}/refine")
def refine_case(
    case_id: str,
    body: RefineBody,
    deps: DeskDeps = Depends(desk_deps),
) -> dict[str, object]:
    """Refine through the desk, then store that version."""
    case = _load_case(deps, case_id)
    try:
        updated = refine(
            case,
            body.instruction,
            message=body.message,
            reply=body.reply,
            retriever=deps.retriever,
            run_dir=deps.run_dir,
            csv_path=deps.csv_path,
        )
    except ContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _save(deps, updated)


@router.post("/cases/{case_id}/decision")
def decide_case(
    case_id: str,
    body: DecisionBody,
    deps: DeskDeps = Depends(desk_deps),
) -> dict[str, object]:
    """Approve or reject the current hash."""
    case = _load_case(deps, case_id)
    try:
        updated = decide(
            case,
            body.decision,
            body.approver_ref,
            decided_at=deps.clock,
        )
    except ContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _save(deps, updated)


@router.post("/cases/{case_id}/publish")
def publish(
    case_id: str,
    body: PublishBody | None = None,
    deps: DeskDeps = Depends(desk_deps),
) -> dict[str, object]:
    """Publish only when the workflow and the current hash both allow it."""
    del body
    case = _load_case(deps, case_id)
    try:
        assert_mcp_permitted(case.run)
        if not approval_matches(case.run.approval, content_digest(case.result)):
            raise ContractError("approval does not match the current reply")
    except ContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if deps.docs is None or deps.gmail is None or deps.state_path is None:
        raise HTTPException(status_code=503, detail="desk publish client is not configured")
    try:
        outcome = publish_case(
            case,
            docs=deps.docs,
            gmail=deps.gmail,
            document_id=deps.document_id,
            recipient=deps.recipient,
            state_path=deps.state_path,
        )
    except ContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    stored = case.model_copy(update={"run": outcome.run})
    _save(deps, stored)
    return outcome.model_dump(mode="json")


def _load_case(deps: DeskDeps, case_id: str) -> DeskCase:
    payload = deps.store.fetch_case(case_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="case not found")
    return DeskCase.model_validate(payload)


def _save(deps: DeskDeps, case: DeskCase) -> dict[str, object]:
    deps.store.save_case(case.model_dump(mode="json"), updated_at=_when(deps))
    stored = deps.store.fetch_case(case.run.case_id)
    return stored or {}


def _when(deps: DeskDeps) -> datetime:
    if deps.clock is not None:
        return deps.clock
    from datetime import timezone

    return datetime.now(timezone.utc)


def _queue_row(
    sanitized_text: str,
    payload: dict[str, object],
    theme_id: str | None,
) -> dict[str, object]:
    result = _mapping(payload.get("result"))
    reply = _mapping(result.get("reply"))
    facts = _mapping(result.get("facts"))
    note = _mapping(result.get("routing_note"))
    pattern = _mapping(result.get("pattern"))
    compliance = _mapping(result.get("compliance"))
    run = _mapping(payload.get("run"))
    coverage = str(facts.get("coverage") or "")
    citations = _strings(note.get("citation_refs"))
    searched = _strings(facts.get("searched_sources"))
    reviews = payload.get("reviews")
    flag = None
    if isinstance(reviews, list) and reviews:
        last = reviews[-1]
        if isinstance(last, dict):
            flag = last.get("decision")
    categories = compliance.get("pii_categories")
    decision = compliance.get("decision")
    count = note.get("matching_count")
    window_start, window_end = _window(note)
    return {
        "case_id": run.get("case_id"),
        "sanitized_text": sanitized_text,
        "draft": None if coverage == "not_covered" else reply.get("text"),
        "not_covered": coverage == "not_covered",
        "citation": citations or searched,
        "reviewer_flag": flag,
        "state": run.get("state"),
        "coverage": coverage,
        "pattern_signal": pattern.get("signal"),
        "matching_count": count if isinstance(count, int) else None,
        "window_start": window_start,
        "window_end": window_end,
        "theme_id": theme_id,
        "compliance_decision": decision if isinstance(decision, str) else None,
        "pii_redacted": bool(compliance.get("pii_detected"))
        or (isinstance(categories, list) and len(categories) > 0),
        "redaction_blocked": decision == "block" and compliance.get("sanitized") is False,
    }


def _case_view(payload: dict[str, object]) -> dict[str, object]:
    result = _mapping(payload.get("result"))
    facts = _mapping(result.get("facts"))
    run = _mapping(payload.get("run"))
    findings: list[object] = []
    reviews = payload.get("reviews")
    if isinstance(reviews, list):
        for review in reviews:
            if not isinstance(review, dict):
                continue
            items = review.get("findings")
            if isinstance(items, list):
                findings.extend(items)
    timings = []
    executions = run.get("executions")
    if isinstance(executions, list):
        for item in executions:
            if not isinstance(item, dict):
                continue
            timings.append(
                {
                    "agent": item.get("agent"),
                    "started_at": item.get("started_at"),
                    "ended_at": item.get("ended_at"),
                }
            )
    return {
        "case_id": run.get("case_id"),
        "draft": result.get("reply"),
        "routing_note": result.get("routing_note"),
        "agent_timings": timings,
        "claims": facts.get("answer_facts") or [],
        "searched_urls": _strings(facts.get("searched_sources")),
        "reviewer_findings": findings,
    }


def _window(note: dict[str, object]) -> tuple[str | None, str | None]:
    window = note.get("analysis_window")
    if not isinstance(window, dict):
        return None, None
    start = window.get("start")
    end = window.get("end")
    return (
        start if isinstance(start, str) else None,
        end if isinstance(end, str) else None,
    )


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
