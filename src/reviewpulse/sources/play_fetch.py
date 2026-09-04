"""Download public Play Store reviews into an export CSV.

Uses the same public reviews endpoint the Play Store web page calls, via the
`google-play-scraper` package. Output is written in the Play Console export
column layout that `play_export.PlayExportSource` already understands, so the
downloaded file and a hand-exported file are interchangeable.

The reviewer name returned by the endpoint is never written to disk — dropping
it here keeps `data/raw/` free of PII, independent of the scrub stage.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

EXPORT_COLUMNS = (
    "Review ID",
    "Review Title",
    "Review Text",
    "Star Rating",
    "Review Date",
)

PAGE_SIZE = 200
MAX_PAGES = 120
INCREMENTAL_OVERLAP_DAYS = 1


class PlayFetchError(RuntimeError):
    """Raised when reviews cannot be downloaded."""


@dataclass
class FetchBatch:
    """Downloaded reviews plus how far back the pager actually got."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    oldest_seen: date | None = None
    reached_window_start: bool = False

    def __len__(self) -> int:
        return len(self.rows)


def incremental_fetch_start(
    window_start: date,
    newest_stored: date | None,
    *,
    overlap_days: int = INCREMENTAL_OVERLAP_DAYS,
) -> tuple[date, str]:
    """Pager start for a weekly tick: full window, or newest stored minus overlap.

    Returns `(fetch_start, fetch_mode)` where mode is `full` or `incremental`.
    """
    if newest_stored is None:
        return window_start, "full"
    cutoff = newest_stored - timedelta(days=overlap_days)
    start = max(window_start, cutoff)
    mode = "incremental" if start > window_start else "full"
    return start, mode


def fetch_reviews(
    package_id: str,
    window_start: date,
    window_end: date,
    *,
    lang: str = "en",
    country: str = "in",
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
    sleep_ms: int = 200,
) -> FetchBatch:
    """Page newest-first until reviews fall before `window_start`.

    Paging also stops at `max_pages`; the returned batch records whether the
    window start was actually reached so callers can flag partial coverage.
    """
    try:
        from google_play_scraper import Sort, reviews as gp_reviews
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise PlayFetchError(
            "google-play-scraper is not installed. Run: pip install google-play-scraper"
        ) from exc

    import time

    collected: dict[str, dict[str, Any]] = {}
    token = None
    pages = 0
    oldest_seen: date | None = None
    reached_window_start = False

    for _ in range(max_pages):
        pages += 1
        try:
            batch, token = gp_reviews(
                package_id,
                lang=lang,
                country=country,
                sort=Sort.NEWEST,
                count=page_size,
                continuation_token=token,
            )
        except Exception as exc:  # network / upstream layout changes
            raise PlayFetchError(f"Play Store request failed: {exc}") from exc

        if not batch:
            reached_window_start = True  # endpoint exhausted; nothing older exists
            break

        for item in batch:
            review_date = _to_utc(item.get("at"))
            if review_date is None:
                continue
            day = review_date.date()
            oldest_seen = day if oldest_seen is None else min(oldest_seen, day)
            if window_start <= day <= window_end:
                key = item.get("reviewId") or f"{day}-{hash(item.get('content'))}"
                collected[key] = {**item, "_utc": review_date}

        if oldest_seen is not None and oldest_seen < window_start:
            reached_window_start = True
            break
        if token is None or getattr(token, "token", None) is None:
            reached_window_start = True
            break
        if sleep_ms:
            time.sleep(sleep_ms / 1000)

    return FetchBatch(
        rows=sorted(collected.values(), key=lambda item: item["_utc"]),
        pages=pages,
        oldest_seen=oldest_seen,
        reached_window_start=reached_window_start,
    )


def resolve_app(package_id: str, *, lang: str = "en", country: str = "in") -> dict[str, str]:
    """Look up the store listing so runs can show which app they pulled.

    Best-effort: an identity lookup failing must not abort a review download.
    """
    try:
        from google_play_scraper import app

        listing = app(package_id, lang=lang, country=country)
    except Exception:
        return {}
    return {
        "title": str(listing.get("title") or ""),
        "developer": str(listing.get("developer") or ""),
    }


def write_export_csv(batch: FetchBatch | list[dict[str, Any]], path: Path) -> Path:
    """Write fetched reviews in Play Console export column order."""
    rows = batch.rows if isinstance(batch, FetchBatch) else batch
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPORT_COLUMNS))
        writer.writeheader()
        for row in _to_export_rows(rows):
            writer.writerow(row)
    return path


def _to_export_rows(rows: list[dict[str, Any]]) -> Iterator[dict[str, str]]:
    for item in rows:
        text = (item.get("content") or "").strip()
        if not text:
            continue
        yield {
            "Review ID": item.get("reviewId") or "",
            "Review Title": "",
            "Review Text": text,
            "Star Rating": str(item.get("score") or ""),
            "Review Date": item["_utc"].strftime("%Y-%m-%d %H:%M:%S"),
        }


def _to_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.astimezone()  # endpoint returns naive local time
    return value.astimezone(timezone.utc)
