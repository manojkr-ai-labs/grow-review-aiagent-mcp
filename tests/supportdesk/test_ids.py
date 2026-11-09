"""Id format, stability, and the rule that ids do not carry message text."""

from __future__ import annotations

import re

from supportdesk.ids import (
    new_case_id,
    new_execution_id,
    new_run_id,
    new_session_id,
    sha256_text,
)

MESSAGE = "The withdrawal is still pending after two days."


def test_ids_match_their_prefix_and_do_not_embed_text() -> None:
    samples = {
        "case": new_case_id(),
        "run": new_run_id(),
        "exec": new_execution_id(),
        "sess": new_session_id(),
    }
    for prefix, value in samples.items():
        assert re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", value)
        assert MESSAGE.casefold() not in value.casefold()
        assert "withdrawal" not in value


def test_ids_are_unique() -> None:
    assert new_case_id() != new_case_id()
    assert new_execution_id() != new_execution_id()
    assert new_run_id() != new_run_id()


def test_sha256_is_stable_and_hides_the_input() -> None:
    first = sha256_text(MESSAGE)
    assert first == sha256_text(MESSAGE)
    assert first != sha256_text(MESSAGE + " ")
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert MESSAGE not in first
