"""Property test: a selected quote is always a slice of its stored review.

Randomised over generated corpora rather than fixed fixtures, because the risk
being guarded against is a text shape nobody thought to write down — reviews
with no punctuation, with runs of whitespace, with quotes and brackets inside
them, or consisting of a single 90-word sentence. Seeded, so a failure is
reproducible.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from reviewpulse.analysis.quotes import select_quotes
from reviewpulse.models import Review, Theme

WORDS = (
    "withdraw money stuck refund charges brokerage support ticket chart scalper "
    "update login kyc order sip mutual fund payout blocked pending slow crash "
    "interface layout button screen very never always again please fix"
).split()

PUNCTUATION = (".", "!", "?", "...", "", " ")
DECORATION = ('"', "'", "(", ")", "[", "]", ":", ";", ",", "-", "\u20b9")


def make_text(rng: random.Random) -> str:
    sentences = []
    for _ in range(rng.randint(1, 5)):
        length = rng.randint(1, 30)
        words = [rng.choice(WORDS) for _ in range(length)]
        if rng.random() < 0.3:
            position = rng.randrange(len(words))
            words[position] += rng.choice(DECORATION)
        separator = " " * rng.randint(1, 3) if rng.random() < 0.2 else " "
        sentences.append(separator.join(words) + rng.choice(PUNCTUATION))
    joiner = "\n" if rng.random() < 0.2 else " "
    return joiner.join(sentences).strip() or "fallback review text here"


def make_corpus(rng: random.Random) -> tuple[list[Theme], list[Review]]:
    reviews: list[Review] = []
    themes: list[Theme] = []
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)

    for theme_index in range(rng.randint(1, 4)):
        members = []
        for member in range(rng.randint(1, 12)):
            review = Review(
                review_id=f"t{theme_index}m{member:03d}",
                source="play",
                rating=rng.choice([1, 2, 3, 4, 5, None]),
                text_clean=make_text(rng),
                date=now - timedelta(days=rng.randint(0, 55)),
                scrub_flags=rng.choice([[], ["phone"], ["email", "handle"]]),
            )
            members.append(review)
        reviews.extend(members)
        ratings = [r.rating for r in members if r.rating is not None]
        themes.append(
            Theme(
                theme_id=f"t{theme_index + 1}",
                label=f"Theme {theme_index}",
                summary="",
                review_ids=[r.review_id for r in members],
                size=len(members),
                mean_rating=(
                    round(sum(ratings) / len(ratings), 2) if ratings else None
                ),
                rank=theme_index + 1,
                keywords=rng.sample(WORDS, rng.randint(0, 8)),
            )
        )
    return themes, reviews


@pytest.mark.parametrize("seed", range(60))
def test_quotes_are_always_substrings_of_their_source(seed: int) -> None:
    rng = random.Random(seed)
    themes, reviews = make_corpus(rng)
    by_id = {review.review_id: review for review in reviews}

    min_words = rng.randint(1, 12)
    max_words = rng.randint(max(min_words, 4), 40)
    selection = select_quotes(
        themes,
        reviews,
        min_words=min_words,
        max_words=max_words,
        limit=rng.randint(1, 3),
    )

    for quote in selection.quotes:
        review = by_id[quote.review_id]
        assert quote.text in review.text_clean
        assert quote.text == quote.text.strip()
        assert quote.text
        assert len(quote.text.split()) <= max_words
        assert quote.rating == review.rating
        assert quote.review_id in dict(
            (theme.theme_id, theme.review_ids) for theme in themes
        )[quote.theme_id]


@pytest.mark.parametrize("seed", range(20))
def test_selection_never_repeats_a_review(seed: int) -> None:
    rng = random.Random(1000 + seed)
    themes, reviews = make_corpus(rng)
    ids = [q.review_id for q in select_quotes(themes, reviews, limit=3).quotes]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("seed", range(20))
def test_selection_is_deterministic(seed: int) -> None:
    """Two runs on the same data must produce the same note, or the artifact
    cannot be reviewed against a previous week."""
    themes, reviews = make_corpus(random.Random(2000 + seed))
    first = select_quotes(themes, reviews, limit=3).quotes
    second = select_quotes(themes, reviews, limit=3).quotes
    assert [(q.review_id, q.text) for q in first] == [
        (q.review_id, q.text) for q in second
    ]
