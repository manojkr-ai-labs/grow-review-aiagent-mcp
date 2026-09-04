"""What a failed gate is allowed to do about itself (Phase 3 task 3.5).

The split is the point. A note that came out at 268 words is a budgeting miss
and one tighter regeneration usually fixes it. A note that failed `no_pii` or
`quotes_verbatim` is a *correctness* failure, and regenerating it would only
reroll the dice on a defect that must abort — so those gates are never retried
however the run is configured (architecture.md §7).
"""

from __future__ import annotations

from dataclasses import dataclass

# Recoverable by re-composing with a tighter budget.
RECOVERABLE_GATES = frozenset({"word_count", "actions_grounded"})

# Recoverable by reselecting quotes, not by re-composing.
RESELECTABLE_GATES = frozenset({"quotes_count"})

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    reason: str
    recompose: bool = False
    reselect_quotes: bool = False


def decide(failed_gates: list[str], attempt: int) -> RetryDecision:
    """Whether to try once more, given the gates that failed on this attempt.

    `attempt` is 1-based. Any hard failure in the set vetoes the retry even when
    a recoverable one is present: publishing a repaired note that still leaks
    PII is worse than aborting.
    """
    if not failed_gates:
        return RetryDecision(False, "all gates passed")

    hard = [
        gate
        for gate in failed_gates
        if gate not in RECOVERABLE_GATES and gate not in RESELECTABLE_GATES
    ]
    if hard:
        return RetryDecision(False, f"unrecoverable gate(s): {', '.join(sorted(hard))}")

    if attempt >= MAX_ATTEMPTS:
        return RetryDecision(
            False,
            f"retry budget exhausted after {attempt} attempt(s); "
            f"still failing: {', '.join(sorted(failed_gates))}",
        )

    return RetryDecision(
        True,
        f"retrying once for: {', '.join(sorted(failed_gates))}",
        recompose=any(gate in RECOVERABLE_GATES for gate in failed_gates),
        reselect_quotes=any(gate in RESELECTABLE_GATES for gate in failed_gates),
    )
