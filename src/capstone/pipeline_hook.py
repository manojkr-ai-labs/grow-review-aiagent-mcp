"""One assemble call after a successful weekly pulse.

The hook does not publish and does not open an MCP client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from capstone.assemble import AssembleResult, run as assemble_run
from capstone.log import LogStore
from supportdesk.facts import RetrievalBundle


class _FinishedJob(Protocol):
    status: str
    run_id: str | None
    logs: list[str]


def assemble_after_pulse(
    job: _FinishedJob,
    *,
    runs_dir: Path,
    store: LogStore | None = None,
    clock: datetime | None = None,
    retriever=None,
) -> AssembleResult | None:
    """Assemble when the pulse job succeeded and a run id is set.

    A failed pulse is not assembled. A failed assemble leaves the note in
    place and returns no package hash.
    """
    if job.status != "succeeded" or not job.run_id:
        return None
    result = assemble_run(
        job.run_id,
        store=store if store is not None else LogStore(),
        clock=clock if clock is not None else datetime.now(timezone.utc),
        retriever=retriever if retriever is not None else _missing,
        runs_dir=runs_dir,
    )
    if not result.assembled:
        job.logs.append("[capstone] assemble wrote no package hash")
    return result


def _missing(question: str) -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])
