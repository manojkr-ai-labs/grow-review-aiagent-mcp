"""Five-times queue signals come from the question log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from capstone.contracts import QuestionLogRow
from capstone.identity import question_key
from capstone.log import LogStore
from capstone.signals import (
    queue_signals,
    queue_signals_for_week,
    read_support_signals,
    render_signal,
    write_support_signals,
)

WEEK = "2026-W36"
OTHER_WEEK = "2026-W37"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
QUESTION = "What is the exit load?"
KEY = question_key(QUESTION)
CLUSTERS = {"themes": [{"theme_id": "fees", "member_count": 40}]}
WINDOW = {"start": "2026-06-01", "end": "2026-09-01"}
DRAFT = "Exit load is listed on the scheme page."


def _case_id(number: int) -> str:
    return f"case_{number:032x}"


def _row(
    number: int,
    text: str = QUESTION,
    *,
    theme_id: str | None = "fees",
    week_id: str = WEEK,
) -> QuestionLogRow:
    return QuestionLogRow(
        case_id=_case_id(number),
        week_id=week_id,
        question_key=question_key(text),
        sanitized_text=text,
        facts_coverage="covered",
        searched_urls=[],
        theme_id=theme_id,
        created_at=NOW,
    )


def _pattern_case(
    *,
    signal: str = "recurring",
    matching_count: int = 4,
    window: dict[str, str] | None = None,
    include_pattern: bool = True,
) -> dict[str, object]:
    result: dict[str, object] = {"reply": {"text": DRAFT}}
    if include_pattern:
        result["pattern"] = {
            "signal": signal,
            "matching_count": matching_count,
            "analysis_window": WINDOW if window is None else window,
        }
    return {"result": result}


def _store(tmp_path: Path) -> LogStore:
    return LogStore(tmp_path / "capstone.db")


def test_five_rows_one_key_emit_one_queue_signal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for number in (5, 1, 4, 2, 3):
        store.append(_row(number))
    store.append(_row(9, week_id=OTHER_WEEK))
    signals = queue_signals_for_week(store, WEEK, clusters=CLUSTERS)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.count == 5
    assert signal.question_key == KEY
    assert signal.week_id == WEEK
    assert signal.evidence_type == "queue"
    assert signal.case_ids == [_case_id(number) for number in range(1, 6)]
    assert signal.theme_id == "fees"
    assert signal.pattern_signal is None
    text = render_signal(signal)
    assert KEY in text
    assert "5" in text
    assert WEEK in text
    assert "question log" in text
    assert text == (
        f'Support was asked "{KEY}" 5 times in {WEEK}. '
        "This line is the question log, not review volume."
    )


def test_four_rows_emit_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for number in range(1, 5):
        store.append(_row(number))
    assert queue_signals_for_week(store, WEEK, clusters=CLUSTERS) == []


def test_empty_keys_are_excluded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for number in range(1, 6):
        store.append(_row(number, "???", theme_id=None))
    for number in range(6, 10):
        store.append(_row(number))
    assert queue_signals_for_week(store, WEEK) == []


def test_mixed_theme_ids_stay_null() -> None:
    rows = [_row(number, theme_id="fees" if number < 5 else "kyc") for number in range(1, 6)]
    signal = queue_signals(rows)[0]
    assert signal.count == 5
    assert signal.theme_id is None


def test_signal_file_round_trip_uses_the_contract_model(tmp_path: Path) -> None:
    rows = [_row(number) for number in range(1, 6)]
    signals = queue_signals(rows, clusters=CLUSTERS)
    run_dir = tmp_path / "runs" / "run_ab" 
    note = run_dir / "note.md"
    run_dir.mkdir(parents=True)
    original = "The weekly note stays 250 words.\n"
    note.write_text(original, encoding="utf-8")

    path = write_support_signals(run_dir, signals)
    empty_dir = tmp_path / "runs" / "empty"
    empty_path = write_support_signals(empty_dir, [])

    assert path.name == "support_signals.json"
    assert read_support_signals(path) == signals
    assert json.loads(empty_path.read_text(encoding="utf-8")) == []
    assert note.read_text(encoding="utf-8") == original
    assert queue_signals([], clusters=CLUSTERS) == []


def test_shared_pattern_fields_are_copied_and_the_draft_stays(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rows = [_row(number) for number in range(1, 6)]
    for row in rows:
        store.append(row)
        store.save_case(_desk_payload(row.case_id), updated_at=NOW)
    before = {row.case_id: store.fetch_case(row.case_id) for row in rows}

    signals = queue_signals_for_week(store, WEEK)
    signal = signals[0]

    assert signal.count == 5
    assert signal.pattern_count == 4
    assert signal.pattern_signal == "recurring"
    assert signal.analysis_window is not None
    assert signal.analysis_window.start == "2026-06-01"
    assert signal.analysis_window.end == "2026-09-01"
    assert {row.case_id: store.fetch_case(row.case_id) for row in rows} == before
    for payload in before.values():
        assert payload is not None
        assert payload["result"]["reply"]["text"] == DRAFT


def test_missing_or_disagreeing_pattern_results_stay_missing() -> None:
    rows = [_row(number) for number in range(1, 6)]
    shared = {row.case_id: _pattern_case() for row in rows}
    shared[rows[0].case_id] = _pattern_case(include_pattern=False)
    missing = queue_signals(rows, cases=shared)[0]
    assert missing.count == 5
    assert missing.pattern_signal is None
    assert missing.pattern_count is None
    assert missing.analysis_window is None

    split = {row.case_id: _pattern_case() for row in rows}
    split[rows[1].case_id] = _pattern_case(matching_count=9)
    disagreed = queue_signals(rows, cases=split)[0]
    assert disagreed.count == 5
    assert disagreed.pattern_signal is None
    assert disagreed.pattern_count is None
    assert disagreed.analysis_window is None


def _desk_payload(case_id: str) -> dict[str, object]:
    from datetime import date

    from supportdesk.contracts import (
        AnalysisWindow,
        ComplianceResult,
        CustomerReply,
        FactClaim,
        FactsResult,
        OrchestratorResult,
        PatternEvidence,
        PatternResult,
        ReviewerResult,
        RoutingNote,
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
        WorkflowState,
    )

    execution_id = "exec_" + "ab" * 16
    window = AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1))
    pattern = PatternResult(
        status=PatternStatus.SUCCESS,
        signal=PatternSignal.RECURRING,
        matching_count=4,
        analysis_window=window,
        matched_themes=["fees: Fees"],
        evidence=[PatternEvidence(theme_id="fees")],
        method="measured",
        execution_id=execution_id,
    )
    facts = FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[
            FactClaim(
                claim=DRAFT,
                source_title="Exit load",
                source_url="https://groww.in/help/exit-load",
                evidence=DRAFT,
            )
        ],
        searched_sources=["https://groww.in/help/exit-load"],
        execution_id=execution_id,
    )
    case = DeskCase(
        run=WorkflowRun(
            run_id="run_" + "cd" * 16,
            case_id=case_id,
            state=WorkflowState.PENDING_APPROVAL,
        ),
        result=OrchestratorResult(
            case_id=case_id,
            reply=CustomerReply(text=DRAFT, sentence_count=1),
            routing_note=RoutingNote(
                team="support",
                priority=Priority.NORMAL,
                reason="The reviewed draft is ready.",
                pattern_signal=pattern.signal,
                matching_count=pattern.matching_count,
                analysis_window=window,
                facts_coverage=facts.coverage,
                next_action="Keep the draft as written.",
            ),
            facts=facts,
            pattern=pattern,
            compliance=ComplianceResult(
                status=ComplianceStatus.SUCCESS,
                pii_detected=False,
                sanitized=True,
                advice_request_detected=False,
                performance_claim_risk=False,
                decision=ComplianceDecision.ALLOW,
                safe_handling="No compliance block. Process the message.",
                execution_id=execution_id,
            ),
        ),
        reviews=[ReviewerResult(decision=ReviewerDecision.PASS, rework_attempt=0)],
    )
    return case.model_dump(mode="json")
