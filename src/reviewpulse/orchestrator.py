"""Pipeline orchestration."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from reviewpulse.analysis import taxonomy as taxonomy_mod
from reviewpulse.analysis.cluster import cluster_reviews
from reviewpulse.analysis.embed import EmbeddingUnavailable, embed_reviews
from reviewpulse.analysis.label import label_clusters
from reviewpulse.analysis.quotes import select_quotes
from reviewpulse.analysis.select import select_for_clustering
from reviewpulse.chains.retry_policy import MAX_ATTEMPTS, decide
from reviewpulse.config import (
    LLMSettings,
    Settings,
    default_raw_dir,
    load_settings,
    runs_dir as default_runs_dir,
)
from reviewpulse.models import PulseNote, Theme
from reviewpulse.privacy.scrubber import scrub_raw_review
from reviewpulse.publish.base import DryRunPublisher, idempotency_key
from reviewpulse.publish.base import publish as publish_note
from reviewpulse.pulse.compose import ComposeStats, compose_draft
from reviewpulse.pulse.render import count_words, render_note
from reviewpulse.pulse.validate import validate_note
from reviewpulse.sources.language import classify, word_count
from reviewpulse.sources.normalize import (
    compute_window,
    filter_window,
    window_stats,
)
from reviewpulse.sources.play_export import PlayExportSource
from reviewpulse.sources.play_fetch import fetch_reviews, incremental_fetch_start, resolve_app, write_export_csv
from reviewpulse.store.sqlite import ReviewStore


@dataclass
class FetchResult:
    package_id: str
    window_weeks: int
    window_start: str
    window_end: str
    fetched_count: int
    export_path: str
    reached_window_start: bool = True
    oldest_seen: str | None = None
    app_title: str | None = None
    app_developer: str | None = None
    fetch_mode: str = "full"
    fetch_start: str | None = None

    @property
    def coverage_warning(self) -> str | None:
        if self.reached_window_start:
            return None
        target = self.fetch_start or self.window_start
        if self.fetch_mode == "incremental":
            return (
                f"Download stopped at {self.oldest_seen} before reaching "
                f"{target}; incremental fetch did not cover back to the newest "
                f"stored review."
            )
        return (
            f"Download stopped at {self.oldest_seen} before reaching "
            f"{self.window_start}; the endpoint served fewer reviews than the "
            f"{self.window_weeks}-week window needs."
        )


@dataclass
class IngestResult:
    run_id: str
    source_file: str
    source_checksum: str
    window_weeks: int
    parsed_count: int
    accepted_count: int
    dropped_out_of_window: int
    dropped_too_short: int
    dropped_non_english: int
    inserted_count: int
    deduped_count: int
    db_path: str
    window: dict
    manifest_path: str
    export_path: str | None = None
    export_count: int = 0
    fetch_mode: str = "full"


@dataclass
class ClusterResult:
    run_id: str
    strategy: str
    window: dict
    total_reviews: int
    clustered_reviews: int
    dropped_low_signal: int
    retention: float
    themes: list[Theme]
    silhouette: float | None
    max_cluster_share: float
    embedding_model: str | None
    embedding_cached: int
    embedding_computed: int
    label_source_counts: dict
    clusters_path: str
    debug_path: str
    manifest_path: str
    checks: dict
    warnings: list[str] = field(default_factory=list)
    # Carried forward for Phase 3: quote selection needs the member text and the
    # vectors to score centrality against, and re-reading them would risk the
    # note being built from a different corpus than the themes.
    reviews: list = field(default_factory=list, repr=False)
    vectors: object | None = field(default=None, repr=False)
    run_dir: str = ""

    @property
    def theme_count(self) -> int:
        return len(self.themes)


@dataclass
class PulseResult:
    run_id: str
    note: object
    rendered: str
    word_count: int
    passed: bool
    checks: dict
    gates: list[dict]
    attempts: int
    compose_source: str
    quotes: list[dict]
    note_path: str | None
    publish_path: str | None
    manifest_path: str
    publish_result: object | None = None
    warnings: list[str] = field(default_factory=list)
    published: bool = False


def fetch_export(
    *,
    window_weeks: int | None = None,
    settings: Settings | None = None,
    out_path: Path | None = None,
    lang: str | None = None,
    country: str | None = None,
    fetch_mode: str = "full",
    db_path: Path | None = None,
) -> FetchResult:
    """Download public Play Store reviews for the window into a raw export CSV."""
    settings = settings or load_settings()
    window_weeks = window_weeks or settings.default_window_weeks
    window_start, window_end = compute_window(window_weeks)
    lang = lang or settings.fetch_lang
    country = country or settings.fetch_country

    pager_start = window_start
    resolved_mode = "full"
    if fetch_mode == "incremental":
        store = ReviewStore(Path(db_path or settings.db_path))
        pager_start, resolved_mode = incremental_fetch_start(
            window_start, store.latest_review_date()
        )

    listing = resolve_app(settings.package_id, lang=lang, country=country)
    batch = fetch_reviews(
        settings.package_id,
        pager_start,
        window_end,
        lang=lang,
        country=country,
    )

    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = default_raw_dir() / (
            f"play_{settings.package_id}_{window_weeks}w_{stamp}.csv"
        )

    export_path = write_export_csv(batch, Path(out_path))

    return FetchResult(
        package_id=settings.package_id,
        window_weeks=window_weeks,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        fetched_count=len(batch.rows),
        export_path=str(export_path),
        reached_window_start=batch.reached_window_start,
        oldest_seen=batch.oldest_seen.isoformat() if batch.oldest_seen else None,
        app_title=listing.get("title") or None,
        app_developer=listing.get("developer") or None,
        fetch_mode=resolved_mode,
        fetch_start=pager_start.isoformat(),
    )


EXPORT_FIELDS = (
    "review_id",
    "source",
    "rating",
    "review_date",
    "lang",
    "word_count",
    "scrub_flags",
    "title_clean",
    "text_clean",
)


def default_export_path(db_path: Path) -> Path:
    """Sit the export beside the database it was built from."""
    return db_path.parent / "exports" / "play_store.csv"


def export_reviews(
    *,
    settings: Settings | None = None,
    db_path: Path | None = None,
    out_path: Path | None = None,
) -> tuple[Path, int]:
    """Write stored (scrubbed, filtered) reviews to a readable CSV.

    This is the post-filter view of the corpus; `data/raw/` keeps the raw
    download so the filtering step stays auditable against its input.
    """
    settings = settings or load_settings()
    db_path = Path(db_path or settings.db_path)
    store = ReviewStore(db_path)
    out_path = Path(out_path or default_export_path(db_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    reviews = store.get_all()
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPORT_FIELDS))
        writer.writeheader()
        for review in reviews:
            writer.writerow(
                {
                    "review_id": review.review_id,
                    "source": review.source,
                    "rating": review.rating if review.rating is not None else "",
                    "review_date": review.date.isoformat(),
                    "lang": review.lang or "",
                    "word_count": word_count(review.text_clean),
                    "scrub_flags": "|".join(review.scrub_flags),
                    "title_clean": review.title_clean or "",
                    "text_clean": review.text_clean,
                }
            )

    return out_path, len(reviews)


def apply_quality_filters(
    reviews: list,
    settings: Settings,
) -> tuple[list, dict]:
    """Drop reviews that are too short or not written in English.

    Filtering happens after scrubbing so the checks see exactly the text that
    would have been stored, redaction placeholders included.
    """
    kept = []
    stats = {"too_short": 0, "non_english": 0, "non_english_reasons": {}}

    for review in reviews:
        if settings.min_words and word_count(review.text_clean) < settings.min_words:
            stats["too_short"] += 1
            continue

        if settings.english_only:
            verdict = classify(review.text_clean)
            if not verdict.is_english:
                reason = verdict.reason.split(":")[0]
                stats["non_english"] += 1
                stats["non_english_reasons"][reason] = (
                    stats["non_english_reasons"].get(reason, 0) + 1
                )
                continue

        kept.append(review)

    return kept, stats


def ingest_reviews(
    file_path: Path,
    *,
    window_weeks: int | None = None,
    settings: Settings | None = None,
    db_path: Path | None = None,
    runs_dir: Path | None = None,
    fetch_mode: str = "full",
) -> IngestResult:
    """Ingest → normalize → scrub → store pipeline (Phase 1)."""
    settings = settings or load_settings()
    window_weeks = window_weeks or settings.default_window_weeks
    db_path = db_path or settings.db_path
    runs_dir = runs_dir or default_runs_dir()

    file_path = file_path.resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Export file not found: {file_path}")

    window_start, window_end = compute_window(window_weeks)
    source = PlayExportSource(file_path, columns=settings.columns)
    store = ReviewStore(db_path)

    parsed = list(source.parse_all())
    in_window = [raw for raw in parsed if filter_window(raw, window_start, window_end)]
    scrubbed = [scrub_raw_review(raw) for raw in in_window]
    kept, quality = apply_quality_filters(scrubbed, settings)
    inserted, deduped = store.upsert_many(kept)

    # Refresh the post-filter CSV so it can never lag the database.
    export_path, export_count = export_reviews(settings=settings, db_path=db_path)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    checksum = _file_checksum(file_path)
    window_info = window_stats(kept, window_start, window_end)
    if window_info["actual_weeks"] and window_info["actual_weeks"] < 8:
        window_info["window_warning"] = (
            "Export covers fewer than 8 weeks of reviews in the requested window."
        )

    manifest = {
        "run_id": run_id,
        "stage": "ingest",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "package_id": settings.package_id,
        "source_file": str(file_path),
        "source_checksum": checksum,
        "window_weeks": window_weeks,
        "counts": {
            "parsed": len(parsed),
            "in_window": len(in_window),
            "accepted": len(kept),
            "dropped_out_of_window": len(parsed) - len(in_window),
            "dropped_too_short": quality["too_short"],
            "dropped_non_english": quality["non_english"],
            "inserted": inserted,
            "deduped": deduped,
            "db_total": store.count(),
        },
        "export_file": str(export_path),
        "filters": {
            "min_words": settings.min_words,
            "english_only": settings.english_only,
            "non_english_reasons": quality["non_english_reasons"],
        },
        "window": window_info,
        "fetch_mode": fetch_mode,
    }

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return IngestResult(
        run_id=run_id,
        source_file=str(file_path),
        source_checksum=checksum,
        window_weeks=window_weeks,
        parsed_count=len(parsed),
        accepted_count=len(kept),
        dropped_out_of_window=len(parsed) - len(in_window),
        dropped_too_short=quality["too_short"],
        dropped_non_english=quality["non_english"],
        inserted_count=inserted,
        deduped_count=deduped,
        db_path=str(db_path),
        export_path=str(export_path),
        export_count=export_count,
        window=window_info,
        manifest_path=str(manifest_path),
        fetch_mode=fetch_mode,
    )


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


def _build_chains(
    build,
    use_llm: bool,
    warnings: list[str],
    *,
    llm_settings: LLMSettings,
    fallback: str,
):
    """Return (chain, retry_chain); (None, None) means run this stage offline.

    `llm_settings` is the calling stage's own provider block, which is why
    labeling can be live on Groq while composition is offline for want of a
    Gemini key, or the reverse. A missing key is a normal offline condition, not
    an error: the run continues with the deterministic path and records that in
    the artifacts.
    """
    if not use_llm:
        return None, None

    from reviewpulse.llm.factory import LLMUnavailable, unavailable_reason

    reason = unavailable_reason(llm_settings)
    if reason:
        warnings.append(f"{reason}; using {fallback}")
        return None, None

    try:
        from reviewpulse.llm.factory import build_chat_model

        llm = build_chat_model(settings=llm_settings)
        return build(llm), build(llm, retry=True)
    except (LLMUnavailable, ImportError) as exc:
        warnings.append(f"LLM unavailable ({exc}); using {fallback}")
        return None, None


def _build_label_chains(
    use_llm: bool, warnings: list[str], llm_settings: LLMSettings
):
    from reviewpulse.chains.label_themes import build_label_chain

    return _build_chains(
        build_label_chain,
        use_llm,
        warnings,
        llm_settings=llm_settings,
        fallback="deterministic keyword labels",
    )


def _build_compose_chains(
    use_llm: bool, warnings: list[str], llm_settings: LLMSettings
):
    from reviewpulse.chains.compose_pulse import build_compose_chain

    return _build_chains(
        build_compose_chain,
        use_llm,
        warnings,
        llm_settings=llm_settings,
        fallback="a deterministic prose frame",
    )


def run_cluster_stage(
    *,
    window_weeks: int | None = None,
    settings: Settings | None = None,
    db_path: Path | None = None,
    runs_dir: Path | None = None,
    mode: str | None = None,
    use_llm: bool | None = None,
    k_max: int | None = None,
    run_id: str | None = None,
) -> ClusterResult:
    """Select → embed → cluster → rank → label pipeline (Phase 2)."""
    settings = settings or load_settings()
    clustering = settings.clustering
    window_weeks = window_weeks or settings.default_window_weeks
    db_path = Path(db_path or settings.db_path)
    runs_dir = runs_dir or default_runs_dir()
    mode = mode or clustering.mode
    use_llm = clustering.label_llm if use_llm is None else use_llm
    k_max = k_max or settings.k_max
    warnings: list[str] = []

    window_start, window_end = compute_window(window_weeks)
    selection = select_for_clustering(
        window_start=window_start,
        window_end=window_end,
        settings=settings,
        db_path=db_path,
    )
    reviews = selection.reviews
    if not reviews:
        raise ValueError(
            f"No reviews to cluster in {window_start}..{window_end}; run ingest first"
        )
    if len(reviews) < settings.min_reviews:
        warnings.append(
            f"only {len(reviews)} reviews after the signal filter, below "
            f"min_reviews={settings.min_reviews}"
        )

    vectors = None
    embedding = None
    if mode == "embedding":
        try:
            embedding = embed_reviews(
                reviews,
                model=clustering.embedding_model,
                cache_dir=clustering.cache_dir,
            )
            vectors = embedding.vectors
        except EmbeddingUnavailable as exc:
            warnings.append(f"embeddings unavailable ({exc}); falling back to keywords")

    buckets = taxonomy_mod.load_taxonomy()
    outcome = cluster_reviews(
        reviews,
        vectors,
        clustering,
        k_max=k_max,
        size_floor=settings.cluster_size_floor,
        window_end=window_end,
        buckets=buckets,
    )

    if len(outcome.clusters) > k_max:
        raise AssertionError(
            f"clustering produced {len(outcome.clusters)} themes, above k_max={k_max}"
        )

    chain, retry_chain = _build_label_chains(use_llm, warnings, settings.llm)
    themes, label_stats = label_clusters(
        outcome.clusters,
        reviews,
        buckets=buckets,
        chain=chain,
        retry_chain=retry_chain,
        use_llm=chain is not None,
        samples=settings.llm.samples_per_theme,
    )
    warnings.extend(label_stats.errors)

    run_id = run_id or _new_run_id()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    window_info = window_stats(reviews, window_start, window_end)
    checks = _cluster_checks(
        themes,
        outcome,
        selection,
        k_max=k_max,
        max_cluster_share=clustering.max_cluster_share,
    )
    label_source_counts = {
        source: sum(1 for t in themes if t.label_source == source)
        for source in ("llm", "heuristic")
    }

    clusters_payload = {
        "run_id": run_id,
        "stage": "cluster",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "package_id": settings.package_id,
        "window": window_info,
        "strategy": outcome.strategy,
        "counts": {
            "window_reviews": selection.total_count,
            "clustered": len(reviews),
            "dropped_low_signal": selection.dropped_low_signal,
            "retention": selection.retention,
            "unassigned": outcome.unassigned_count,
        },
        "themes": [
            {
                **theme.model_dump(mode="json"),
                "cluster_key": cluster.cluster_key,
            }
            for theme, cluster in zip(themes, outcome.clusters)
        ],
    }
    clusters_path = run_dir / "clusters.json"
    clusters_path.write_text(
        json.dumps(clusters_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    debug_payload = {
        "run_id": run_id,
        "strategy": outcome.strategy,
        "k_requested": outcome.k_requested,
        "silhouette": outcome.silhouette,
        "max_cluster_share": round(outcome.max_cluster_share, 4),
        "balance_guard": clustering.max_cluster_share,
        "attempts": outcome.attempts,
        "size_histogram": [c.size for c in outcome.clusters],
        "selection": {
            "window_reviews": selection.total_count,
            "clustered": len(reviews),
            "dropped_low_signal": selection.dropped_low_signal,
            "retention": selection.retention,
            "criteria": selection.criteria,
        },
        "embedding": {
            "model": embedding.model if embedding else None,
            "dim": embedding.dim if embedding else None,
            "cached_hits": embedding.cached_hits if embedding else 0,
            "computed": embedding.computed if embedding else 0,
        },
        "taxonomy": {
            "other_share": outcome.other_share,
            "unassigned": outcome.unassigned_count,
        },
        "labeling": {
            "llm_calls": label_stats.llm_calls,
            "retries": label_stats.retries,
            "rejected_labels": label_stats.rejected_labels,
            "heuristic_fallbacks": label_stats.heuristic_fallbacks,
            "sources": label_source_counts,
        },
        "clusters": [
            {
                "cluster_key": cluster.cluster_key,
                "rank": theme.rank,
                "label": theme.label,
                "label_source": theme.label_source,
                "size": cluster.size,
                "mean_rating": cluster.mean_rating,
                "neg_share": cluster.neg_share,
                "priority": cluster.priority,
                "early_count": cluster.early_count,
                "late_count": cluster.late_count,
                "trend": cluster.trend,
                "emerging": cluster.emerging,
                "top_terms": cluster.terms[:10],
                "example_review_ids": cluster.example_review_ids,
            }
            for theme, cluster in zip(themes, outcome.clusters)
        ],
        "checks": checks,
        "warnings": warnings,
    }
    debug_path = run_dir / "cluster_debug.json"
    debug_path.write_text(
        json.dumps(debug_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = {
        "run_id": run_id,
        "stage": "cluster",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "package_id": settings.package_id,
        "window_weeks": window_weeks,
        "window": window_info,
        "clustering": {
            "mode": mode,
            "strategy": outcome.strategy,
            "linkage": clustering.linkage,
            "embedding_model": embedding.model if embedding else None,
            "k_max": k_max,
            "rank_by": clustering.rank_by,
            "random_seed": clustering.random_seed,
        },
        "counts": {
            "window_reviews": selection.total_count,
            "clustered": len(reviews),
            "dropped_low_signal": selection.dropped_low_signal,
            "themes": len(themes),
        },
        "themes": [
            {
                "theme_id": theme.theme_id,
                "rank": theme.rank,
                "label": theme.label,
                "size": theme.size,
                "mean_rating": theme.mean_rating,
                "neg_share": theme.neg_share,
                "priority": theme.priority,
                "trend": theme.trend,
                "emerging": theme.emerging,
                "label_source": theme.label_source,
            }
            for theme in themes
        ],
        "checks": checks,
        "artifacts": {
            "clusters": str(clusters_path),
            "cluster_debug": str(debug_path),
        },
        "warnings": warnings,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return ClusterResult(
        run_id=run_id,
        strategy=outcome.strategy,
        window=window_info,
        total_reviews=selection.total_count,
        clustered_reviews=len(reviews),
        dropped_low_signal=selection.dropped_low_signal,
        retention=selection.retention,
        themes=themes,
        silhouette=outcome.silhouette,
        max_cluster_share=round(outcome.max_cluster_share, 4),
        embedding_model=embedding.model if embedding else None,
        embedding_cached=embedding.cached_hits if embedding else 0,
        embedding_computed=embedding.computed if embedding else 0,
        label_source_counts=label_source_counts,
        clusters_path=str(clusters_path),
        debug_path=str(debug_path),
        manifest_path=str(manifest_path),
        checks=checks,
        warnings=warnings,
        reviews=reviews,
        vectors=vectors,
        run_dir=str(run_dir),
    )


def _cluster_checks(
    themes: list[Theme],
    outcome,
    selection,
    *,
    k_max: int,
    max_cluster_share: float,
) -> dict:
    """Machine-checkable form of the Phase 2 exit criteria."""
    rank_one = themes[0] if themes else None
    return {
        "themes_capped": len(themes) <= k_max,
        "themes_in_range": 3 <= len(themes) <= k_max,
        "balanced": outcome.max_cluster_share <= max_cluster_share,
        "retention_in_range": 0.60 <= selection.retention <= 0.75,
        "rank1_actionable": bool(
            rank_one and (rank_one.mean_rating is None or rank_one.mean_rating <= 4.0)
        ),
        "labels_are_surfaces": all(
            not _looks_like_sentiment(theme.label) for theme in themes
        ),
        "labels_distinct": len({theme.label.lower() for theme in themes})
        == len(themes),
        "stats_from_data": all(
            theme.size == len(theme.review_ids) for theme in themes
        ),
    }


def _looks_like_sentiment(label: str) -> bool:
    from reviewpulse.analysis.label import is_sentiment_label

    return is_sentiment_label(label)


def run_pulse_stage(
    *,
    cluster: ClusterResult | None = None,
    window_weeks: int | None = None,
    settings: Settings | None = None,
    db_path: Path | None = None,
    runs_dir: Path | None = None,
    use_llm: bool | None = None,
    cluster_use_llm: bool | None = None,
    mode: str | None = None,
    live: bool = False,
    send: bool = False,
    publisher=None,
) -> PulseResult:
    """Quotes -> compose -> render -> validate -> dry-run publish (Phase 3).

    Nothing is published unless every gate passes. A rejected note is still
    written, under a different name, because a run that aborted is exactly the
    one someone needs to read.
    """
    settings = settings or load_settings()
    pulse_cfg = settings.pulse
    window_weeks = window_weeks or settings.default_window_weeks
    db_path = Path(db_path or settings.db_path)
    runs_dir = runs_dir or default_runs_dir()
    use_llm = pulse_cfg.compose_llm if use_llm is None else use_llm

    if cluster is None:
        cluster = run_cluster_stage(
            window_weeks=window_weeks,
            settings=settings,
            db_path=db_path,
            runs_dir=runs_dir,
            mode=mode,
            use_llm=cluster_use_llm,
        )

    warnings = list(cluster.warnings)
    run_dir = Path(cluster.run_dir or (runs_dir / cluster.run_id))
    run_dir.mkdir(parents=True, exist_ok=True)
    store = ReviewStore(db_path)

    reviews = cluster.reviews
    top_themes = cluster.themes[: pulse_cfg.top_themes]
    if len(top_themes) < pulse_cfg.top_themes:
        warnings.append(
            f"only {len(top_themes)} themes available for a note that needs "
            f"{pulse_cfg.top_themes}"
        )

    ratings = [r.rating for r in reviews if r.rating is not None]
    mean_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    selection = select_quotes(
        top_themes,
        reviews,
        vectors=cluster.vectors,
        min_words=pulse_cfg.quote_min_words,
        max_words=pulse_cfg.quote_max_words,
        limit=pulse_cfg.quote_count,
    )
    for theme_id in selection.shortfall:
        warnings.append(f"no quotable review found for theme {theme_id}")

    chain, retry_chain = _build_compose_chains(use_llm, warnings, pulse_cfg.llm)
    compose_stats = ComposeStats()
    if chain is not None:
        from reviewpulse.llm.factory import resolved_model

        compose_stats.provider = pulse_cfg.llm.provider
        compose_stats.model = resolved_model(pulse_cfg.llm)

    attempt = 0
    note = None
    rendered = ""
    report = None
    decisions: list[dict] = []

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        draft, compose_stats = compose_draft(
            top_themes,
            selection.quotes,
            window_start=date.fromisoformat(cluster.window["requested_start"]),
            window_end=date.fromisoformat(cluster.window["requested_end"]),
            review_count=len(reviews),
            mean_rating=mean_rating,
            theme_count=cluster.theme_count,
            chain=chain,
            retry_chain=retry_chain,
            tighter=attempt > 1,
            stats=compose_stats,
        )

        note = PulseNote(
            run_id=cluster.run_id,
            window_start=date.fromisoformat(cluster.window["requested_start"]),
            window_end=date.fromisoformat(cluster.window["requested_end"]),
            review_count=len(reviews),
            mean_rating=mean_rating,
            theme_count=cluster.theme_count,
            top_themes=top_themes,
            theme_lines=draft.theme_lines,
            quotes=selection.quotes,
            actions=draft.actions,
            word_count=0,
            compose_source=compose_stats.source,
        )
        rendered = render_note(note)
        note.word_count = count_words(rendered)

        report = validate_note(
            note,
            rendered,
            resolve=store.get_by_id,
            k_max=settings.k_max,
            max_words=pulse_cfg.max_words,
            quote_count=pulse_cfg.quote_count,
            top_themes=pulse_cfg.top_themes,
            window=cluster.window,
        )

        decision = decide(report.failures, attempt)
        decisions.append(
            {
                "attempt": attempt,
                "word_count": note.word_count,
                "failed_gates": report.failures,
                "retry": decision.retry,
                "reason": decision.reason,
            }
        )
        if not decision.retry:
            break

        if decision.reselect_quotes:
            # Drop the length floor, not the ceiling: a theme whose members are
            # all shorter than quote_min_words still has to fit the note.
            selection = select_quotes(
                top_themes,
                reviews,
                vectors=cluster.vectors,
                min_words=1,
                max_words=pulse_cfg.quote_max_words,
                limit=pulse_cfg.quote_count,
            )

    warnings.extend(compose_stats.errors)

    publish_result = None
    note_path: str | None = None
    publish_path: str | None = None
    publish_error: Exception | None = None
    published = False

    if report.passed:
        if publisher is None and live:
            from reviewpulse.publish.mcp import build_mcp_publisher

            publisher = build_mcp_publisher(settings, run_dir, send=send)
        if publisher is None:
            publisher = DryRunPublisher(run_dir, recipient=pulse_cfg.recipient_alias)
        try:
            publish_result, _, _ = publish_note(publisher, note, rendered)
            note_path = str(publisher.note_path)
            publish_path = str(publisher.publish_path)
            published = bool(
                publish_result
                and (
                    publish_result.draft_id
                    or publish_result.message_id
                    or publish_result.doc_id
                )
            )
        except Exception as exc:  # noqa: BLE001 - persist then re-raise
            from reviewpulse.mcp.client import MCPError
            from reviewpulse.models import PublishResult as PublishResultModel

            publish_error = exc
            warnings.append(f"publish failed: {exc}")
            if getattr(publisher, "note_path", None) and publisher.note_path.is_file():
                note_path = str(publisher.note_path)
            if getattr(publisher, "publish_path", None) and publisher.publish_path.is_file():
                publish_path = str(publisher.publish_path)
                try:
                    partial = json.loads(publisher.publish_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    partial = {}
                doc = partial.get("doc") or {}
                publish_result = PublishResultModel(
                    doc_id=doc.get("doc_id"),
                    doc_url=doc.get("url"),
                    draft_id=None,
                    idempotency_key=partial.get("idempotency_key")
                    or idempotency_key(note.window_end),
                )
            if not isinstance(exc, MCPError):
                publish_error = MCPError(str(exc))
    else:
        publisher = publisher or DryRunPublisher(
            run_dir, recipient=pulse_cfg.recipient_alias
        )
        rejected = run_dir / "note.rejected.md"
        rejected.write_text(rendered, encoding="utf-8")
        note_path = str(rejected)
        warnings.append(
            "gates failed; nothing published - see "
            + ", ".join(report.failures)
        )

    manifest_path = _write_pulse_manifest(
        run_dir,
        settings=settings,
        cluster=cluster,
        note=note,
        report=report,
        selection=selection,
        compose_stats=compose_stats,
        decisions=decisions,
        publisher=publisher,
        publish_result=publish_result,
        reviews=reviews,
        mean_rating=mean_rating,
        warnings=warnings,
    )

    result = PulseResult(
        run_id=cluster.run_id,
        note=note,
        rendered=rendered,
        word_count=note.word_count,
        passed=report.passed,
        checks=report.as_checks(),
        gates=report.as_list(),
        attempts=attempt,
        compose_source=compose_stats.source,
        quotes=selection.diagnostics,
        note_path=note_path,
        publish_path=publish_path,
        manifest_path=manifest_path,
        publish_result=publish_result,
        warnings=warnings,
        published=published,
    )
    if publish_error is not None:
        raise publish_error
    return result


def _scrub_flag_histogram(reviews: list) -> dict:
    histogram: dict[str, int] = {}
    for review in reviews:
        for flag in review.scrub_flags:
            histogram[flag] = histogram.get(flag, 0) + 1
    return histogram


def _write_pulse_manifest(
    run_dir: Path,
    *,
    settings: Settings,
    cluster: ClusterResult,
    note,
    report,
    selection,
    compose_stats,
    decisions: list[dict],
    publisher,
    publish_result,
    reviews: list,
    mean_rating: float | None,
    warnings: list[str],
) -> str:
    """Extend the run's manifest rather than replacing the cluster stage's.

    One manifest per run is what makes a questioned quote traceable in a single
    file: theme -> member review_ids -> the quote's own review_id.
    """
    manifest_path = run_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    stages = list(manifest.get("stages", []))
    if manifest.get("stage") and manifest["stage"] not in stages:
        stages.append(manifest["stage"])
    if "pulse" not in stages:
        stages.append("pulse")

    manifest.update(
        {
            "run_id": cluster.run_id,
            "stage": "pulse",
            "stages": stages,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pulse": {
                "analysed_reviews": len(reviews),
                "mean_rating": mean_rating,
                "word_count": note.word_count,
                "max_words": settings.pulse.max_words,
                "compose_source": compose_stats.source,
                "compose_provider": compose_stats.provider,
                "compose_model": compose_stats.model,
                "llm_calls": compose_stats.llm_calls,
                "retries": compose_stats.retries,
                "attempts": decisions,
                "scrub_flags": _scrub_flag_histogram(reviews),
                "top_themes": [
                    {
                        "theme_id": theme.theme_id,
                        "rank": theme.rank,
                        "label": theme.label,
                        "line": note.line_for(theme.theme_id),
                        "size": theme.size,
                        "mean_rating": theme.mean_rating,
                        "neg_share": theme.neg_share,
                        "emerging": theme.emerging,
                        "review_ids": theme.review_ids,
                    }
                    for theme in note.top_themes
                ],
                "quotes": [
                    {
                        "review_id": quote.review_id,
                        "theme_id": quote.theme_id,
                        "rating": quote.rating,
                        "text": quote.text,
                        **next(
                            (
                                {
                                    k: v
                                    for k, v in diag.items()
                                    if k not in {"review_id", "theme_id", "rating"}
                                }
                                for diag in selection.diagnostics
                                if diag["review_id"] == quote.review_id
                            ),
                            {},
                        ),
                    }
                    for quote in note.quotes
                ],
                "actions": [
                    {"text": action.text, "theme_ids": action.theme_ids}
                    for action in note.actions
                ],
            },
            "gates": report.as_list(),
            # The gates win the `themes_capped` name they share with a cluster
            # check. That is safe in one direction only, and it is this one: the
            # gate additionally requires 3 themes in the note, so it cannot pass
            # where the cluster check failed. `gates` keeps the detail either way.
            "checks": {**manifest.get("checks", {}), **report.as_checks()},
            "publish": {
                "mode": getattr(publisher, "mode", "dry_run"),
                "published": bool(
                    publish_result is not None and getattr(publish_result, "draft_id", None)
                ),
                "idempotency_key": publish_result.idempotency_key
                if publish_result
                else idempotency_key(note.window_end),
                "doc_id": publish_result.doc_id if publish_result else None,
                "doc_url": getattr(publish_result, "doc_url", None)
                if publish_result
                else None,
                "draft_id": publish_result.draft_id if publish_result else None,
                "calls": getattr(publisher, "calls", []),
            },
            "warnings": warnings,
        }
    )

    artifacts = dict(manifest.get("artifacts", {}))
    if publish_result is not None:
        artifacts["note"] = str(publisher.note_path)
        artifacts["publish"] = str(publisher.publish_path)
    else:
        artifacts["rejected_note"] = str(run_dir / "note.rejected.md")
    manifest["artifacts"] = artifacts

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return str(manifest_path)


def run_pipeline(
    *,
    dry_run: bool = False,
    window_weeks: int = 12,
    send: bool = False,
    fetch_mode: str = "full",
    skip_if_no_new: bool = False,
    settings: Settings | None = None,
) -> bool:
    """fetch -> ingest -> cluster -> pulse -> publish.

    Live runs verify MCP tool names *before* download or LLM spend, then replace
    the dry-run publisher with `McpPublisher`. `--dry-run` never opens a session.
    `--send` / a scheduled job may call `send_email`; interactive runs draft.
    """
    settings = settings or load_settings()

    if send and dry_run:
        raise ValueError("--send and --dry-run cannot be combined")

    if not dry_run:
        from reviewpulse.mcp.client import MCPConfigError, verify_publish_servers

        verify_publish_servers(settings.mcp, allow_send=send)
        if not settings.pulse.recipient_alias:
            raise MCPConfigError(
                "gmail.recipient_alias is empty; set it in config/settings.toml"
            )

    fetched = fetch_export(
        window_weeks=window_weeks,
        settings=settings,
        fetch_mode=fetch_mode,
    )
    print(
        f"[reviewpulse] Downloaded {fetched.fetched_count} reviews for "
        f"{fetched.app_title or settings.package_id} -> {fetched.export_path}"
        f" ({fetched.fetch_mode})"
    )
    if fetched.coverage_warning:
        print(f"[reviewpulse] warning: {fetched.coverage_warning}")

    ingested = ingest_reviews(
        Path(fetched.export_path),
        window_weeks=window_weeks,
        settings=settings,
        fetch_mode=fetched.fetch_mode,
    )
    print(
        f"[reviewpulse] Stored {ingested.inserted_count} new, "
        f"{ingested.deduped_count} already present -> {ingested.manifest_path}"
    )

    if skip_if_no_new and ingested.inserted_count == 0:
        print("[reviewpulse] schedule skipped: no new reviews")
        return True

    clustered = run_cluster_stage(window_weeks=window_weeks, settings=settings)
    print(
        f"[reviewpulse] Clustered {clustered.clustered_reviews} reviews into "
        f"{clustered.theme_count} themes via {clustered.strategy} "
        f"-> {clustered.clusters_path}"
    )
    for theme in clustered.themes:
        print(
            f"    {theme.rank}. {theme.label} (n={theme.size}, "
            f"rating={theme.mean_rating}, neg={theme.neg_share:.0%})"
        )

    pulse = run_pulse_stage(
        cluster=clustered,
        settings=settings,
        live=not dry_run,
        send=send,
    )
    print(
        f"[reviewpulse] Composed a {pulse.word_count}-word note "
        f"({pulse.compose_source}, {pulse.attempts} attempt(s))"
    )
    for name, passed in pulse.checks.items():
        print(f"    [{'ok' if passed else 'FAIL'}] {name}")
    for warning in pulse.warnings:
        print(f"[reviewpulse] warning: {warning}")

    if not pulse.passed:
        print(
            f"[reviewpulse] Gates failed; nothing published. "
            f"Rejected note: {pulse.note_path}"
        )
        return False

    print(f"[reviewpulse] Note: {pulse.note_path}")
    if dry_run:
        print(f"[reviewpulse] Dry-run publish: {pulse.publish_path}")
        return True

    result = pulse.publish_result
    print(
        f"[reviewpulse] Published via MCP: doc={getattr(result, 'doc_id', None)} "
        f"draft={getattr(result, 'draft_id', None)} "
        f"message={getattr(result, 'message_id', None)} "
        f"key={getattr(result, 'idempotency_key', None)}"
    )
    if getattr(result, "doc_url", None):
        print(f"[reviewpulse] Doc URL: {result.doc_url}")
    return pulse.published


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
