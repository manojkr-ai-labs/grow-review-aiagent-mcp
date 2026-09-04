"""Renderer and word-counter tests (Phase 3 tasks 3.6-3.7)."""

from __future__ import annotations

from datetime import date

import pytest

from reviewpulse.models import ActionIdea, PulseNote, Quote, Theme, ThemeLine
from reviewpulse.pulse.render import count_words, render_note, to_ascii


def make_theme(index: int, label: str, size: int, rating: float) -> Theme:
    return Theme(
        theme_id=f"t{index}",
        label=label,
        summary=f"Summary for {label.lower()}.",
        review_ids=[f"r{index}{n}" for n in range(size)],
        size=size,
        mean_rating=rating,
        rank=index,
        neg_share=0.8,
        keywords=["alpha", "beta"],
    )


def make_note(**overrides) -> PulseNote:
    themes = [
        make_theme(1, "Withdrawal delays", 60, 1.4),
        make_theme(2, "Brokerage charges", 30, 2.1),
        make_theme(3, "Support responsiveness", 10, 1.2),
    ]
    defaults = dict(
        run_id="run-1",
        window_start=date(2026, 7, 6),
        window_end=date(2026, 8, 29),
        review_count=100,
        mean_rating=2.96,
        theme_count=5,
        top_themes=themes,
        theme_lines=[
            ThemeLine(theme_id=f"t{i}", line=f"Line {i}") for i in (1, 2, 3)
        ],
        quotes=[
            Quote(review_id=f"r{i}0", theme_id=f"t{i}", text=f"Quote {i}", rating=i)
            for i in (1, 2, 3)
        ],
        actions=[
            ActionIdea(text=f"Action {i}", theme_ids=[f"t{i}"]) for i in (1, 2, 3)
        ],
        word_count=0,
    )
    defaults.update(overrides)
    return PulseNote(**defaults)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("one two three", 3),
        ("- bullet item", 2),
        ("1. numbered item", 3),
        ("avg 2.9\u2605", 2),
        ("\u2014 \u00b7 -", 0),
        ("", 0),
    ],
)
def test_count_words_ignores_pure_punctuation_tokens(text: str, expected: int) -> None:
    assert count_words(text) == expected


def test_note_follows_the_architecture_template() -> None:
    rendered = render_note(make_note())
    lines = rendered.splitlines()

    assert lines[0].startswith("Groww \u2014 Weekly Review Pulse")
    assert "2026-07-06 to 2026-08-29" in lines[0]
    assert "100 reviews" in lines[0]
    assert "avg 3.0\u2605" in lines[0]
    assert "Top themes" in lines
    assert "What users said" in lines
    assert "Three things to do next" in lines


def test_theme_lines_carry_counts_shares_and_ratings_from_the_data() -> None:
    rendered = render_note(make_note())
    assert "1. Withdrawal delays \u2014 60 reviews (60%), avg 1.4\u2605" in rendered
    assert "2. Brokerage charges \u2014 30 reviews (30%), avg 2.1\u2605" in rendered


def test_compose_line_wins_over_the_phase_2_summary() -> None:
    rendered = render_note(make_note())
    assert "Line 1" in rendered
    assert "Summary for withdrawal delays." not in rendered


def test_theme_falls_back_to_its_label_summary_when_no_line_was_written() -> None:
    rendered = render_note(make_note(theme_lines=[]))
    assert "Summary for withdrawal delays." in rendered


def test_emerging_theme_is_marked() -> None:
    note = make_note()
    note.top_themes[0].emerging = True
    assert "rising" in render_note(note)


def test_quotes_are_injected_verbatim_and_attributed() -> None:
    rendered = render_note(make_note())
    assert '- "Quote 1" \u2014 1\u2605' in rendered
    assert '- "Quote 3" \u2014 3\u2605' in rendered


def test_actions_name_the_theme_they_cite() -> None:
    rendered = render_note(make_note())
    assert "1. Action 1 (theme: Withdrawal delays)" in rendered


def test_action_citing_an_unknown_theme_gets_no_attribution() -> None:
    note = make_note(
        actions=[ActionIdea(text="Floating action", theme_ids=["t9"])],
    )
    assert "1. Floating action\n" in render_note(note)


def test_missing_mean_rating_renders_as_not_available() -> None:
    rendered = render_note(make_note(mean_rating=None))
    assert "avg n/a" in rendered.splitlines()[0]
    assert "n/a\u2605" not in rendered.splitlines()[0]


def test_zero_review_count_does_not_divide_by_zero() -> None:
    assert "(0%)" in render_note(make_note(review_count=0))


def test_ascii_fallback_is_only_for_consoles() -> None:
    rendered = render_note(make_note())
    folded = to_ascii(rendered)
    assert "\u2605" not in folded and "*" in folded
    assert "\u2605" in rendered
