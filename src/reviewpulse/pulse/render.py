"""Render a `PulseNote` to the one-page note (Phase 3 tasks 3.6-3.7).

Quotes are injected here, sliced verbatim out of the stored review text, and
they are the only part of the note the compose chain never touched. Every count,
share and star rating on the page comes from the `Theme` objects, so the numbers
are the database's claim rather than the model's.

Word count is measured on this output, not on the LLM's, because the header,
the counts and the quotes are all words on the page that the model never saw.
"""

from __future__ import annotations

import re
from datetime import date

from reviewpulse.models import PulseNote

TITLE = "Groww \u2014 Weekly Review Pulse"
STAR = "\u2605"
SEP = "\u00b7"

# A token counts as a word if it contains a letter or a digit, so "1,260" and
# "3.2*" count while a bare bullet "-" does not. Anything looser would let the
# 250-word ceiling be gamed by moving content into list markers.
_WORD = re.compile(r"[^\W_]", re.UNICODE)


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if _WORD.search(token))


def format_window(start: date, end: date) -> str:
    return f"{start.isoformat()} to {end.isoformat()}"


def render_note(note: PulseNote) -> str:
    """Markdown/plain-text body, per architecture.md §6.7."""
    lines: list[str] = [_header(note), ""]

    lines.append("Top themes")
    for position, theme in enumerate(note.top_themes, start=1):
        share = theme.size / note.review_count if note.review_count else 0.0
        summary = note.line_for(theme.theme_id) or theme.summary
        emerging = ", rising" if theme.emerging else ""
        lines.append(
            f"{position}. {theme.label} \u2014 {theme.size} reviews ({share:.0%}), "
            f"avg {_stars(theme.mean_rating)}{emerging} {SEP} {summary}"
        )

    lines.extend(["", "What users said"])
    for quote in note.quotes:
        stars = f" \u2014 {quote.rating}{STAR}" if quote.rating is not None else ""
        lines.append(f'- "{quote.text}"{stars}')

    lines.extend(["", "Three things to do next"])
    labels = {theme.theme_id: theme.label for theme in note.top_themes}
    for position, action in enumerate(note.actions, start=1):
        cited = [labels[tid] for tid in action.theme_ids if tid in labels]
        attribution = f" (theme: {', '.join(cited)})" if cited else ""
        lines.append(f"{position}. {action.text}{attribution}")

    return "\n".join(lines).rstrip() + "\n"


def _stars(rating: float | None) -> str:
    return "n/a" if rating is None else f"{rating:.1f}{STAR}"


def _header(note: PulseNote) -> str:
    return (
        f"{TITLE} {SEP} {format_window(note.window_start, note.window_end)} {SEP} "
        f"{note.review_count} reviews {SEP} avg {_stars(note.mean_rating)}"
    )


ASCII_FALLBACK = {STAR: "*", "\u2014": "-", SEP: "-", "\u2018": "'", "\u2019": "'"}


def to_ascii(text: str) -> str:
    """For consoles that cannot encode the note; artifacts keep the real glyphs."""
    for char, replacement in ASCII_FALLBACK.items():
        text = text.replace(char, replacement)
    return text


def render_email_body(note: PulseNote, rendered: str, doc_url: str | None = None) -> str:
    """Gmail body: the same note, plus the doc link when there is one."""
    if not doc_url:
        return rendered
    return f"{rendered}\nFull document: {doc_url}\n"
