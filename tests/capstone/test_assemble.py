"""Assemble writes the package hash and leaves note.md unchanged."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from capstone.assemble import run
from capstone.contracts import QuestionLogRow, WeeklyPackageManifest
from capstone.explainer import EMPTY_LEDGER_SENTENCE
from capstone.identity import question_key
from capstone.log import LogStore
from capstone.package import package_hash
from capstone.record import week_id_for
from reviewpulse.pulse.validate import GATE_NAMES
from supportdesk.facts import RetrievalBundle

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
WEEK = week_id_for(CLOCK)
NOTE = "ALPHA NOTE BODY\n"
PASSAGE = "Exit load is listed on the scheme page."
GROWW = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
QUESTION = "What is the exit load?"


def _manifest(*, passed: bool) -> dict:
    return {
        "gates": [
            {"gate": name, "passed": passed, "detail": ""}
            for name in GATE_NAMES
        ]
    }


def _failed_manifest() -> dict:
    return {
        "gates": [
            {"gate": name, "passed": name != "word_count", "detail": ""}
            for name in GATE_NAMES
        ]
    }


def _write_run(root: Path, run_id: str, manifest: dict, note: str = NOTE) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "note.md").write_text(note, encoding="utf-8")
    (run_dir / "clusters.json").write_text(
        json.dumps(
            {
                "themes": [
                    {
                        "theme_id": "t-fees",
                        "label": "Fees",
                        "keywords": ["fee"],
                        "size": 4,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _store(tmp_path: Path, count: int) -> LogStore:
    store = LogStore(tmp_path / "capstone.db")
    for number in range(1, count + 1):
        store.append(
            QuestionLogRow(
                case_id=f"case_{number:032x}",
                week_id=WEEK,
                question_key=question_key(QUESTION),
                sanitized_text=QUESTION,
                facts_coverage="covered",
                searched_urls=[GROWW],
                created_at=CLOCK,
            )
        )
    return store


def _hit(question: str) -> RetrievalBundle:
    return RetrievalBundle(
        status="hit",
        chunks=[
            {
                "source_url": GROWW,
                "source_title": "HDFC Mid Cap Fund — Direct Growth",
                "text": PASSAGE,
                "retrieved_on": "2026-09-01",
            }
        ],
    )


def _missing(question: str) -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])


def _json_names(run_dir: Path) -> list[str]:
    return [
        name
        for name in ("explainer.json", "support_signals.json", "package.json")
        if (run_dir / name).is_file()
    ]


def test_passing_run_hash_is_stable_and_the_note_is_unchanged(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_ok", _manifest(passed=True))
    before = (run_dir / "note.md").read_bytes()
    store = _store(tmp_path, 5)

    first = run("run_ok", store=store, clock=CLOCK, retriever=_hit, runs_dir=tmp_path / "runs")
    second = run("run_ok", store=store, clock=CLOCK, retriever=_hit, runs_dir=tmp_path / "runs")

    assert first.assembled is True
    assert first.package_hash == second.package_hash
    assert (run_dir / "note.md").read_bytes() == before
    assert (run_dir / "explainer.json").is_file()
    assert (run_dir / "support_signals.json").is_file()
    signals = json.loads((run_dir / "support_signals.json").read_text(encoding="utf-8"))
    assert len(signals) == 1
    assert signals[0]["count"] == 5
    package = WeeklyPackageManifest.model_validate_json(
        (run_dir / "package.json").read_text(encoding="utf-8")
    )
    assert package.package_hash == first.package_hash
    assert package.fee_theme == "t-fees"
    assert NOTE.strip() not in (run_dir / "package.json").read_text(encoding="utf-8")
    assert package.package_hash == package_hash(
        before,
        (run_dir / "explainer.json").read_bytes(),
        (run_dir / "support_signals.json").read_bytes(),
    )


def test_failed_pulse_manifest_writes_no_json_and_no_hash(tmp_path: Path) -> None:
    def boom(question: str) -> RetrievalBundle:
        raise AssertionError("retriever called")

    run_dir = _write_run(tmp_path / "runs", "run_bad", _failed_manifest())
    outcome = run(
        "run_bad",
        store=LogStore(tmp_path / "capstone.db"),
        clock=CLOCK,
        retriever=boom,
        runs_dir=tmp_path / "runs",
    )

    assert outcome.assembled is False
    assert outcome.package_hash is None
    assert _json_names(run_dir) == []

    missing = _write_run(tmp_path / "runs", "run_missing", {})
    outcome = run(
        "run_missing",
        store=LogStore(tmp_path / "other.db"),
        clock=CLOCK,
        retriever=boom,
        runs_dir=tmp_path / "runs",
    )
    assert outcome.assembled is False
    assert _json_names(missing) == []


def test_empty_signals_and_ledger_still_hash_the_empty_sentence(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_empty", _manifest(passed=True))
    outcome = run(
        "run_empty",
        store=LogStore(tmp_path / "capstone.db"),
        clock=CLOCK,
        retriever=_missing,
        runs_dir=tmp_path / "runs",
    )

    assert outcome.assembled is True
    explainer = json.loads((run_dir / "explainer.json").read_text(encoding="utf-8"))
    assert explainer["bullets"][-1]["text"] == EMPTY_LEDGER_SENTENCE
    assert json.loads((run_dir / "support_signals.json").read_text(encoding="utf-8")) == []
    assert EMPTY_LEDGER_SENTENCE.encode("utf-8") in (run_dir / "explainer.json").read_bytes()
    assert outcome.package_hash == package_hash(
        (run_dir / "note.md").read_bytes(),
        (run_dir / "explainer.json").read_bytes(),
        (run_dir / "support_signals.json").read_bytes(),
    )


def test_one_byte_note_change_changes_the_hash(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_byte", _manifest(passed=True))
    store = LogStore(tmp_path / "capstone.db")
    first = run(
        "run_byte",
        store=store,
        clock=CLOCK,
        retriever=_missing,
        runs_dir=tmp_path / "runs",
    )
    note = run_dir / "note.md"
    note.write_bytes(note.read_bytes().replace(b"A", b"B", 1))
    second = run(
        "run_byte",
        store=store,
        clock=CLOCK,
        retriever=_missing,
        runs_dir=tmp_path / "runs",
    )

    assert first.package_hash != second.package_hash


def test_assemble_does_not_publish() -> None:
    source = Path(run.__code__.co_filename).read_text(encoding="utf-8")
    assert "publish_case" not in source
    assert "import mcp" not in source
