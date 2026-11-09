"""Deterministic PII detection and redaction.

This module is separate from ``reviewpulse.privacy.scrubber``. Review ingest
keeps its own scrubber. Support-desk text is redacted here, before a
``SanitizedRequest`` exists.

A value is redacted only when a pattern matches. The word "PAN" or "folio"
without a value is left as written. Released text is scanned again; if any
pattern still matches, the text is withheld.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from supportdesk.enums import PiiCategory

# Indian PAN: five letters, four digits, one letter.
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
# Indian mobile, optional +91, optional space or hyphen after the first five digits.
# Hex letters count as part of the token so a SHA-256 or execution id is not a phone.
_PHONE = re.compile(
    r"(?<![A-Fa-f0-9])(?:\+91[\s-]?)?(?:[6-9]\d{4}[\s-]?\d{5}|[6-9]\d{9})(?![A-Fa-f0-9])"
)
# Code next to an OTP/PIN cue. The cue word stays; the digits are redacted.
_OTP = re.compile(
    r"\b(?:otp|one[\s-]?time(?:\s+password)?|pin)\b.{0,24}?\b(\d{4,8})\b",
    re.IGNORECASE,
)
# 4-4-4 with a separator. Contiguous 12 digits are handled separately.
_AADHAAR_SEPARATED = re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b")
# Exactly 12 digits is Aadhaar length. Longer runs are account numbers.
_AADHAAR_CONTIGUOUS = re.compile(r"\b\d{12}\b")
_ACCOUNT_DIGITS = re.compile(r"\b\d{13,}\b")
_ACCOUNT_LABELED = re.compile(
    r"\b(?:account|customer|folio|client)\s*(?:id|number|no|num)\b"
    r"\s*(?:is\s+)?[:#-]?\s*((?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{5,})",
    re.IGNORECASE,
)

_PLACEHOLDER = {
    PiiCategory.PAN: "[pan]",
    PiiCategory.AADHAAR: "[aadhaar]",
    PiiCategory.ACCOUNT: "[account]",
    PiiCategory.PHONE: "[phone]",
    PiiCategory.EMAIL: "[email]",
    PiiCategory.OTP: "[otp]",
}

# Higher priority wins when two patterns cover the same characters.
_PRIORITY = {
    PiiCategory.OTP: 50,
    PiiCategory.PAN: 40,
    PiiCategory.EMAIL: 40,
    PiiCategory.PHONE: 30,
    PiiCategory.ACCOUNT: 30,
    PiiCategory.AADHAAR: 20,
}


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    category: PiiCategory

    @property
    def priority(self) -> int:
        return _PRIORITY[self.category]


@dataclass(frozen=True)
class Redaction:
    """Redacted text, or an empty string when the result is not safe to release."""

    text: str
    categories: tuple[PiiCategory, ...]
    sanitized: bool

    @property
    def blocked(self) -> bool:
        return not self.sanitized


def contains_pii(text: str) -> bool:
    """True when any support-desk PII pattern matches."""
    return bool(_spans(text))


def redact_pii(text: str) -> Redaction:
    """Replace PII with category placeholders.

    The original value is not copied into the result. If a pattern still
    matches afterwards, ``text`` is empty and ``sanitized`` is false.
    """
    spans = _choose(_spans(text))
    if not spans:
        return Redaction(text=text, categories=(), sanitized=True)

    pieces: list[str] = []
    cursor = 0
    categories: list[PiiCategory] = []
    for span in spans:
        pieces.append(text[cursor : span.start])
        pieces.append(_PLACEHOLDER[span.category])
        categories.append(span.category)
        cursor = span.end
    pieces.append(text[cursor:])
    redacted = "".join(pieces)
    ordered = tuple(category for category in PiiCategory if category in categories)
    return release_text(redacted, ordered)


def release_text(text: str, categories: tuple[PiiCategory, ...] = ()) -> Redaction:
    """Release ``text`` only when no PII pattern still matches."""
    if contains_pii(text):
        return Redaction(text="", categories=categories, sanitized=False)
    return Redaction(text=text, categories=categories, sanitized=True)


def _spans(text: str) -> list[_Span]:
    if not text:
        return []
    found: list[_Span] = []
    for match in _OTP.finditer(text):
        found.append(_Span(match.start(1), match.end(1), PiiCategory.OTP))
    for pattern, category in (
        (_PAN, PiiCategory.PAN),
        (_EMAIL, PiiCategory.EMAIL),
        (_PHONE, PiiCategory.PHONE),
        (_AADHAAR_SEPARATED, PiiCategory.AADHAAR),
        (_AADHAAR_CONTIGUOUS, PiiCategory.AADHAAR),
        (_ACCOUNT_DIGITS, PiiCategory.ACCOUNT),
    ):
        for match in pattern.finditer(text):
            found.append(_Span(match.start(), match.end(), category))
    for match in _ACCOUNT_LABELED.finditer(text):
        found.append(_Span(match.start(1), match.end(1), PiiCategory.ACCOUNT))
    return found


def _choose(spans: list[_Span]) -> list[_Span]:
    """Keep non-overlapping spans. The same start keeps the higher priority."""
    ordered = sorted(spans, key=lambda span: (span.start, -span.priority, -(span.end - span.start)))
    chosen: list[_Span] = []
    occupied = -1
    for span in ordered:
        if span.start < occupied or span.end <= span.start:
            continue
        chosen.append(span)
        occupied = span.end
    return chosen
