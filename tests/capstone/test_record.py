"""Record a reviewed desk case into the log without publishing it."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from capstone.log import LogStore
from capstone.record import record_case
from supportdesk.contracts import (
    AnalysisWindow,
    ComplianceResult,
    CustomerReply,
    FactClaim,
    FactsResult,
    OrchestratorResult,
    PatternEvidence,
    PatternResult,
    ReviewerFinding,
    ReviewerResult,
    RoutingNote,
    SanitizedRequest,
    WorkflowRun,
)
from supportdesk.decisions import DeskCase
from supportdesk.enums import (
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    PatternSignal,
    PatternStatus,
    Priority,
    ReviewerDecision,
    ReviewerFindingCode,
    WorkflowState,
)
from supportdesk.reviewer import ReviewedCase

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
WEEK = "2026-W36"
WINDOW = AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1))
EXECUTION = "exec_" + "ab" * 16
COVERED_URL = "https://groww.in/help/exit-load"
GAP_URLS = [
    "https://groww.in/help/exit-load",
    "https://groww.in/help/charges",
]
COVERED_TEXT = "What is the exit load?"
GAP_TEXT = "What is the exit load for [phone]?"
REPLY = "Exit load is listed on the scheme page."


def _case_id(number: int) -> str:
    return f"case_{number:032x}"


def _run_id(number: int) -> str:
    return f"run_{number:032x}"


def _request(case_id: str, text: str) -> SanitizedRequest:
    return SanitizedRequest(
        case_id=case_id,
        session_id="sess_" + "cd" * 16,
        text=text,
        input_hash=hashlib.sha256(text.encode()).hexdigest(),
        received_at=CLOCK,
        pii_redacted="[" in text,
    )


def _compliance(*, blocked: bool = False) -> ComplianceResult:
    return ComplianceResult(
        status=ComplianceStatus.SUCCESS,
        pii_detected=blocked,
        pii_categories=["phone"] if blocked else [],
        sanitized=not blocked,
        advice_request_detected=False,
        performance_claim_risk=False,
        decision=ComplianceDecision.BLOCK if blocked else ComplianceDecision.ALLOW,
        safe_handling=(
            "Block the case. Sanitization could not be guaranteed."
            if blocked
            else "No compliance block. Process the message."
        ),
        execution_id=EXECUTION,
    )


def _facts(covered: bool, urls: list[str]) -> FactsResult:
    if covered:
        return FactsResult(
            status=FactsStatus.SUPPORTED,
            coverage=Coverage.COVERED,
            answer_facts=[
                FactClaim(
                    claim="Exit load is listed on the scheme page.",
                    source_title="Exit load",
                    source_url=urls[0],
                    evidence="Exit load is listed on the scheme page.",
                )
            ],
            searched_sources=list(urls),
            execution_id=EXECUTION,
        )
    return FactsResult(
        status=FactsStatus.NOT_COVERED,
        coverage=Coverage.NOT_COVERED,
        searched_sources=list(urls),
        execution_id=EXECUTION,
    )


def _pattern(*, matched: bool) -> PatternResult:
    if matched:
        return PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.RECURRING,
            matching_count=4,
            analysis_window=WINDOW,
            matched_themes=["fees: Fees"],
            evidence=[PatternEvidence(theme_id="fees")],
            method="measured",
            execution_id=EXECUTION,
        )
    return PatternResult(
        status=PatternStatus.INSUFFICIENT_DATA,
        signal=PatternSignal.INSUFFICIENT_DATA,
        matching_count=0,
        analysis_window=AnalysisWindow(),
        matched_themes=["fees: Fees"],
        evidence=[PatternEvidence(theme_id="fees")],
        method="not measured",
        execution_id=EXECUTION,
    )


def _desk_case(
    number: int,
    *,
    covered: bool,
    urls: list[str],
    matched: bool,
    blocked: bool = False,
) -> DeskCase:
    case_id = _case_id(number)
    pattern = _pattern(matched=matched)
    facts = _facts(covered, urls)
    reply = REPLY if covered else "The approved sources do not list that detail."
    return DeskCase(
        run=WorkflowRun(
            run_id=_run_id(number),
            case_id=case_id,
            state=WorkflowState.PENDING_APPROVAL,
        ),
        result=OrchestratorResult(
            case_id=case_id,
            reply=CustomerReply(text=reply, sentence_count=1),
            routing_note=RoutingNote(
                team="support",
                priority=Priority.NORMAL,
                reason="The reviewed draft is ready to record.",
                pattern_signal=pattern.signal,
                matching_count=pattern.matching_count,
                analysis_window=pattern.analysis_window,
                facts_coverage=facts.coverage,
                next_action="Record the sanitized question.",
            ),
            facts=facts,
            pattern=pattern,
            compliance=_compliance(blocked=blocked),
        ),
        reviews=[ReviewerResult(decision=ReviewerDecision.PASS, rework_attempt=0)],
    )


def _store(tmp_path: Path) -> LogStore:
    return LogStore(tmp_path / "capstone.db")


def _table_counts(store: LogStore) -> tuple[int, int, int]:
    connection = sqlite3.connect(store.db_path)
    try:
        counts = []
        for table in ("question_log", "not_covered_ledger", "desk_cases"):
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts.append(int(row[0]))
        return counts[0], counts[1], counts[2]
    finally:
        connection.close()


def test_covered_case_writes_one_log_row_and_the_case_blob(tmp_path: Path) -> None:
    store = _store(tmp_path)
    case = _desk_case(1, covered=True, urls=[COVERED_URL], matched=True)
    outcome = record_case(case, _request(case.run.case_id, COVERED_TEXT), store=store, clock=CLOCK)

    assert outcome.recorded is True
    assert outcome.case_id == case.run.case_id
    assert outcome.week_id == WEEK
    rows = store.list_by_week(WEEK)
    assert len(rows) == 1
    assert rows[0].sanitized_text == COVERED_TEXT
    assert rows[0].facts_coverage == "covered"
    assert rows[0].searched_urls == [COVERED_URL]
    assert rows[0].theme_id == "fees"
    assert rows[0].question_key == "what is the exit load"
    assert store.fetch_ledger(case.run.case_id) is None
    stored = store.fetch_case(case.run.case_id)
    assert stored is not None
    assert stored["result"]["reply"]["text"] == REPLY
    assert stored["result"]["pattern"]["signal"] == "recurring"
    assert stored["result"]["pattern"]["matching_count"] == 4
    assert stored["result"]["pattern"]["analysis_window"]["start"] == "2026-06-01"
    assert stored["result"]["pattern"]["analysis_window"]["end"] == "2026-09-01"


def test_not_covered_case_copies_the_facts_urls_and_skips_a_weak_theme(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    case = _desk_case(2, covered=False, urls=GAP_URLS, matched=False)
    outcome = record_case(case, _request(case.run.case_id, GAP_TEXT), store=store, clock=CLOCK)

    assert outcome.recorded is True
    row = store.fetch(case.run.case_id)
    ledger = store.fetch_ledger(case.run.case_id)
    assert row is not None and ledger is not None
    assert row.facts_coverage == "not_covered"
    assert row.searched_urls == GAP_URLS
    assert row.theme_id is None
    assert ledger.searched_urls == GAP_URLS
    assert ledger.sanitized_text == GAP_TEXT
    assert ledger.theme_id is None
    assert "[phone]" in row.sanitized_text
    assert "phone" not in row.question_key


def test_blocked_redaction_leaves_all_three_tables_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    kept = _desk_case(3, covered=True, urls=[COVERED_URL], matched=True)
    record_case(kept, _request(kept.run.case_id, COVERED_TEXT), store=store, clock=CLOCK)
    before = _table_counts(store)
    blocked = ReviewedCase(
        run=WorkflowRun(
            run_id=_run_id(4),
            case_id=_case_id(4),
            state=WorkflowState.BLOCKED,
        ),
        result=None,
        states=[WorkflowState.BLOCKED],
        reviews=[
            ReviewerResult(
                decision=ReviewerDecision.FAIL,
                findings=[
                    ReviewerFinding(
                        code=ReviewerFindingCode.PII,
                        message="Sanitization could not be guaranteed.",
                        repairable=False,
                    )
                ],
                rework_attempt=0,
            )
        ],
    )
    outcome = record_case(blocked, None, store=store, clock=CLOCK)
    flagged = _desk_case(5, covered=True, urls=[COVERED_URL], matched=True, blocked=True)

    assert outcome.recorded is False
    assert record_case(
        flagged,
        _request(flagged.run.case_id, "What is the exit load for [phone]?"),
        store=store,
        clock=CLOCK,
    ).recorded is False
    assert _table_counts(store) == before
    assert store.fetch(_case_id(4)) is None
    assert store.fetch(_case_id(5)) is None
    assert store.fetch_case(_case_id(4)) is None
    assert store.fetch_case(_case_id(5)) is None


def test_raw_phone_or_pan_is_not_stored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    case = _desk_case(6, covered=True, urls=[COVERED_URL], matched=True)
    phone = record_case(
        case,
        _request(case.run.case_id, "What is the exit load for 9876543210?"),
        store=store,
        clock=CLOCK,
    )
    pan = record_case(
        case,
        _request(case.run.case_id, "What is the exit load for ABCDE1234F?"),
        store=store,
        clock=CLOCK,
    )

    assert phone.recorded is False
    assert pan.recorded is False
    assert _table_counts(store) == (0, 0, 0)


def test_record_case_does_not_call_publish_case() -> None:
    source = Path(record_case.__code__.co_filename).read_text(encoding="utf-8")
    assert "publish_case" not in source
    assert "orchestrate(" not in source
