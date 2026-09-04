"""Turn ranked clusters into labeled `Theme` objects (Phase 2 task 2.15).

Two safeguards come straight from the Phase 1 data:

* **Stratified sampling.** Clusters span mean ratings 1.6-4.7, so a head-of-list
  sample misreads mixed clusters; samples are drawn round-robin across the
  ratings actually present.
* **Sentiment-label rejection.** Embeddings separate this corpus by sentiment, so
  the model is prone to answering "Negative feedback". Such labels are rejected,
  re-asked once with a stricter prompt, then replaced by a keyword-derived label.

All themes are named in **one** call rather than one call each, so the naming
rules and the response schema are sent once per run instead of once per theme.
Only the rejected themes are re-sent on the retry, which caps a run at two calls
regardless of how many themes there are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from reviewpulse.analysis import taxonomy as taxonomy_mod
from reviewpulse.analysis.cluster import (
    QUOTABLE_MAX_WORDS,
    QUOTABLE_MIN_WORDS,
    ClusterStats,
)
from reviewpulse.models import Review, Theme, ThemeLabel, ThemeLabelEntry, ThemeLabels
from reviewpulse.sources.language import word_count

# Six samples still give the round-robin one or two per rating present, which is
# what stratification is for; ten cost 60% more tokens for the same surface.
MAX_SAMPLES = 6

# Reviews are picked from the short end of the quotable band, so this cap is a
# guard against an outlier rather than the usual case.
MAX_SAMPLE_CHARS = 180

ANCHOR_TERMS = 10

# A label made only of these words describes how users felt, not what they used.
SENTIMENT_WORDS = frozenset(
    """
positive negative neutral mixed sentiment praise praises complaint complaints
criticism satisfaction dissatisfaction happy unhappy happiness frustration
frustrated angry delight delighted love hate liked disliked
good bad worst best poor great excellent terrible awful amazing awesome
issue issues problem problems concern concerns
""".split()
)

GENERIC_WORDS = frozenset(
    """
app application software platform product service overall general
quality experience feedback review reviews user users customer customers
performance usage thing things stuff misc miscellaneous other others
""".split()
)

_LABEL_TOKEN_RE = re.compile(r"[a-z]+")


def is_sentiment_label(label: str) -> bool:
    """True when a label conveys sentiment or generic quality, not a surface."""
    tokens = _LABEL_TOKEN_RE.findall(label.lower())
    meaningful = [t for t in tokens if t not in {"and", "of", "the", "in", "for", "with", "on"}]
    if not meaningful:
        return True
    if any(token == "sentiment" for token in meaningful):
        return True
    return all(token in SENTIMENT_WORDS or token in GENERIC_WORDS for token in meaningful)


def stratified_sample(
    members: list[Review],
    limit: int = MAX_SAMPLES,
) -> list[Review]:
    """Round-robin across the ratings present, shortest quotable reviews first.

    Within the quotable band the shortest reviews are preferred: a 12-word
    complaint names its surface as plainly as a 45-word one and costs a third of
    the tokens, and it arrives untruncated.
    """
    by_rating: dict[int, list[Review]] = {}
    for review in members:
        by_rating.setdefault(review.rating if review.rating is not None else 0, []).append(
            review
        )

    def within_rating(review: Review) -> tuple[int, int]:
        words = word_count(review.text_clean)
        if QUOTABLE_MIN_WORDS <= words <= QUOTABLE_MAX_WORDS:
            return (0, words)
        # Outside the band, only the over-long reviews say anything useful:
        # what is left under 12 words is "nice app", which names no surface.
        return (1, -words)

    for reviews in by_rating.values():
        reviews.sort(key=within_rating)

    picked: list[Review] = []
    ratings = sorted(by_rating)
    position = 0
    while len(picked) < limit:
        added = False
        for rating in ratings:
            bucket = by_rating[rating]
            if position < len(bucket):
                picked.append(bucket[position])
                added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        position += 1
    return picked


def format_samples(members: list[Review]) -> str:
    lines = []
    for review in members:
        stars = f"{review.rating}*" if review.rating is not None else "?"
        text = review.text_clean
        if len(text) > MAX_SAMPLE_CHARS:
            text = text[:MAX_SAMPLE_CHARS].rstrip() + "..."
        lines.append(f"- [{stars}] {text}")
    return "\n".join(lines)


def theme_id(cluster: ClusterStats) -> str:
    """The id the model echoes back, matching the final `Theme.theme_id`."""
    return f"t{cluster.rank}"


def format_themes(
    clusters: list[ClusterStats],
    reviews: list[Review],
    *,
    samples: int = MAX_SAMPLES,
) -> str:
    """Render every cluster as one block of the naming prompt.

    Cluster size, mean rating, and negative share are deliberately left out. The
    per-sample star ratings already carry the sentiment, the aggregates cannot
    help name a surface, and the prompt would only have to forbid restating them.
    """
    blocks = []
    for cluster in clusters:
        members = [reviews[i] for i in cluster.member_indices]
        blocks.append(
            f"[{theme_id(cluster)}] anchor terms: "
            f"{', '.join(cluster.terms[:ANCHOR_TERMS])}\n"
            f"{format_samples(stratified_sample(members, samples))}"
        )
    return "\n\n".join(blocks)


@dataclass
class LabelStats:
    llm_calls: int = 0
    retries: int = 0
    rejected_labels: list[str] = None  # type: ignore[assignment]
    heuristic_fallbacks: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.rejected_labels is None:
            self.rejected_labels = []
        if self.errors is None:
            self.errors = []


MIN_BUCKET_PRESENCE = 0.10


def assign_heuristic_labels(
    clusters: list[ClusterStats],
    reviews: list[Review],
    buckets: list[taxonomy_mod.Bucket],
) -> dict[str, ThemeLabel]:
    """Give each cluster a distinct taxonomy bucket.

    Raw match counts hand the same broad bucket ("charts and trading interface"
    matches 21% of the corpus) to several clusters at once, while pure lift does
    the opposite and hands a support-complaint cluster to a rare bucket it barely
    touches. The score is therefore presence x lift — how much of the cluster
    mentions the bucket, weighted by how over-represented that is against the
    corpus — assigned greedily with each bucket usable once. On the real corpus
    this matches the optimal one-to-one assignment.
    """
    if not clusters:
        return {}

    n_corpus = max(len(reviews), 1)
    corpus_rate: dict[str, float] = {}
    bucket_by_id = {bucket.id: bucket for bucket in buckets}
    for bucket in buckets:
        hits = sum(1 for review in reviews if bucket.matches(review.text_clean))
        corpus_rate[bucket.id] = hits / n_corpus

    candidates: list[tuple[float, float, str, str]] = []
    for cluster in clusters:
        members = [reviews[i] for i in cluster.member_indices]
        size = max(len(members), 1)
        for bucket in buckets:
            hits = sum(1 for review in members if bucket.matches(review.text_clean))
            rate = hits / size
            if rate < MIN_BUCKET_PRESENCE:
                continue
            base = corpus_rate[bucket.id]
            lift = rate / base if base else rate
            candidates.append((rate * lift, rate, cluster.cluster_key, bucket.id))

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))

    assigned: dict[str, ThemeLabel] = {}
    used_buckets: set[str] = set()
    for _, _, cluster_key, bucket_id in candidates:
        if cluster_key in assigned or bucket_id in used_buckets:
            continue
        assigned[cluster_key] = ThemeLabel(
            label=bucket_by_id[bucket_id].label,
            summary="",
        )
        used_buckets.add(bucket_id)

    for cluster in clusters:
        label = assigned.get(cluster.cluster_key)
        if label is None:
            label = ThemeLabel(label=_terms_label(cluster), summary="")
            assigned[cluster.cluster_key] = label
        label.summary = _terms_summary(cluster)
    return assigned


def _terms_label(cluster: ClusterStats) -> str:
    """Last resort when no taxonomy bucket is over-represented."""
    top = cluster.terms[:3]
    if not top:
        return f"Unlabeled theme {cluster.cluster_key}"
    return " and ".join(top).capitalize()


def heuristic_label(
    cluster: ClusterStats,
    members: list[Review],
    buckets: list[taxonomy_mod.Bucket],
) -> ThemeLabel:
    """Single-cluster keyword label, used when the LLM answer is unusable."""
    if cluster.suggested_label:
        return ThemeLabel(
            label=cluster.suggested_label,
            summary=_terms_summary(cluster),
        )

    scores: list[tuple[int, int, taxonomy_mod.Bucket]] = []
    for bucket in buckets:
        hits = sum(1 for review in members if bucket.matches(review.text_clean))
        if hits:
            scores.append((hits, -bucket.priority, bucket))
    if scores:
        scores.sort(key=lambda item: (-item[0], -item[1]))
        best = scores[0][2]
        return ThemeLabel(label=best.label, summary=_terms_summary(cluster))

    return ThemeLabel(label=_terms_label(cluster), summary=_terms_summary(cluster))


def _terms_summary(cluster: ClusterStats) -> str:
    terms = ", ".join(cluster.terms[:6]) or "no recurring terms"
    return f"Reviews in this cluster recur on: {terms}."


def label_clusters(
    clusters: list[ClusterStats],
    reviews: list[Review],
    *,
    buckets: list[taxonomy_mod.Bucket] | None = None,
    chain=None,
    retry_chain=None,
    use_llm: bool = True,
    samples: int = MAX_SAMPLES,
) -> tuple[list[Theme], LabelStats]:
    """Attach labels to ranked clusters and return `Theme` objects.

    All numeric fields are copied from the cluster stats; the model contributes
    only `label` and `summary`.
    """
    buckets = buckets if buckets is not None else taxonomy_mod.load_taxonomy()
    stats = LabelStats()
    themes: list[Theme] = []
    keyword_labels = assign_heuristic_labels(clusters, reviews, buckets)

    llm_labels: dict[str, ThemeLabel] = {}
    if use_llm and chain is not None:
        llm_labels = _label_with_llm(
            clusters, reviews, chain, retry_chain, stats, samples
        )

    for cluster in clusters:
        label = llm_labels.get(cluster.cluster_key)
        label_source = "llm"

        if label is None:
            label_source = "heuristic"
            members = [reviews[i] for i in cluster.member_indices]
            label = keyword_labels.get(cluster.cluster_key) or heuristic_label(
                cluster, members, buckets
            )
            if use_llm and chain is not None:
                stats.heuristic_fallbacks += 1

        themes.append(
            Theme(
                theme_id=theme_id(cluster),
                label=label.label.strip(),
                summary=label.summary.strip(),
                review_ids=cluster.review_ids,
                size=cluster.size,
                mean_rating=cluster.mean_rating,
                rank=cluster.rank,
                neg_share=cluster.neg_share,
                priority=cluster.priority,
                trend=cluster.trend,
                emerging=cluster.emerging,
                keywords=cluster.terms,
                example_review_ids=cluster.example_review_ids,
                label_source=label_source,
            )
        )

    return themes, stats


def _label_with_llm(
    clusters: list[ClusterStats],
    reviews: list[Review],
    chain,
    retry_chain,
    stats: LabelStats,
    samples: int,
) -> dict[str, ThemeLabel]:
    """Name every cluster in one call, re-asking only for what was rejected.

    Returns labels keyed by `cluster_key`; anything absent is left for the
    caller's keyword fallback, so a partial answer costs only the themes it
    missed rather than the whole stage.
    """
    accepted: dict[str, ThemeLabel] = {}
    pending = list(clusters)

    for attempt, active in enumerate((chain, retry_chain or chain)):
        if not pending:
            break
        try:
            stats.llm_calls += 1
            if attempt:
                stats.retries += 1
            result = active.invoke(
                {"themes": format_themes(pending, reviews, samples=samples)}
            )
        except Exception as exc:  # noqa: BLE001 - degrade to heuristic labels
            stats.errors.append(f"{type(exc).__name__}: {exc}")
            break

        by_id = _entries_by_theme_id(result)
        still_pending = []
        for cluster in pending:
            entry = by_id.get(theme_id(cluster))
            if entry is None:
                still_pending.append(cluster)
            elif is_sentiment_label(entry.label):
                stats.rejected_labels.append(entry.label)
                still_pending.append(cluster)
            else:
                accepted[cluster.cluster_key] = ThemeLabel(
                    label=entry.label, summary=entry.summary
                )
        pending = still_pending

    return accepted


def _entries_by_theme_id(result) -> dict[str, ThemeLabelEntry]:
    """Index a batch answer by the id the model echoed back."""
    batch = result if isinstance(result, ThemeLabels) else ThemeLabels(**result)
    return {entry.theme_id: entry for entry in batch.labels}
