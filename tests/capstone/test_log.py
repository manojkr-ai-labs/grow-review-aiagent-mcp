"""Question log, ledger copy, and sanitized case durability."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from capstone.contracts import QuestionLogRow
from capstone.identity import question_key
from capstone.log import DEFAULT_DB_PATH, LogStore
from supportdesk.decisions import DeskCase
from supportdesk.contracts import (
    AnalysisWindow,
    ComplianceResult,
    CustomerReply,
    FactsResult,
    OrchestratorResult,
    PatternResult,
    ReviewerResult,
    WorkflowRun,
)
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

WEEK = "2026-W37"
OTHER_WEEK = "2026-W38"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)
COVERED_TEXT = "What is the exit load?"
GAP_TEXT = "What is the exit load for [phone]?"
REVISED_TEXT = "Where is the expense ratio listed?"
URLS = [
    "https://groww.in/help/exit-load",
    "https://groww.in/help/charges",
]
REPO_ROOT = Path(__file__).resolve().parents[2]


def _case_id(number: int) -> str:
    return f"case_{number:032x}"


def _log_row(
    number: int,
    text: str,
    coverage: str,
    *,
    week_id: str = WEEK,
    urls: list[str] | None = None,
    theme_id: str | None = None,
    created_at: datetime = NOW,
) -> QuestionLogRow:
    return QuestionLogRow(
        case_id=_case_id(number),
        week_id=week_id,
        question_key=question_key(text),
        sanitized_text=text,
        facts_coverage=coverage,
        searched_urls=list(URLS if urls is None else urls),
        theme_id=theme_id,
        created_at=created_at,
    )


def _store(tmp_path: Path) -> LogStore:
    return LogStore(tmp_path / "capstone.db")


def _column_names(db_path: Path) -> list[str]:
    connection = sqlite3.connect(db_path)
    try:
        names: list[str] = []
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table_name,) in tables:
            info = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            names.extend(row[1] for row in info)
        return names
    finally:
        connection.close()


def _sanitized_case(case_id: str) -> dict[str, object]:
    execution_id = "exec_" + "ab" * 16
    window = AnalysisWindow()
    result = OrchestratorResult(
        case_id=case_id,
        reply=CustomerReply(
            text="This page does not list that detail.",
            sentence_count=1,
        ),
        routing_note={
            "team": "support",
            "priority": Priority.NORMAL,
            "reason": "The corpus does not cover this question.",
            "pattern_signal": PatternSignal.INSUFFICIENT_DATA,
            "matching_count": 0,
            "analysis_window": window,
            "facts_coverage": Coverage.NOT_COVERED,
            "next_action": "Keep the question on the not-covered ledger.",
        },
        facts=FactsResult(
            status=FactsStatus.NOT_COVERED,
            coverage=Coverage.NOT_COVERED,
            execution_id=execution_id,
        ),
        pattern=PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.INSUFFICIENT_DATA,
            matching_count=0,
            analysis_window=window,
            method="not measured",
            execution_id=execution_id,
        ),
        compliance=ComplianceResult(
            status=ComplianceStatus.SUCCESS,
            pii_detected=False,
            pii_categories=[],
            sanitized=True,
            advice_request_detected=False,
            performance_claim_risk=False,
            decision=ComplianceDecision.ALLOW,
            safe_handling="No compliance block. Process the message.",
            execution_id=execution_id,
        ),
    )
    case = {
        "run": WorkflowRun(
            run_id="run_" + "cd" * 16,
            case_id=case_id,
            state=WorkflowState.PENDING_APPROVAL,
        ).model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "reviews": [
            ReviewerResult(
                decision=ReviewerDecision.PASS,
                rework_attempt=0,
            ).model_dump(mode="json")
        ],
    }
    return case


def test_default_database_path_is_gitignored() -> None:
    assert DEFAULT_DB_PATH == Path("data/capstone.db")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/capstone.db" in gitignore.splitlines()


def test_covered_row_does_not_enter_the_ledger(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _log_row(1, COVERED_TEXT, "covered", theme_id="fees")
    store.append(row)

    assert store.fetch(row.case_id) == row
    assert store.fetch_ledger(row.case_id) is None
    assert store.list_ledger(WEEK) == []
    assert store.list_by_week(WEEK) == [row]


def test_not_covered_row_copies_the_ledger_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = _log_row(2, GAP_TEXT, "not_covered", urls=URLS, theme_id="fees")
    store.append(row)

    ledger = store.fetch_ledger(row.case_id)
    assert ledger is not None
    assert ledger.case_id == row.case_id
    assert ledger.sanitized_text == row.sanitized_text
    assert ledger.searched_urls == URLS
    assert ledger.week_id == row.week_id
    assert ledger.theme_id == "fees"
    assert store.list_ledger(WEEK) == [ledger]


def test_second_append_updates_the_same_case_without_a_second_ledger_row(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    case_id = _case_id(3)
    first = _log_row(3, GAP_TEXT, "not_covered", urls=URLS, theme_id="fees")
    store.append(first)
    revised_urls = ["https://groww.in/help/expense-ratio"]
    revised = _log_row(
        3,
        REVISED_TEXT,
        "not_covered",
        urls=revised_urls,
        theme_id="expense",
        created_at=LATER,
    )
    assert revised.case_id == case_id
    store.append(revised)

    assert store.fetch(case_id) == revised
    assert store.list_by_week(WEEK) == [revised]
    ledger_rows = store.list_ledger(WEEK)
    assert len(ledger_rows) == 1
    assert ledger_rows[0].sanitized_text == REVISED_TEXT
    assert ledger_rows[0].searched_urls == revised_urls
    assert ledger_rows[0].theme_id == "expense"
    assert ledger_rows[0].week_id == WEEK


def test_schema_has_no_raw_column(tmp_path: Path) -> None:
    store = _store(tmp_path)
    names = _column_names(store.db_path)
    assert "case_id" in names
    assert "payload" in names
    assert names
    assert all("raw" not in name.casefold() for name in names)


def test_sanitized_case_round_trip_and_missing_keys_are_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    case_id = _case_id(4)
    payload = DeskCase.model_validate(_sanitized_case(case_id)).model_dump(mode="json")
    stored_id = store.save_case(payload, updated_at=NOW)

    assert stored_id == case_id
    assert store.fetch_case(case_id) == payload

    with pytest.raises(ValidationError):
        store.save_case({"accepted_hash": None}, updated_at=LATER)
    assert store.fetch_case(case_id) == payload
