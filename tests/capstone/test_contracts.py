"""Pydantic contracts reject unknown fields and non-queue evidence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from capstone.contracts import (
    Explainer,
    ExplainerBullet,
    LedgerRow,
    QuestionLogRow,
    SupportSignal,
    WeeklyPackageManifest,
)
from capstone.identity import question_key

WEEK = "2026-W37"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
SANITIZED = "What is the exit load?"
PACKAGE_HASH = "ab" * 32


def _case_id(number: int) -> str:
    return f"case_{number:032x}"


def _log_row() -> QuestionLogRow:
    return QuestionLogRow(
        case_id=_case_id(1),
        week_id=WEEK,
        question_key=question_key(SANITIZED),
        sanitized_text=SANITIZED,
        facts_coverage="covered",
        searched_urls=["https://groww.in/help/exit-load"],
        theme_id=None,
        created_at=NOW,
    )


def _ledger_row() -> LedgerRow:
    return LedgerRow(
        case_id=_case_id(1),
        week_id=WEEK,
        sanitized_text=SANITIZED,
        searched_urls=["https://groww.in/help/exit-load"],
        theme_id=None,
    )


def _signal() -> SupportSignal:
    return SupportSignal(
        week_id=WEEK,
        question_key=question_key(SANITIZED),
        count=5,
        case_ids=[_case_id(number) for number in range(1, 6)],
        theme_id=None,
        evidence_type="queue",
    )


def _bullet() -> ExplainerBullet:
    return ExplainerBullet(
        text="Exit load is listed on the scheme page.",
        url="https://groww.in/help/exit-load",
        last_checked="unavailable",
    )


def _explainer() -> Explainer:
    return Explainer(week_id=WEEK, fee_theme=None, bullets=[_bullet()])


def _manifest() -> WeeklyPackageManifest:
    return WeeklyPackageManifest(
        package_hash=PACKAGE_HASH,
        fee_theme=None,
        files=["note.md", "explainer.json", "support_signals.json"],
    )


@pytest.mark.parametrize(
    "build",
    [_log_row, _ledger_row, _signal, _bullet, _explainer, _manifest],
)
def test_model_dump_rejects_an_unknown_field(build) -> None:
    model = build()
    payload = model.model_dump()
    payload["not_a_field"] = "no"
    with pytest.raises(ValidationError):
        type(model).model_validate(payload)


def test_signal_rejects_pattern_and_review_evidence() -> None:
    payload = _signal().model_dump()
    assert payload["evidence_type"] == "queue"
    for evidence_type in ("pattern", "review"):
        rejected = dict(payload)
        rejected["evidence_type"] = evidence_type
        with pytest.raises(ValidationError):
            SupportSignal.model_validate(rejected)
