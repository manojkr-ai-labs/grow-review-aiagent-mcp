"""Fee-theme selection from clusters.json. No explainer bullets."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from capstone.explainer import NO_FEE_THEME_SENTENCE, select_fee_theme


def _clusters(tmp_path: Path, themes: list[dict]) -> Path:
    path = tmp_path / "clusters.json"
    path.write_text(json.dumps({"themes": themes}), encoding="utf-8")
    return path


def test_larger_qualifying_theme_wins(tmp_path: Path) -> None:
    path = _clusters(
        tmp_path,
        [
            {
                "theme_id": "t-fees",
                "label": "Fees",
                "keywords": ["fee"],
                "size": 4,
            },
            {
                "theme_id": "t-expense",
                "label": "Payments",
                "keywords": ["expense ratio"],
                "size": 9,
            },
            {
                "theme_id": "t-login",
                "label": "Login problems",
                "keywords": ["otp"],
                "size": 40,
            },
            {
                "theme_id": "t-small",
                "label": "Demat charges",
                "keywords": [],
                "size": 2,
            },
        ],
    )

    result = select_fee_theme(path)

    assert result.fee_theme == "t-expense"
    assert result.sentence is None


def test_no_qualifying_theme_returns_null_and_the_bar_sentence(tmp_path: Path) -> None:
    path = _clusters(
        tmp_path,
        [
            {
                "theme_id": "t-feedback",
                "label": "App feedback",
                "keywords": ["feedback"],
                "size": 12,
            },
            {
                "theme_id": "t-login",
                "label": "Login problems",
                "keywords": ["password"],
                "size": 8,
            },
        ],
    )

    result = select_fee_theme(path)

    assert result.fee_theme is None
    assert result.sentence == NO_FEE_THEME_SENTENCE
    assert result.sentence == "No fee theme met the bar."


def test_count_of_two_does_not_qualify(tmp_path: Path) -> None:
    path = _clusters(
        tmp_path,
        [
            {
                "theme_id": "t-fee",
                "label": "Exit load",
                "keywords": ["fee"],
                "size": 2,
            }
        ],
    )

    result = select_fee_theme(path)

    assert result.fee_theme is None
    assert result.sentence == "No fee theme met the bar."


def test_selection_does_not_call_the_facts_retriever() -> None:
    source = inspect.getsource(select_fee_theme)
    assert "answer_facts(" not in source
    assert "explainer.json" not in source
