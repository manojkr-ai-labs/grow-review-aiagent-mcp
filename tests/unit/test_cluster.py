"""Clustering, ranking, trend and guard-rail tests (Phase 2 tasks 2.4-2.9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from reviewpulse.analysis.cluster import (
    balance_share,
    cluster_reviews,
    effective_k,
    merge_tiny_clusters,
    rank_clusters,
)
from reviewpulse.analysis.select import apply_signal_filter, is_signal
from reviewpulse.analysis.taxonomy import Bucket, load_taxonomy
from reviewpulse.config import ClusteringSettings
from reviewpulse.models import Review

WINDOW_END = datetime(2026, 8, 29, tzinfo=timezone.utc).date()


def make_review(
    index: int,
    text: str,
    rating: int,
    *,
    days_ago: int = 1,
) -> Review:
    return Review(
        review_id=f"r{index:04d}",
        source="play",
        rating=rating,
        text_clean=text,
        date=datetime(2026, 8, 29, tzinfo=timezone.utc) - timedelta(days=days_ago),
    )


def synthetic_corpus() -> tuple[list[Review], np.ndarray]:
    """Three well-separated topics with distinct ratings."""
    topics = [
        ("customer support never replies to my ticket about this problem", 1),
        ("brokerage charges are far too high for every single trade i place", 2),
        ("charts are smooth and the interface is easy for new investors here", 5),
    ]
    reviews: list[Review] = []
    vectors: list[np.ndarray] = []
    for topic_index, (text, rating) in enumerate(topics):
        base = np.zeros(6, dtype=np.float32)
        base[topic_index] = 1.0
        for member in range(10):
            reviews.append(
                make_review(
                    topic_index * 10 + member,
                    f"{text} number {member}",
                    rating,
                    days_ago=1 + member,
                )
            )
            jitter = np.zeros(6, dtype=np.float32)
            jitter[3 + topic_index] = 0.05 * member
            vector = base + jitter
            vectors.append(vector / np.linalg.norm(vector))
    return reviews, np.vstack(vectors)


def default_clustering(**overrides) -> ClusteringSettings:
    settings = ClusteringSettings()
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


@pytest.mark.parametrize(
    "n_samples,k_max,expected",
    [(1260, 5, 5), (3, 5, 3), (1, 5, 1), (0, 5, 1), (10, 1, 1)],
)
def test_effective_k_never_exceeds_k_max(n_samples, k_max, expected) -> None:
    assert effective_k(n_samples, k_max) == expected


def test_k_max_never_exceeded_regardless_of_review_count() -> None:
    reviews, vectors = synthetic_corpus()
    for k_max in (1, 2, 3, 5, 8):
        outcome = cluster_reviews(
            reviews,
            vectors,
            default_clustering(),
            k_max=k_max,
            size_floor=1,
            window_end=WINDOW_END,
        )
        assert len(outcome.clusters) <= k_max


def test_ward_recovers_separated_topics() -> None:
    reviews, vectors = synthetic_corpus()
    outcome = cluster_reviews(
        reviews,
        vectors,
        default_clustering(),
        k_max=3,
        size_floor=1,
        window_end=WINDOW_END,
    )
    assert outcome.strategy == "ward"
    assert sorted(c.size for c in outcome.clusters) == [10, 10, 10]


def test_balance_guard_rejects_mega_cluster_and_falls_back() -> None:
    """The F1 regression: a partition with a 98% cluster must not be accepted."""
    # 39 near-identical points plus one outlier: ward at k=2 yields 39/1.
    vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (39, 1))
    vectors = np.vstack([vectors, np.array([[0.0, 1.0]], dtype=np.float32)])
    vectors += np.random.default_rng(0).normal(0, 1e-4, vectors.shape).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    reviews = [
        make_review(i, f"charges are too high for trade {i}", 1 + (i % 2))
        for i in range(40)
    ]

    outcome = cluster_reviews(
        reviews,
        vectors,
        default_clustering(max_cluster_share=0.60),
        k_max=2,
        size_floor=1,
        window_end=WINDOW_END,
    )

    # Ward and KMeans both split 39/1 here, so both must be rejected and the
    # ladder must descend. A genuinely single-topic corpus cannot be balanced,
    # so the final rung is accepted and the orchestrator's `balanced` check is
    # what reports the residual imbalance.
    assert outcome.strategy != "ward"
    for strategy in ("ward", "kmeans"):
        attempt = next(a for a in outcome.attempts if a["strategy"] == strategy)
        assert attempt["accepted"] is False
        assert "balance guard" in attempt["reason"]
        assert attempt["max_cluster_share"] > 0.60


def test_balance_share() -> None:
    assert balance_share(np.array([0, 0, 0, 1])) == 0.75
    assert balance_share(np.array([0, 1])) == 0.5
    assert balance_share(np.array([], dtype=int)) == 0.0


def test_merge_tiny_clusters_folds_into_nearest_centroid() -> None:
    vectors = np.array(
        [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02], [0.0, 1.0]], dtype=np.float32
    )
    labels = np.array([0, 0, 0, 1])
    merged = merge_tiny_clusters(labels, vectors, size_floor=2)
    assert len(set(merged.tolist())) == 1


def test_merge_tiny_clusters_is_noop_above_floor() -> None:
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    labels = np.array([0, 0, 1, 1])
    assert merge_tiny_clusters(labels, vectors, size_floor=2).tolist() == [0, 0, 1, 1]


def test_severity_ranking_beats_size_ranking() -> None:
    """F4: a big happy cluster must not outrank a smaller furious one."""
    reviews = [make_review(i, f"charges too high {i}", 1) for i in range(20)]
    reviews += [make_review(100 + i, f"easy to use and simple {i}", 5) for i in range(60)]
    vectors = np.vstack(
        [np.array([[1.0, 0.0]], dtype=np.float32)] * 20
        + [np.array([[0.0, 1.0]], dtype=np.float32)] * 60
    )

    by_priority = cluster_reviews(
        reviews, vectors, default_clustering(rank_by="priority"),
        k_max=2, size_floor=1, window_end=WINDOW_END,
    )
    assert by_priority.clusters[0].size == 20
    assert by_priority.clusters[0].neg_share == 1.0

    by_size = cluster_reviews(
        reviews, vectors, default_clustering(rank_by="size"),
        k_max=2, size_floor=1, window_end=WINDOW_END,
    )
    assert by_size.clusters[0].size == 60


def test_priority_equals_negative_review_count() -> None:
    reviews = [make_review(i, f"support never replies {i}", 1) for i in range(6)]
    reviews += [make_review(50 + i, f"support never replies ok {i}", 5) for i in range(4)]
    vectors = np.vstack([np.array([[1.0, 0.0]], dtype=np.float32)] * 10)
    outcome = cluster_reviews(
        reviews, vectors, default_clustering(), k_max=1, size_floor=1,
        window_end=WINDOW_END,
    )
    cluster = outcome.clusters[0]
    assert cluster.size == 10
    assert cluster.neg_share == 0.6
    assert cluster.priority == 6.0


def test_rank_clusters_assigns_contiguous_ranks() -> None:
    reviews = [make_review(i, f"text {i}", 1) for i in range(4)]
    vectors = np.vstack([np.array([[1.0, 0.0]], dtype=np.float32)] * 4)
    outcome = cluster_reviews(
        reviews, vectors, default_clustering(), k_max=1, size_floor=1,
        window_end=WINDOW_END,
    )
    ranked = rank_clusters(outcome.clusters, "priority")
    assert [c.rank for c in ranked] == list(range(1, len(ranked) + 1))


def test_trend_flags_recent_spike() -> None:
    """F5: a theme concentrated in the last 4 weeks is flagged emerging."""
    reviews = [
        make_review(i, f"scalper button appears after update {i}", 1, days_ago=3)
        for i in range(9)
    ]
    reviews += [
        make_review(50 + i, f"scalper button appears after update {i}", 1, days_ago=50)
        for i in range(3)
    ]
    vectors = np.vstack([np.array([[1.0, 0.0]], dtype=np.float32)] * 12)

    outcome = cluster_reviews(
        reviews, vectors, default_clustering(trend_split_weeks=4),
        k_max=1, size_floor=1, window_end=WINDOW_END,
    )
    cluster = outcome.clusters[0]
    assert cluster.late_count == 9
    assert cluster.early_count == 3
    assert cluster.trend == 3.0
    assert cluster.emerging is True


def test_keyword_fallback_used_when_no_vectors() -> None:
    reviews = [
        make_review(i, "customer care never replies to my complaint at all", 1)
        for i in range(5)
    ]
    reviews += [
        make_review(50 + i, "brokerage charges are too high on every trade", 2)
        for i in range(5)
    ]
    outcome = cluster_reviews(
        reviews, None, default_clustering(), k_max=5, size_floor=1,
        window_end=WINDOW_END, buckets=load_taxonomy(),
    )
    assert outcome.strategy == "keyword"
    labels = {c.suggested_label for c in outcome.clusters}
    assert "Customer support responsiveness" in labels
    assert "Charges and brokerage" in labels


def test_keyword_fallback_caps_at_k_max_and_reports_other() -> None:
    buckets = load_taxonomy()
    reviews = []
    texts = [
        "customer care never replies to my ticket",
        "brokerage charges are too high here",
        "withdraw my money it is stuck now",
        "kyc verification is pending for days",
        "chart interface is cluttered and confusing",
        "sip in mutual fund did not process",
        "zerodha provides this feature but not available here",
    ]
    for topic, text in enumerate(texts):
        for member in range(4):
            reviews.append(make_review(topic * 10 + member, f"{text} {member}", 1))
    reviews.append(make_review(999, "the sky is unusually blue today my friend", 5))

    outcome = cluster_reviews(
        reviews, None, default_clustering(), k_max=3, size_floor=1,
        window_end=WINDOW_END, buckets=buckets,
    )
    assert len(outcome.clusters) == 3
    assert [c.rank for c in outcome.clusters] == [1, 2, 3]
    assert outcome.other_share > 0
    assert outcome.unassigned_count >= 1


def test_signal_filter_keeps_complaints_and_long_praise() -> None:
    clustering = default_clustering(signal_max_rating=3, signal_min_words=20)
    short_praise = make_review(1, "super app nice work", 5)
    short_complaint = make_review(2, "worst app ever do not install", 1)
    long_praise = make_review(3, " ".join(["word"] * 25), 5)

    assert is_signal(short_praise, clustering) is False
    assert is_signal(short_complaint, clustering) is True
    assert is_signal(long_praise, clustering) is True

    result = apply_signal_filter([short_praise, short_complaint, long_praise], clustering)
    assert result.dropped_low_signal == 1
    assert result.total_count == 3
    assert result.retention == pytest.approx(2 / 3, abs=1e-3)


def test_empty_corpus_returns_no_clusters() -> None:
    outcome = cluster_reviews(
        [], None, default_clustering(), k_max=5, size_floor=3, window_end=WINDOW_END
    )
    assert outcome.clusters == []
    assert outcome.strategy == "none"


def test_bucket_matching_is_case_insensitive() -> None:
    bucket = Bucket(id="x", label="X", priority=1, keywords=["brokerage"])
    assert bucket.matches("BROKERAGE is high") is True
    assert bucket.matches("nothing relevant") is False
