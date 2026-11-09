"""Pattern counts, windows, and the rising rule."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from supportdesk.compliance import ComplianceSession
from supportdesk.enums import PatternSignal, PatternStatus
from supportdesk.ids import new_case_id, new_execution_id
from supportdesk.pattern import answer_pattern, default_paths
from supportdesk.privacy import contains_pii

WINDOW = {
    "requested_start": "2026-06-01",
    "requested_end": "2026-09-01",
    "actual_start": "2026-06-01",
    "actual_end": "2026-09-01",
}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["review_id", "review_date", "text_clean"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_run(
    path: Path,
    review_ids: list[str],
    *,
    window: dict | None = None,
    early: int | None = 2,
    late: int | None = 2,
    emerging: bool = False,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "clusters.json").write_text(
        json.dumps(
            {
                "window": WINDOW if window is None else window,
                "themes": [
                    {
                        "theme_id": "t1",
                        "cluster_key": "c1",
                        "label": "Customer support responsiveness",
                        "keywords": ["customer", "support", "care"],
                        "review_ids": review_ids,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (path / "cluster_debug.json").write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "cluster_key": "c1",
                        "label": "Customer support responsiveness",
                        "early_count": early,
                        "late_count": late,
                        "emerging": emerging,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _rows(specs: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [
        {"review_id": review_id, "review_date": reviewed_on, "text_clean": text}
        for review_id, reviewed_on, text in specs
    ]


def _ask(tmp_path: Path, message: str = "customer support is not responding", **kwargs):
    return answer_pattern(
        message,
        session=ComplianceSession(),
        case_id=new_case_id(),
        execution_id=new_execution_id(),
        csv_path=kwargs.pop("csv_path", tmp_path / "play_store.csv"),
        run_dir=kwargs.pop("run_dir", tmp_path / "run"),
        **kwargs,
    )


def test_recurring_when_the_ratio_is_below_the_threshold(tmp_path: Path) -> None:
    ids = ["r1", "r2", "r3", "r4"]
    _write_run(tmp_path / "run", ids)
    _write_csv(
        tmp_path / "play_store.csv",
        _rows(
            [
                ("r1", "2026-07-01", "customer support never replied"),
                ("r2", "2026-07-02", "support queue is stuck"),
                ("r3", "2026-07-03", "customer care is slow"),
                ("r4", "2026-08-20", "still waiting on support"),
            ]
        ),
    )
    result = _ask(tmp_path).result
    assert result.matching_count == 4
    assert result.signal is PatternSignal.RECURRING
    assert result.status is PatternStatus.SUCCESS
    assert result.comparable_periods is True
    assert result.analysis_window.start.isoformat() == "2026-06-01"
    assert result.analysis_window.end.isoformat() == "2026-09-01"
    assert result.evidence[0].snippet is not None
    assert "customer support" in result.evidence[0].snippet


def test_rising_uses_the_counted_dates_not_the_emerging_flag(tmp_path: Path) -> None:
    ids = ["r1", "r2", "r3", "r4", "r5", "r6"]
    _write_run(tmp_path / "run", ids, early=0, late=6, emerging=True)
    _write_csv(
        tmp_path / "play_store.csv",
        _rows(
            [
                ("r1", "2026-07-01", "customer support failed"),
                ("r2", "2026-07-15", "support did not answer"),
                ("r3", "2026-08-10", "customer support is worse"),
                ("r4", "2026-08-20", "support still missing"),
                ("r5", "2026-08-25", "customer care queue grew"),
                ("r6", "2026-08-28", "support backlog grew"),
            ]
        ),
    )
    result = _ask(tmp_path).result
    assert result.matching_count == 6
    assert result.signal is PatternSignal.RISING
    assert result.comparable_periods is True
    assert any(item.startswith("early=2 late=4 ") for item in result.limitations)


def test_empty_early_period_is_not_rising(tmp_path: Path) -> None:
    ids = ["r1", "r2", "r3", "r4"]
    _write_run(tmp_path / "run", ids, early=0, late=4, emerging=True)
    _write_csv(
        tmp_path / "play_store.csv",
        _rows([(f"r{i}", "2026-08-20", "customer support failed") for i in range(1, 5)]),
    )
    result = _ask(tmp_path).result
    assert result.matching_count == 4
    assert result.signal is PatternSignal.RECURRING
    assert result.comparable_periods is False
    assert any("not classified as rising" in item for item in result.limitations)


def test_one_match_and_a_below_floor_count(tmp_path: Path) -> None:
    _write_run(tmp_path / "run", ["r1"])
    _write_csv(
        tmp_path / "play_store.csv",
        _rows([("r1", "2026-07-01", "customer support failed")]),
    )
    single = _ask(tmp_path).result
    assert single.signal is PatternSignal.ONE_OFF
    assert single.matching_count == 1

    _write_run(tmp_path / "run", ["r1", "r2"])
    _write_csv(
        tmp_path / "play_store.csv",
        _rows(
            [
                ("r1", "2026-07-01", "customer support failed"),
                ("r2", "2026-07-02", "support did not answer"),
            ]
        ),
    )
    pair = _ask(tmp_path).result
    assert pair.matching_count == 2
    assert pair.signal is PatternSignal.INSUFFICIENT_DATA


def test_empty_csv_missing_dates_and_missing_window(tmp_path: Path) -> None:
    _write_run(tmp_path / "run", ["r1", "r2"])
    _write_csv(tmp_path / "play_store.csv", [])
    empty = _ask(tmp_path).result
    assert empty.matching_count == 0
    assert empty.signal is PatternSignal.INSUFFICIENT_DATA
    assert any("no review rows" in item for item in empty.limitations)

    _write_csv(
        tmp_path / "play_store.csv",
        _rows(
            [
                ("r1", "2026-07-01", "customer support failed"),
                ("r2", "", "support did not answer"),
            ]
        ),
    )
    undated = _ask(tmp_path).result
    assert undated.matching_count == 1
    assert undated.signal is PatternSignal.ONE_OFF
    assert any("no parseable review date" in item for item in undated.limitations)

    _write_run(tmp_path / "run", ["r1"], window={})
    _write_csv(
        tmp_path / "play_store.csv",
        _rows([("r1", "2026-07-01", "customer support failed")]),
    )
    missing_window = _ask(tmp_path).result
    assert missing_window.matching_count == 0
    assert missing_window.signal is PatternSignal.INSUFFICIENT_DATA
    assert missing_window.analysis_window.start is None


def test_missing_theme_file_and_broken_json(tmp_path: Path) -> None:
    _write_csv(tmp_path / "play_store.csv", [])
    missing = _ask(tmp_path, run_dir=tmp_path / "absent").result
    assert missing.status is PatternStatus.INSUFFICIENT_DATA
    assert "theme artifact is missing" in missing.limitations

    run = tmp_path / "broken"
    run.mkdir()
    (run / "clusters.json").write_text("{", encoding="utf-8")
    broken = _ask(tmp_path, run_dir=run).result
    assert broken.status is PatternStatus.ERROR
    assert broken.matching_count == 0


def test_store_intersection_and_pii_are_not_quoted(tmp_path: Path) -> None:
    from reviewpulse.models import Review
    from reviewpulse.store.sqlite import ReviewStore

    ids = ["r1", "r2", "r3", "r4"]
    _write_run(tmp_path / "run", ids, early=4, late=0, emerging=False)
    pan = "ABCDE1234F"
    _write_csv(
        tmp_path / "play_store.csv",
        _rows(
            [
                ("r1", "2026-07-01", f"customer support {pan}"),
                ("r2", "2026-07-02", "support did not answer"),
                ("r3", "2026-07-03", "customer care is slow"),
                ("r4", "2026-07-04", "support queue is stuck"),
            ]
        ),
    )
    db = tmp_path / "reviews.db"
    store = ReviewStore(db)
    for review_id, day in (("r1", 1), ("r2", 2), ("r3", 3)):
        store.upsert(
            Review(
                review_id=review_id,
                source="play",
                text_clean="customer support was slow",
                date=datetime(2026, 7, day, tzinfo=timezone.utc),
            )
        )
    output = _ask(tmp_path, db_path=db)
    result = output.result
    assert result.matching_count == 3
    assert result.signal is PatternSignal.RECURRING
    assert any("not in the review store" in item for item in result.limitations)
    dumped = output.model_dump_json()
    assert pan not in dumped
    assert contains_pii(dumped) is False
    quoted = [item.snippet for item in result.evidence if item.snippet]
    assert quoted
    assert all(pan not in snippet for snippet in quoted)


def test_blocked_message_does_not_depend_on_the_csv(tmp_path: Path) -> None:
    output = _ask(tmp_path, message="   ", csv_path=tmp_path / "missing.csv", run_dir=tmp_path / "absent")
    assert output.result.status is PatternStatus.ERROR
    assert "export CSV" not in output.model_dump_json()
    assert "theme artifact" not in output.model_dump_json()


def test_live_support_theme_count_matches_the_files() -> None:
    csv_path, runs_dir, db_path = default_paths()
    if not csv_path.is_file() or not runs_dir.is_dir():
        pytest.skip("local review export or runs directory is absent")
    runs = [path for path in runs_dir.iterdir() if (path / "clusters.json").is_file()]
    if not runs:
        pytest.skip("no cluster artifact")
    run = max(runs, key=lambda path: path.name)
    output = answer_pattern(
        "The customer support team is not responding.",
        session=ComplianceSession(),
        case_id=new_case_id(),
        csv_path=csv_path,
        run_dir=run,
        db_path=db_path if db_path.is_file() else None,
    )
    result = output.result
    assert any(label.startswith("t1:") for label in result.matched_themes)
    assert result.signal is not PatternSignal.RISING
    assert result.comparable_periods is True
    assert result.matching_count >= 3

    payload = json.loads((run / "clusters.json").read_text(encoding="utf-8"))
    window = payload["window"]
    start = window["actual_start"]
    end = window["actual_end"]
    matched_ids: set[str] = set()
    labels = {label.split(":", 1)[0] for label in result.matched_themes}
    for theme in payload["themes"]:
        if str(theme["theme_id"]) in labels:
            matched_ids.update(theme["review_ids"])
    present: set[str] = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            reviewed = str(row.get("review_date") or "")[:10]
            if row["review_id"] in matched_ids and start <= reviewed <= end:
                present.add(row["review_id"])
    if db_path.is_file():
        from reviewpulse.store.sqlite import ReviewStore

        stored = {item.review_id for item in ReviewStore(db_path).get_by_ids(list(present))}
        present &= stored
    assert result.matching_count == len(present)
    assert result.analysis_window.start.isoformat() == start
    assert result.analysis_window.end.isoformat() == end
