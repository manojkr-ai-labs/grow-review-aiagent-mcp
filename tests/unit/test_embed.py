"""Embedding input and cache tests (Phase 2 tasks 2.2-2.3)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from reviewpulse.analysis.embed import embed_reviews, embedding_text
from reviewpulse.models import Review


def make_review(index: int, text: str, title: str | None = None) -> Review:
    return Review(
        review_id=f"r{index:04d}",
        source="play",
        rating=3,
        title_clean=title,
        text_clean=text,
        date=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )


class CountingEmbedder:
    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.calls = 0
        self.seen: list[str] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        self.seen.extend(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            out[row, len(text) % self.dim] = 1.0
            out[row, 0] += 0.5
        return out


def test_embedding_input_excludes_title() -> None:
    """Titles are empty on every stored row, so they are not concatenated."""
    review = make_review(1, "charts are slow", title="Should be ignored")
    assert embedding_text(review) == "charts are slow"


def test_vectors_are_unit_length(tmp_path) -> None:
    reviews = [make_review(i, f"review number {i}") for i in range(5)]
    result = embed_reviews(
        reviews, model="stub", cache_dir=tmp_path, embed_fn=CountingEmbedder()
    )
    norms = np.linalg.norm(result.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_cache_avoids_recomputation_on_second_run(tmp_path) -> None:
    reviews = [make_review(i, f"review number {i}") for i in range(6)]
    embedder = CountingEmbedder()

    first = embed_reviews(reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder)
    assert first.computed == 6
    assert first.cached_hits == 0
    assert embedder.calls == 1

    second = embed_reviews(reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder)
    assert second.computed == 0
    assert second.cached_hits == 6
    assert embedder.calls == 1
    assert np.allclose(first.vectors, second.vectors)


def test_cache_computes_only_new_reviews(tmp_path) -> None:
    reviews = [make_review(i, f"review number {i}") for i in range(4)]
    embedder = CountingEmbedder()
    embed_reviews(reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder)

    extended = reviews + [make_review(99, "a brand new review appears")]
    result = embed_reviews(
        extended, model="stub", cache_dir=tmp_path, embed_fn=embedder
    )
    assert result.computed == 1
    assert result.cached_hits == 4


def test_cache_is_keyed_by_model(tmp_path) -> None:
    reviews = [make_review(i, f"review number {i}") for i in range(3)]
    embedder = CountingEmbedder()
    embed_reviews(reviews, model="model-a", cache_dir=tmp_path, embed_fn=embedder)
    result = embed_reviews(
        reviews, model="model-b", cache_dir=tmp_path, embed_fn=embedder
    )
    assert result.computed == 3


def test_vector_order_follows_review_order(tmp_path) -> None:
    reviews = [make_review(i, f"text of length {'x' * i}") for i in range(5)]
    embedder = CountingEmbedder()
    first = embed_reviews(reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder)

    reversed_reviews = list(reversed(reviews))
    second = embed_reviews(
        reversed_reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder
    )
    assert np.allclose(first.vectors, second.vectors[::-1])


def test_empty_input_returns_empty_result(tmp_path) -> None:
    result = embed_reviews([], model="stub", cache_dir=tmp_path)
    assert result.vectors.size == 0
    assert result.computed == 0


def test_corrupt_cache_is_recomputed(tmp_path) -> None:
    reviews = [make_review(i, f"review {i}") for i in range(3)]
    embedder = CountingEmbedder()
    embed_reviews(reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder)

    cache_file = next(tmp_path.glob("embeddings_*.npz"))
    cache_file.write_bytes(b"not an npz file")

    result = embed_reviews(
        reviews, model="stub", cache_dir=tmp_path, embed_fn=embedder
    )
    assert result.computed == 3
