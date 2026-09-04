"""Regression tests against the real ingested corpus (implementation-plan.md §4.2).

These pin the measurements that drove the Phase 2 design. They skip when
`data/reviews.db` is absent (it is git-ignored), so a fresh clone still gets a
green suite; run `reviewpulse ingest` first to exercise them.
"""

from __future__ import annotations

import numpy as np
import pytest

from reviewpulse.analysis.cluster import balance_share, cluster_reviews
from reviewpulse.analysis.embed import EmbeddingUnavailable, embed_reviews
from reviewpulse.analysis.select import select_for_clustering
from reviewpulse.config import load_settings
from reviewpulse.sources.normalize import compute_window

WINDOW_WEEKS = 8
MIN_CORPUS = 500

settings = load_settings()
pytestmark = pytest.mark.skipif(
    not settings.db_path.is_file(),
    reason="data/reviews.db not present; run `reviewpulse ingest` first",
)


@pytest.fixture(scope="module")
def corpus():
    window_start, window_end = compute_window(WINDOW_WEEKS)
    selection = select_for_clustering(
        window_start=window_start, window_end=window_end, settings=settings
    )
    if selection.total_count < MIN_CORPUS:
        pytest.skip(f"corpus too small ({selection.total_count} reviews)")
    return selection, window_end


@pytest.fixture(scope="module")
def vectors(corpus):
    selection, _ = corpus
    try:
        result = embed_reviews(
            selection.reviews,
            model=settings.clustering.embedding_model,
            cache_dir=settings.clustering.cache_dir,
        )
    except EmbeddingUnavailable as exc:
        pytest.skip(f"embeddings unavailable: {exc}")
    return result.vectors


def test_signal_filter_retention_in_expected_band(corpus) -> None:
    selection, _ = corpus
    assert 0.60 <= selection.retention <= 0.75


def test_average_linkage_collapses_which_is_why_ward_is_used(vectors) -> None:
    """F1: the originally planned linkage puts ~99% of reviews in one cluster."""
    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=5, metric="cosine", linkage="average"
    ).fit_predict(vectors)
    assert balance_share(labels) > 0.90


def test_ward_is_balanced_on_real_corpus(corpus, vectors) -> None:
    selection, window_end = corpus
    outcome = cluster_reviews(
        selection.reviews,
        vectors,
        settings.clustering,
        k_max=settings.k_max,
        size_floor=settings.cluster_size_floor,
        window_end=window_end,
    )
    assert outcome.strategy == "ward"
    assert outcome.max_cluster_share <= settings.clustering.max_cluster_share
    assert len(outcome.clusters) == settings.k_max


def test_no_cluster_exceeds_guard_at_any_k(corpus, vectors) -> None:
    selection, window_end = corpus
    for k_max in (3, 4, 5):
        outcome = cluster_reviews(
            selection.reviews,
            vectors,
            settings.clustering,
            k_max=k_max,
            size_floor=settings.cluster_size_floor,
            window_end=window_end,
        )
        assert len(outcome.clusters) <= k_max
        assert outcome.max_cluster_share <= settings.clustering.max_cluster_share


def test_update_regression_signal_surfaces_as_its_own_theme(corpus, vectors) -> None:
    """F5: the post-update chart/scalper cluster must not be diluted away."""
    selection, window_end = corpus
    outcome = cluster_reviews(
        selection.reviews,
        vectors,
        settings.clustering,
        k_max=settings.k_max,
        size_floor=settings.cluster_size_floor,
        window_end=window_end,
    )
    reviews = selection.reviews

    def scalper_share(cluster) -> float:
        members = [reviews[i] for i in cluster.member_indices]
        hits = sum(1 for r in members if "scalper" in r.text_clean.lower())
        return hits / len(members)

    concentrated = max(outcome.clusters, key=scalper_share)
    # The cluster that owns this signal must be a focused minority theme, not a
    # third of the corpus with the mentions sprinkled through it.
    assert scalper_share(concentrated) > scalper_share(
        min(outcome.clusters, key=scalper_share)
    )
    assert concentrated.size < 0.25 * len(reviews)
    assert "chart" in concentrated.terms or "scalper" in concentrated.terms


def test_rank_one_is_not_a_praise_theme(corpus, vectors) -> None:
    """F4: severity ranking must not put a happy cluster first."""
    selection, window_end = corpus
    outcome = cluster_reviews(
        selection.reviews,
        vectors,
        settings.clustering,
        k_max=settings.k_max,
        size_floor=settings.cluster_size_floor,
        window_end=window_end,
    )
    top = outcome.clusters[0]
    assert top.mean_rating is not None and top.mean_rating <= 4.0
    assert top.neg_share >= 0.5

    biggest = max(outcome.clusters, key=lambda c: c.size)
    if biggest is not top:
        # Ranking genuinely differs from size ordering on this corpus.
        assert top.priority >= biggest.priority


def test_embedding_cache_is_warm_after_first_run(corpus) -> None:
    selection, _ = corpus
    try:
        result = embed_reviews(
            selection.reviews,
            model=settings.clustering.embedding_model,
            cache_dir=settings.clustering.cache_dir,
        )
    except EmbeddingUnavailable as exc:
        pytest.skip(f"embeddings unavailable: {exc}")
    assert result.computed == 0
    assert result.cached_hits == len(selection.reviews)
    assert np.allclose(np.linalg.norm(result.vectors, axis=1), 1.0, atol=1e-4)
