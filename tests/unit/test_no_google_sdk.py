"""Guardrail: Google credentials stay in the MCP servers (architecture D1)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "reviewpulse"
FORBIDDEN = ("googleapiclient", "google.oauth2", "google.auth", "from googleapiclient")


def test_no_direct_google_api_or_oauth_in_src() -> None:
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)}: {needle}")
    assert hits == []
