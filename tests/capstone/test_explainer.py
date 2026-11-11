"""Ledger bullet and explainer.json gates."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from capstone.contracts import Explainer, ExplainerBullet, LedgerRow, QuestionLogRow
from capstone.explainer import (
    EMPTY_LEDGER_SENTENCE,
    factual_bullets,
    write_explainer,
)
from capstone.identity import question_key
from capstone.log import LogStore
from supportdesk.facts import RetrievalBundle

WEEK = "2026-W36"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
PASSAGE = "Exit load of 1% if redeemed within 1 year."
QUESTION = "What is the exit load on HDFC Mid Cap Fund Direct Growth?"


def _case_id(number: int) -> str:
    return f"case_{number:032x}"


def _ledger(number: int, text: str) -> LedgerRow:
    return LedgerRow(
        case_id=_case_id(number),
        week_id=WEEK,
        sanitized_text=text,
        searched_urls=["https://groww.in/help/exit-load"],
    )


def _run(tmp_path: Path) -> Path:
    return tmp_path / "runs" / "run_explainer"


def test_empty_ledger_uses_the_exact_sentence(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    outcome = write_explainer(
        run_dir,
        week_id=WEEK,
        fee_theme=None,
        factual=[],
        ledger=[],
    )

    assert outcome.written is True
    saved = Explainer.model_validate_json(Path(outcome.path or "").read_text(encoding="utf-8"))
    assert saved.bullets[-1].text == EMPTY_LEDGER_SENTENCE
    assert saved.bullets[-1].text == "No queued question in this week was outside the corpus."
    assert saved.bullets[-1].last_checked is None


def test_six_ledger_rows_stay_one_bullet(tmp_path: Path) -> None:
    store = LogStore(tmp_path / "capstone.db")
    for number in range(1, 7):
        text = f"What is gap {number}?"
        store.append(
            QuestionLogRow(
                case_id=_case_id(number),
                week_id=WEEK,
                question_key=question_key(text),
                sanitized_text=text,
                facts_coverage="not_covered",
                searched_urls=["https://groww.in/help/exit-load"],
                created_at=NOW,
            )
        )
    rows = store.list_ledger(WEEK)
    factual = ExplainerBullet(
        text=PASSAGE,
        url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        last_checked="2026-09-01",
    )
    outcome = write_explainer(
        _run(tmp_path),
        week_id=WEEK,
        fee_theme="t-expense",
        factual=[factual],
        ledger=rows,
    )

    assert outcome.written is True
    saved = Explainer.model_validate_json(Path(outcome.path or "").read_text(encoding="utf-8"))
    assert len(saved.bullets) == 2
    last = saved.bullets[-1]
    assert len(last.case_ids) == 6
    for case_id in last.case_ids:
        assert case_id in last.text
    assert last.last_checked != date.today().isoformat()


def test_you_should_redeem_writes_no_file(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    outcome = write_explainer(
        run_dir,
        week_id=WEEK,
        fee_theme=None,
        factual=[
            ExplainerBullet(
                text="You should redeem this fund.",
                url="https://groww.in/help/exit-load",
                last_checked="2026-09-01",
            )
        ],
        ledger=[],
    )

    assert outcome.written is False
    assert "advice" in outcome.codes
    assert not (run_dir / "explainer.json").exists()


def test_last_checked_is_not_filled_with_today(tmp_path: Path) -> None:
    def retriever(question: str) -> RetrievalBundle:
        return RetrievalBundle(
            status="hit",
            chunks=[
                {
                    "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
                    "source_title": "HDFC Mid Cap Fund — Direct Growth",
                    "text": PASSAGE,
                    "retrieved_on": "2026-09-01",
                }
            ],
        )

    bullets = factual_bullets(retriever, questions=(QUESTION,))
    outcome = write_explainer(
        _run(tmp_path),
        week_id=WEEK,
        fee_theme=None,
        factual=bullets,
        ledger=[_ledger(1, "What is the exit load for [phone]?")],
    )

    body = Path(outcome.path or "").read_text(encoding="utf-8")
    assert outcome.written is True
    assert "2026-09-01" in body
    assert date.today().isoformat() not in body
    assert "date.today" not in Path(write_explainer.__code__.co_filename).read_text(encoding="utf-8")
