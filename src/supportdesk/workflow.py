"""Legal workflow transitions.

MCP actions are reachable only from an approved run whose approval hash matches
the current content. Rejection and block have no path to MCP.
"""

from __future__ import annotations

from supportdesk.approval import ApprovalRecord, approval_matches
from supportdesk.contracts import WorkflowRun
from supportdesk.enums import ApprovalDecision, WorkflowState
from supportdesk.ids import is_sha256, new_run_id

MAX_REFINEMENT_ROUNDS = 5
MAX_AUTOMATIC_REWORKS = 1

_MCP_SOURCES = frozenset({WorkflowState.APPROVED, WorkflowState.PARTIAL_FAILURE})
_CONTENT_LOCKED = frozenset(
    {WorkflowState.COMPLETED, WorkflowState.BLOCKED, WorkflowState.REJECTED}
)
_INVALIDATE_ON_EDIT = frozenset(
    {
        WorkflowState.APPROVED,
        WorkflowState.MCP_ACTIONS,
        WorkflowState.PARTIAL_FAILURE,
    }
)

LEGAL_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.RECEIVED: frozenset({WorkflowState.SANITIZING}),
    WorkflowState.SANITIZING: frozenset(
        {WorkflowState.AGENTS_RUNNING, WorkflowState.BLOCKED}
    ),
    WorkflowState.AGENTS_RUNNING: frozenset(
        {
            WorkflowState.ORCHESTRATED,
            WorkflowState.INSUFFICIENT_EVIDENCE,
            WorkflowState.AGENT_ERROR,
        }
    ),
    WorkflowState.INSUFFICIENT_EVIDENCE: frozenset({WorkflowState.ORCHESTRATED}),
    WorkflowState.AGENT_ERROR: frozenset(
        {WorkflowState.ORCHESTRATED, WorkflowState.BLOCKED}
    ),
    WorkflowState.ORCHESTRATED: frozenset({WorkflowState.DRAFTED}),
    WorkflowState.DRAFTED: frozenset({WorkflowState.REVIEWING}),
    WorkflowState.REVIEWING: frozenset(
        {
            WorkflowState.PENDING_APPROVAL,
            WorkflowState.REWORK_ONCE,
            WorkflowState.BLOCKED,
        }
    ),
    WorkflowState.REWORK_ONCE: frozenset({WorkflowState.REVIEWING}),
    WorkflowState.PENDING_APPROVAL: frozenset(
        {
            WorkflowState.APPROVED,
            WorkflowState.REJECTED,
            WorkflowState.REVIEWING,
        }
    ),
    WorkflowState.APPROVED: frozenset(
        {WorkflowState.MCP_ACTIONS, WorkflowState.REVIEWING}
    ),
    WorkflowState.REJECTED: frozenset(),
    WorkflowState.BLOCKED: frozenset(),
    WorkflowState.MCP_ACTIONS: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.PARTIAL_FAILURE}
    ),
    WorkflowState.PARTIAL_FAILURE: frozenset({WorkflowState.MCP_ACTIONS}),
    WorkflowState.COMPLETED: frozenset(),
}


class ContractError(ValueError):
    """A transition, rework limit, or approval rule was violated."""


def new_workflow_run(case_id: str) -> WorkflowRun:
    return WorkflowRun(
        run_id=new_run_id(),
        case_id=case_id,
        state=WorkflowState.RECEIVED,
    )


def next_refinement_round(current: int) -> int:
    """Return the next human-refinement index, or raise at the cap of five."""
    if current < 0:
        raise ContractError("refinement round cannot be negative")
    if current >= MAX_REFINEMENT_ROUNDS:
        raise ContractError(
            f"human refinement is limited to {MAX_REFINEMENT_ROUNDS} rounds"
        )
    return current + 1


def transition(
    run: WorkflowRun,
    to: WorkflowState,
    *,
    approval: ApprovalRecord | None = None,
    content_hash: str | None = None,
) -> WorkflowRun:
    """Return a new run in `to` when that edge is legal."""
    allowed = LEGAL_TRANSITIONS[run.state]
    if to not in allowed:
        raise ContractError(f"{run.state.value} -> {to.value} is not a legal transition")

    updates: dict[str, object] = {"state": to}

    if run.state is WorkflowState.REVIEWING and to is WorkflowState.REWORK_ONCE:
        if run.rework_count >= MAX_AUTOMATIC_REWORKS:
            raise ContractError("automatic rework is limited to one attempt")
        updates["rework_count"] = run.rework_count + 1

    if to is WorkflowState.APPROVED:
        updates.update(_approval_updates(run, approval, content_hash, ApprovalDecision.APPROVE))
    elif to is WorkflowState.REJECTED:
        updates.update(_approval_updates(run, approval, content_hash, ApprovalDecision.REJECT))
    elif to is WorkflowState.MCP_ACTIONS:
        _require_mcp_approval(run, content_hash)
    elif run.state is WorkflowState.APPROVED and to is WorkflowState.REVIEWING:
        updates["approval"] = None

    return run.model_copy(update=updates)


def bind_content(run: WorkflowRun, digest: str) -> WorkflowRun:
    """Attach a content hash. An edit after approval sends the run back to review."""
    if not is_sha256(digest):
        raise ContractError("content hash must be sha256 hex")
    if run.content_hash == digest:
        return run
    if run.state in _CONTENT_LOCKED:
        raise ContractError(f"cannot change content while the run is {run.state.value}")
    if (
        run.state is WorkflowState.PENDING_APPROVAL
        and run.content_hash is not None
        and run.content_hash != digest
    ):
        return run.model_copy(
            update={
                "content_hash": digest,
                "approval": None,
                "state": WorkflowState.REVIEWING,
            }
        )
    if run.state in _INVALIDATE_ON_EDIT or (
        run.approval is not None and run.approval.content_hash != digest
    ):
        return run.model_copy(
            update={
                "content_hash": digest,
                "approval": None,
                "state": WorkflowState.REVIEWING,
            }
        )
    return run.model_copy(update={"content_hash": digest})


def assert_mcp_permitted(run: WorkflowRun) -> None:
    """Raise unless this run may start or resume external writes."""
    if run.state not in _MCP_SOURCES and run.state is not WorkflowState.MCP_ACTIONS:
        raise ContractError(
            f"MCP actions are not permitted from state {run.state.value}"
        )
    digest = run.content_hash or ""
    if not approval_matches(run.approval, digest):
        raise ContractError("MCP actions require approval of the current content")


def _approval_updates(
    run: WorkflowRun,
    approval: ApprovalRecord | None,
    digest: str | None,
    expected: ApprovalDecision,
) -> dict[str, object]:
    if approval is None or digest is None:
        raise ContractError("this transition requires an approval record and content hash")
    if not is_sha256(digest):
        raise ContractError("content hash must be sha256 hex")
    if approval.decision is not expected:
        raise ContractError(f"this transition requires decision={expected.value}")
    if approval.case_id != run.case_id:
        raise ContractError("approval case_id does not match the run")
    if approval.content_hash != digest:
        raise ContractError("approval is not bound to this content hash")
    return {"approval": approval, "content_hash": digest}


def _require_mcp_approval(run: WorkflowRun, digest: str | None) -> None:
    current = digest or run.content_hash
    if current is None or (digest is not None and digest != run.content_hash):
        raise ContractError("MCP action content hash does not match the approved version")
    if run.state not in _MCP_SOURCES:
        raise ContractError(
            f"MCP actions are not permitted from state {run.state.value}"
        )
    if not approval_matches(run.approval, current):
        raise ContractError("MCP actions require approval of the current content")
