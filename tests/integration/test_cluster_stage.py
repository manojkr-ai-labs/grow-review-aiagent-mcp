"""End-to-end cluster stage test on a synthetic store (Phase 2 tasks 2.16-2.18).

Uses keyword mode so the test needs no model download; the embedding path is
covered by tests/unit/test_embed.py and verified against the real corpus in
tests/integration/test_cluster_real_corpus.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from reviewpulse.config import load_settings
from reviewpulse.models import Review
from reviewpulse.orchestrator import run_cluster_stage
from reviewpulse.store.sqlite import ReviewStore

TOPICS = [
    ("customer care never responds to my support ticket about this account", 1, 14),
    ("brokerage charges are far too high on every single trade i place here", 2, 12),
    ("i cannot withdraw my money it has been stuck on hold for many days", 1, 10),
    ("the chart interface is cluttered and the layout is confusing to use", 2, 8),
    ("zerodha provides this feature but it is not available on this platform", 3, 6),
]


@pytest.fixture()
def populated_db(tmp_path):
    store = ReviewStore(tmp_path / "reviews.db")
    now = datetime.now(timezone.utc)
    reviews = []
    for topic_index, (text, rating, days) in enumerate(TOPICS):
        for member in range(12):
            reviews.append(
                Review(
                    review_id=f"t{topic_index}m{member:03d}",
                    source="play",
                    rating=rating,
                    text_clean=f"{text} instance {member}",
                    date=now - timedelta(days=days + member),
                )
            )
    # Short 5-star praise that the signal filter must drop.
    for member in range(20):
        reviews.append(
            Review(
                review_id=f"praise{member:03d}",
                source="play",
                rating=5,
                text_clean=f"super app nice {member}",
                date=now - timedelta(days=5),
            )
        )
    store.upsert_many(reviews)
    return tmp_path / "reviews.db"


def run_stage(populated_db, tmp_path, **kwargs):
    return run_cluster_stage(
        window_weeks=8,
        settings=load_settings(),
        db_path=populated_db,
        runs_dir=tmp_path / "runs",
        mode="keyword_fallback",
        use_llm=False,
        **kwargs,
    )


def test_cluster_stage_produces_capped_ranked_themes(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)

    assert result.theme_count <= 5
    assert 3 <= result.theme_count <= 5
    assert [t.rank for t in result.themes] == list(range(1, result.theme_count + 1))
    assert [t.theme_id for t in result.themes] == [
        f"t{i}" for i in range(1, result.theme_count + 1)
    ]
    # Ranked by severity: priority must be non-increasing.
    priorities = [t.priority for t in result.themes]
    assert priorities == sorted(priorities, reverse=True)


def test_signal_filter_drops_short_praise(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    assert result.total_reviews == 80
    assert result.clustered_reviews == 60
    assert result.dropped_low_signal == 20


def test_k_max_override_is_respected(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path, k_max=3)
    assert result.theme_count == 3


def test_artifacts_are_written_with_traceable_members(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)

    clusters = json.loads(open(result.clusters_path, encoding="utf-8").read())
    debug = json.loads(open(result.debug_path, encoding="utf-8").read())
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())

    assert clusters["stage"] == "cluster"
    assert len(clusters["themes"]) == result.theme_count
    for theme in clusters["themes"]:
        assert theme["size"] == len(theme["review_ids"])
        assert theme["cluster_key"]
        assert theme["example_review_ids"]

    assert debug["strategy"] == result.strategy
    assert debug["attempts"]
    assert debug["size_histogram"]
    assert debug["selection"]["dropped_low_signal"] == 20
    assert debug["clusters"][0]["top_terms"]

    assert manifest["stage"] == "cluster"
    assert manifest["checks"]["themes_capped"] is True
    assert manifest["clustering"]["rank_by"] == "priority"


def test_stats_match_stored_reviews(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    store = ReviewStore(populated_db)

    for theme in result.themes:
        members = [store.get_by_id(rid) for rid in theme.review_ids]
        assert all(m is not None for m in members)
        ratings = [m.rating for m in members if m.rating is not None]
        assert theme.mean_rating == pytest.approx(sum(ratings) / len(ratings), abs=0.01)
        negatives = sum(1 for r in ratings if r <= 2)
        assert theme.priority == float(negatives)
        assert theme.neg_share == pytest.approx(negatives / len(members), abs=1e-4)


def test_all_exit_criteria_checks_pass(populated_db, tmp_path) -> None:
    result = run_stage(populated_db, tmp_path)
    assert result.checks["themes_capped"] is True
    assert result.checks["balanced"] is True
    assert result.checks["labels_are_surfaces"] is True
    assert result.checks["labels_distinct"] is True
    assert result.checks["stats_from_data"] is True
    assert result.checks["rank1_actionable"] is True


def test_empty_window_raises(tmp_path) -> None:
    ReviewStore(tmp_path / "empty.db")
    with pytest.raises(ValueError, match="No reviews to cluster"):
        run_cluster_stage(
            window_weeks=8,
            settings=load_settings(),
            db_path=tmp_path / "empty.db",
            runs_dir=tmp_path / "runs",
            mode="keyword_fallback",
            use_llm=False,
        )
