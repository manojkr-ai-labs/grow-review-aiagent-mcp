"""The seven gates between synthesis and publishing (Phase 3 task 3.8).

Any failure aborts the run; nothing partial is published (architecture.md §7).
Two of them are worth stating plainly:

* `quotes_verbatim` resolves each quote against the **store**, not against the
  in-memory reviews the pipeline happened to be holding. If a quote cannot be
  traced back to a persisted row it is not defensible, whatever produced it.
* `no_pii` re-runs the ingestion-time detectors on the *final artifact*. The
  same rules at both ends of the pipeline is the point: it catches leakage
  introduced by any stage in between, including the model echoing its prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from reviewpulse.chains.retry_policy import RECOVERABLE_GATES, RESELECTABLE_GATES
from reviewpulse.models import PulseNote, Review
from reviewpulse.privacy.scrubber import contains_pii
from reviewpulse.pulse.render import count_words

GATE_NAMES = (
    "themes_capped",
    "quotes_verbatim",
    "quotes_count",
    "actions_grounded",
    "word_count",
    "no_pii",
    "window_declared",
)

ReviewLookup = Callable[[str], Review | None]


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""

    @property
    def recoverable(self) -> bool:
        return self.name in RECOVERABLE_GATES or self.name in RESELECTABLE_GATES

    def as_dict(self) -> dict:
        return {
            "gate": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "recoverable": self.recoverable,
        }


@dataclass
class ValidationReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> list[str]:
        return [result.name for result in self.results if not result.passed]

    def as_checks(self) -> dict[str, bool]:
        return {result.name: result.passed for result in self.results}

    def as_list(self) -> list[dict]:
        return [result.as_dict() for result in self.results]

    def detail(self, name: str) -> str:
        for result in self.results:
            if result.name == name:
                return result.detail
        return ""


def validate_note(
    note: PulseNote,
    rendered: str,
    *,
    resolve: ReviewLookup,
    k_max: int = 5,
    max_words: int = 250,
    quote_count: int = 3,
    top_themes: int = 3,
    window: dict | None = None,
) -> ValidationReport:
    """Run every gate; never short-circuit, so the manifest shows them all."""
    return ValidationReport(
        results=[
            _themes_capped(note, k_max=k_max, top_themes=top_themes),
            _quotes_verbatim(note, resolve),
            _quotes_count(note, quote_count),
            _actions_grounded(note),
            _word_count(rendered, max_words),
            _no_pii(rendered),
            _window_declared(note, window),
        ]
    )


def _themes_capped(note: PulseNote, *, k_max: int, top_themes: int) -> GateResult:
    total = note.theme_count or len(note.top_themes)
    ok = total <= k_max and len(note.top_themes) == top_themes
    return GateResult(
        "themes_capped",
        ok,
        f"{total} themes clustered (max {k_max}), "
        f"{len(note.top_themes)} in the note (need {top_themes})",
    )


def _quotes_verbatim(note: PulseNote, resolve: ReviewLookup) -> GateResult:
    offenders = []
    for quote in note.quotes:
        review = resolve(quote.review_id)
        if review is None:
            offenders.append(f"{quote.review_id}: not found in store")
        elif quote.text not in review.text_clean:
            offenders.append(f"{quote.review_id}: not a substring of the stored review")
    return GateResult(
        "quotes_verbatim",
        not offenders,
        "; ".join(offenders) or f"{len(note.quotes)} quotes trace to stored review text",
    )


def _quotes_count(note: PulseNote, expected: int) -> GateResult:
    ids = [quote.review_id for quote in note.quotes]
    ok = len(ids) == expected and len(set(ids)) == len(ids)
    return GateResult(
        "quotes_count",
        ok,
        f"{len(ids)} quotes from {len(set(ids))} distinct reviews (need {expected})",
    )


def _actions_grounded(note: PulseNote) -> GateResult:
    known = {theme.theme_id for theme in note.top_themes}
    ungrounded = [
        action.text
        for action in note.actions
        if not any(theme_id in known for theme_id in action.theme_ids)
    ]
    ok = len(note.actions) == 3 and not ungrounded
    detail = f"{len(note.actions)} actions"
    if ungrounded:
        detail += f"; {len(ungrounded)} cite no known theme_id"
    return GateResult("actions_grounded", ok, detail)


def _word_count(rendered: str, max_words: int) -> GateResult:
    words = count_words(rendered)
    return GateResult(
        "word_count", words <= max_words, f"{words} words (max {max_words})"
    )


def _no_pii(rendered: str) -> GateResult:
    leaked = contains_pii(rendered)
    return GateResult(
        "no_pii",
        not leaked,
        "scrubber patterns matched the rendered note"
        if leaked
        else "no scrubber pattern matches the rendered note",
    )


def _window_declared(note: PulseNote, window: dict | None) -> GateResult:
    """The note must not claim a window the data does not cover."""
    if not window:
        return GateResult("window_declared", False, "no window recorded for the run")

    requested_start = _as_date(window.get("requested_start"))
    requested_end = _as_date(window.get("requested_end"))
    actual_start = _as_date(window.get("actual_start"))
    actual_end = _as_date(window.get("actual_end"))

    if note.window_start != requested_start or note.window_end != requested_end:
        return GateResult(
            "window_declared",
            False,
            f"note declares {note.window_start}..{note.window_end} but the run "
            f"queried {requested_start}..{requested_end}",
        )

    if actual_start is None or actual_end is None:
        return GateResult("window_declared", False, "no reviews found in the window")

    if actual_start < requested_start or actual_end > requested_end:
        return GateResult(
            "window_declared",
            False,
            f"data spans {actual_start}..{actual_end}, outside the declared window",
        )

    return GateResult(
        "window_declared",
        True,
        f"declared {requested_start}..{requested_end}, data covers "
        f"{actual_start}..{actual_end}",
    )


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
