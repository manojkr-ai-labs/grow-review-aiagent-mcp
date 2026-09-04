"""Validation gate tests (Phase 3 task 3.8, architecture.md §7)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from reviewpulse.chains.retry_policy import MAX_ATTEMPTS, decide
from reviewpulse.models import ActionIdea, PulseNote, Quote, Review, Theme, ThemeLine
from reviewpulse.pulse.render import render_note
from reviewpulse.pulse.validate import GATE_NAMES, validate_note

WINDOW = {
    "requested_start": "2026-07-06",
    "requested_end": "2026-08-29",
    "actual_start": "2026-07-06",
    "actual_end": "2026-08-29",
    "actual_weeks": 7.71,
}

QUOTE_TEXTS = {
    "r10": "Customer care never replies to my ticket about this account problem",
    "r20": "Brokerage charges are far too high on every single trade i place",
    "r30": "I cannot withdraw my money it has been stuck on hold for many days",
}


def make_store() -> dict[str, Review]:
    return {
        review_id: Review(
            review_id=review_id,
            source="play",
            rating=1,
            text_clean=text,
            date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        for review_id, text in QUOTE_TEXTS.items()
    }


def make_note(**overrides) -> PulseNote:
    themes = [
        Theme(
            theme_id=f"t{i}",
            label=f"Theme {i}",
            summary="",
            review_ids=[f"r{i}0"],
            size=10 * i,
            mean_rating=1.5,
            rank=i,
            neg_share=0.8,
        )
        for i in (1, 2, 3)
    ]
    defaults = dict(
        run_id="run-1",
        window_start=date(2026, 7, 6),
        window_end=date(2026, 8, 29),
        review_count=100,
        mean_rating=2.5,
        theme_count=5,
        top_themes=themes,
        theme_lines=[ThemeLine(theme_id=f"t{i}", line=f"Line {i}") for i in (1, 2, 3)],
        quotes=[
            Quote(
                review_id=f"r{i}0",
                theme_id=f"t{i}",
                text=QUOTE_TEXTS[f"r{i}0"][:40],
                rating=1,
            )
            for i in (1, 2, 3)
        ],
        actions=[ActionIdea(text=f"Action {i}", theme_ids=[f"t{i}"]) for i in (1, 2, 3)],
        word_count=0,
    )
    defaults.update(overrides)
    return PulseNote(**defaults)


def run_gates(note: PulseNote, *, rendered: str | None = None, **kwargs):
    store = make_store()
    return validate_note(
        note,
        rendered if rendered is not None else render_note(note),
        resolve=store.get,
        window=WINDOW,
        **kwargs,
    )


def test_every_gate_runs_and_a_valid_note_passes() -> None:
    report = run_gates(make_note())
    assert [result.name for result in report.results] == list(GATE_NAMES)
    assert report.passed, report.failures


def test_no_gate_short_circuits_the_rest() -> None:
    """The manifest has to show all seven, not just the first failure."""
    note = make_note(theme_count=9, quotes=[])
    report = run_gates(note)
    assert len(report.results) == len(GATE_NAMES)
    assert {"themes_capped", "quotes_count"} <= set(report.failures)


def test_themes_capped_rejects_more_than_k_max_clusters() -> None:
    assert "themes_capped" in run_gates(make_note(theme_count=6)).failures


def test_themes_capped_requires_exactly_three_in_the_note() -> None:
    note = make_note()
    note.top_themes = note.top_themes[:2]
    assert "themes_capped" in run_gates(note).failures


def test_quotes_verbatim_rejects_a_paraphrase() -> None:
    note = make_note()
    note.quotes[1].text = "Charges here are much too high on every trade"
    report = run_gates(note)
    assert "quotes_verbatim" in report.failures
    assert "r20" in report.detail("quotes_verbatim")


def test_quotes_verbatim_rejects_a_quote_with_no_stored_review() -> None:
    note = make_note()
    note.quotes[0].review_id = "ghost"
    report = run_gates(note)
    assert "quotes_verbatim" in report.failures
    assert "not found in store" in report.detail("quotes_verbatim")


def test_quotes_count_rejects_two_quotes() -> None:
    note = make_note()
    note.quotes = note.quotes[:2]
    assert "quotes_count" in run_gates(note).failures


def test_quotes_count_rejects_the_same_review_twice() -> None:
    note = make_note()
    note.quotes[2] = note.quotes[0].model_copy()
    assert "quotes_count" in run_gates(note).failures


def test_actions_grounded_rejects_an_unknown_theme_id() -> None:
    note = make_note()
    note.actions[0].theme_ids = ["t9"]
    assert "actions_grounded" in run_gates(note).failures


def test_actions_grounded_rejects_an_action_citing_nothing() -> None:
    note = make_note()
    note.actions[2].theme_ids = []
    assert "actions_grounded" in run_gates(note).failures


def test_actions_grounded_rejects_the_wrong_number_of_actions() -> None:
    note = make_note()
    note.actions = note.actions[:2]
    assert "actions_grounded" in run_gates(note).failures


def test_word_count_is_measured_on_the_rendered_note() -> None:
    note = make_note()
    note.actions[0].text = "word " * 400
    report = run_gates(note)
    assert "word_count" in report.failures
    assert "max 250" in report.detail("word_count")


def test_word_count_ceiling_is_configurable() -> None:
    assert "word_count" in run_gates(make_note(), max_words=10).failures


@pytest.mark.parametrize(
    "leak",
    [
        "reach me at user@example.com",
        "call +91 98765 43210",
        "account 123456789012345",
        "ping @someuser about it",
    ],
)
def test_no_pii_catches_leakage_in_the_final_artifact(leak: str) -> None:
    note = make_note()
    report = run_gates(note, rendered=render_note(note) + "\n" + leak)
    assert "no_pii" in report.failures


def test_no_pii_allows_the_brand_handle() -> None:
    note = make_note()
    report = run_gates(note, rendered=render_note(note) + "\nfrom @groww support")
    assert "no_pii" not in report.failures


def test_window_declared_rejects_a_note_claiming_a_different_window() -> None:
    note = make_note(window_start=date(2026, 6, 1))
    report = run_gates(note)
    assert "window_declared" in report.failures
    assert "2026-06-01" in report.detail("window_declared")


def test_window_declared_rejects_data_outside_the_declared_range() -> None:
    note = make_note()
    store = make_store()
    report = validate_note(
        note,
        render_note(note),
        resolve=store.get,
        window={**WINDOW, "actual_end": "2026-09-15"},
    )
    assert "window_declared" in report.failures


def test_window_declared_rejects_an_empty_window() -> None:
    note = make_note()
    store = make_store()
    report = validate_note(
        note,
        render_note(note),
        resolve=store.get,
        window={**WINDOW, "actual_start": None, "actual_end": None},
    )
    assert "window_declared" in report.failures


def test_report_serialises_gates_for_the_manifest() -> None:
    report = run_gates(make_note())
    assert report.as_checks() == {name: True for name in GATE_NAMES}
    for entry in report.as_list():
        assert set(entry) == {"gate", "passed", "detail", "recoverable"}
        assert entry["detail"]


def test_word_count_and_actions_are_recoverable_but_pii_is_not() -> None:
    report = run_gates(make_note())
    recoverable = {r.name for r in report.results if r.recoverable}
    assert recoverable == {"word_count", "actions_grounded", "quotes_count"}


def test_retry_is_offered_once_for_a_recoverable_failure() -> None:
    first = decide(["word_count"], 1)
    assert first.retry and first.recompose
    assert decide(["word_count"], MAX_ATTEMPTS).retry is False


def test_a_hard_failure_vetoes_the_retry_even_alongside_a_soft_one() -> None:
    decision = decide(["word_count", "no_pii"], 1)
    assert decision.retry is False
    assert "no_pii" in decision.reason


def test_quote_shortfall_asks_for_a_reselect_not_a_recompose() -> None:
    decision = decide(["quotes_count"], 1)
    assert decision.reselect_quotes is True
    assert decision.recompose is False
