"""Load the window from SQLite and drop low-signal reviews before clustering.

Phase 2 tasks 2.0-2.1. The filter exists because 22.7% of the real corpus is
short high-star praise ("super app nice") which, left in, forms its own cluster
and crowds out actionable feedback (implementation-plan.md §4.2 F3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from reviewpulse.config import ClusteringSettings, Settings, load_settings
from reviewpulse.models import Review
from reviewpulse.sources.language import word_count
from reviewpulse.store.sqlite import ReviewStore


@dataclass
class SelectionResult:
    reviews: list[Review]
    total_count: int
    dropped_low_signal: int
    retention: float
    criteria: dict = field(default_factory=dict)


def is_signal(review: Review, clustering: ClusteringSettings) -> bool:
    """Keep a review if it complains, or if it is long enough to say something.

    Short praise carries no product signal; short criticism still names a broken
    surface, so the rating test comes first.
    """
    rating = review.rating
    if rating is not None and rating <= clustering.signal_max_rating:
        return True
    return word_count(review.text_clean) >= clustering.signal_min_words


def apply_signal_filter(
    reviews: list[Review],
    clustering: ClusteringSettings,
) -> SelectionResult:
    kept = [r for r in reviews if is_signal(r, clustering)]
    total = len(reviews)
    return SelectionResult(
        reviews=kept,
        total_count=total,
        dropped_low_signal=total - len(kept),
        retention=round(len(kept) / total, 4) if total else 0.0,
        criteria={
            "signal_max_rating": clustering.signal_max_rating,
            "signal_min_words": clustering.signal_min_words,
        },
    )


def select_for_clustering(
    *,
    window_start: date,
    window_end: date,
    settings: Settings | None = None,
    db_path=None,
) -> SelectionResult:
    """Read the window from the store, then apply the signal filter."""
    settings = settings or load_settings()
    store = ReviewStore(db_path or settings.db_path)
    reviews = store.get_reviews(window_start, window_end)
    return apply_signal_filter(reviews, settings.clustering)
