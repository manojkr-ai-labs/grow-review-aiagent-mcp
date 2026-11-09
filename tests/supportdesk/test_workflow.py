"""Legal transitions, one rework, five refinements, and approval binding."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from supportdesk.approval import ApprovalRecord, content_hash
from supportdesk.contracts import WorkflowRun
from supportdesk.enums import ApprovalDecision, WorkflowState
from supportdesk.ids import new_case_id
from supportdesk.workflow import (
    LEGAL_TRANSITIONS,
    ContractError,
    assert_mcp_permitted,
    bind_content,
    new_workflow_run,
    next_refinement_round,
    transition,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
REPLY = "Thanks for writing. The public page lists the expense ratio."
NOTE = "Team: general support. Priority: normal. Signal: insufficient_data."


def _record(case_id: str, digest: str, decision: ApprovalDecision) -> ApprovalRecord:
    return ApprovalRecord(
        case_id=case_id,
        decision=decision,
        content_hash=digest,
        decided_at=NOW,
        approver_ref="operator:test",
    )


def _advance(run: WorkflowRun, *states: WorkflowState) -> WorkflowRun:
    for state in states:
        run = transition(run, state)
    return run


def _to_pending(case_id: str) -> WorkflowRun:
    run = new_workflow_run(case_id)
    return _advance(
        run,
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.ORCHESTRATED,
        WorkflowState.DRAFTED,
        WorkflowState.REVIEWING,
        WorkflowState.PENDING_APPROVAL,
    )


def test_every_state_has_an_explicit_edge_list() -> None:
    assert set(LEGAL_TRANSITIONS) == set(WorkflowState)


def test_happy_path_reaches_mcp_only_after_approval() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    run = _to_pending(case_id)
    assert run.state is WorkflowState.PENDING_APPROVAL

    with pytest.raises(ContractError):
        transition(run, WorkflowState.MCP_ACTIONS)

    approved = transition(
        run,
        WorkflowState.APPROVED,
        approval=_record(case_id, digest, ApprovalDecision.APPROVE),
        content_hash=digest,
    )
    assert_mcp_permitted(approved)
    writing = transition(approved, WorkflowState.MCP_ACTIONS)
    done = transition(writing, WorkflowState.COMPLETED)
    assert done.state is WorkflowState.COMPLETED
    assert done.approval is not None
    assert done.approval.content_hash == digest
    with pytest.raises(ContractError):
        transition(done, WorkflowState.MCP_ACTIONS)


def test_rejection_has_no_mcp_path() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    pending = _to_pending(case_id)
    rejected = transition(
        pending,
        WorkflowState.REJECTED,
        approval=_record(case_id, digest, ApprovalDecision.REJECT),
        content_hash=digest,
    )
    assert rejected.state is WorkflowState.REJECTED
    with pytest.raises(ContractError):
        transition(rejected, WorkflowState.MCP_ACTIONS)
    with pytest.raises(ContractError):
        assert_mcp_permitted(rejected)


def test_second_review_failure_blocks_and_cannot_be_approved() -> None:
    case_id = new_case_id()
    run = _advance(
        new_workflow_run(case_id),
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.ORCHESTRATED,
        WorkflowState.DRAFTED,
        WorkflowState.REVIEWING,
    )
    reworked = transition(run, WorkflowState.REWORK_ONCE)
    assert reworked.rework_count == 1
    reviewed_again = transition(reworked, WorkflowState.REVIEWING)
    with pytest.raises(ContractError):
        transition(reviewed_again, WorkflowState.REWORK_ONCE)
    blocked = transition(reviewed_again, WorkflowState.BLOCKED)
    with pytest.raises(ContractError):
        transition(blocked, WorkflowState.APPROVED)
    with pytest.raises(ContractError):
        transition(blocked, WorkflowState.MCP_ACTIONS)


def test_content_change_invalidates_approval() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    approved = transition(
        _to_pending(case_id),
        WorkflowState.APPROVED,
        approval=_record(case_id, digest, ApprovalDecision.APPROVE),
        content_hash=digest,
    )
    edited = content_hash(reply=REPLY + " Updated.", routing_note=NOTE)
    invalidated = bind_content(approved, edited)
    assert invalidated.state is WorkflowState.REVIEWING
    assert invalidated.approval is None
    assert invalidated.content_hash == edited
    with pytest.raises(ContractError):
        transition(invalidated, WorkflowState.MCP_ACTIONS)


def test_partial_failure_retries_only_while_approval_still_matches() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    approved = transition(
        _to_pending(case_id),
        WorkflowState.APPROVED,
        approval=_record(case_id, digest, ApprovalDecision.APPROVE),
        content_hash=digest,
    )
    partial = transition(
        transition(approved, WorkflowState.MCP_ACTIONS),
        WorkflowState.PARTIAL_FAILURE,
    )
    resumed = transition(partial, WorkflowState.MCP_ACTIONS)
    assert resumed.state is WorkflowState.MCP_ACTIONS

    edited = content_hash(reply="A different reply.", routing_note=NOTE)
    invalidated = bind_content(partial, edited)
    assert invalidated.state is WorkflowState.REVIEWING
    with pytest.raises(ContractError):
        transition(invalidated, WorkflowState.MCP_ACTIONS)


def test_insufficient_evidence_can_continue_but_not_skip_to_mcp() -> None:
    run = _advance(
        new_workflow_run(new_case_id()),
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.INSUFFICIENT_EVIDENCE,
        WorkflowState.ORCHESTRATED,
    )
    assert run.state is WorkflowState.ORCHESTRATED
    with pytest.raises(ContractError):
        transition(run, WorkflowState.MCP_ACTIONS)


@pytest.mark.parametrize(
    ("origin", "target"),
    [
        (WorkflowState.RECEIVED, WorkflowState.MCP_ACTIONS),
        (WorkflowState.PENDING_APPROVAL, WorkflowState.MCP_ACTIONS),
        (WorkflowState.BLOCKED, WorkflowState.MCP_ACTIONS),
        (WorkflowState.SANITIZING, WorkflowState.DRAFTED),
        (WorkflowState.AGENTS_RUNNING, WorkflowState.APPROVED),
    ],
)
def test_illegal_transitions_are_rejected(
    origin: WorkflowState,
    target: WorkflowState,
) -> None:
    case_id = new_case_id()
    run = WorkflowRun(run_id=_to_pending(case_id).run_id, case_id=case_id, state=origin)
    with pytest.raises(ContractError):
        transition(run, target)


def test_approved_state_cannot_be_constructed_without_a_record() -> None:
    case_id = new_case_id()
    with pytest.raises(ValidationError):
        WorkflowRun(
            run_id=new_workflow_run(case_id).run_id,
            case_id=case_id,
            state=WorkflowState.APPROVED,
        )


def test_approval_of_a_different_hash_is_rejected() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    other = content_hash(reply="Other reply.", routing_note=NOTE)
    pending = _to_pending(case_id)
    with pytest.raises(ContractError):
        transition(
            pending,
            WorkflowState.APPROVED,
            approval=_record(case_id, digest, ApprovalDecision.APPROVE),
            content_hash=other,
        )


def test_refinement_stops_at_five_rounds() -> None:
    current = 0
    for expected in range(1, 6):
        current = next_refinement_round(current)
        assert current == expected
    with pytest.raises(ContractError):
        next_refinement_round(current)
    with pytest.raises(ValidationError):
        WorkflowRun(
            run_id=_to_pending(new_case_id()).run_id,
            case_id=new_case_id(),
            state=WorkflowState.RECEIVED,
            refinement_round=6,
        )


def test_completed_content_cannot_be_rewritten() -> None:
    case_id = new_case_id()
    digest = content_hash(reply=REPLY, routing_note=NOTE)
    approved = transition(
        _to_pending(case_id),
        WorkflowState.APPROVED,
        approval=_record(case_id, digest, ApprovalDecision.APPROVE),
        content_hash=digest,
    )
    completed = transition(
        transition(approved, WorkflowState.MCP_ACTIONS),
        WorkflowState.COMPLETED,
    )
    with pytest.raises(ContractError):
        bind_content(completed, content_hash(reply="Changed.", routing_note=NOTE))
