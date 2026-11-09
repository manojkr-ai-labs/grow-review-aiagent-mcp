"""Deterministic investment-advice and performance-claim checks.

A failed sell order or an exit-load question is a support request. A request
to buy, sell, hold, redeem, judge suitability, or predict a return is not.
"""

from __future__ import annotations

import re

_ADVICE = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bshould i\b",
        r"\bshall i\b",
        r"\bshould we\b",
        r"\bi should (?:buy|sell|hold|redeem|exit|invest)\b",
        r"\bif i should\b",
        r"\bdo you think i should\b",
        r"\bwould you (?:buy|sell|hold|redeem|exit|invest|recommend)\b",
        r"\bwhat would you do\b",
        r"\bif you were me\b",
        r"\bgood for me\b",
        r"\bright for me\b",
        r"\bsuitable for me\b",
        r"\bsuitability\b",
        r"\bworth investing\b",
        r"\bworth staying\b",
        r"\bstay invested\b",
        r"\brecommend\b",
        r"\byour suggestion\b",
        r"\bsuggest a fund\b",
        r"\bwhich (?:mutual )?fund should i\b",
        r"\bwhich scheme should i\b",
        r"\bwhich one should i\b",
        r"\bwhat should i (?:do|buy|sell|pick|choose)\b",
        r"\bwhether to (?:buy|sell|hold|redeem|exit|invest)\b",
        r"\bwise to (?:buy|sell|hold|redeem|exit|invest|stay)\b",
        r"\bgood idea to (?:buy|sell|hold|redeem|exit|invest)\b",
        r"\btell me (?:to|whether to) (?:buy|sell|hold|redeem|exit|invest)\b",
        r"\b(?:buy|sell|hold|redeem) or (?:buy|sell|hold|redeem)\b",
    )
)

# Vague asks that count only after this session has already requested advice.
_ADVICE_FOLLOWUP = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bin my place\b",
        r"\byour thoughts\b",
        r"\bwhat(?: is|s) the move\b",
        r"\bjust tell me\b",
        r"\bso which\b",
        r"\bwhich one\b",
        r"\bwhat do you think\b",
        r"\banswer anyway\b",
        r"\bignore (?:the |your )?(?:rules|policy|instructions)\b",
    )
)

_PERFORMANCE = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bhow much return\b",
        r"\bhow much will i (?:get|earn|make)\b",
        r"\bwhat returns? (?:can|will|should) i\b",
        r"\breturns? can i expect\b",
        r"\bexpected returns?\b",
        r"\bguaranteed? (?:a |me )?returns?\b",
        r"\bcan you guarantee\b",
        r"\bpredict(?:ed)? returns?\b",
        r"\bwhat cagr\b",
        r"\bwill (?:this|it|the fund|the scheme) (?:beat|outperform)\b",
    )
)

_PERFORMANCE_FOLLOWUP = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bso how much\b",
        r"\bwhat number\b",
        r"\bexpect then\b",
    )
)


def fold_message(text: str) -> str:
    """Lowercase and flatten punctuation so rephrases share one shape."""
    folded = text.casefold().replace("'", "").replace("\u2019", "")
    folded = re.sub(r"[^a-z0-9+\s]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def requests_advice(text: str) -> bool:
    folded = fold_message(text)
    return any(pattern.search(folded) for pattern in _ADVICE)


def continues_advice(text: str) -> bool:
    folded = fold_message(text)
    return any(pattern.search(folded) for pattern in _ADVICE_FOLLOWUP)


def requests_performance(text: str) -> bool:
    folded = fold_message(text)
    return any(pattern.search(folded) for pattern in _PERFORMANCE)


def continues_performance(text: str) -> bool:
    folded = fold_message(text)
    return any(pattern.search(folded) for pattern in _PERFORMANCE_FOLLOWUP)
