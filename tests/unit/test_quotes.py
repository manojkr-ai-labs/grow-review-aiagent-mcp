"""Quote selection tests (Phase 3 tasks 3.1-3.2).

The load-bearing property is that a quote is always a character slice of
`text_clean`. It is asserted here on every candidate span, not just the winner,
because the gate in `pulse/validate.py` only ever sees three of them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from reviewpulse.analysis.quotes import (
    candidate_spans,
    content_overlap,
    distinctive_anchors,
    length_fit,
    rating_alignment,
    score_candidates,
    select_quotes,
    sentence_spans,
)
from reviewpulse.models import Review, Theme


def make_review(index: int, text: str, rating: int, flags=None) -> Review:
    return Review(
        review_id=f"r{index:04d}",
        source="play",
        rating=rating,
        text_clean=text,
        date=datetime(2026, 8, 29, tzinfo=timezone.utc) - timedelta(days=index + 1),
        scrub_flags=list(flags or []),
    )


def make_theme(
    theme_id: str,
    reviews: list[Review],
    *,
    label: str = "Withdrawal delays",
    keywords=None,
    rank: int = 1,
) -> Theme:
    ratings = [r.rating for r in reviews if r.rating is not None]
    return Theme(
        theme_id=theme_id,
        label=label,
        summary="",
        review_ids=[r.review_id for r in reviews],
        size=len(reviews),
        mean_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        rank=rank,
        neg_share=sum(1 for r in ratings if r <= 2) / len(ratings) if ratings else 0.0,
        keywords=list(keywords or ["withdraw", "money", "refund"]),
    )


SUPPORT = "Customer care never replies. My withdrawal has been stuck for ten days now."


def test_sentence_spans_cover_the_text_verbatim() -> None:
    spans = sentence_spans(SUPPORT)
    assert len(spans) == 2
    assert [SUPPORT[s:e] for s, e in spans] == [
        "Customer care never replies.",
        "My withdrawal has been stuck for ten days now.",
    ]


def test_text_without_punctuation_is_one_span() -> None:
    text = "money stuck for ten days no reply from anyone at all"
    assert [text[s:e] for s, e in sentence_spans(text)] == [text]


def test_every_candidate_span_is_a_substring() -> None:
    for start, end, _ in candidate_spans(SUPPORT, max_words=26):
        assert SUPPORT[start:end] in SUPPORT


def test_candidates_include_one_and_two_sentence_windows() -> None:
    spans = {SUPPORT[s:e] for s, e, _ in candidate_spans(SUPPORT, max_words=40)}
    assert "Customer care never replies." in spans
    assert SUPPORT in spans


def test_long_span_is_trimmed_at_a_word_boundary() -> None:
    text = " ".join(f"word{i}" for i in range(40))
    spans = candidate_spans(text, max_words=10)
    for start, end, complete in spans:
        assert len(text[start:end].split()) <= 10
        assert text[start:end] in text
        assert complete is False


def test_trimmed_span_never_ends_mid_word() -> None:
    text = " ".join(f"word{i}" for i in range(40))
    start, end, _ = candidate_spans(text, max_words=10)[0]
    assert text[start:end].endswith("word9")


@pytest.mark.parametrize(
    ("words", "expected"),
    [(8, 1.0), (20, 1.0), (4, 0.5), (0, 0.0)],
)
def test_length_fit_only_penalises_short_spans(words: int, expected: float) -> None:
    assert length_fit(words, min_words=8, max_words=26) == expected


@pytest.mark.parametrize(
    ("rating", "theme_mean", "expected"),
    [(1, 1.0, 1.0), (5, 1.0, 0.0), (1, 5.0, 0.0), (3, 3.0, 1.0), (None, 1.0, 0.5)],
)
def test_rating_alignment_matches_quote_to_theme(rating, theme_mean, expected) -> None:
    assert rating_alignment(rating, theme_mean) == pytest.approx(expected)


def test_praise_is_not_quoted_for_a_complaint_theme() -> None:
    """The failure this guard exists for: a 92%-negative theme quoting the one
    reviewer who liked it, purely because they shared its vocabulary."""
    complaints = [
        make_review(i, "I cannot withdraw my money it has been stuck for ten days", 1)
        for i in range(6)
    ]
    praise = make_review(
        99, "It is very easy to deposit and withdraw money from this app", 5
    )
    members = complaints + [praise]
    theme = make_theme("t1", members)

    best = score_candidates(
        theme, members, min_words=8, max_words=26
    )[0]
    assert best.review_id != praise.review_id


def test_redacted_reviews_are_penalised_but_not_banned() -> None:
    clean = make_review(1, "I cannot withdraw my money it has been stuck for days", 1)
    redacted = make_review(
        2, "I cannot withdraw my money it has been stuck for days", 1, flags=["phone"]
    )
    theme = make_theme("t1", [redacted, clean])

    best = score_candidates(theme, [redacted, clean], min_words=8, max_words=26)[0]
    assert best.review_id == clean.review_id

    only_redacted = make_theme("t1", [redacted])
    fallback = score_candidates(
        only_redacted, [redacted], min_words=8, max_words=26
    )
    assert fallback and fallback[0].review_id == redacted.review_id


def test_centrality_prefers_the_review_nearest_the_centroid() -> None:
    members = [
        make_review(i, "withdrawal money stuck refund not credited yet at all", 1)
        for i in range(3)
    ]
    outlier = make_review(9, "withdrawal money stuck refund not credited yet at all", 1)
    reviews = members + [outlier]
    vectors = np.vstack(
        [np.array([[1.0, 0.0]], dtype=np.float32)] * 3
        + [np.array([[0.0, 1.0]], dtype=np.float32)]
    )
    theme = make_theme("t1", reviews)

    selection = select_quotes([theme], reviews, vectors=vectors, limit=1)
    assert selection.quotes[0].review_id != outlier.review_id


def build_three_themes():
    reviews = []
    themes = []
    topics = [
        ("customer care never replies to my ticket about this account problem", 1),
        ("brokerage charges are far too high on every single trade i place", 2),
        ("i cannot withdraw my money it has been stuck on hold for days", 1),
    ]
    for index, (text, rating) in enumerate(topics):
        members = [
            make_review(index * 10 + m, f"{text} number {m}", rating) for m in range(5)
        ]
        reviews.extend(members)
        themes.append(
            make_theme(f"t{index + 1}", members, label=f"Theme {index}", rank=index + 1)
        )
    return themes, reviews


def test_one_quote_per_theme_from_distinct_reviews() -> None:
    themes, reviews = build_three_themes()
    selection = select_quotes(themes, reviews, limit=3)

    assert [q.theme_id for q in selection.quotes] == ["t1", "t2", "t3"]
    assert len({q.review_id for q in selection.quotes}) == 3
    assert not selection.shortfall


def test_selected_quotes_are_substrings_of_their_source_review() -> None:
    themes, reviews = build_three_themes()
    by_id = {r.review_id: r for r in reviews}
    for quote in select_quotes(themes, reviews, limit=3).quotes:
        assert quote.text in by_id[quote.review_id].text_clean


def test_quotes_respect_the_word_ceiling() -> None:
    themes, reviews = build_three_themes()
    for quote in select_quotes(themes, reviews, max_words=12, limit=3).quotes:
        assert len(quote.text.split()) <= 12


def test_selection_stops_at_the_limit() -> None:
    themes, reviews = build_three_themes()
    assert len(select_quotes(themes, reviews, limit=2).quotes) == 2


def test_theme_with_no_members_is_reported_as_a_shortfall() -> None:
    themes, reviews = build_three_themes()
    empty = make_theme("t4", [], label="Empty", rank=4)
    empty.review_ids = []
    selection = select_quotes([empty], reviews, limit=1)

    assert selection.quotes == []
    assert selection.shortfall == ["t4"]


def test_terms_shared_by_two_themes_in_the_note_anchor_neither() -> None:
    """"charges" anchors both the brokerage theme and the ease-of-use one, so it
    cannot be evidence that a span belongs to either."""
    brokerage = make_theme(
        "t1", [], label="Brokerage", keywords=["brokerage", "charges", "stocks"]
    )
    ease = make_theme(
        "t2", [], label="Ease of use", keywords=["easy", "charges", "interface"]
    )

    assert distinctive_anchors(brokerage, [brokerage, ease]) == ["brokerage", "stocks"]
    assert distinctive_anchors(ease, [brokerage, ease]) == ["easy", "interface"]


def test_a_theme_whose_terms_are_all_shared_keeps_them() -> None:
    a = make_theme("t1", [], keywords=["charges", "trading"])
    b = make_theme("t2", [], keywords=["charges", "trading"])
    assert distinctive_anchors(a, [a, b]) == ["charges", "trading"]


def test_shared_vocabulary_does_not_pull_a_quote_off_its_theme() -> None:
    charges = [
        make_review(i, "brokerage charges are far too high on every trade i place", 1)
        for i in range(5)
    ]
    ease = [
        make_review(20 + i, "the app is easy to use with a clean simple interface", 3)
        for i in range(4)
    ]
    # One member of the ease theme is really a charges complaint.
    stray = make_review(30, "very high charges in every segment of this platform", 1)
    ease_members = ease + [stray]

    themes = [
        make_theme(
            "t1", charges, label="Charges", keywords=["brokerage", "charges", "trade"]
        ),
        make_theme(
            "t2",
            ease_members,
            label="Ease of use",
            keywords=["easy", "interface", "charges"],
            rank=2,
        ),
    ]
    selection = select_quotes(themes, charges + ease_members, limit=2)

    assert selection.quotes[1].review_id != stray.review_id


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("withdraw money stuck", "withdraw money stuck", 1.0),
        ("withdraw money stuck", "chart scalper button", 0.0),
        ("", "anything here", 0.0),
    ],
)
def test_content_overlap_ignores_stopwords(left, right, expected) -> None:
    assert content_overlap(left, right) == pytest.approx(expected)


def test_a_theme_does_not_repeat_a_quote_already_in_the_note() -> None:
    shared = "customer support never replies to any ticket i raise about this"
    first = [make_review(i, shared + f" case {i}", 1) for i in range(4)]
    # The second theme's best-scoring member says the same thing as the first's.
    echo = make_review(20, shared + " again", 1)
    distinct = [
        make_review(30 + i, "my withdrawal request has been pending for two weeks", 1)
        for i in range(4)
    ]
    second = [echo] + distinct

    themes = [
        make_theme("t1", first, label="Support", keywords=["support", "ticket"]),
        make_theme(
            "t2", second, label="Withdrawals", keywords=["withdrawal", "pending"], rank=2
        ),
    ]
    selection = select_quotes(themes, first + second, limit=2)

    assert selection.quotes[1].review_id != echo.review_id
    assert selection.diagnostics[1]["redundant"] is False


def test_a_theme_with_only_redundant_evidence_still_gets_a_quote() -> None:
    shared = "customer support never replies to any ticket i raise about this"
    first = [make_review(i, shared + f" case {i}", 1) for i in range(4)]
    second = [make_review(20 + i, shared + f" again {i}", 1) for i in range(3)]

    themes = [
        make_theme("t1", first, label="Support", keywords=["support", "ticket"]),
        make_theme("t2", second, label="Echo", keywords=["support", "ticket"], rank=2),
    ]
    selection = select_quotes(themes, first + second, limit=2)

    assert len(selection.quotes) == 2
    assert selection.diagnostics[1]["redundant"] is True


def test_diagnostics_trace_the_choice_back_to_the_review() -> None:
    themes, reviews = build_three_themes()
    selection = select_quotes(themes, reviews, limit=3)

    for quote, diag in zip(selection.quotes, selection.diagnostics):
        assert diag["review_id"] == quote.review_id
        assert diag["theme_id"] == quote.theme_id
        assert diag["candidates"] > 0
        assert diag["member_reviews"] == 5
