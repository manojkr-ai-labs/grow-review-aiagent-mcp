"""CORS_ORIGINS parsing (deployment-plan.md §5.2)."""

from __future__ import annotations

import pytest

from reviewpulse.api.cors import DEFAULT_CORS_ORIGINS, cors_origins


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == list(DEFAULT_CORS_ORIGINS)


def test_comma_separated_list() -> None:
    assert cors_origins("https://web.up.railway.app, http://127.0.0.1:3000") == [
        "https://web.up.railway.app",
        "http://127.0.0.1:3000",
    ]


def test_blank_falls_back() -> None:
    assert cors_origins("  ,  ") == list(DEFAULT_CORS_ORIGINS)


def test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://console.example")
    assert cors_origins() == ["https://console.example"]
