"""Theme labeling tests (Phase 2 tasks 2.13-2.15)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from reviewpulse.analysis.cluster import cluster_reviews
from reviewpulse.analysis.label import (
    assign_heuristic_labels,
    format_samples,
    format_themes,
    is_sentiment_label,
    label_clusters,
    stratified_sample,
)
from reviewpulse.analysis.taxonomy import load_taxonomy
from reviewpulse.config import ClusteringSettings
from reviewpulse.models import Review, ThemeLabelEntry, ThemeLabels

WINDOW_END = datetime(2026, 8, 29, tzinfo=timezone.utc).date()


def make_review(index: int, text: str, rating: int, days_ago: int = 1) -> Review:
    return Review(
        review_id=f"r{index:04d}",
        source="play",
        rating=rating,
        text_clean=text,
        date=datetime(2026, 8, 29, tzinfo=timezone.utc) - timedelta(days=days_ago),
    )


class StubChain:
    """Stands in for `prompt | llm.with_structured_output(ThemeLabels)`.

    One queued item per expected call: the labels to answer with, assigned to the
    theme ids that call's prompt contained — which is how the real model echoes
    ids back — or an exception to raise instead. Fewer labels than ids answers
    only some of the themes.
    """

    def __init__(self, *rounds: str | tuple[str, ...] | Exception) -> None:
        self.rounds = list(rounds)
        self.calls: list[dict] = []

    def invoke(self, payload: dict) -> ThemeLabels:
        self.calls.append(payload)
        answer = self.rounds.pop(0) if self.rounds else ()
        if isinstance(answer, Exception):
            raise answer
        labels = [answer] if isinstance(answer, str) else list(answer)
        return ThemeLabels(
            labels=[
                ThemeLabelEntry(
                    theme_id=theme_id, label=label, summary=f"Users report {label}."
                )
                for theme_id, label in zip(self.theme_ids(payload), labels)
            ]
        )

    @staticmethod
    def theme_ids(payload: dict) -> list[str]:
        return re.findall(r"\[(t\d+)\]", payload["themes"])


@pytest.mark.parametrize(
    "label",
    [
        "Positive feedback",
        "Negative reviews",
        "User complaints",
        "Mixed sentiment",
        "App quality",
        "General feedback",
        "Overall experience",
        "Bad app",
        "Customer sentiment",
        "Issues",
        "",
    ],
)
def test_sentiment_labels_are_rejected(label: str) -> None:
    assert is_sentiment_label(label) is True


@pytest.mark.parametrize(
    "label",
    [
        "Withdrawal delays",
        "Charts and scalper controls",
        "Brokerage charges",
        "Customer support responsiveness",
        "KYC verification delays",
        "Mutual fund SIP failures",
        "Order execution errors",
    ],
)
def test_product_surface_labels_are_accepted(label: str) -> None:
    assert is_sentiment_label(label) is False


def test_stratified_sample_spans_ratings_present() -> None:
    members = [make_review(i, " ".join(["word"] * 20), 1) for i in range(20)]
    members += [make_review(100 + i, " ".join(["other"] * 20), 5) for i in range(3)]
    picked = stratified_sample(members, limit=6)
    ratings = {r.rating for r in picked}
    assert ratings == {1, 5}
    # Round-robin, so the rare rating is not crowded out by the common one.
    assert sum(1 for r in picked if r.rating == 5) == 3


def test_stratified_sample_prefers_quotable_length() -> None:
    short = make_review(1, "too short here", 1)
    quotable = make_review(2, " ".join(["word"] * 20), 1)
    members = [short, quotable]
    assert stratified_sample(members, limit=1)[0].review_id == quotable.review_id


def test_stratified_sample_prefers_the_short_end_of_the_quotable_band() -> None:
    """Both name the surface; the shorter one costs a third of the tokens."""
    brief = make_review(1, " ".join(["word"] * 13), 1)
    verbose = make_review(2, " ".join(["word"] * 44), 1)
    picked = stratified_sample([verbose, brief], limit=1)
    assert picked[0].review_id == brief.review_id


def test_format_samples_truncates_long_text() -> None:
    long_review = make_review(1, "x" * 400, 3)
    formatted = format_samples([long_review])
    assert formatted.startswith("- [3*]")
    assert formatted.endswith("...")
    assert len(formatted) < 300


def support_and_charges_clusters():
    reviews = [
        make_review(i, "customer care never responds to my ticket about money", 1)
        for i in range(10)
    ]
    reviews += [
        make_review(50 + i, "brokerage charges are too high on every single trade", 2)
        for i in range(10)
    ]
    vectors = np.vstack(
        [np.array([[1.0, 0.0]], dtype=np.float32)] * 10
        + [np.array([[0.0, 1.0]], dtype=np.float32)] * 10
    )
    outcome = cluster_reviews(
        reviews, vectors, ClusteringSettings(), k_max=2, size_floor=1,
        window_end=WINDOW_END,
    )
    return outcome, reviews


def support_cluster(outcome, reviews):
    """The two clusters tie on priority, so pick by membership, not by rank."""
    return next(
        cluster
        for cluster in outcome.clusters
        if reviews[cluster.member_indices[0]].review_id.startswith("r00")
        and "customer care" in reviews[cluster.member_indices[0]].text_clean
    )


def test_heuristic_labels_are_distinct_product_surfaces() -> None:
    outcome, reviews = support_and_charges_clusters()
    labels = assign_heuristic_labels(outcome.clusters, reviews, load_taxonomy())
    values = [labels[c.cluster_key].label for c in outcome.clusters]
    assert len(set(values)) == len(values)
    assert "Customer support responsiveness" in values
    assert "Charges and brokerage" in values


def test_broad_bucket_is_not_reused_across_clusters() -> None:
    """A bucket that matches many clusters may only claim one of them."""
    reviews = []
    for topic in range(3):
        for member in range(8):
            reviews.append(
                make_review(
                    topic * 10 + member,
                    f"the chart interface is confusing and {'charges high' if topic == 1 else 'support never replies' if topic == 2 else 'layout cluttered'} {member}",
                    1,
                )
            )
    vectors = np.vstack(
        [np.array([[1.0, 0.0, 0.0]], dtype=np.float32)] * 8
        + [np.array([[0.0, 1.0, 0.0]], dtype=np.float32)] * 8
        + [np.array([[0.0, 0.0, 1.0]], dtype=np.float32)] * 8
    )
    outcome = cluster_reviews(
        reviews, vectors, ClusteringSettings(), k_max=3, size_floor=1,
        window_end=WINDOW_END,
    )
    labels = assign_heuristic_labels(outcome.clusters, reviews, load_taxonomy())
    values = [labels[c.cluster_key].label for c in outcome.clusters]
    assert len(set(values)) == 3


def test_label_clusters_uses_llm_label_when_valid() -> None:
    outcome, reviews = support_and_charges_clusters()
    chain = StubChain(("Support ticket delays", "Brokerage charges"))
    themes, stats = label_clusters(
        outcome.clusters, reviews, buckets=load_taxonomy(), chain=chain, use_llm=True
    )
    assert [t.label for t in themes] == ["Support ticket delays", "Brokerage charges"]
    assert all(t.label_source == "llm" for t in themes)
    assert stats.retries == 0


def test_every_theme_is_named_in_one_call() -> None:
    """The token budget rests on this: one call per run, not one per theme."""
    outcome, reviews = support_and_charges_clusters()
    chain = StubChain(("Support ticket delays", "Brokerage charges"))

    _, stats = label_clusters(
        outcome.clusters, reviews, buckets=load_taxonomy(), chain=chain, use_llm=True
    )

    assert stats.llm_calls == 1
    assert len(chain.calls) == 1
    assert chain.theme_ids(chain.calls[0]) == ["t1", "t2"]


def test_a_theme_the_model_skipped_falls_back_alone() -> None:
    outcome, reviews = support_and_charges_clusters()
    keyword = assign_heuristic_labels(outcome.clusters, reviews, load_taxonomy())
    # One label for two themes: the second is left out of the answer entirely,
    # re-asked on its own, and still unanswered.
    chain = StubChain(("Support ticket delays",), ())

    themes, stats = label_clusters(
        outcome.clusters, reviews, buckets=load_taxonomy(), chain=chain, use_llm=True
    )

    assert [t.label_source for t in themes] == ["llm", "heuristic"]
    assert themes[1].label == keyword[outcome.clusters[1].cluster_key].label
    assert stats.heuristic_fallbacks == 1
    assert chain.theme_ids(chain.calls[1]) == ["t2"]


def test_sentiment_label_triggers_one_retry_then_heuristic() -> None:
    outcome, reviews = support_and_charges_clusters()
    single = [support_cluster(outcome, reviews)]
    chain = StubChain("Negative feedback")
    retry_chain = StubChain("User complaints")

    themes, stats = label_clusters(
        single, reviews, buckets=load_taxonomy(),
        chain=chain, retry_chain=retry_chain, use_llm=True,
    )

    assert stats.retries == 1
    assert stats.rejected_labels == ["Negative feedback", "User complaints"]
    assert themes[0].label_source == "heuristic"
    assert themes[0].label == "Customer support responsiveness"


def test_only_the_rejected_themes_are_re_asked() -> None:
    outcome, reviews = support_and_charges_clusters()
    chain = StubChain(("Negative feedback", "Brokerage charges"))
    retry_chain = StubChain("Support response times")

    themes, stats = label_clusters(
        outcome.clusters, reviews, buckets=load_taxonomy(),
        chain=chain, retry_chain=retry_chain, use_llm=True,
    )

    # The accepted theme is not paid for twice.
    assert chain.theme_ids(retry_chain.calls[0]) == ["t1"]
    assert [t.label for t in themes] == ["Support response times", "Brokerage charges"]
    assert stats.llm_calls == 2


def test_retry_label_is_kept_when_it_names_a_surface() -> None:
    outcome, reviews = support_and_charges_clusters()
    single = [support_cluster(outcome, reviews)]
    chain = StubChain("Positive feedback")
    retry_chain = StubChain("Support response times")

    themes, stats = label_clusters(
        single, reviews, buckets=load_taxonomy(),
        chain=chain, retry_chain=retry_chain, use_llm=True,
    )
    assert themes[0].label == "Support response times"
    assert themes[0].label_source == "llm"
    assert stats.retries == 1


def test_llm_error_degrades_to_heuristic_label() -> None:
    outcome, reviews = support_and_charges_clusters()
    single = [support_cluster(outcome, reviews)]
    chain = StubChain(RuntimeError("api down"))

    themes, stats = label_clusters(
        single, reviews, buckets=load_taxonomy(), chain=chain, use_llm=True
    )
    assert themes[0].label_source == "heuristic"
    assert stats.errors and "api down" in stats.errors[0]


def test_theme_stats_come_from_data_not_llm() -> None:
    outcome, reviews = support_and_charges_clusters()
    chain = StubChain(("Support ticket delays", "Brokerage charges"))
    themes, _ = label_clusters(
        outcome.clusters, reviews, buckets=load_taxonomy(), chain=chain, use_llm=True
    )
    for theme, cluster in zip(themes, outcome.clusters):
        assert theme.size == cluster.size == len(theme.review_ids)
        assert theme.mean_rating == cluster.mean_rating
        assert theme.neg_share == cluster.neg_share
        assert theme.priority == cluster.priority
        assert theme.rank == cluster.rank
        assert theme.theme_id == f"t{cluster.rank}"


def test_prompt_forbids_sentiment_labels() -> None:
    from reviewpulse.prompts import load_prompt

    spec = load_prompt("label_themes.yaml")
    assert "MUST NOT describe sentiment" in spec.system
    assert "{themes}" in spec.human
    assert spec.retry_suffix.strip()


def test_prompt_asks_for_labels_that_tell_the_themes_apart() -> None:
    """Only possible because the themes are named together, in one call."""
    from reviewpulse.prompts import load_prompt

    assert "MUST tell the themes apart" in load_prompt("label_themes.yaml").system


def test_format_themes_keys_each_block_by_theme_id() -> None:
    outcome, reviews = support_and_charges_clusters()
    block = format_themes(outcome.clusters, reviews, samples=2)

    assert re.findall(r"\[(t\d+)\]", block) == ["t1", "t2"]
    assert "anchor terms:" in block
    # Two samples per theme, and nothing else costing tokens.
    assert block.count("\n- ") == 4


def test_format_themes_omits_cluster_aggregates() -> None:
    """Sizes and ratings cannot name a surface, so they are not paid for."""
    outcome, reviews = support_and_charges_clusters()
    block = format_themes(outcome.clusters, reviews)

    for cluster in outcome.clusters:
        assert str(cluster.size) not in block
        assert "mean rating" not in block
        assert "neg" not in block
