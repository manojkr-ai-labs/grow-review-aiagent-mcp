"""PII scrubber unit tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from reviewpulse.models import RawReview
from reviewpulse.privacy.scrubber import contains_pii, scrub_raw_review, scrub_text
from reviewpulse.store.sqlite import ReviewStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PII_CASES = json.loads((FIXTURES / "pii_reviews.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PII_CASES, ids=[c["id"] for c in PII_CASES])
def test_scrub_text_patterns(case: dict) -> None:
    cleaned, flags = scrub_text(case["text"])
    assert cleaned == case["expected_text"]
    assert flags == case["expected_flags"]


def test_scrub_raw_review_drops_author(tmp_path: Path) -> None:
    raw = RawReview(
        source="play",
        external_id="r1",
        rating=2,
        title="Issue",
        text="Email user@example.com about my account",
        date=datetime(2026, 8, 1, tzinfo=timezone.utc),
        author="Secret User",
    )
    review = scrub_raw_review(raw)
    assert review.text_clean == "Email [email] about my account"
    assert "email" in review.scrub_flags
    assert review.review_id

    store = ReviewStore(tmp_path / "test.db")
    store.upsert(review)
    assert store.has_author_column() is False
    stored = store.get_by_id(review.review_id)
    assert stored is not None
    assert "Secret" not in stored.text_clean
    assert stored.title_clean == "Issue"


def test_contains_pii_detects_email() -> None:
    assert contains_pii("reach me at a@b.co")
    assert not contains_pii("Great mutual fund app")


def test_scrub_flags_on_title_and_text() -> None:
    raw = RawReview(
        source="play",
        text="Normal review body",
        title="Title with +91 9876543210",
        date=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    review = scrub_raw_review(raw)
    assert review.title_clean == "Title with [phone]"
    assert "phone" in review.scrub_flags
