"""Question identity for the five-times count.

Two questions share a key only when this function returns the same string.
The model is not called. Words are not stemmed.
"""

from __future__ import annotations

import unicodedata

_PLACEHOLDERS = (
    "[pan]",
    "[aadhaar]",
    "[account]",
    "[phone]",
    "[email]",
    "[otp]",
)


def question_key(text: str) -> str:
    """Build the stored question key.

    Order: NFKC, casefold, strip redaction placeholders, keep letters and
    digits, collapse whitespace. An empty result is stored as an empty key.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for placeholder in _PLACEHOLDERS:
        normalized = normalized.replace(placeholder, "")
    letters_and_digits = "".join(
        character if character.isalpha() or character.isdecimal() else " "
        for character in normalized
    )
    return " ".join(letters_and_digits.split())


def counts_for_signal(key: str) -> bool:
    """Return whether this question key enters the five-times count.

    An empty key does not. Empty keys must not merge into one signal.
    """
    return question_key(key) != ""
