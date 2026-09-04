"""Phase 0 bootstrap tests."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from reviewpulse.cli import build_parser, main
from reviewpulse.models import (
    ActionIdea,
    PulseNote,
    PublishResult,
    Quote,
    RawReview,
    Review,
    Theme,
    ThemeLabel,
)


def test_models_raw_review_defaults() -> None:
    review = RawReview(
        text="Good app",
        date=datetime(2026, 8, 1, 12, 0, 0),
    )
    assert review.source == "play"
    assert review.author is None


def test_models_pulse_note_shape() -> None:
    theme = Theme(
        theme_id="t1",
        label="KYC delays",
        summary="Users report slow verification.",
        review_ids=["r1"],
        size=10,
        mean_rating=2.1,
        rank=1,
    )
    note = PulseNote(
        run_id="run-1",
        window_start=date(2026, 6, 1),
        window_end=date(2026, 8, 31),
        review_count=100,
        top_themes=[theme, theme, theme],
        quotes=[
            Quote(review_id="r1", theme_id="t1", text="KYC pending", rating=2),
            Quote(review_id="r2", theme_id="t1", text="Still waiting", rating=1),
            Quote(review_id="r3", theme_id="t1", text="Verify faster", rating=2),
        ],
        actions=[
            ActionIdea(text="Reduce KYC SLA", theme_ids=["t1"]),
            ActionIdea(text="Add status page", theme_ids=["t1"]),
            ActionIdea(text="Notify on delay", theme_ids=["t1"]),
        ],
        word_count=200,
    )
    assert note.word_count <= 250
    assert len(note.quotes) == 3


def test_theme_label_structured_output_fields() -> None:
    label = ThemeLabel(label="Payment failures", summary="UPI errors during checkout.")
    assert label.label
    assert label.summary


def test_publish_result_idempotency_key() -> None:
    result = PublishResult(idempotency_key="groww:2026-W35")
    assert result.doc_id is None
    assert result.idempotency_key.startswith("groww:")


def test_review_scrub_flags_default() -> None:
    review = Review(
        review_id="abc",
        source="play",
        text_clean="Hello",
        date=datetime(2026, 8, 1),
    )
    assert review.scrub_flags == []


def test_cli_help_exits_zero() -> None:
    parser = build_parser()
    with __import__("pytest").raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


def test_cli_run_dry_run(monkeypatch) -> None:
    # `run` downloads and stores before the Phase 2+ stages; stub both so the
    # test stays offline and leaves the real database untouched.
    from reviewpulse import orchestrator

    fetched = orchestrator.FetchResult(
        package_id="com.example",
        window_weeks=12,
        window_start="2026-06-08",
        window_end="2026-08-31",
        fetched_count=3,
        export_path="data/raw/stub.csv",
    )
    monkeypatch.setattr(orchestrator, "fetch_export", lambda **_: fetched)
    monkeypatch.setattr(
        orchestrator,
        "ingest_reviews",
        lambda *_, **__: SimpleNamespace(
            inserted_count=3,
            deduped_count=0,
            manifest_path="runs/stub/manifest.json",
        ),
    )

    assert main(["run", "--dry-run", "--window-weeks", "12"]) == 0


def test_cli_run_live_fails_before_fetch_when_mcp_is_unconfigured(monkeypatch) -> None:
    from reviewpulse import orchestrator
    from reviewpulse.config import EXAMPLE_SETTINGS_PATH, load_settings as real_load

    monkeypatch.setattr(
        orchestrator, "load_settings", lambda: real_load(EXAMPLE_SETTINGS_PATH)
    )

    called: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "fetch_export",
        lambda **_: called.append("fetch") or (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    assert main(["run", "--window-weeks", "12"]) == 1
    assert called == []
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["run", "--window-weeks", "0"])
    assert exc.value.code == 2


def test_cli_mcp_check_fails_when_unconfigured(monkeypatch) -> None:
    from reviewpulse import cli as cli_mod
    from reviewpulse.config import EXAMPLE_SETTINGS_PATH, load_settings as real_load

    monkeypatch.setattr(cli_mod, "load_settings", lambda: real_load(EXAMPLE_SETTINGS_PATH))
    assert main(["mcp-check"]) == 1
