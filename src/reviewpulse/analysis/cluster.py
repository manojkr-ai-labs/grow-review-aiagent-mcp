"""Clustering, ranking and trend metrics (Phase 2 tasks 2.4-2.9).

Three things here are deliberate reversals of the original plan, each forced by a
measurement on the real corpus (implementation-plan.md §4.2):

* **Ward, not cosine/average linkage.** Average linkage put 98.7% of reviews in a
  single cluster at every k from 2 to 8, and scored the *highest* silhouette
  while doing it — so silhouette cannot be the selection metric. A balance guard
  on cluster share is used instead.
* **Severity ranking, not size ranking.** The largest clusters are generic praise;
  ranking by size buries a 91.8%-negative support cluster below a 4.62-mean-rating
  praise cluster.
* **A trend metric.** The sharpest signal in the window (a post-update chart
  regression) is recent, and window-wide averages hide it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta, timezone

import numpy as np

from reviewpulse.analysis import taxonomy as taxonomy_mod
from reviewpulse.analysis.terms import distinctive_terms, top_terms
from reviewpulse.config import ClusteringSettings
from reviewpulse.models import Review

NEGATIVE_MAX_RATING = 2
QUOTABLE_MIN_WORDS = 12
QUOTABLE_MAX_WORDS = 45


@dataclass
class ClusterStats:
    """One cluster with every metric computed from the data, not the LLM."""

    cluster_key: str
    member_indices: list[int]
    review_ids: list[str]
    size: int
    mean_rating: float | None
    neg_share: float
    priority: float
    early_count: int
    late_count: int
    trend: float | None
    emerging: bool
    terms: list[str]
    example_review_ids: list[str]
    rank: int = 0
    suggested_label: str | None = None


@dataclass
class ClusterOutcome:
    strategy: str
    clusters: list[ClusterStats]
    silhouette: float | None
    attempts: list[dict] = field(default_factory=list)
    unassigned_count: int = 0
    other_share: float = 0.0
    k_requested: int = 0

    @property
    def max_cluster_share(self) -> float:
        assigned = sum(c.size for c in self.clusters)
        if not assigned:
            return 0.0
        return max(c.size for c in self.clusters) / assigned


def effective_k(n_samples: int, k_max: int) -> int:
    """Never ask for more clusters than there are reviews."""
    return max(1, min(k_max, n_samples))


def _fit_ward(vectors: np.ndarray, k: int) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering

    if k <= 1:
        return np.zeros(len(vectors), dtype=int)
    # Euclidean on unit-length vectors is monotonic in cosine distance, which is
    # what lets ward's variance criterion work on embeddings.
    model = AgglomerativeClustering(n_clusters=k, linkage="ward")
    return model.fit_predict(vectors)


def _fit_kmeans(vectors: np.ndarray, k: int, seed: int) -> np.ndarray:
    from sklearn.cluster import KMeans

    if k <= 1:
        return np.zeros(len(vectors), dtype=int)
    model = KMeans(n_clusters=k, random_state=seed, n_init=10)
    return model.fit_predict(vectors)


def _silhouette(vectors: np.ndarray, labels: np.ndarray) -> float | None:
    if len(set(labels.tolist())) < 2 or len(vectors) <= len(set(labels.tolist())):
        return None
    from sklearn.metrics import silhouette_score

    return round(float(silhouette_score(vectors, labels, metric="cosine")), 4)


def balance_share(labels: np.ndarray) -> float:
    """Share of members held by the biggest cluster."""
    if len(labels) == 0:
        return 0.0
    _, counts = np.unique(labels, return_counts=True)
    return float(counts.max() / counts.sum())


def merge_tiny_clusters(
    labels: np.ndarray,
    vectors: np.ndarray,
    size_floor: int,
) -> np.ndarray:
    """Fold clusters below the floor into the nearest surviving centroid.

    Inert on the current corpus (smallest observed cluster is 61) but keeps the
    pipeline safe for sparse weeks.
    """
    labels = labels.copy()
    unique, counts = np.unique(labels, return_counts=True)
    if len(unique) <= 1:
        return labels

    survivors = [label for label, count in zip(unique, counts) if count >= size_floor]
    tiny = [label for label, count in zip(unique, counts) if count < size_floor]
    if not tiny or not survivors:
        return labels

    centroids = {
        label: vectors[labels == label].mean(axis=0) for label in survivors
    }
    for label in tiny:
        for index in np.where(labels == label)[0]:
            vector = vectors[index]
            nearest = min(
                survivors,
                key=lambda s: float(np.linalg.norm(vector - centroids[s])),
            )
            labels[index] = nearest
    return labels


def _window_split(window_end: date, trend_split_weeks: int) -> date:
    return window_end - timedelta(weeks=trend_split_weeks)


def _review_date(review: Review) -> date:
    return review.date.astimezone(timezone.utc).date()


def _build_stats(
    cluster_key: str,
    indices: list[int],
    reviews: list[Review],
    corpus_texts: list[str],
    *,
    split_date: date,
    emerging_ratio: float,
    anchor_terms: list[str] | None = None,
) -> ClusterStats:
    members = [reviews[i] for i in indices]
    ratings = [r.rating for r in members if r.rating is not None]
    mean_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    negatives = sum(1 for r in ratings if r <= NEGATIVE_MAX_RATING)
    neg_share = round(negatives / len(members), 4) if members else 0.0

    late = sum(1 for r in members if _review_date(r) > split_date)
    early = len(members) - late
    trend = round(late / early, 2) if early else None
    emerging = (trend is not None and trend >= emerging_ratio) or (
        early == 0 and late >= 3
    )

    texts = [r.text_clean for r in members]
    terms = anchor_terms or distinctive_terms(texts, corpus_texts, limit=10)
    if not terms:
        terms = top_terms(texts, limit=10)

    return ClusterStats(
        cluster_key=cluster_key,
        member_indices=list(indices),
        review_ids=[r.review_id for r in members],
        size=len(members),
        mean_rating=mean_rating,
        neg_share=neg_share,
        # size x neg_share reduces exactly to the count of 1-2 star reviews, so
        # it is taken from the count directly rather than from the rounded share.
        priority=float(negatives),
        early_count=early,
        late_count=late,
        trend=trend,
        emerging=emerging,
        terms=terms,
        example_review_ids=_pick_examples(members),
    )


def _pick_examples(members: list[Review], limit: int = 3) -> list[str]:
    """Mid-length members make the most legible label samples and quotes."""
    from reviewpulse.sources.language import word_count

    def sort_key(review: Review) -> tuple[int, int]:
        words = word_count(review.text_clean)
        in_band = QUOTABLE_MIN_WORDS <= words <= QUOTABLE_MAX_WORDS
        return (0 if in_band else 1, -words)

    return [r.review_id for r in sorted(members, key=sort_key)[:limit]]


def rank_clusters(
    clusters: list[ClusterStats],
    rank_by: str = "priority",
) -> list[ClusterStats]:
    """Order by severity (size x negative share), falling back to size."""
    if rank_by == "size":
        key = lambda c: (-c.size, -c.priority, c.cluster_key)  # noqa: E731
    else:
        key = lambda c: (-c.priority, -c.size, c.cluster_key)  # noqa: E731
    ordered = sorted(clusters, key=key)
    for position, cluster in enumerate(ordered, start=1):
        cluster.rank = position
    return ordered


def _clusters_from_labels(
    labels: np.ndarray,
    reviews: list[Review],
    *,
    split_date: date,
    emerging_ratio: float,
) -> list[ClusterStats]:
    corpus_texts = [r.text_clean for r in reviews]
    clusters: list[ClusterStats] = []
    for label in sorted(set(labels.tolist())):
        indices = [i for i, value in enumerate(labels) if value == label]
        clusters.append(
            _build_stats(
                f"c{label}",
                indices,
                reviews,
                corpus_texts,
                split_date=split_date,
                emerging_ratio=emerging_ratio,
            )
        )
    return clusters


def cluster_by_keywords(
    reviews: list[Review],
    clustering: ClusteringSettings,
    *,
    k_max: int,
    window_end: date,
    buckets: list[taxonomy_mod.Bucket] | None = None,
) -> ClusterOutcome:
    """Keyword-taxonomy fallback: single-label buckets, top k_max by severity."""
    buckets = buckets if buckets is not None else taxonomy_mod.load_taxonomy()
    groups, used = taxonomy_mod.assign_all(reviews, buckets)
    split_date = _window_split(window_end, clustering.trend_split_weeks)
    corpus_texts = [r.text_clean for r in reviews]

    other_indices = groups.pop(taxonomy_mod.OTHER_BUCKET_ID, [])
    candidates = [
        _build_stats(
            bucket_id,
            indices,
            reviews,
            corpus_texts,
            split_date=split_date,
            emerging_ratio=clustering.emerging_trend_ratio,
            anchor_terms=used[bucket_id].anchor_terms(),
        )
        for bucket_id, indices in groups.items()
    ]
    for cluster in candidates:
        cluster.suggested_label = used[cluster.cluster_key].label

    ranked = rank_clusters(candidates, clustering.rank_by)
    kept = ranked[:k_max]
    dropped = sum(c.size for c in ranked[k_max:])
    # Re-rank so ranks are contiguous 1..len(kept) after the cap.
    kept = rank_clusters(kept, clustering.rank_by)

    unassigned = len(other_indices) + dropped
    return ClusterOutcome(
        strategy="keyword",
        clusters=kept,
        silhouette=None,
        unassigned_count=unassigned,
        other_share=round(len(other_indices) / len(reviews), 4) if reviews else 0.0,
        k_requested=k_max,
    )


def cluster_reviews(
    reviews: list[Review],
    vectors: np.ndarray | None,
    clustering: ClusteringSettings,
    *,
    k_max: int,
    size_floor: int,
    window_end: date,
    buckets: list[taxonomy_mod.Bucket] | None = None,
) -> ClusterOutcome:
    """Cluster with a fallback ladder: ward -> kmeans -> keyword taxonomy.

    Each rung is accepted only if no cluster holds more than
    `max_cluster_share` of members — the guard that catches the mega-cluster
    collapse that average linkage produced on this corpus.
    """
    if not reviews:
        return ClusterOutcome(strategy="none", clusters=[], silhouette=None)

    split_date = _window_split(window_end, clustering.trend_split_weeks)
    emerging_ratio = clustering.emerging_trend_ratio
    attempts: list[dict] = []

    if vectors is not None and len(vectors) == len(reviews) and vectors.size:
        k = effective_k(len(reviews), k_max)
        rungs = (
            ("ward", lambda: _fit_ward(vectors, k)),
            ("kmeans", lambda: _fit_kmeans(vectors, k, clustering.random_seed)),
        )
        for name, fit in rungs:
            labels = np.asarray(fit(), dtype=int)
            labels = merge_tiny_clusters(labels, vectors, size_floor)
            share = balance_share(labels)
            n_clusters = len(set(labels.tolist()))
            # With k=1 a single cluster is the requested answer, not a collapse.
            accepted = k <= 1 or share <= clustering.max_cluster_share
            attempts.append(
                {
                    "strategy": name,
                    "k_requested": k,
                    "clusters": n_clusters,
                    "max_cluster_share": round(share, 4),
                    "silhouette": _silhouette(vectors, labels),
                    "accepted": accepted,
                    "reason": None
                    if accepted
                    else (
                        f"largest cluster holds {share:.1%} of members, above the "
                        f"{clustering.max_cluster_share:.0%} balance guard"
                    ),
                }
            )
            if not accepted:
                continue

            clusters = _clusters_from_labels(
                labels,
                reviews,
                split_date=split_date,
                emerging_ratio=emerging_ratio,
            )
            ranked = rank_clusters(clusters, clustering.rank_by)
            return ClusterOutcome(
                strategy=name,
                clusters=ranked,
                silhouette=_silhouette(vectors, labels),
                attempts=attempts,
                k_requested=k,
            )

    outcome = cluster_by_keywords(
        reviews,
        clustering,
        k_max=k_max,
        window_end=window_end,
        buckets=buckets,
    )
    attempts.append(
        {
            "strategy": "keyword",
            "k_requested": k_max,
            "clusters": len(outcome.clusters),
            "max_cluster_share": round(outcome.max_cluster_share, 4),
            "silhouette": None,
            "accepted": bool(outcome.clusters),
            "reason": "embedding rungs unavailable or rejected by balance guard",
        }
    )

    if not outcome.clusters:
        # Nothing matched the taxonomy. One catch-all theme keeps the pipeline
        # producing an auditable artifact; the themes_in_range check will flag it.
        labels = np.zeros(len(reviews), dtype=int)
        outcome = ClusterOutcome(
            strategy="catch_all",
            clusters=rank_clusters(
                _clusters_from_labels(
                    labels,
                    reviews,
                    split_date=split_date,
                    emerging_ratio=emerging_ratio,
                ),
                clustering.rank_by,
            ),
            silhouette=None,
            k_requested=k_max,
        )
        attempts.append(
            {
                "strategy": "catch_all",
                "k_requested": k_max,
                "clusters": 1,
                "max_cluster_share": 1.0,
                "silhouette": None,
                "accepted": True,
                "reason": "no taxonomy bucket matched any review",
            }
        )

    outcome.attempts = attempts
    return outcome
