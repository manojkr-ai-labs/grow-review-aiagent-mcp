"""Phase 6 scheduler: next-fire, lock, incremental cutoff, CLI guards."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from reviewpulse.cli import build_parser, main
from reviewpulse.config import ScheduleSettings
from reviewpulse.schedule.job import run_scheduled_job
from reviewpulse.schedule.lock import ScheduleLock, pid_is_alive
from reviewpulse.schedule.loop import next_fire
from reviewpulse.sources.play_fetch import incremental_fetch_start


KOLKATA = ZoneInfo("Asia/Kolkata")


def test_next_fire_asia_kolkata_from_friday() -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=KOLKATA)  # Friday
    fire = next_fire(now, ScheduleSettings())
    assert fire.tzinfo == KOLKATA
    assert fire.date() == date(2026, 9, 7)  # next Monday
    assert fire.hour == 9
    assert fire.minute == 0


def test_next_fire_same_monday_before_slot() -> None:
    now = datetime(2026, 9, 7, 8, 0, tzinfo=KOLKATA)
    fire = next_fire(now, ScheduleSettings())
    assert fire.date() == date(2026, 9, 7)
    assert fire.hour == 9


def test_next_fire_monday_at_exact_slot_fires_now() -> None:
    now = datetime(2026, 9, 7, 9, 0, tzinfo=KOLKATA)
    fire = next_fire(now, ScheduleSettings())
    assert fire == now


def test_next_fire_monday_after_slot_goes_next_week() -> None:
    now = datetime(2026, 9, 7, 9, 1, tzinfo=KOLKATA)
    fire = next_fire(now, ScheduleSettings())
    assert fire.date() == date(2026, 9, 14)


def test_incremental_cutoff_empty_store_is_full_window() -> None:
    start, mode = incremental_fetch_start(date(2026, 6, 12), None)
    assert start == date(2026, 6, 12)
    assert mode == "full"


def test_incremental_cutoff_uses_newest_minus_one_day() -> None:
    window_start = date(2026, 6, 12)
    newest = date(2026, 9, 3)
    start, mode = incremental_fetch_start(window_start, newest)
    assert start == date(2026, 9, 2)
    assert mode == "incremental"


def test_incremental_cutoff_does_not_go_before_window() -> None:
    window_start = date(2026, 8, 1)
    start, mode = incremental_fetch_start(window_start, date(2026, 8, 1))
    assert start == window_start
    assert mode == "full"


def test_lock_second_acquire_skips_while_held(tmp_path) -> None:
    path = tmp_path / "schedule.lock"
    first = ScheduleLock(path, timeout_minutes=120)
    second = ScheduleLock(path, timeout_minutes=120)
    got = first.acquire()
    assert got.acquired is True
    skipped = second.acquire()
    assert skipped.acquired is False
    assert skipped.reason == "lock_held"
    first.release()
    retry = second.acquire()
    assert retry.acquired is True
    second.release()


def test_lock_steals_dead_pid(tmp_path) -> None:
    path = tmp_path / "schedule.lock"
    path.write_text(
        json.dumps(
            {
                "pid": 999_999_999,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert not pid_is_alive(999_999_999)
    lock = ScheduleLock(path, timeout_minutes=120)
    got = lock.acquire()
    assert got.acquired is True
    assert got.stolen is True
    lock.release()


def test_lock_steals_expired_even_if_pid_alive(tmp_path) -> None:
    path = tmp_path / "schedule.lock"
    started = datetime.now(timezone.utc) - timedelta(hours=3)
    path.write_text(
        json.dumps({"pid": __import__("os").getpid(), "started_at": started.isoformat()}),
        encoding="utf-8",
    )
    lock = ScheduleLock(path, timeout_minutes=120)
    got = lock.acquire()
    assert got.acquired is True
    assert got.stolen is True
    lock.release()


def test_job_skips_when_lock_held(tmp_path, monkeypatch) -> None:
    from reviewpulse import orchestrator
    from reviewpulse.config import load_settings

    path = tmp_path / "schedule.lock"
    held = ScheduleLock(path, timeout_minutes=120)
    assert held.acquire().acquired is True

    called: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "run_pipeline",
        lambda **_: called.append("run") or True,
    )
    settings = load_settings()
    outcome = run_scheduled_job(
        dry_run=True,
        settings=settings,
        lock_path=path,
    )
    assert outcome.status == "skipped"
    assert outcome.reason == "lock_held"
    assert outcome.exit_code == 0
    assert called == []
    held.release()


def test_send_and_dry_run_rejected() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["run", "--send", "--dry-run"])
    assert exc.value.code == 2


def test_schedule_help_exits_zero() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["schedule", "--help"])
    assert exc.value.code == 0


def test_job_runs_incremental_send_pipeline(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def fake_pipeline(**kwargs):
        seen.update(kwargs)
        return True

    monkeypatch.setattr("reviewpulse.orchestrator.run_pipeline", fake_pipeline)
    from reviewpulse.config import load_settings

    settings = load_settings()
    settings.schedule.send_email = True
    outcome = run_scheduled_job(
        dry_run=False,
        settings=settings,
        lock_path=tmp_path / "schedule.lock",
    )
    assert outcome.status == "ok"
    assert seen["send"] is True
    assert seen["fetch_mode"] == "incremental"
    assert seen["dry_run"] is False
    assert seen["skip_if_no_new"] is False


def test_skip_if_no_new_skips_cluster(monkeypatch) -> None:
    from types import SimpleNamespace

    from reviewpulse import orchestrator

    fetched = orchestrator.FetchResult(
        package_id="com.example",
        window_weeks=12,
        window_start="2026-06-08",
        window_end="2026-09-04",
        fetched_count=0,
        export_path="data/raw/stub.csv",
        fetch_mode="incremental",
        fetch_start="2026-09-03",
    )
    monkeypatch.setattr(orchestrator, "fetch_export", lambda **_: fetched)
    monkeypatch.setattr(
        orchestrator,
        "ingest_reviews",
        lambda *_, **__: SimpleNamespace(
            inserted_count=0,
            deduped_count=10,
            manifest_path="runs/stub/manifest.json",
            fetch_mode="incremental",
        ),
    )
    called: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "run_cluster_stage",
        lambda **_: called.append("cluster"),
    )
    assert orchestrator.run_pipeline(dry_run=True, skip_if_no_new=True) is True
    assert called == []
