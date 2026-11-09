"""Validation rules on the Phase 1 contracts."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from supportdesk.approval import (
    ApprovalRecord,
    approval_matches,
    content_hash,
    mcp_idempotency_key,
)
from supportdesk.contracts import (
    AnalysisWindow,
    ComplianceResult,
    CustomerReply,
    FactClaim,
    FactsResult,
    McpActionRequest,
    PatternResult,
    ReviewerFinding,
    ReviewerResult,
)
from supportdesk.enums import (
    ApprovalDecision,
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    McpActionKind,
    PatternSignal,
    PatternStatus,
    PiiCategory,
    ReviewerDecision,
    ReviewerFindingCode,
)
from supportdesk.ids import new_case_id, new_execution_id

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
WINDOW = AnalysisWindow(start=date(2026, 6, 12), end=date(2026, 9, 3))


def _claim() -> FactClaim:
    return FactClaim(
        claim="The page lists an expense ratio.",
        source_title="HDFC Large Cap Fund",
        source_url="https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        evidence="Expense ratio is shown on the scheme page.",
        last_checked=date(2026, 9, 1),
    )


def test_supported_facts_require_a_claim_and_https_citation() -> None:
    execution_id = new_execution_id()
    result = FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[_claim()],
        searched_sources=["https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"],
        execution_id=execution_id,
    )
    assert result.answer_facts[0].last_checked == date(2026, 9, 1)

    with pytest.raises(ValidationError):
        FactsResult(
            status=FactsStatus.SUPPORTED,
            coverage=Coverage.COVERED,
            execution_id=execution_id,
        )
    with pytest.raises(ValidationError):
        FactClaim(
            claim="A claim",
            source_title="Title",
            source_url="http://groww.in/example",
            evidence="Evidence",
        )


def test_not_covered_rejects_invented_claims() -> None:
    FactsResult(
        status=FactsStatus.NOT_COVERED,
        coverage=Coverage.NOT_COVERED,
        searched_sources=["https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"],
        limitations=["No chunk matched the question."],
        execution_id=new_execution_id(),
    )
    with pytest.raises(ValidationError):
        FactsResult(
            status=FactsStatus.NOT_COVERED,
            coverage=Coverage.NOT_COVERED,
            answer_facts=[_claim()],
            execution_id=new_execution_id(),
        )


def test_rising_requires_comparable_periods_and_a_window() -> None:
    with pytest.raises(ValidationError):
        PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.RISING,
            matching_count=4,
            analysis_window=WINDOW,
            comparable_periods=False,
            method="late/early on the selected cluster run",
            execution_id=new_execution_id(),
        )
    with pytest.raises(ValidationError):
        PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.RISING,
            matching_count=4,
            analysis_window=AnalysisWindow(),
            comparable_periods=True,
            method="late/early on the selected cluster run",
            execution_id=new_execution_id(),
        )


def test_signal_counts_are_consistent() -> None:
    with pytest.raises(ValidationError):
        PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.ONE_OFF,
            matching_count=2,
            analysis_window=WINDOW,
            method="theme membership count",
            execution_id=new_execution_id(),
        )
    with pytest.raises(ValidationError):
        PatternResult(
            status=PatternStatus.SUCCESS,
            signal=PatternSignal.RECURRING,
            matching_count=0,
            analysis_window=WINDOW,
            method="theme membership count",
            execution_id=new_execution_id(),
        )
    empty = PatternResult(
        status=PatternStatus.INSUFFICIENT_DATA,
        signal=PatternSignal.INSUFFICIENT_DATA,
        matching_count=0,
        analysis_window=AnalysisWindow(),
        method="no theme file",
        limitations=["cluster artifact missing"],
        execution_id=new_execution_id(),
    )
    assert empty.comparable_periods is False


def test_reply_is_capped_at_three_sentences() -> None:
    reply = CustomerReply(
        text="Thanks for writing. The public page lists the expense ratio. Please check that page.",
        sentence_count=3,
    )
    assert reply.sentence_count == 3
    with pytest.raises(ValidationError):
        CustomerReply(
            text="One. Two. Three. Four.",
            sentence_count=4,
        )


def test_compliance_refuses_advice_and_unsanitized_pii() -> None:
    execution_id = new_execution_id()
    with pytest.raises(ValidationError):
        ComplianceResult(
            status=ComplianceStatus.SUCCESS,
            pii_detected=False,
            sanitized=True,
            advice_request_detected=True,
            performance_claim_risk=False,
            decision=ComplianceDecision.ALLOW,
            safe_handling="Refuse the recommendation.",
            execution_id=execution_id,
        )
    with pytest.raises(ValidationError):
        ComplianceResult(
            status=ComplianceStatus.SUCCESS,
            pii_detected=True,
            pii_categories=[PiiCategory.PHONE],
            sanitized=False,
            advice_request_detected=False,
            performance_claim_risk=False,
            decision=ComplianceDecision.ALLOW,
            safe_handling="Block until redaction succeeds.",
            execution_id=execution_id,
        )
    refused = ComplianceResult(
        status=ComplianceStatus.SUCCESS,
        pii_detected=False,
        sanitized=True,
        advice_request_detected=True,
        performance_claim_risk=False,
        decision=ComplianceDecision.REFUSE,
        flags=["advice"],
        safe_handling="Refuse the recommendation.",
        execution_id=execution_id,
    )
    assert refused.decision is ComplianceDecision.REFUSE


def test_reviewer_fail_requires_a_finding_and_rework_is_at_most_one() -> None:
    ReviewerResult(decision=ReviewerDecision.PASS, rework_attempt=0)
    ReviewerResult(
        decision=ReviewerDecision.FAIL,
        rework_attempt=1,
        findings=[
            ReviewerFinding(
                code=ReviewerFindingCode.MISSING_CITATION,
                message="The reply states a fact without a citation.",
                repairable=True,
            )
        ],
    )
    with pytest.raises(ValidationError):
        ReviewerResult(decision=ReviewerDecision.FAIL, rework_attempt=0)
    with pytest.raises(ValidationError):
        ReviewerResult(decision=ReviewerDecision.PASS, rework_attempt=2)


def test_content_hash_is_stable_and_approval_is_exact() -> None:
    reply = "Thanks for writing. The public page lists the expense ratio."
    note = "Team: general support. Priority: normal."
    digest = content_hash(reply=reply, routing_note=note)
    assert digest == content_hash(reply=reply, routing_note=note)
    changed = content_hash(reply=reply + " Extra sentence.", routing_note=note)
    assert digest != changed
    assert digest != content_hash(reply=reply, routing_note=note + " more")

    case_id = new_case_id()
    approval = ApprovalRecord(
        case_id=case_id,
        decision=ApprovalDecision.APPROVE,
        content_hash=digest,
        decided_at=NOW,
        approver_ref="operator:test",
    )
    assert approval_matches(approval, digest) is True
    assert approval_matches(approval, changed) is False
    rejected = approval.model_copy(update={"decision": ApprovalDecision.REJECT})
    assert approval_matches(rejected, digest) is False


def test_mcp_request_requires_matching_approval_and_has_no_send_action() -> None:
    assert {kind.value for kind in McpActionKind} == {"docs_append", "gmail_draft"}
    with pytest.raises(ValueError):
        McpActionKind("send_email")

    case_id = new_case_id()
    digest = content_hash(reply="Thanks for writing.", routing_note="Priority: normal.")
    approval = ApprovalRecord(
        case_id=case_id,
        decision=ApprovalDecision.APPROVE,
        content_hash=digest,
        decided_at=NOW,
        approver_ref="operator:test",
    )
    key = mcp_idempotency_key(case_id, digest, McpActionKind.GMAIL_DRAFT)
    request = McpActionRequest(
        case_id=case_id,
        kind=McpActionKind.GMAIL_DRAFT,
        content_hash=digest,
        approval=approval,
        idempotency_key=key,
    )
    assert request.idempotency_key == key
    assert "Thanks for writing" not in key

    with pytest.raises(ValidationError):
        McpActionRequest(
            case_id=case_id,
            kind=McpActionKind.DOCS_APPEND,
            content_hash=digest,
            approval=approval.model_copy(update={"decision": ApprovalDecision.REJECT}),
            idempotency_key=mcp_idempotency_key(case_id, digest, McpActionKind.DOCS_APPEND),
        )
    with pytest.raises(ValidationError):
        other = content_hash(reply="Different reply.", routing_note="Priority: normal.")
        McpActionRequest(
            case_id=case_id,
            kind=McpActionKind.DOCS_APPEND,
            content_hash=other,
            approval=approval,
            idempotency_key=mcp_idempotency_key(case_id, other, McpActionKind.DOCS_APPEND),
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CustomerReply(
            text="Thanks for writing.",
            sentence_count=1,
            author="someone",  # type: ignore[call-arg]
        )
