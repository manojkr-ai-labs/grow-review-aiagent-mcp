"""Exclusive file lock so overlapping weekly ticks do not double-send (F22)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reviewpulse.config import default_lock_path


@dataclass
class LockAcquisition:
    acquired: bool
    stolen: bool = False
    reason: str = ""


def lock_is_held(path: Path | None = None, *, timeout_minutes: int = 120) -> bool:
    """True when a non-stale lock file exists (does not acquire or steal)."""
    lock = ScheduleLock(path, timeout_minutes=timeout_minutes)
    if not lock.path.exists():
        return False
    existing = _read_lock(lock.path)
    if not existing:
        return False
    return not lock._is_stale(existing)


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class ScheduleLock:
    """PID + started-at lock at `data/schedule.lock`."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        timeout_minutes: int = 120,
        pid: int | None = None,
        now: datetime | None = None,
    ) -> None:
        self.path = Path(path or default_lock_path())
        self.timeout = timedelta(minutes=timeout_minutes)
        self.pid = os.getpid() if pid is None else pid
        self._now = now
        self._held = False

    def _clock(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def acquire(self) -> LockAcquisition:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stolen = False
        if self.path.exists():
            existing = _read_lock(self.path)
            if existing and not self._is_stale(existing):
                return LockAcquisition(acquired=False, reason="lock_held")
            stolen = True
            try:
                self.path.unlink()
            except OSError:
                return LockAcquisition(acquired=False, reason="lock_held")
        payload = {
            "pid": self.pid,
            "started_at": self._clock().astimezone(timezone.utc).isoformat(),
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return LockAcquisition(acquired=False, reason="lock_held")
        try:
            os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True
        return LockAcquisition(acquired=True, stolen=stolen)

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            current = _read_lock(self.path)
            if current.get("pid") == self.pid:
                self.path.unlink()
        except OSError:
            return

    def _is_stale(self, payload: dict[str, Any]) -> bool:
        pid = int(payload.get("pid") or 0)
        if not pid_is_alive(pid):
            return True
        started = _parse_started(payload.get("started_at"))
        if started is None:
            return True
        return self._clock() - started > self.timeout

    def __enter__(self) -> LockAcquisition:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_started(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
