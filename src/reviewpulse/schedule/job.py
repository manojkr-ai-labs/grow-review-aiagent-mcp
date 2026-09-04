"""One weekly tick: lock → verify MCP → incremental fetch → classify → publish."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reviewpulse.config import Settings, default_lock_path, load_settings
from reviewpulse.schedule.lock import ScheduleLock


@dataclass
class JobOutcome:
    status: str  # ok | failed | skipped
    reason: str = ""
    inserted_count: int | None = None
    passed: bool | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def run_scheduled_job(
    *,
    dry_run: bool = False,
    window_weeks: int | None = None,
    full_window: bool = False,
    settings: Settings | None = None,
    lock_path: Path | None = None,
    lock: ScheduleLock | None = None,
) -> JobOutcome:
    """Body of `reviewpulse schedule --once` (and each in-process loop tick)."""
    from reviewpulse.orchestrator import run_pipeline

    settings = settings or load_settings()
    weeks = window_weeks or settings.schedule.window_weeks
    send = bool(settings.schedule.send_email) and not dry_run
    fetch_mode = "full" if full_window else "incremental"
    lock_file = Path(lock_path or default_lock_path())
    held = lock or ScheduleLock(
        lock_file,
        timeout_minutes=settings.schedule.lock_timeout_minutes,
    )
    acquisition = held.acquire()
    if not acquisition.acquired:
        print(f"[reviewpulse] schedule skipped: {acquisition.reason}")
        return JobOutcome(status="skipped", reason=acquisition.reason)
    if acquisition.stolen:
        print("[reviewpulse] schedule stole a stale lock")
    try:
        passed = run_pipeline(
            dry_run=dry_run,
            window_weeks=weeks,
            send=send,
            fetch_mode=fetch_mode,
            skip_if_no_new=settings.schedule.skip_if_no_new,
            settings=settings,
        )
        if passed:
            return JobOutcome(status="ok", passed=True)
        return JobOutcome(status="failed", passed=False, reason="gates_failed")
    finally:
        held.release()
