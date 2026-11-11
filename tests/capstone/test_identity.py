"""Question key: same wording, no personal-data tokens, no empty merge."""

from __future__ import annotations

from capstone.identity import counts_for_signal, question_key


def test_case_and_spacing_share_one_key() -> None:
    plain = "What is the exit load?"
    varied = "  WHAT   is   the EXIT   load? "
    assert question_key(plain) == question_key(varied)
    assert question_key(plain) == "what is the exit load"


def test_fullwidth_letters_share_the_plain_key() -> None:
    assert question_key("ＥＸＩＴ load") == question_key("exit load")


def test_pan_and_phone_placeholders_share_a_key_with_neither_token() -> None:
    pan = "What is the exit load for [PAN]?"
    phone = "What is the exit load for [phone]?"
    assert question_key(pan) == question_key(phone)
    key = question_key(pan)
    assert "pan" not in key
    assert "phone" not in key
    assert "[pan]" not in key
    assert "[phone]" not in key


def test_every_redaction_placeholder_is_stripped() -> None:
    text = "Fee for [PAN] [aadhaar] [account] [phone] [email] [otp] please"
    key = question_key(text)
    assert key == "fee for please"
    for token in ("pan", "aadhaar", "account", "phone", "email", "otp"):
        assert token not in key


def test_empty_or_punctuation_only_yields_an_empty_key() -> None:
    for text in ("", "   ", "???", "!!!", "---"):
        key = question_key(text)
        assert key == ""
        assert counts_for_signal(key) is False


def test_a_real_question_counts_and_is_not_stemmed() -> None:
    key = question_key("What is the exit load?")
    assert counts_for_signal(key) is True
    assert question_key("exit loads") != question_key("exit load")
