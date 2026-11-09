"""Twenty real sanitized reviews, measured without storing the reply text."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import pytest

from supportdesk.evalset import SELECTION_METHOD, ExampleSet, measure, select_examples
from supportdesk.pattern import default_paths
from supportdesk.privacy import contains_pii

_FIXTURE = Path(__file__).parent / "fixtures" / "sanitized_examples.json"


def _recorded_run() -> Path:
    """Theme run named by the committed examples. A newer pipeline run stays out."""
    _csv, runs_dir, _db = default_paths()
    stored = ExampleSet.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))
    recorded = runs_dir / stored.run_id
    if not (recorded / "clusters.json").is_file():
        pytest.skip("recorded theme run is absent")
    return recorded


def test_selection_records_the_window_and_stores_redacted_text_only() -> None:
    csv_path, runs_dir, _db = default_paths()
    if not csv_path.is_file() or not runs_dir.is_dir():
        pytest.skip("local review export or runs directory is absent")
    recorded = _recorded_run()
    selected = select_examples(run_dir=recorded)
    assert selected.selection_method == SELECTION_METHOD
    assert selected.source_csv == "data/exports/play_store.csv"
    assert selected.source_csv != "data/publish-state.json"
    assert len(selected.examples) == 20
    assert len({item.source_review_id for item in selected.examples}) == 20
    assert selected.window_start <= selected.window_end
    dumped = selected.model_dump_json()
    assert contains_pii(dumped) is False
    for example in selected.examples:
        assert contains_pii(example.sanitized_text) is False
        assert example.review_date >= selected.window_start
        assert example.review_date <= selected.window_end
        assert example.sanitized_text.strip()
    stored = ExampleSet.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))
    assert stored == selected


def test_twenty_examples_pass_the_safety_measurement() -> None:
    csv_path, runs_dir, _db = default_paths()
    if not csv_path.is_file() or not runs_dir.is_dir():
        pytest.skip("local review export or runs directory is absent")
    recorded = _recorded_run()
    selected = select_examples(run_dir=recorded)
    measured = asyncio.run(measure(selected, run_dir=recorded))
    assert len(measured) == 20
    failed = [item for item in measured if not item.passed]
    assert failed == []
    assert all(item.parallel for item in measured)
    assert {item.source_review_id for item in measured} == {
        item.source_review_id for item in selected.examples
    }
    blob = " ".join(item.model_dump_json() for item in measured)
    assert contains_pii(blob) is False
    facts = Counter(item.facts_status or "blocked" for item in measured)
    signals = Counter(item.pattern_signal or "blocked" for item in measured)
    reviews = Counter(item.reviewer_decision or "not_reviewed" for item in measured)
    states = Counter(item.workflow_state for item in measured)
    summary = (
        f"window={selected.window_start.isoformat()}..{selected.window_end.isoformat()} "
        f"run={selected.run_id} skipped_pii={selected.skipped_residual_pii} "
        f"skipped_empty={selected.skipped_empty} "
        f"facts={dict(facts)} pattern={dict(signals)} "
        f"review={dict(reviews)} state={dict(states)}"
    )
    assert contains_pii(summary) is False
    for example in selected.examples:
        assert example.sanitized_text not in blob
        assert example.sanitized_text not in summary
    assert summary.startswith("window=")
