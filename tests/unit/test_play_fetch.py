"""Downloader tests — the Play endpoint is stubbed, so these never hit the network."""

from __future__ import annotations

import csv
import sys
import types
from datetime import date, datetime, timedelta

import pytest

from reviewpulse.sources.play_fetch import (
    EXPORT_COLUMNS,
    PlayFetchError,
    fetch_reviews,
    write_export_csv,
)

WINDOW_END = date(2026, 8, 31)
WINDOW_START = WINDOW_END - timedelta(weeks=8)


class _Token:
    def __init__(self, token: str | None) -> None:
        self.token = token


def _review(review_id: str, day: date, text: str = "solid app", score: int = 4) -> dict:
    return {
        "reviewId": review_id,
        "userName": "Real Person",
        "content": text,
        "score": score,
        "at": datetime(day.year, day.month, day.day, 12, 0, 0),
    }


def _install_stub(monkeypatch: pytest.MonkeyPatch, pages: list[list[dict]]) -> list[int]:
    """Serve `pages` one call at a time; return a list recording call count."""
    calls: list[int] = []

    def fake_reviews(app_id, **kwargs):
        index = len(calls)
        calls.append(index)
        if index >= len(pages):
            return [], _Token(None)
        has_more = index < len(pages) - 1
        return pages[index], _Token("next" if has_more else None)

    module = types.ModuleType("google_play_scraper")
    module.reviews = fake_reviews
    module.Sort = types.SimpleNamespace(NEWEST=2)
    monkeypatch.setitem(sys.modules, "google_play_scraper", module)
    return calls


def test_fetch_collects_reviews_inside_window(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [[_review("a", WINDOW_END - timedelta(days=1)), _review("b", WINDOW_END - timedelta(days=5))]]
    _install_stub(monkeypatch, pages)

    batch = fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)

    assert [row["reviewId"] for row in batch.rows] == ["b", "a"]  # oldest first


def test_fetch_stops_paging_once_older_than_window(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        [_review("recent", WINDOW_END - timedelta(days=2))],
        [_review("old", WINDOW_START - timedelta(days=3))],
        [_review("never-reached", WINDOW_END - timedelta(days=1))],
    ]
    calls = _install_stub(monkeypatch, pages)

    batch = fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)

    assert [row["reviewId"] for row in batch.rows] == ["recent"]
    assert len(calls) == 2
    assert batch.reached_window_start is True


def test_fetch_flags_partial_coverage_when_page_cap_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        [_review("a", WINDOW_END - timedelta(days=1))],
        [_review("b", WINDOW_END - timedelta(days=2))],
        [_review("c", WINDOW_END - timedelta(days=3))],
    ]
    _install_stub(monkeypatch, pages)

    batch = fetch_reviews(
        "com.example", WINDOW_START, WINDOW_END, max_pages=2, sleep_ms=0
    )

    assert batch.reached_window_start is False
    assert batch.oldest_seen == WINDOW_END - timedelta(days=2)


def test_fetch_deduplicates_repeated_review_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    day = WINDOW_END - timedelta(days=4)
    pages = [[_review("dup", day)], [_review("dup", day)]]
    _install_stub(monkeypatch, pages)

    batch = fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)

    assert len(batch.rows) == 1


def test_fetch_raises_when_library_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "google_play_scraper", None)

    with pytest.raises(PlayFetchError):
        fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)


def test_export_csv_matches_ingest_columns_and_omits_author(monkeypatch, tmp_path) -> None:
    _install_stub(monkeypatch, [[_review("a", WINDOW_END - timedelta(days=1), text="great")]])
    batch = fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)

    path = write_export_csv(batch, tmp_path / "export.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(EXPORT_COLUMNS)
        written = list(reader)

    assert written[0]["Review Text"] == "great"
    assert written[0]["Star Rating"] == "4"
    assert "Real Person" not in path.read_text(encoding="utf-8")


def test_export_csv_skips_empty_text(monkeypatch, tmp_path) -> None:
    _install_stub(monkeypatch, [[_review("a", WINDOW_END - timedelta(days=1), text="   ")]])
    batch = fetch_reviews("com.example", WINDOW_START, WINDOW_END, sleep_ms=0)

    path = write_export_csv(batch, tmp_path / "export.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
