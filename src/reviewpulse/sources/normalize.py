"""Normalize and filter raw Play Store reviews."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from reviewpulse.models import RawReview
from reviewpulse.sources.language import classify


def parse_datetime(value: str) -> datetime | None:
    """Parse common Play export date formats into UTC."""
    value = value.strip()
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def detect_language(text: str) -> str:
    return classify(text).language


def normalize_raw_review(raw: RawReview) -> RawReview | None:
    """Coerce fields; drop rows with no usable text."""
    text = _normalize_whitespace(raw.text)
    title = _normalize_whitespace(raw.title) if raw.title else None

    if not text and title:
        text = title
    if not text:
        return None

    review_date = raw.date
    if review_date.tzinfo is None:
        review_date = review_date.replace(tzinfo=timezone.utc)
    else:
        review_date = review_date.astimezone(timezone.utc)

    # Exclude future-dated rows beyond 1-day clock skew tolerance.
    if review_date > datetime.now(timezone.utc) + timedelta(days=1):
        return None

    return RawReview(
        source=raw.source,
        external_id=raw.external_id,
        rating=raw.rating,
        title=title,
        text=text,
        date=review_date,
        author=raw.author,
    )


def filter_window(raw: RawReview, window_start: date, window_end: date) -> bool:
    review_date = raw.date.astimezone(timezone.utc).date()
    return window_start <= review_date <= window_end


def compute_window(
    window_weeks: int,
    *,
    reference: datetime | None = None,
) -> tuple[date, date]:
    """Return inclusive [start, end] dates for the lookback window."""
    now = reference or datetime.now(timezone.utc)
    end = now.date()
    start = end - timedelta(weeks=window_weeks)
    return start, end


def window_stats(reviews: list, window_start: date, window_end: date) -> dict:
    """Summarize actual date coverage for manifest."""
    if not reviews:
        return {
            "requested_start": window_start.isoformat(),
            "requested_end": window_end.isoformat(),
            "actual_start": None,
            "actual_end": None,
            "actual_weeks": 0.0,
        }

    dates = [r.date.astimezone(timezone.utc).date() for r in reviews]
    actual_start = min(dates)
    actual_end = max(dates)
    actual_days = (actual_end - actual_start).days
    return {
        "requested_start": window_start.isoformat(),
        "requested_end": window_end.isoformat(),
        "actual_start": actual_start.isoformat(),
        "actual_end": actual_end.isoformat(),
        "actual_weeks": round(actual_days / 7, 2),
    }


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())
