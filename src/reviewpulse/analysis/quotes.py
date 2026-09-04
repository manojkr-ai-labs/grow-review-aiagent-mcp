"""Extractive quote selection (Phase 3 tasks 3.1-3.2).

Every quote is a **character slice of `text_clean`**, never a string built up
from tokens. That is the whole design: `quotes_verbatim` can then be an exact
substring assertion rather than a fuzzy comparison, and the LLM is structurally
unable to author a quote because it is never asked for one
(architecture.md §6.3, §6.6).

Selection runs over the top themes only and scores candidate spans on three
things — how central the review is to its theme, how much of the theme's
vocabulary the span actually contains, and whether it reads as a whole sentence
of usable length. Reviews carrying redaction placeholders are penalised rather
than banned, so a theme whose evidence is entirely redacted still gets a quote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from reviewpulse.analysis.terms import tokenize
from reviewpulse.models import Quote, Review, Theme

# A sentence break, or a hard line break in a review that uses no punctuation.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?\u2026])[\"')\]]*\s+|\n+")
_TOKEN = re.compile(r"\S+")

# Anchor terms beyond the first few are long-tail noise, not theme vocabulary.
ANCHOR_TERMS = 8

# Weights sum to 1 before the bonus and penalty are applied.
W_CENTRALITY = 0.30
W_DENSITY = 0.25
W_LENGTH = 0.25
W_ALIGNMENT = 0.20
BONUS_COMPLETE = 0.05
PENALTY_SCRUBBED = 0.10

# Two quotes making the same complaint waste a third of the note's evidence, so
# a candidate overlapping this much with one already chosen is passed over —
# themes are only weakly separable here (§4.2 F2) and neighbouring clusters
# routinely share vocabulary.
OVERLAP_LIMIT = 0.30


@dataclass
class QuoteCandidate:
    """One span of one review, with the parts of its score kept separate."""

    review_id: str
    theme_id: str
    text: str
    rating: int | None
    centrality: float
    density: float
    length_fit: float
    alignment: float
    complete: bool
    scrubbed: bool
    score: float


@dataclass
class QuoteSelection:
    quotes: list[Quote]
    diagnostics: list[dict] = field(default_factory=list)
    shortfall: list[str] = field(default_factory=list)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character offsets of each sentence, so slices stay verbatim."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        if match.start() > start:
            spans.append((start, match.start()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _word_offsets(text: str, start: int, end: int) -> list[tuple[int, int]]:
    return [
        (match.start() + start, match.end() + start)
        for match in _TOKEN.finditer(text[start:end])
    ]


def _trim_to_words(text: str, start: int, end: int, max_words: int) -> tuple[int, int]:
    """Cut the span at a word boundary so it can never blow the note's budget."""
    words = _word_offsets(text, start, end)
    if len(words) <= max_words:
        return start, end
    return start, words[max_words - 1][1]


def candidate_spans(
    text: str,
    *,
    max_words: int,
    max_sentences: int = 2,
) -> list[tuple[int, int, bool]]:
    """Spans of one or two sentences, each trimmed to the word ceiling.

    The third element records whether the span survived trimming intact, which
    is what separates a quote that reads as a sentence from one that stops
    mid-thought.
    """
    sentences = sentence_spans(text)
    seen: set[tuple[int, int]] = set()
    spans: list[tuple[int, int, bool]] = []

    for first in range(len(sentences)):
        for length in range(1, max_sentences + 1):
            last = first + length - 1
            if last >= len(sentences):
                break
            start, end = _strip_span(text, sentences[first][0], sentences[last][1])
            if start >= end:
                continue
            trimmed_end = _trim_to_words(text, start, end, max_words)[1]
            start, trimmed_end = _strip_span(text, start, trimmed_end)
            if start >= trimmed_end or (start, trimmed_end) in seen:
                continue
            seen.add((start, trimmed_end))
            spans.append((start, trimmed_end, trimmed_end == end))

    return spans


def length_fit(words: int, *, min_words: int, max_words: int) -> float:
    """1.0 inside the band, decaying linearly below it.

    There is no penalty above the band because trimming already caps every
    candidate at `max_words`.
    """
    if words >= min_words:
        return 1.0
    return max(0.0, words / min_words) if min_words else 1.0


def _density(span: str, anchors: list[str]) -> float:
    """Share of the theme's anchor terms the span actually contains."""
    if not anchors:
        return 0.5
    tokens = set(tokenize(span))
    if not tokens:
        return 0.0
    hits = sum(1 for term in anchors if term in tokens)
    return min(1.0, hits / min(len(anchors), 3))


def rating_alignment(rating: int | None, theme_mean: float | None) -> float:
    """How closely the quote's star rating matches the theme's own.

    A theme that is 92% one-star complaints must not be illustrated by the one
    reviewer who liked it. Without embeddings this is the only representativeness
    signal available, and with them it still corrects for the fact that the
    corpus separates by sentiment more than by topic (§4.2 F2) — a positive
    review can sit near a complaint centroid purely on shared vocabulary.
    """
    if rating is None or theme_mean is None:
        return 0.5
    return 1.0 - abs((rating - 1) / 4.0 - (theme_mean - 1) / 4.0)


def content_overlap(left: str, right: str) -> float:
    """Jaccard similarity on content words, ignoring stopwords and sentiment."""
    a, b = set(tokenize(left)), set(tokenize(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _centroid(vectors: np.ndarray, indices: list[int]) -> np.ndarray | None:
    if vectors is None or not indices:
        return None
    centroid = vectors[indices].mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    return centroid / norm if norm else None


def _centrality(vector: np.ndarray | None, centroid: np.ndarray | None) -> float:
    """Cosine similarity mapped to [0, 1]; neutral when there are no vectors."""
    if vector is None or centroid is None:
        return 0.5
    return float(np.clip((float(vector @ centroid) + 1.0) / 2.0, 0.0, 1.0))


def distinctive_anchors(theme: Theme, rivals: list[Theme]) -> list[str]:
    """Anchor terms that belong to this theme and not to its neighbours.

    Adjacent themes on this corpus share vocabulary — "charges" and "trading"
    anchor both the brokerage theme and the ease-of-use one — so counting a
    shared term as evidence lets a charges complaint be picked to illustrate a
    theme it is not about. A term common to two themes in the same note
    distinguishes neither, so it is dropped from both.
    """
    own = theme.keywords[:ANCHOR_TERMS]
    shared = {
        term
        for rival in rivals
        if rival.theme_id != theme.theme_id
        for term in rival.keywords[:ANCHOR_TERMS]
    }
    distinctive = [term for term in own if term not in shared]
    # Every term shared: fall back to the full list rather than score on nothing.
    return distinctive or own


def score_candidates(
    theme: Theme,
    members: list[Review],
    *,
    centroid: np.ndarray | None = None,
    member_vectors: dict[str, np.ndarray] | None = None,
    anchors: list[str] | None = None,
    min_words: int,
    max_words: int,
) -> list[QuoteCandidate]:
    """Every usable span of every member review, best first."""
    anchors = anchors if anchors is not None else theme.keywords[:ANCHOR_TERMS]
    candidates: list[QuoteCandidate] = []

    for review in members:
        text = review.text_clean
        vector = (member_vectors or {}).get(review.review_id)
        centrality = _centrality(vector, centroid)
        alignment = rating_alignment(review.rating, theme.mean_rating)
        scrubbed = bool(review.scrub_flags)

        for start, end, complete in candidate_spans(text, max_words=max_words):
            span = text[start:end]
            words = len(_word_offsets(text, start, end))
            density = _density(span, anchors)
            fit = length_fit(words, min_words=min_words, max_words=max_words)
            score = (
                W_CENTRALITY * centrality
                + W_DENSITY * density
                + W_LENGTH * fit
                + W_ALIGNMENT * alignment
                + (BONUS_COMPLETE if complete else 0.0)
                - (PENALTY_SCRUBBED if scrubbed else 0.0)
            )
            candidates.append(
                QuoteCandidate(
                    review_id=review.review_id,
                    theme_id=theme.theme_id,
                    text=span,
                    rating=review.rating,
                    centrality=round(centrality, 4),
                    density=round(density, 4),
                    length_fit=round(fit, 4),
                    alignment=round(alignment, 4),
                    complete=complete,
                    scrubbed=scrubbed,
                    score=round(score, 4),
                )
            )

    candidates.sort(key=lambda c: (-c.score, c.review_id, c.text))
    return candidates


def select_quotes(
    themes: list[Theme],
    reviews: list[Review],
    *,
    vectors: np.ndarray | None = None,
    min_words: int = 8,
    max_words: int = 26,
    limit: int = 3,
) -> QuoteSelection:
    """One quote per theme, distinct reviews, in theme rank order.

    `themes` is expected to be the top themes already; ranking is Phase 2's job
    (§4.2 F4) and is not second-guessed here.
    """
    by_id = {review.review_id: review for review in reviews}
    index_of = {review.review_id: i for i, review in enumerate(reviews)}
    member_vectors: dict[str, np.ndarray] = {}
    if vectors is not None and len(vectors) == len(reviews) and vectors.size:
        member_vectors = {rid: vectors[i] for rid, i in index_of.items()}

    quotes: list[Quote] = []
    diagnostics: list[dict] = []
    shortfall: list[str] = []
    used: set[str] = set()

    for theme in themes[:limit]:
        members = [by_id[rid] for rid in theme.review_ids if rid in by_id]
        centroid = (
            _centroid(vectors, [index_of[r.review_id] for r in members])
            if member_vectors
            else None
        )
        candidates = score_candidates(
            theme,
            members,
            centroid=centroid,
            member_vectors=member_vectors,
            anchors=distinctive_anchors(theme, themes[:limit]),
            min_words=min_words,
            max_words=max_words,
        )
        chosen, redundant = _pick(candidates, used, quotes)
        if chosen is None:
            shortfall.append(theme.theme_id)
            continue

        used.add(chosen.review_id)
        quotes.append(
            Quote(
                review_id=chosen.review_id,
                theme_id=theme.theme_id,
                text=chosen.text,
                rating=chosen.rating,
            )
        )
        diagnostics.append(
            {
                "theme_id": theme.theme_id,
                "review_id": chosen.review_id,
                "rating": chosen.rating,
                "words": len(chosen.text.split()),
                "score": chosen.score,
                "centrality": chosen.centrality,
                "density": chosen.density,
                "length_fit": chosen.length_fit,
                "rating_alignment": chosen.alignment,
                "complete_sentence": chosen.complete,
                "redacted": chosen.scrubbed,
                "redundant": redundant,
                "candidates": len(candidates),
                "member_reviews": len(members),
            }
        )

    return QuoteSelection(quotes=quotes, diagnostics=diagnostics, shortfall=shortfall)


def _pick(
    candidates: list[QuoteCandidate],
    used: set[str],
    chosen: list[Quote],
) -> tuple[QuoteCandidate | None, bool]:
    """Best candidate that does not repeat a quote already in the note.

    Falling back to the best redundant candidate is deliberate: a theme with no
    distinct evidence should still be illustrated, and the flag makes the
    repetition visible in the manifest rather than silent.
    """
    best: QuoteCandidate | None = None
    for candidate in candidates:
        if candidate.review_id in used:
            continue
        if best is None:
            best = candidate
        if all(
            content_overlap(candidate.text, quote.text) <= OVERLAP_LIMIT
            for quote in chosen
        ):
            return candidate, False
    return best, best is not None
