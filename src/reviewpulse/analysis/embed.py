"""Sentence embeddings with an on-disk cache (Phase 2 tasks 2.2-2.3).

Embedding input is `text_clean` only: the public Play endpoint returns no review
titles, so `title_clean` is empty on all 1,260 stored rows and concatenating it
would add nothing (implementation-plan.md §4.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from reviewpulse.models import Review

EmbedFn = Callable[[list[str]], np.ndarray]


class EmbeddingUnavailable(RuntimeError):
    """Raised when the embedding backend cannot be loaded or downloaded."""


@dataclass
class EmbeddingResult:
    vectors: np.ndarray
    model: str
    cached_hits: int
    computed: int

    @property
    def dim(self) -> int:
        return int(self.vectors.shape[1]) if self.vectors.size else 0


def embedding_text(review: Review) -> str:
    return review.text_clean


def _cache_file(cache_dir: Path, model: str) -> Path:
    slug = model.replace("/", "__").replace(":", "_")
    return cache_dir / f"embeddings_{slug}.npz"


def _load_cache(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        return {}
    try:
        with np.load(path, allow_pickle=False) as data:
            ids = data["ids"]
            vectors = data["vectors"]
    except (OSError, KeyError, ValueError):
        # A corrupt cache must never break a run; recompute instead.
        return {}
    return {str(review_id): vectors[i] for i, review_id in enumerate(ids)}


def _save_cache(path: Path, cache: dict[str, np.ndarray]) -> None:
    if not cache:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = np.array(list(cache.keys()), dtype=object).astype(str)
    vectors = np.vstack([cache[key] for key in cache])
    np.savez_compressed(path, ids=ids, vectors=vectors)


def load_sentence_transformer(model_name: str) -> EmbedFn:
    """Build an embed function backed by sentence-transformers.

    Imported lazily: the package pulls in torch, and the keyword fallback path
    must stay usable on machines where the model cannot be downloaded.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise EmbeddingUnavailable(
            f"sentence-transformers is not installed: {exc}"
        ) from exc

    try:
        model = SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - network/disk dependent
        raise EmbeddingUnavailable(
            f"could not load embedding model {model_name!r}: {exc}"
        ) from exc

    def _embed(texts: list[str]) -> np.ndarray:
        return np.asarray(
            model.encode(
                texts,
                batch_size=64,
                show_progress_bar=False,
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )

    return _embed


def embed_reviews(
    reviews: Sequence[Review],
    *,
    model: str,
    cache_dir: Path | None = None,
    embed_fn: EmbedFn | None = None,
) -> EmbeddingResult:
    """Embed reviews, reusing any cached vectors keyed by review_id."""
    if not reviews:
        return EmbeddingResult(
            vectors=np.zeros((0, 0), dtype=np.float32),
            model=model,
            cached_hits=0,
            computed=0,
        )

    cache_path = _cache_file(cache_dir, model) if cache_dir else None
    cache = _load_cache(cache_path) if cache_path else {}

    missing = [r for r in reviews if r.review_id not in cache]
    if missing:
        embed_fn = embed_fn or load_sentence_transformer(model)
        fresh = embed_fn([embedding_text(r) for r in missing])
        fresh = _normalize(np.asarray(fresh, dtype=np.float32))
        for review, vector in zip(missing, fresh):
            cache[review.review_id] = vector
        if cache_path:
            _save_cache(cache_path, cache)

    vectors = np.vstack([cache[r.review_id] for r in reviews]).astype(np.float32)
    return EmbeddingResult(
        vectors=vectors,
        model=model,
        cached_hits=len(reviews) - len(missing),
        computed=len(missing),
    )


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """Unit-length rows so ward's euclidean distance tracks cosine distance."""
    if vectors.ndim != 2 or vectors.size == 0:
        return vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
