"""Review source protocol."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Protocol

from reviewpulse.models import RawReview


class ReviewSource(Protocol):
    """Loads raw reviews from a public Play Store export."""

    def fetch(self, window_start: date, window_end: date) -> Iterable[RawReview]:
        """Yield reviews whose dates fall within the inclusive window."""
