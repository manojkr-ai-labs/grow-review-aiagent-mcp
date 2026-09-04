"""PII scrubbing — runs before persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reviewpulse.models import RawReview, Review
from reviewpulse.store.sqlite import compute_review_id

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{4,6}(?!\d)"
)
LONG_DIGIT_PATTERN = re.compile(r"\b\d{12,}\b")
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
HANDLE_PATTERN = re.compile(r"(?<!\w)@([A-Za-z0-9_]{2,})\b")
URL_QUERY_PATTERN = re.compile(
    r"https?://[^\s]+?\?[^\s]+",
    re.IGNORECASE,
)

BRAND_HANDLES = frozenset({"groww"})


@dataclass(frozen=True)
class ScrubRule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


SCRUB_RULES: tuple[ScrubRule, ...] = (
    ScrubRule("email", EMAIL_PATTERN, "[email]"),
    ScrubRule("number", LONG_DIGIT_PATTERN, "[number]"),
    ScrubRule("phone", PHONE_PATTERN, "[phone]"),
    ScrubRule("uuid", UUID_PATTERN, "[uuid]"),
    ScrubRule("url", URL_QUERY_PATTERN, "[url]"),
)


def scrub_text(text: str) -> tuple[str, list[str]]:
    """Redact PII patterns; return cleaned text and scrub flag names."""
    flags: list[str] = []
    cleaned = text

    for rule in SCRUB_RULES:
        if rule.pattern.search(cleaned):
            cleaned = rule.pattern.sub(rule.replacement, cleaned)
            flags.append(rule.name)

    cleaned, handle_flags = _scrub_handles(cleaned)
    flags.extend(handle_flags)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_flags = []
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            unique_flags.append(flag)

    return cleaned, unique_flags


def scrub_raw_review(raw: RawReview) -> Review:
    """Convert RawReview to scrubbed Review. Author is never carried forward."""
    title_clean = None
    title_flags: list[str] = []
    if raw.title:
        title_clean, title_flags = scrub_text(raw.title)

    text_clean, text_flags = scrub_text(raw.text)
    scrub_flags = _merge_flags(title_flags, text_flags)

    return Review(
        review_id=compute_review_id(raw),
        source=raw.source,
        rating=raw.rating,
        title_clean=title_clean,
        text_clean=text_clean,
        date=raw.date,
        lang=detect_language(text_clean),
        scrub_flags=scrub_flags,
    )


def contains_pii(text: str) -> bool:
    """Return True if any scrubber pattern matches (for output validation gates)."""
    for rule in SCRUB_RULES:
        if rule.pattern.search(text):
            return True
    if HANDLE_PATTERN.search(text):
        for match in HANDLE_PATTERN.finditer(text):
            if match.group(1).lower() not in BRAND_HANDLES:
                return True
    return False


def _scrub_handles(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []

    def replace(match: re.Match[str]) -> str:
        handle = match.group(1)
        if handle.lower() in BRAND_HANDLES:
            return match.group(0)
        flags.append("handle")
        return "[handle]"

    return HANDLE_PATTERN.sub(replace, text), flags


def _merge_flags(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for flag in group:
            if flag not in seen:
                seen.add(flag)
                merged.append(flag)
    return merged


def detect_language(text: str) -> str:
    from reviewpulse.sources.normalize import detect_language as _detect

    return _detect(text)
