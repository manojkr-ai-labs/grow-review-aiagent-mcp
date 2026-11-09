"""Five refinement rounds and approval bound to one content hash."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from supportdesk.approval import content_hash
from supportdesk.compliance import ComplianceSession
from supportdesk.contracts import (
    AnalysisWindow,
    ComplianceResult,
    CustomerReply,
    FactClaim,
    FactsResult,
    OrchestratorResult,
    PatternResult,
    count_sentences,
)
from supportdesk.decisions import (
    affected_work,
    approval_packet,
    content_digest,
    decide,
    open_case,
    refine,
)
from supportdesk.enums import (
    AgentName,
    ApprovalDecision,
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    PatternSignal,
    PatternStatus,
    WorkflowState,
)
from supportdesk.facts import RetrievalBundle, answer_facts
from supportdesk.ids import new_case_id, new_execution_id
from supportdesk.orchestrate import OrchestrationOutcome, draft_from_agents
from supportdesk.reviewer import review_case
from supportdesk.workflow import (
    ContractError,
    assert_mcp_permitted,
    bind_content,
    new_workflow_run,
    transition,
)

URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
CLAIM = "Expense ratio is listed on this page."
PHONE = "9876543210"
WHEN = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _facts(claim: str = CLAIM) -> FactsResult:
    return FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[
            FactClaim(
                claim=claim,
                source_title="HDFC Large Cap Fund",
                source_url=URL,
                evidence=claim,
                last_checked=date(2026, 9, 1),
            )
        ],
        searched_sources=[URL],
        limitations=["retrieval status hit"],
        execution_id=new_execution_id(),
    )


def _pattern() -> PatternResult:
    return PatternResult(
        status=PatternStatus.SUCCESS,
        signal=PatternSignal.RECURRING,
        matching_count=4,
        analysis_window=AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1)),
        matched_themes=["t1: Customer support responsiveness"],
        method="stub",
        limitations=["measured from review dates"],
        execution_id=new_execution_id(),
    )


def _compliance() -> ComplianceResult:
    return ComplianceResult(
        status=ComplianceStatus.SUCCESS,
        pii_detected=False,
        pii_categories=[],
        sanitized=True,
        advice_request_detected=False,
        performance_claim_risk=False,
        decision=ComplianceDecision.ALLOW,
        flags=[],
        safe_handling="No compliance block. Process the message.",
        execution_id=new_execution_id(),
    )


def _pending(claim: str = CLAIM):
    facts, pattern, compliance = _facts(claim), _pattern(), _compliance()
    reply, note, disagreements, withheld = draft_from_agents(facts, pattern, compliance)
    assert withheld is False
    case_id = new_case_id()
    result = OrchestratorResult(
        case_id=case_id,
        reply=CustomerReply(text=reply, sentence_count=count_sentences(reply)),
        routing_note=note,
        facts=facts,
        pattern=pattern,
        compliance=compliance,
        disagreements=disagreements,
    )
    run = new_workflow_run(case_id)
    for target in (
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.ORCHESTRATED,
        WorkflowState.DRAFTED,
    ):
        run = transition(run, target)
    reviewed = review_case(
        OrchestrationOutcome(
            run=run,
            result=result,
            states=[WorkflowState.DRAFTED],
            agent_details=[],
        )
    )
    return open_case(reviewed)


def test_instruction_routing_names_only_the_affected_agents() -> None:
    facts, fact_stages = affected_work("Please check the facts.")
    pattern, pattern_stages = affected_work("Check the recurring pattern.")
    draft, draft_stages = affected_work("Make the reply shorter.")
    assert facts == {AgentName.FACTS}
    assert AgentName.PATTERN not in facts
    assert "draft" in fact_stages and "review" in fact_stages
    assert pattern == {AgentName.PATTERN}
    assert AgentName.FACTS not in pattern
    assert draft == set()
    assert draft_stages == ["draft", "review"]


def test_packet_and_approval_are_bound_to_the_reviewed_hash() -> None:
    case = _pending()
    packet = approval_packet(case)
    assert packet.content_hash == content_digest(case.result)
    assert packet.reply == case.result.reply.text
    assert packet.citation_refs == [URL]
    assert packet.pattern_signal == "recurring"
    assert packet.matching_count == 4
    assert packet.reviewer_decision == "pass"
    assert packet.refinement_round == 0
    with pytest.raises(ContractError):
        assert_mcp_permitted(case.run)

    approved = decide(case, ApprovalDecision.APPROVE, "operator:desk", decided_at=WHEN)
    assert approved.run.state is WorkflowState.APPROVED
    assert approved.run.approval is not None
    assert approved.run.approval.content_hash == packet.content_hash
    assert_mcp_permitted(approved.run)
    with pytest.raises(ContractError):
        decide(approved, ApprovalDecision.APPROVE, "operator:desk", decided_at=WHEN)


def test_rejection_ends_refinement_and_mcp() -> None:
    case = _pending()
    rejected = decide(case, ApprovalDecision.REJECT, "operator:desk", decided_at=WHEN)
    assert rejected.run.state is WorkflowState.REJECTED
    with pytest.raises(ContractError):
        assert_mcp_permitted(rejected.run)
    with pytest.raises(ContractError):
        transition(rejected.run, WorkflowState.MCP_ACTIONS)
    with pytest.raises(ContractError):
        refine(rejected, "Make the reply shorter.", reply=case.result.reply.text)
    with pytest.raises(ContractError):
        approval_packet(rejected)


def test_failed_reply_edit_keeps_the_accepted_version() -> None:
    case = _pending()
    edited = refine(case, "Make the reply shorter.", reply="You should buy this fund.")
    assert edited.run.state is WorkflowState.PENDING_APPROVAL
    assert edited.run.refinement_round == 1
    assert edited.accepted_hash == case.accepted_hash
    assert edited.result.reply.text == case.result.reply.text
    assert edited.refinements[-1].accepted is False
    assert edited.refinements[-1].agents == []
    assert "should" not in edited.result.reply.text.casefold()
    packet = approval_packet(edited)
    assert packet.content_hash == case.accepted_hash
    approved = decide(edited, ApprovalDecision.APPROVE, "operator:desk", decided_at=WHEN)
    assert approved.run.approval is not None
    assert approved.run.approval.content_hash == case.accepted_hash


def test_facts_rerun_does_not_call_pattern_and_clears_approval() -> None:
    case = decide(_pending(), ApprovalDecision.APPROVE, "operator:desk", decided_at=WHEN)
    seen: list[str] = []
    pattern_calls = {"count": 0}

    def retriever(question: str) -> RetrievalBundle:
        seen.append(question)
        return RetrievalBundle(
            status="hit",
            chunks=[
                {
                    "text": "Exit load is listed on this page.",
                    "source_url": URL,
                    "source_title": "HDFC Large Cap Fund",
                    "retrieved_on": "2026-09-01",
                }
            ],
        )

    def pattern_runner(_text: str) -> object:
        pattern_calls["count"] += 1
        raise AssertionError("pattern should not run")

    refined = refine(
        case,
        "Check the facts.",
        message="What is the exit load of HDFC Large Cap Fund?",
        retriever=retriever,
        pattern_runner=pattern_runner,
    )
    assert pattern_calls["count"] == 0
    assert seen == ["What is the exit load of HDFC Large Cap Fund?"]
    assert refined.run.state is WorkflowState.PENDING_APPROVAL
    assert refined.run.approval is None
    assert refined.run.refinement_round == 1
    assert {item.agent for item in refined.run.executions} == {AgentName.COMPLIANCE, AgentName.FACTS}
    assert {item.round_index for item in refined.run.executions} == {1}
    assert refined.refinements[0].accepted is True
    assert "Exit load is listed on this page." in refined.result.reply.text
    assert refined.accepted_hash != case.accepted_hash
    with pytest.raises(ContractError):
        assert_mcp_permitted(refined.run)
    again = decide(refined, ApprovalDecision.APPROVE, "lead:ops", decided_at=WHEN)
    assert again.run.approval is not None
    assert again.run.approval.content_hash == refined.accepted_hash
    assert_mcp_permitted(again.run)


def test_phone_instruction_is_stored_without_the_number() -> None:
    case = _pending()
    seen: list[str] = []

    def facts_runner(text: str):
        seen.append(text)
        return answer_facts(
            text,
            session=ComplianceSession(),
            case_id=case.run.case_id,
            retriever=lambda _question: RetrievalBundle(status="not_found", chunks=[]),
        )

    refined = refine(
        case,
        f"Call {PHONE} and check the facts.",
        message=f"Call {PHONE} about the expense ratio.",
        facts_runner=facts_runner,
    )
    dumped = refined.model_dump_json()
    assert PHONE not in dumped
    assert "[phone]" in refined.refinements[0].instruction
    assert seen and PHONE not in seen[0]


def test_advice_refinement_does_not_retrieve() -> None:
    case = _pending()
    session = ComplianceSession()
    calls = {"count": 0}

    def retriever(_question: str) -> RetrievalBundle:
        calls["count"] += 1
        return RetrievalBundle(status="hit", chunks=[])

    refine(
        case,
        "Check the facts.",
        message="Should I buy this fund?",
        session=session,
        retriever=retriever,
    )
    assert calls["count"] == 0
    assert session.advice_requested is True


def test_five_rounds_stop_before_a_sixth_agent_call() -> None:
    case = _pending()
    calls = {"count": 0}

    def retriever(_question: str) -> RetrievalBundle:
        calls["count"] += 1
        raise AssertionError("draft-only refinement must not retrieve")

    current = case
    reply = case.result.reply.text
    for _ in range(5):
        current = refine(current, "Make the reply shorter.", reply=reply, retriever=retriever)
    assert current.run.refinement_round == 5
    assert len(current.refinements) == 5
    assert calls["count"] == 0
    with pytest.raises(ContractError):
        refine(current, "Make the reply shorter.", reply=reply, retriever=retriever)
    assert current.run.refinement_round == 5


def test_pending_hash_change_returns_to_review() -> None:
    case = _pending()
    other = content_hash(reply="A different reply.", routing_note="A different note.")
    moved = bind_content(case.run, other)
    assert moved.state is WorkflowState.REVIEWING
    assert moved.approval is None
    with pytest.raises(ContractError):
        assert_mcp_permitted(moved)


def test_approver_ref_cannot_carry_free_text() -> None:
    case = _pending()
    with pytest.raises(ContractError):
        decide(case, ApprovalDecision.APPROVE, "Manoj K", decided_at=WHEN)
