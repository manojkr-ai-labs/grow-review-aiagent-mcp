"""Ingestion and storage integration tests."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reviewpulse.config import Settings
from reviewpulse.orchestrator import ingest_reviews
from reviewpulse.sources.normalize import compute_window, filter_window
from reviewpulse.store.sqlite import ReviewStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_EXPORT = FIXTURES / "sample_play_export.csv"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Filters off by default so window/dedupe tests stay focused."""
    return Settings(db_path=tmp_path / "reviews.db", min_words=0, english_only=False)


@pytest.fixture
def filtered_settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "reviews.db", min_words=8, english_only=True)


def test_ingest_sample_export(settings: Settings, tmp_path: Path) -> None:
    result = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=settings,
        runs_dir=tmp_path / "runs",
    )

    assert result.accepted_count == 8
    assert result.inserted_count == 8
    assert result.deduped_count == 0

    store = ReviewStore(settings.db_path)
    assert store.count() == 8
    assert store.has_author_column() is False


def test_ingest_drops_short_reviews(filtered_settings: Settings, tmp_path: Path) -> None:
    # play-007 ("Best investing app in India. Highly recommend.") is 7 words.
    result = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=filtered_settings,
        runs_dir=tmp_path / "runs",
    )

    assert result.dropped_too_short == 1
    assert result.accepted_count == 7
    assert ReviewStore(filtered_settings.db_path).count() == 7


def test_ingest_refreshes_filtered_export(
    filtered_settings: Settings, tmp_path: Path
) -> None:
    result = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=filtered_settings,
        runs_dir=tmp_path / "runs",
    )

    export_path = Path(result.export_path)
    assert export_path.name == "play_store.csv"
    assert result.export_count == 7

    with export_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 7
    assert all(int(row["word_count"]) >= 8 for row in rows)
    # The 7-word review must not survive into the export.
    assert all("Highly recommend" not in row["text_clean"] for row in rows)


def test_ingest_records_filter_settings_in_manifest(
    filtered_settings: Settings, tmp_path: Path
) -> None:
    result = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=filtered_settings,
        runs_dir=tmp_path / "runs",
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["filters"]["min_words"] == 8
    assert manifest["filters"]["english_only"] is True
    assert manifest["counts"]["dropped_too_short"] == 1

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["stage"] == "ingest"
    assert manifest["window"]["requested_start"]
    assert manifest["window"]["actual_start"]


def test_ingest_is_idempotent(settings: Settings, tmp_path: Path) -> None:
    ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=settings,
        runs_dir=tmp_path / "runs",
    )
    second = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=settings,
        runs_dir=tmp_path / "runs",
    )

    assert second.inserted_count == 0
    assert second.deduped_count == 8
    assert ReviewStore(settings.db_path).count() == 8


def test_window_filter_excludes_old_reviews(settings: Settings, tmp_path: Path) -> None:
    # 1-week window from a fixed reference should drop July reviews in the sample.
    reference = datetime(2026, 8, 31, tzinfo=timezone.utc)
    window_start, window_end = compute_window(1, reference=reference)

    result = ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=1,
        settings=settings,
        runs_dir=tmp_path / "runs",
    )

    store = ReviewStore(settings.db_path)
    reviews = store.get_reviews(window_start, window_end)
    assert result.accepted_count == len(reviews)
    for review in reviews:
        assert filter_window(
            type("R", (), {"date": review.date})(),
            window_start,
            window_end,
        )


def test_get_reviews_window_query(settings: Settings, tmp_path: Path) -> None:
    ingest_reviews(
        SAMPLE_EXPORT,
        window_weeks=12,
        settings=settings,
        runs_dir=tmp_path / "runs",
    )
    store = ReviewStore(settings.db_path)
    end = datetime(2026, 8, 31, tzinfo=timezone.utc).date()
    start = end - timedelta(weeks=12)
    reviews = store.get_reviews(start, end)
    assert len(reviews) == 8
