"""The weekly job assembles once after a successful pulse and does not publish."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from capstone.assemble import run as assemble_run
from capstone.log import LogStore
from capstone.pipeline_hook import assemble_after_pulse
from reviewpulse.api.context import ApiContext
from reviewpulse.api.jobs import JobStore, PipelineJob
from reviewpulse.config import Settings
from reviewpulse.mcp.client import MCPClient, verify_publish_servers
from reviewpulse.orchestrator import run_pipeline
from reviewpulse.pulse.validate import GATE_NAMES
from supportdesk.facts import RetrievalBundle

CLOCK = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
NOTE = "ALPHA NOTE BODY\n"


def _manifest(*, passed: bool) -> dict:
    return {
        "gates": [
            {"gate": name, "passed": passed, "detail": ""}
            for name in GATE_NAMES
        ]
    }


def _write_run(root: Path, run_id: str, *, passed: bool) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "note.md").write_text(NOTE, encoding="utf-8")
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
    (run_dir / "manifest.json").write_text(
        json.dumps(_manifest(passed=passed)),
        encoding="utf-8",
    )
    return run_dir


def _missing(question: str) -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])


def _ctx(tmp_path: Path) -> ApiContext:
    settings = Settings()
    settings.db_path = tmp_path / "reviews.db"
    return ApiContext(
        settings=settings,
        runs_dir=tmp_path / "runs",
        db_path=settings.db_path,
        publish_state_path=tmp_path / "publish-state.json",
        lock_path=tmp_path / "schedule.lock",
    )


def _job(*, send: bool = False) -> PipelineJob:
    return PipelineJob(
        job_id="job-hook",
        status="queued",
        dry_run=True,
        send=send,
        window_weeks=12,
    )


def test_cli_send_is_not_wired_to_assemble() -> None:
    assert "assemble" not in inspect.getsource(run_pipeline)
    assert "publish_case" not in inspect.getsource(assemble_after_pulse)
    assert "send_email" not in inspect.getsource(assemble_after_pulse)
    assert "MCPClient" not in inspect.getsource(assemble_after_pulse)


def test_success_triggers_assemble_once_and_writes_a_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_ok", passed=True)
    before = (run_dir / "note.md").read_bytes()
    calls: list[str] = []
    real = assemble_run

    def _once(run_id: str, **kwargs):
        calls.append(run_id)
        return real(run_id, **kwargs)

    monkeypatch.setattr("capstone.assemble.run", _once)
    monkeypatch.setattr(
        "capstone.pipeline_hook.assemble_run",
        _once,
    )
    mcp: list[str] = []
    monkeypatch.setattr(
        "reviewpulse.mcp.client.verify_publish_servers",
        lambda *args, **kwargs: mcp.append("verify"),
    )
    monkeypatch.setattr(
        MCPClient,
        "call_tool",
        lambda self, name, arguments: mcp.append(name),
    )

    job = _job(send=True)
    job.status = "succeeded"
    job.run_id = "run_ok"
    result = assemble_after_pulse(
        job,
        runs_dir=tmp_path / "runs",
        store=LogStore(tmp_path / "capstone.db"),
        clock=CLOCK,
        retriever=_missing,
    )

    assert calls == ["run_ok"]
    assert mcp == []
    assert verify_publish_servers  # imported so the patch target exists
    assert result is not None
    assert result.assembled is True
    assert result.package_hash
    assert (run_dir / "note.md").read_bytes() == before
    package = json.loads((run_dir / "package.json").read_text(encoding="utf-8"))
    assert package["package_hash"] == result.package_hash


def test_failed_pulse_does_not_assemble(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_bad", passed=False)
    before = (run_dir / "note.md").read_bytes()

    def boom(*args, **kwargs):
        raise AssertionError("assemble called")

    monkeypatch.setattr("capstone.pipeline_hook.assemble_run", boom)
    job = _job()
    job.status = "failed"
    job.run_id = "run_bad"
    job.error = "gates_failed"

    assert assemble_after_pulse(
        job,
        runs_dir=tmp_path / "runs",
        store=LogStore(tmp_path / "capstone.db"),
        clock=CLOCK,
        retriever=_missing,
    ) is None
    assert (run_dir / "note.md").read_bytes() == before
    assert not (run_dir / "package.json").is_file()
    assert not (run_dir / "explainer.json").is_file()


def test_job_runs_the_hook_once_and_a_failed_job_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = tmp_path / "runs"
    run_dir = _write_run(runs, "run_ok", passed=True)
    before = (run_dir / "note.md").read_bytes()
    store = LogStore(tmp_path / "capstone.db")
    seen: list[str] = []
    real = assemble_after_pulse

    def _wrapped(job, **kwargs):
        seen.append(job.status)
        return real(
            job,
            runs_dir=kwargs["runs_dir"],
            store=store,
            clock=CLOCK,
            retriever=_missing,
        )

    monkeypatch.setattr("capstone.pipeline_hook.assemble_after_pulse", _wrapped)
    mcp: list[str] = []
    monkeypatch.setattr(
        "reviewpulse.mcp.client.verify_publish_servers",
        lambda *args, **kwargs: mcp.append("verify"),
    )
    monkeypatch.setattr(
        MCPClient,
        "call_tool",
        lambda self, name, arguments: mcp.append(name),
    )

    ctx = _ctx(tmp_path)
    jobs = JobStore()
    jobs.set_pipeline(lambda **kwargs: True)
    job = _job(send=True)
    jobs._run(ctx, job)

    assert seen == ["succeeded"]
    assert mcp == []
    assert job.status == "succeeded"
    assert job.run_id == "run_ok"
    package = json.loads((run_dir / "package.json").read_text(encoding="utf-8"))
    assert package["package_hash"]
    assert (run_dir / "note.md").read_bytes() == before

    failed_dir = _write_run(runs, "run_bad", passed=False)
    failed_before = (failed_dir / "note.md").read_bytes()
    jobs.set_pipeline(lambda **kwargs: False)
    failed = _job()
    jobs._run(ctx, failed)

    assert seen == ["succeeded"]
    assert failed.status == "failed"
    assert failed.run_id == "run_ok"
    assert (failed_dir / "note.md").read_bytes() == failed_before
    assert not (failed_dir / "package.json").is_file()


def test_failed_assemble_leaves_the_note_and_writes_no_hash(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "runs", "run_stop", passed=False)
    before = (run_dir / "note.md").read_bytes()
    job = _job()
    job.status = "succeeded"
    job.run_id = "run_stop"

    result = assemble_after_pulse(
        job,
        runs_dir=tmp_path / "runs",
        store=LogStore(tmp_path / "capstone.db"),
        clock=CLOCK,
        retriever=_missing,
    )

    assert result is not None
    assert result.assembled is False
    assert result.package_hash is None
    assert (run_dir / "note.md").read_bytes() == before
    assert not (run_dir / "package.json").is_file()
    assert any("no package hash" in line for line in job.logs)
