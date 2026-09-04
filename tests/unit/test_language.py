"""Word count and English-detection tests."""

from __future__ import annotations

import pytest

from reviewpulse.sources.language import classify, is_english, word_count


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Easy to start SIP on Groww. Love the interface.", 9),
        ("good app", 2),
        ("", 0),
        ("5 stars 100% 24/7", 1),  # digits are not words
        ("Nice app!!! :) 🚀", 2),  # emoji and punctuation are not words
        ("well-designed easy-to-use interface", 3),  # hyphenated counts once
    ],
)
def test_word_count(text: str, expected: int) -> None:
    assert word_count(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "The best investment app I have found. Direct mutual funds are available.",
        "Application is too slow when market opens and it fails to load charts.",
        "Kindly add MF IDCW fund against dividend reinvestment option and payout option",
        "GROWW APP IS THIRD CLASS APP STOPLOSS NOT WORKING AND CUSTOMER CARE IS BAD",
    ],
)
def test_english_reviews_are_kept(text: str) -> None:
    assert is_english(text) is True


@pytest.mark.parametrize(
    "text,expected_language",
    [
        ("बहुत अच्छा ऐप है मुझे यह पसंद है", "devanagari"),
        ("இந்த செயலி மிகவும் நன்றாக உள்ளது", "tamil"),
        ("చాలా బాగుంది ఈ యాప్ చాలా ఉపయోగకరంగా ఉంది", "telugu"),
        ("هذا التطبيق جيد جدا وسهل الاستخدام", "arabic"),
    ],
)
def test_non_latin_scripts_are_rejected(text: str, expected_language: str) -> None:
    verdict = classify(text)
    assert verdict.is_english is False
    assert verdict.language == expected_language


@pytest.mark.parametrize(
    "text",
    [
        "bhut achha ap hai sab ko achhe se chalana hai",
        "thik thak h bese abhi m kuch bada nahi kar paya hu bas",
        "koi grow use n kare ye apna man se demat account chalu kar deta hai",
        "trading kro mjja kro risk lo par sef jon me",
    ],
)
def test_romanized_hindi_is_rejected(text: str) -> None:
    """Latin script, so only the marker/lexicon signals can catch these."""
    assert is_english(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Day by Day charges badhate ja rhe h..",
        "hamesha slow chalta hai fhaltu ka app hai",
        "automatic share gayab ho jate hai worthless app",
    ],
)
def test_single_marker_with_unknown_words_is_rejected(text: str) -> None:
    """One marker plus mostly unrecognised words still means Hinglish."""
    assert is_english(text) is False


@pytest.mark.parametrize(
    "text",
    [
        # 'hi', 'log', 'tab', 'hue', 'ache', 'niche' and 'lie' read as Hindi but
        # are ordinary English; they must not be treated as markers.
        "hi team please fix the log in tab on the app it keeps failing",
        "the colour hue of the niche sector chart gives me an ache to read",
    ],
)
def test_english_words_that_look_like_markers_are_not_rejected(text: str) -> None:
    assert is_english(text) is True


def test_mixed_script_review_is_rejected() -> None:
    verdict = classify("SIP का पैसा नहीं आया GROWW isme koe sip mat karna")
    assert verdict.is_english is False
    assert verdict.reason.startswith("non_latin_script")


def test_incidental_foreign_word_does_not_reject_english() -> None:
    text = "The app is good but the loading time on the portfolio page is very slow"
    assert is_english(text) is True


def test_empty_text_is_not_english() -> None:
    assert classify("   ").reason == "empty"
