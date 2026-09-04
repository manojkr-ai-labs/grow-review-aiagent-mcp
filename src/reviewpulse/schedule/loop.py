"""In-process wait-until-next-slot loop. Ops prefer `--once` + an OS timer."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reviewpulse.config import WEEKDAYS, ScheduleSettings, Settings, load_settings


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown timezone {name!r}. Install the tzdata package "
            "(pip install tzdata) or set schedule.timezone to a valid IANA name."
        ) from exc


def next_fire(now: datetime, schedule: ScheduleSettings) -> datetime:
    """Next `[schedule]` weekday/time strictly in `schedule.timezone`.

    If today's slot is still in the future or is exactly `now`, that slot fires.
    If it has already passed, the following week is returned.
    """
    tz = resolve_timezone(schedule.timezone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(tz)
    target_weekday = WEEKDAYS.index(schedule.weekday)
    candidate = local.replace(
        hour=schedule.hour,
        minute=schedule.minute,
        second=0,
        microsecond=0,
    )
    days_ahead = (target_weekday - candidate.weekday()) % 7
    if days_ahead == 0 and candidate < local:
        days_ahead = 7
    return candidate + timedelta(days=days_ahead)


def run_schedule_loop(
    *,
    dry_run: bool = False,
    window_weeks: int | None = None,
    full_window: bool = False,
    settings: Settings | None = None,
    sleep=time.sleep,
    now_fn=None,
) -> int:
    """Sleep until the next configured slot, run the job, repeat.

    Returns 0 on KeyboardInterrupt. A failed job does not stop the loop.
    """
    from reviewpulse.schedule.job import run_scheduled_job

    settings = settings or load_settings()
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    while True:
        fire = next_fire(clock(), settings.schedule)
        delay = (fire - clock().astimezone(fire.tzinfo)).total_seconds()
        if delay > 0:
            print(
                f"[reviewpulse] schedule sleeping {int(delay)}s until "
                f"{fire.isoformat()}"
            )
            try:
                sleep(delay)
            except KeyboardInterrupt:
                print("[reviewpulse] schedule stopped")
                return 0
        try:
            outcome = run_scheduled_job(
                dry_run=dry_run,
                window_weeks=window_weeks,
                full_window=full_window,
                settings=settings,
            )
        except KeyboardInterrupt:
            print("[reviewpulse] schedule stopped")
            return 0
        print(f"[reviewpulse] schedule tick {outcome.status}: {outcome.reason or 'ok'}")
