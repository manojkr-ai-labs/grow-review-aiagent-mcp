"""In-process pipeline jobs with a log ring buffer for SSE."""

from __future__ import annotations

import io
import sys
import threading
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from reviewpulse.api.context import ApiContext
from reviewpulse.schedule.lock import ScheduleLock, lock_is_held

PipelineFn = Callable[..., bool]


@dataclass
class PipelineJob:
    job_id: str
    status: str
    dry_run: bool
    send: bool
    window_weeks: int
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class _Tee(io.TextIOBase):
    def __init__(self, job: PipelineJob, downstream: io.TextIOBase) -> None:
        self.job = job
        self.downstream = downstream
        self._buf = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self.job.logs.append(line)
        try:
            self.downstream.write(data)
        except Exception:
            pass
        return len(data)

    def flush(self) -> None:
        if self._buf:
            self.job.logs.append(self._buf)
            self._buf = ""
        try:
            self.downstream.flush()
        except Exception:
            pass


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, PipelineJob] = {}
        self._lock = threading.Lock()
        self._pipeline: PipelineFn | None = None

    def set_pipeline(self, fn: PipelineFn | None) -> None:
        self._pipeline = fn

    def get(self, job_id: str) -> PipelineJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def current_running(self) -> PipelineJob | None:
        with self._lock:
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    return job
        return None

    def start(
        self,
        ctx: ApiContext,
        *,
        window_weeks: int,
        dry_run: bool,
        send: bool,
    ) -> PipelineJob:
        if send and dry_run:
            raise ValueError("send and dry_run cannot be combined")
        if lock_is_held(ctx.lock_path, timeout_minutes=ctx.settings.schedule.lock_timeout_minutes):
            raise LockHeldError("lock_held")
        if self.current_running():
            raise LockHeldError("lock_held")
        job = PipelineJob(
            job_id=uuid.uuid4().hex[:12],
            status="queued",
            dry_run=dry_run,
            send=send,
            window_weeks=window_weeks,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(ctx, job),
            name=f"reviewpulse-job-{job.job_id}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(self, ctx: ApiContext, job: PipelineJob) -> None:
        lock = ScheduleLock(
            ctx.lock_path,
            timeout_minutes=ctx.settings.schedule.lock_timeout_minutes,
        )
        acquired = lock.acquire()
        if not acquired.acquired:
            job.status = "failed"
            job.error = "lock_held"
            job.finished_at = _now()
            return
        job.status = "running"
        job.started_at = _now()
        stdout = _Tee(job, sys.stdout)
        stderr = _Tee(job, sys.stderr)
        try:
            fn = self._pipeline
            if fn is None:
                from reviewpulse.orchestrator import run_pipeline as fn
            with redirect_stdout(stdout), redirect_stderr(stderr):
                ok = fn(
                    dry_run=job.dry_run,
                    window_weeks=job.window_weeks,
                    send=job.send,
                    settings=ctx.settings,
                )
            stdout.flush()
            from reviewpulse.api.catalog import list_run_dirs

            dirs = list_run_dirs(ctx.runs_dir)
            job.run_id = dirs[0].name if dirs else None
            job.status = "succeeded" if ok else "failed"
            if not ok:
                job.error = job.error or "gates_failed"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.logs.append(f"[reviewpulse] job failed: {exc}")
        finally:
            stdout.flush()
            job.finished_at = _now()
            lock.release()


class LockHeldError(RuntimeError):
    pass


JOBS = JobStore()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
