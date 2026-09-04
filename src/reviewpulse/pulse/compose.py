"""Turn ranked themes and selected quotes into the note's prose frame.

The model contributes two things and nothing else: one line per theme and three
actions. Counts, shares, ratings and the quotes themselves are printed by the
renderer straight from the data, which is the same separation Phase 2 applies to
theme labels — the LLM names and narrates, the database asserts.

The model is Gemini (`[pulse.llm]`), not the Groq model Phase 2 labels with; a
chain is handed in already built, so nothing here depends on which.

A missing or unusable answer is a normal offline condition, not an error: the
heuristic frame below keeps `--dry-run` working with no API key at all, which is
what makes every Phase 3 gate verifiable without network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from reviewpulse.models import ActionIdea, PulseDraft, Quote, Theme, ThemeLine

ANCHOR_TERMS = 8

# Deterministic frame only; the LLM path is not held to these.
HEURISTIC_VERBS = ("Prioritise", "Investigate", "Instrument")


@dataclass
class ComposeStats:
    """`provider`/`model` record what was *attempted*, `source` what was used.

    They differ on a run where the model was reachable but its answer was
    unusable, and that is the difference someone reading the manifest after a
    surprising note needs to see.
    """

    source: str = "heuristic"
    provider: str | None = None
    model: str | None = None
    llm_calls: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


def format_stats(
    *,
    window_start: date,
    window_end: date,
    review_count: int,
    mean_rating: float | None,
    theme_count: int,
    top_count: int,
) -> str:
    rating = "n/a" if mean_rating is None else f"{mean_rating:.1f}"
    return (
        f"Window: {window_start.isoformat()} to {window_end.isoformat()}\n"
        f"Reviews analysed: {review_count}\n"
        f"Average rating: {rating} out of 5\n"
        f"Themes found: {theme_count}; the top {top_count} are below"
    )


def format_themes(themes: list[Theme]) -> str:
    """One block per theme, keyed by the id the model has to echo back."""
    blocks = []
    for theme in themes:
        rating = "n/a" if theme.mean_rating is None else f"{theme.mean_rating:.2f}"
        trend = "steady"
        if theme.emerging:
            trend = "rising in the recent half of the window"
        elif theme.trend is not None:
            trend = f"late/early volume ratio {theme.trend:.2f}"
        blocks.append(
            f"[{theme.theme_id}] {theme.label}\n"
            f"  scale: {theme.size} reviews, {theme.neg_share:.0%} rated 1-2 stars, "
            f"mean {rating}\n"
            f"  trend: {trend}\n"
            f"  terms: {', '.join(theme.keywords[:ANCHOR_TERMS])}"
        )
    return "\n\n".join(blocks)


def format_quotes(quotes: list[Quote]) -> str:
    lines = []
    for quote in quotes:
        stars = f"{quote.rating}*" if quote.rating is not None else "?"
        lines.append(f'- [{quote.theme_id}] "{quote.text}" ({stars})')
    return "\n".join(lines)


def heuristic_draft(themes: list[Theme], quotes: list[Quote]) -> PulseDraft:
    """Deterministic frame used when no chat model is configured."""
    lines = [
        ThemeLine(theme_id=theme.theme_id, line=_heuristic_line(theme))
        for theme in themes
    ]
    actions = [
        ActionIdea(text=_heuristic_action(theme, position), theme_ids=[theme.theme_id])
        for position, theme in enumerate(themes)
    ]
    return PulseDraft(theme_lines=lines, actions=actions)


def _heuristic_line(theme: Theme) -> str:
    terms = ", ".join(_distinct_terms(theme.keywords, limit=3))
    subject = f"Complaints centre on {terms}" if terms else "Recurring feedback here"
    if theme.emerging:
        return f"{subject}; volume is rising late in the window"
    return subject


def _distinct_terms(terms: list[str], *, limit: int) -> list[str]:
    """Anchor terms overlap by word ("customer care", "customer support").

    Listing all three spends the line's whole budget saying "customer" three
    times, so a term sharing any word with one already picked is skipped.
    """
    picked: list[str] = []
    seen_words: set[str] = set()
    for term in terms:
        words = set(term.split())
        if words & seen_words:
            continue
        picked.append(term)
        seen_words |= words
        if len(picked) == limit:
            break
    return picked


def _heuristic_action(theme: Theme, position: int) -> str:
    verb = HEURISTIC_VERBS[position % len(HEURISTIC_VERBS)]
    surface = theme.label[:1].lower() + theme.label[1:] if theme.label else "this area"
    if theme.emerging:
        return f"{verb} {surface} before the rising complaint volume compounds"
    return f"{verb} {surface} and close the top complaint reported here"


def compose_draft(
    themes: list[Theme],
    quotes: list[Quote],
    *,
    window_start: date,
    window_end: date,
    review_count: int,
    mean_rating: float | None,
    theme_count: int,
    chain=None,
    retry_chain=None,
    tighter: bool = False,
    stats: ComposeStats | None = None,
) -> tuple[PulseDraft, ComposeStats]:
    """Compose once. Retrying is the orchestrator's call, not this function's.

    `tighter=True` swaps in the retry prompt for the single bounded regeneration
    after a recoverable gate failure.
    """
    stats = stats or ComposeStats()
    active = (retry_chain or chain) if tighter else chain
    if active is None:
        return heuristic_draft(themes, quotes), stats

    payload = {
        "stats": format_stats(
            window_start=window_start,
            window_end=window_end,
            review_count=review_count,
            mean_rating=mean_rating,
            theme_count=theme_count,
            top_count=len(themes),
        ),
        "themes": format_themes(themes),
        "quotes": format_quotes(quotes),
    }

    try:
        stats.llm_calls += 1
        if tighter:
            stats.retries += 1
        result = active.invoke(payload)
    except Exception as exc:  # noqa: BLE001 - degrade to the deterministic frame
        stats.errors.append(f"{type(exc).__name__}: {exc}")
        return heuristic_draft(themes, quotes), stats

    draft = _normalize(result, themes, quotes, stats)
    return draft, stats


def _normalize(
    result,
    themes: list[Theme],
    quotes: list[Quote],
    stats: ComposeStats,
) -> PulseDraft:
    """Tidy whitespace and fill missing theme lines; never repair the actions.

    A theme line the model skipped can be replaced with a deterministic one
    because nothing is gated on it. The actions are gated on
    (`actions_grounded`), so an unusable set is left exactly as returned and the
    gate is allowed to fail — repairing it here would make the gate vacuous.
    """
    draft = result if isinstance(result, PulseDraft) else PulseDraft(**result)

    by_id = {entry.theme_id: entry.line.strip() for entry in draft.theme_lines}
    lines = [
        ThemeLine(
            theme_id=theme.theme_id,
            line=by_id.get(theme.theme_id) or _heuristic_line(theme),
        )
        for theme in themes
    ]

    actions = [
        ActionIdea(text=action.text.strip(), theme_ids=list(action.theme_ids))
        for action in draft.actions
        if action.text.strip()
    ]
    if actions:
        stats.source = "llm"
    else:
        stats.errors.append("model returned no usable actions")
        return heuristic_draft(themes, quotes)

    return PulseDraft(theme_lines=lines, actions=actions)
