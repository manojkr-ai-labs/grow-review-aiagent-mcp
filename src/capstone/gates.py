"""Pulse-manifest gates and the explainer gates.

Word count stays in the pulse manifest. This module does not count words.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from capstone.contracts import ExplainerBullet
from capstone.explainer import bullet_gate_codes
from reviewpulse.pulse.validate import GATE_NAMES


def pulse_gates_passed(manifest: Mapping[str, object] | None) -> bool:
    """True only when the stored pulse gate record exists and every gate passed."""
    if not isinstance(manifest, Mapping):
        return False
    gates = manifest.get("gates")
    if not isinstance(gates, list) or not gates:
        return False
    passed: dict[str, bool] = {}
    for item in gates:
        if not isinstance(item, Mapping) or not item.get("gate"):
            continue
        passed[str(item["gate"])] = bool(item.get("passed"))
    return all(passed.get(name) is True for name in GATE_NAMES)


def explainer_gates(bullets: Sequence[ExplainerBullet]) -> list[str]:
    """Re-run the Phase 5 bullet, link, advice, and personal-data gates."""
    return bullet_gate_codes(bullets)
