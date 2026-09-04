"""Pydantic data models for the review pulse pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RawReview(BaseModel):
    """Exactly as the Play Store export provides it."""

    source: Literal["play"] = "play"
    external_id: str | None = None
    rating: int | None = None
    title: str | None = None
    text: str
    date: datetime
    author: str | None = None  # dropped by scrubber, never persisted


class Review(BaseModel):
    """Post-scrub form — the only shape stored in SQLite."""

    review_id: str
    source: str
    rating: int | None = None
    title_clean: str | None = None
    text_clean: str
    date: datetime
    lang: str | None = None
    scrub_flags: list[str] = Field(default_factory=list)


class ThemeLabel(BaseModel):
    """A name and summary for one theme (Phase 2)."""

    label: str
    summary: str


class ThemeLabelEntry(ThemeLabel):
    """One theme's name inside a batch, tied back to its cluster by `theme_id`."""

    theme_id: str


class ThemeLabels(BaseModel):
    """LLM structured output for theme naming: every theme named in one call."""

    labels: list[ThemeLabelEntry]


class Theme(BaseModel):
    theme_id: str
    label: str
    summary: str
    review_ids: list[str] = Field(default_factory=list)
    size: int
    mean_rating: float | None = None
    rank: int
    # Phase 2 additions — computed from the data, never from the LLM.
    neg_share: float = 0.0
    priority: float = 0.0
    trend: float | None = None
    emerging: bool = False
    keywords: list[str] = Field(default_factory=list)
    example_review_ids: list[str] = Field(default_factory=list)
    label_source: Literal["llm", "heuristic"] = "llm"


class Quote(BaseModel):
    review_id: str
    theme_id: str
    text: str
    rating: int | None = None


class ActionIdea(BaseModel):
    text: str
    theme_ids: list[str] = Field(default_factory=list)


class ThemeLine(BaseModel):
    """The one-line description the note prints under a theme's heading."""

    theme_id: str
    line: str


class PulseDraft(BaseModel):
    """LLM structured output for the note (Phase 3 task 3.4).

    The prose frame only. Quotes are absent by construction: the renderer
    injects them from `text_clean`, so the model is never in a position to
    author one.
    """

    theme_lines: list[ThemeLine]
    actions: list[ActionIdea]


class PulseNote(BaseModel):
    run_id: str
    window_start: date
    window_end: date
    review_count: int
    top_themes: list[Theme]
    quotes: list[Quote]
    actions: list[ActionIdea]
    word_count: int
    # Phase 3 additions.
    mean_rating: float | None = None
    theme_count: int = 0  # themes produced by clustering, not just the top 3
    theme_lines: list[ThemeLine] = Field(default_factory=list)
    compose_source: Literal["llm", "heuristic"] = "llm"

    def line_for(self, theme_id: str) -> str:
        for entry in self.theme_lines:
            if entry.theme_id == theme_id:
                return entry.line
        return ""


class PublishResult(BaseModel):
    doc_id: str | None = None
    doc_url: str | None = None
    draft_id: str | None = None
    message_id: str | None = None
    idempotency_key: str
