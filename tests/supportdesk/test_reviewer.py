"""Reviewer hard gates and a single draft rework."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import date
from pathlib import Path

import pytest

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
from supportdesk.enums import (
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    PatternSignal,
    PatternStatus,
    ReviewerDecision,
    ReviewerFindingCode,
    WorkflowState,
)
from supportdesk.facts import RetrievalBundle
from supportdesk.ids import new_case_id, new_execution_id
from supportdesk.orchestrate import OrchestrationOutcome, draft_from_agents, orchestrate
from supportdesk.reviewer import exceeds_sentence_limit, review, review_case
from supportdesk.workflow import ContractError, assert_mcp_permitted, new_workflow_run, transition

URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
CLAIM = "Expense ratio is listed on this page."
PHONE = "9876543210"
PAN = "ABCDE1234F"


def _facts(claim: str = CLAIM, evidence: str | None = None) -> FactsResult:
    body = evidence if evidence is not None else claim
    return FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[
            FactClaim(
                claim=claim,
                source_title="HDFC Large Cap Fund",
                source_url=URL,
                evidence=body,
                last_checked=date(2026, 9, 1),
            )
        ],
        searched_sources=[URL],
        limitations=["retrieval status hit"],
        execution_id=new_execution_id(),
    )


def _pattern(signal: PatternSignal = PatternSignal.RECURRING, count: int = 4) -> PatternResult:
    return PatternResult(
        status=PatternStatus.SUCCESS,
        signal=signal,
        matching_count=count,
        analysis_window=AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1)),
        matched_themes=["t1: Customer support responsiveness"],
        method="stub",
        limitations=["measured from review dates"],
        comparable_periods=signal is PatternSignal.RISING,
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


def _result(case_id: str, facts: FactsResult | None = None, pattern: PatternResult | None = None) -> OrchestratorResult:
    facts = facts or _facts()
    pattern = pattern or _pattern()
    compliance = _compliance()
    reply, note, disagreements, withheld = draft_from_agents(facts, pattern, compliance)
    assert withheld is False
    return OrchestratorResult(
        case_id=case_id,
        reply=CustomerReply(text=reply, sentence_count=count_sentences(reply)),
        routing_note=note,
        facts=facts,
        pattern=pattern,
        compliance=compliance,
        disagreements=disagreements,
    )


def _drafted(result: OrchestratorResult) -> OrchestrationOutcome:
    run = new_workflow_run(result.case_id)
    states = [run.state]
    for target in (
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.ORCHESTRATED,
        WorkflowState.DRAFTED,
    ):
        run = transition(run, target)
        states.append(target)
    return OrchestrationOutcome(run=run, result=result, states=states, agent_details=[])


def _codes(case: object) -> set[ReviewerFindingCode]:
    reviews = getattr(case, "reviews")
    return {item.code for review in reviews for item in review.findings}


def test_sentence_counter_rejects_a_fourth_sentence() -> None:
    assert exceeds_sentence_limit("One. Two. Three. Four.") is True
    assert exceeds_sentence_limit("One. Two. Three.") is False


def test_digit_run_inside_an_execution_id_is_not_pii() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    digit_heavy = "exec_" + "6789012345abcdefabcdefabcdefabcd"
    facts = original.facts.model_copy(update={"execution_id": digit_heavy})
    reviewed = review_case(_drafted(original.model_copy(update={"facts": facts})))
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.reviews[0].decision is ReviewerDecision.PASS


def test_clean_draft_passes_without_rework() -> None:
    case_id = new_case_id()
    reviewed = review_case(_drafted(_result(case_id)))
    assert reviewed.reviews[0].decision is ReviewerDecision.PASS
    assert reviewed.reviews[0].findings == []
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.run.rework_count == 0
    assert reviewed.states[-2:] == [WorkflowState.REVIEWING, WorkflowState.PENDING_APPROVAL]
    assert reviewed.result is not None
    assert URL in reviewed.result.reply.text
    with pytest.raises(ContractError):
        assert_mcp_permitted(reviewed.run)


def test_bad_reply_is_redrafted_once_and_then_passes() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    broken = original.model_copy(
        update={
            "reply": CustomerReply(
                text="You should buy this fund.",
                sentence_count=1,
            ),
            "disagreements": [],
            "routing_note": original.routing_note.model_copy(
                update={"disagreement": None, "citation_refs": [], "matching_count": 1}
            ),
        }
    )
    reviewed = review_case(_drafted(broken))
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.run.rework_count == 1
    assert [item.rework_attempt for item in reviewed.reviews] == [0, 1]
    assert reviewed.reviews[0].decision is ReviewerDecision.FAIL
    assert reviewed.reviews[1].decision is ReviewerDecision.PASS
    assert ReviewerFindingCode.INVESTMENT_ADVICE in _codes(reviewed)
    assert ReviewerFindingCode.HIDDEN_DISAGREEMENT in _codes(reviewed)
    assert reviewed.result is not None
    assert reviewed.result.reply.text == original.reply.text
    assert "should" not in reviewed.result.reply.text.casefold()
    assert reviewed.states[-4:] == [
        WorkflowState.REVIEWING,
        WorkflowState.REWORK_ONCE,
        WorkflowState.REVIEWING,
        WorkflowState.PENDING_APPROVAL,
    ]


def test_advice_that_is_the_evidence_blocks_on_the_second_review() -> None:
    case_id = new_case_id()
    advice = "You should buy this fund."
    result = _result(case_id, facts=_facts(advice))
    reviewed = review_case(_drafted(result))
    assert reviewed.run.state is WorkflowState.BLOCKED
    assert reviewed.run.rework_count == 1
    assert [item.decision for item in reviewed.reviews] == [
        ReviewerDecision.FAIL,
        ReviewerDecision.FAIL,
    ]
    assert ReviewerFindingCode.INVESTMENT_ADVICE in _codes(reviewed)
    with pytest.raises(ContractError):
        transition(reviewed.run, WorkflowState.REWORK_ONCE)
    with pytest.raises(ContractError):
        transition(reviewed.run, WorkflowState.APPROVED)
    with pytest.raises(ContractError):
        assert_mcp_permitted(reviewed.run)


def test_phone_in_the_reply_is_removed_and_not_stored_in_findings() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    leaked = original.model_copy(
        update={
            "reply": CustomerReply(
                text=f"Call {PHONE} today.",
                sentence_count=1,
            )
        }
    )
    reviewed = review_case(_drafted(leaked))
    dumped = reviewed.model_dump_json()
    assert PHONE not in dumped
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.result is not None
    assert URL in reviewed.result.reply.text
    assert ReviewerFindingCode.PII in _codes(reviewed)


def test_pan_inside_a_fact_claim_is_dropped() -> None:
    case_id = new_case_id()
    tainted = f"Account PAN {PAN} is on file."
    result = _result(case_id, facts=_facts(tainted))
    reviewed = review_case(_drafted(result))
    dumped = reviewed.model_dump_json()
    assert PAN not in dumped
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.result is not None
    assert reviewed.result.facts.answer_facts == []
    assert "https://" not in reviewed.result.reply.text


def test_wrong_date_and_missing_citation_are_repaired() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    missing = original.model_copy(
        update={
            "reply": CustomerReply(text=CLAIM, sentence_count=1),
            "routing_note": original.routing_note.model_copy(update={"citation_refs": []}),
        }
    )
    repaired = review_case(_drafted(missing))
    assert repaired.run.state is WorkflowState.PENDING_APPROVAL
    assert repaired.result is not None
    assert "last checked 2026-09-01" in repaired.result.reply.text
    assert ReviewerFindingCode.MISSING_CITATION in _codes(repaired)

    dated = original.model_copy(
        update={
            "reply": CustomerReply(
                text=f"{CLAIM} Source: {URL}, last checked 1999-01-01.",
                sentence_count=count_sentences(f"{CLAIM} Source: {URL}, last checked 1999-01-01."),
            )
        }
    )
    fixed = review_case(_drafted(dated))
    assert fixed.result is not None
    assert "1999-01-01" not in fixed.result.reply.text
    assert "last checked 2026-09-01" in fixed.result.reply.text
    assert ReviewerFindingCode.MISSING_CITATION in _codes(fixed)


def test_foreign_citation_is_not_kept() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    foreign = "https://example.com/funds/other"
    text = f"{CLAIM} Source: {foreign}."
    leaked = original.model_copy(
        update={
            "reply": CustomerReply(text=text, sentence_count=count_sentences(text)),
            "routing_note": original.routing_note.model_copy(update={"citation_refs": [foreign]}),
        }
    )
    reviewed = review_case(_drafted(leaked))
    assert reviewed.result is not None
    assert "example.com" not in reviewed.model_dump_json()
    assert URL in reviewed.result.reply.text
    assert ReviewerFindingCode.CITATION_DOMAIN in _codes(reviewed)
    assert ReviewerFindingCode.CITATION_NOT_RETRIEVED in _codes(reviewed)


def test_unsupported_sentence_is_replaced_with_the_evidence() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    text = "The expense ratio is definitely half a percent."
    invented = original.model_copy(
        update={"reply": CustomerReply(text=text, sentence_count=1)}
    )
    reviewed = review_case(_drafted(invented))
    assert reviewed.result is not None
    assert "half" not in reviewed.result.reply.text
    assert CLAIM in reviewed.result.reply.text
    assert ReviewerFindingCode.EVIDENCE_MISMATCH in _codes(reviewed)


def test_performance_claim_is_removed() -> None:
    case_id = new_case_id()
    original = _result(case_id)
    promised = original.model_copy(
        update={
            "reply": CustomerReply(
                text="Returns are guaranteed.",
                sentence_count=1,
            )
        }
    )
    reviewed = review_case(_drafted(promised))
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.result is not None
    assert "guaranteed" not in reviewed.result.reply.text.casefold()
    assert ReviewerFindingCode.PERFORMANCE_CLAIM in _codes(reviewed)


def test_review_before_draft_does_not_rework() -> None:
    case_id = new_case_id()
    run = new_workflow_run(case_id)
    outcome = OrchestrationOutcome(
        run=run,
        result=_result(case_id),
        states=[run.state],
        agent_details=[],
    )
    reviewed = review_case(outcome)
    assert reviewed.run.state is WorkflowState.RECEIVED
    assert reviewed.run.rework_count == 0
    assert reviewed.reviews[0].findings[0].repairable is False
    assert reviewed.reviews[0].findings[0].code is ReviewerFindingCode.ILLEGAL_TRANSITION


def test_case_id_mismatch_blocks() -> None:
    result = _result(new_case_id())
    run = new_workflow_run(new_case_id())
    for target in (
        WorkflowState.SANITIZING,
        WorkflowState.AGENTS_RUNNING,
        WorkflowState.ORCHESTRATED,
        WorkflowState.DRAFTED,
    ):
        run = transition(run, target)
    reviewed = review_case(
        OrchestrationOutcome(run=run, result=result, states=[WorkflowState.DRAFTED], agent_details=[])
    )
    assert reviewed.run.state is WorkflowState.BLOCKED
    assert reviewed.run.rework_count == 0
    assert reviewed.result is None
    assert reviewed.reviews[0].findings[0].code is ReviewerFindingCode.ILLEGAL_TRANSITION


def test_orchestrated_disagreement_passes_review(tmp_path: Path) -> None:
    csv_path = tmp_path / "reviews.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["review_id", "review_date", "text_clean"])
        writer.writeheader()
        for review_id, reviewed in zip(
            ["r1", "r2", "r3", "r4"],
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-08-20"],
            strict=True,
        ):
            writer.writerow(
                {
                    "review_id": review_id,
                    "review_date": reviewed,
                    "text_clean": "The customer support team is slow.",
                }
            )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "clusters.json").write_text(
        json.dumps(
            {
                "window": {
                    "requested_start": "2026-06-01",
                    "requested_end": "2026-09-01",
                    "actual_start": "2026-06-01",
                    "actual_end": "2026-09-01",
                },
                "themes": [
                    {
                        "theme_id": "t1",
                        "cluster_key": "c1",
                        "label": "Customer support responsiveness",
                        "keywords": ["customer", "support"],
                        "review_ids": ["r1", "r2", "r3", "r4"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "cluster_debug.json").write_text("{}", encoding="utf-8")
    outcome = asyncio.run(
        orchestrate(
            "What is the expense ratio of HDFC Large Cap Fund? The customer support team is not responding.",
            session=ComplianceSession(),
            retriever=lambda _question: RetrievalBundle(
                status="hit",
                chunks=[
                    {
                        "text": f"The scheme was launched in 1994. {CLAIM} Past results vary.",
                        "source_url": URL,
                        "source_title": "HDFC Large Cap Fund",
                        "retrieved_on": "2026-09-01",
                    }
                ],
                lane="A",
                scheme_id="hdfc-large-cap-direct-growth",
            ),
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert outcome.result is not None
    reviewed = review_case(outcome)
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.run.rework_count == 0
    assert review(outcome.result).decision is ReviewerDecision.PASS
    assert reviewed.result is not None
    assert reviewed.result.routing_note.pattern_signal is PatternSignal.RECURRING
    assert reviewed.result.disagreements
