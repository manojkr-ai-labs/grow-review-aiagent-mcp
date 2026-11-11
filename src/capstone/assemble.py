"""Build the weekly package from a finished pulse run.

Does not publish, and does not import an MCP client.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from capstone.contracts import PACKAGE_FILES, Explainer, WeeklyPackageManifest
from capstone.explainer import factual_bullets, ledger_bullet, select_fee_theme
from capstone.gates import explainer_gates, pulse_gates_passed
from capstone.log import LogStore
from capstone.package import canonical_json, package_hash
from capstone.record import week_id_for
from capstone.signals import queue_signals_for_week
from supportdesk.facts import RetrievalBundle


class AssembleResult(BaseModel):
    """Hash of one assembled package, or the reason assembly stopped."""

    model_config = ConfigDict(extra="forbid")

    assembled: bool
    codes: list[str]
    package_hash: str | None = None
    fee_theme: str | None = None

    @model_validator(mode="after")
    def hash_follows_assembly(self) -> AssembleResult:
        if self.assembled and not self.package_hash:
            raise ValueError("an assembled package has a hash")
        if not self.assembled and self.package_hash is not None:
            raise ValueError("a refused package has no hash")
        return self


def run(
    run_id: str,
    *,
    store: LogStore,
    clock: datetime,
    retriever: Callable[[str], RetrievalBundle],
    runs_dir: Path | None = None,
) -> AssembleResult:
    """Write the two JSON files and ``package.json`` when the pulse gates passed."""
    run_dir = (Path("runs") if runs_dir is None else Path(runs_dir)) / run_id
    note_path = run_dir / "note.md"
    clusters_path = run_dir / "clusters.json"
    manifest_path = run_dir / "manifest.json"
    if not note_path.is_file() or not clusters_path.is_file():
        return AssembleResult(assembled=False, codes=["pulse_gates"])
    if not manifest_path.is_file():
        return AssembleResult(assembled=False, codes=["pulse_gates"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not pulse_gates_passed(manifest):
        return AssembleResult(assembled=False, codes=["pulse_gates"])

    week_id = week_id_for(clock)
    fee = select_fee_theme(clusters_path)
    factual = factual_bullets(retriever)
    bullets = [*factual, ledger_bullet(store.list_ledger(week_id))]
    codes = explainer_gates(bullets)
    if codes:
        return AssembleResult(assembled=False, codes=codes, fee_theme=fee.fee_theme)

    signals = queue_signals_for_week(store, week_id)
    explainer = Explainer(week_id=week_id, fee_theme=fee.fee_theme, bullets=bullets)
    signal_bytes = canonical_json([item.model_dump(mode="json") for item in signals])
    explainer_bytes = canonical_json(explainer.model_dump(mode="json"))
    (run_dir / "support_signals.json").write_bytes(signal_bytes)
    (run_dir / "explainer.json").write_bytes(explainer_bytes)
    digest = package_hash(
        note_path.read_bytes(),
        (run_dir / "explainer.json").read_bytes(),
        (run_dir / "support_signals.json").read_bytes(),
    )
    package = WeeklyPackageManifest(
        package_hash=digest,
        fee_theme=fee.fee_theme,
        files=list(PACKAGE_FILES),
    )
    (run_dir / "package.json").write_bytes(canonical_json(package.model_dump(mode="json")))
    return AssembleResult(
        assembled=True,
        codes=[],
        package_hash=digest,
        fee_theme=fee.fee_theme,
    )
