"""Mocked Docs append and Gmail draft. Nothing is sent."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

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
from supportdesk.decisions import decide, open_case
from supportdesk.enums import (
    ApprovalDecision,
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    McpActionStatus,
    PatternSignal,
    PatternStatus,
    WorkflowState,
)
from supportdesk.ids import new_case_id, new_execution_id
from supportdesk.orchestrate import OrchestrationOutcome, draft_from_agents
from supportdesk.publish import DEFAULT_STATE_NAME, publish_case
from supportdesk.reviewer import review_case
from supportdesk.workflow import ContractError, new_workflow_run, transition
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client

URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
CLAIM = "Expense ratio is listed on this page."
PHONE = "9876543210"
DOC_ID = "support-doc-1"
RECIPIENT = "desk@example.test"
WHEN = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _approved():
    return decide(_pending(), ApprovalDecision.APPROVE, "operator:desk", decided_at=WHEN)


def _pending():
    return open_case(_reviewed())


def _reviewed():
    facts = FactsResult(
        status=FactsStatus.SUPPORTED,
        coverage=Coverage.COVERED,
        answer_facts=[
            FactClaim(
                claim=CLAIM,
                source_title="HDFC Large Cap Fund",
                source_url=URL,
                evidence=CLAIM,
                last_checked=date(2026, 9, 1),
            )
        ],
        searched_sources=[URL],
        limitations=["retrieval status hit"],
        execution_id=new_execution_id(),
    )
    pattern = PatternResult(
        status=PatternStatus.SUCCESS,
        signal=PatternSignal.RECURRING,
        matching_count=4,
        analysis_window=AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1)),
        matched_themes=["t1: Customer support responsiveness"],
        method="stub",
        limitations=["measured from review dates"],
        execution_id=new_execution_id(),
    )
    compliance = ComplianceResult(
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
    reply, note, disagreements, _withheld = draft_from_agents(facts, pattern, compliance)
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
    return review_case(
        OrchestrationOutcome(run=run, result=result, states=[WorkflowState.DRAFTED], agent_details=[])
    )


def _names(client) -> list[str]:
    return [name for name, _args in client.calls]


def test_approved_case_appends_and_drafts_without_sending(tmp_path: Path) -> None:
    case = _approved()
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    state = tmp_path / "supportdesk-publish-state.json"
    outcome = publish_case(
        case,
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert outcome.run.state is WorkflowState.COMPLETED
    assert _names(docs) == ["append_to_google_doc"]
    assert _names(gmail) == ["draft_email"]
    assert "send_email" not in _names(gmail)
    assert docs.calls[0][1]["documentId"] == DOC_ID
    assert CLAIM in docs.calls[0][1]["content"]
    assert gmail.calls[0][1]["to"] == [RECIPIENT]
    assert gmail.calls[0][1]["subject"] == f"Support desk {case.run.case_id}"
    assert "weekly review pulse" not in gmail.calls[0][1]["subject"].lower()
    assert docs.calls[0][1]["prependNewline"] is True
    assert [item.status for item in outcome.actions] == [
        McpActionStatus.SUCCEEDED,
        McpActionStatus.SUCCEEDED,
    ]
    assert outcome.actions[0].external_id == DOC_ID
    assert outcome.actions[1].external_id
    saved = state.read_text(encoding="utf-8")
    assert CLAIM not in saved
    assert PHONE not in saved

    again = publish_case(
        case.model_copy(update={"run": outcome.run}),
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert again.run.state is WorkflowState.COMPLETED
    assert [item.status for item in again.actions] == [
        McpActionStatus.SKIPPED_DUPLICATE,
        McpActionStatus.SKIPPED_DUPLICATE,
    ]
    assert _names(docs) == ["append_to_google_doc"]
    assert _names(gmail) == ["draft_email"]
    assert DEFAULT_STATE_NAME == "supportdesk-publish-state.json"
    assert state.name == DEFAULT_STATE_NAME


def test_draft_failure_retries_only_gmail(tmp_path: Path) -> None:
    case = _approved()
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    gmail.fail_next = "draft_email"
    gmail.fail_message = "503 unavailable"
    state = tmp_path / "state.json"
    first = publish_case(
        case,
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert first.run.state is WorkflowState.PARTIAL_FAILURE
    assert first.actions[0].status is McpActionStatus.SUCCEEDED
    assert first.actions[1].status is McpActionStatus.FAILED
    assert first.actions[1].error == "MCPError"
    text_after_first = docs.store["docs"][DOC_ID]["text"]

    second = publish_case(
        case.model_copy(update={"run": first.run}),
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert second.run.state is WorkflowState.COMPLETED
    assert _names(docs) == ["append_to_google_doc"]
    assert _names(gmail) == ["draft_email", "draft_email"]
    assert docs.store["docs"][DOC_ID]["text"] == text_after_first
    assert second.actions[0].status is McpActionStatus.SKIPPED_DUPLICATE
    assert second.actions[1].status is McpActionStatus.SUCCEEDED


def test_timeout_stays_uncertain_and_is_not_retried(tmp_path: Path) -> None:
    case = _approved()
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    docs.fail_next = "append_to_google_doc"
    docs.fail_message = "timeout waiting for the server"
    state = tmp_path / "state.json"
    first = publish_case(
        case,
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert first.run.state is WorkflowState.PARTIAL_FAILURE
    assert first.actions[0].status is McpActionStatus.UNCERTAIN
    assert first.actions[0].error == "timed out"
    assert gmail.calls == []
    assert len(first.actions) == 1

    second = publish_case(
        case.model_copy(update={"run": first.run}),
        docs=docs,
        gmail=gmail,
        document_id=DOC_ID,
        recipient=RECIPIENT,
        state_path=state,
    )
    assert second.actions[0].status is McpActionStatus.UNCERTAIN
    assert _names(docs) == ["append_to_google_doc"]
    assert gmail.calls == []
    assert second.run.state is WorkflowState.PARTIAL_FAILURE


def test_unapproved_cases_do_not_call_mcp(tmp_path: Path) -> None:
    approved = _approved()
    pending = approved.model_copy(
        update={
            "run": approved.run.model_copy(
                update={"state": WorkflowState.PENDING_APPROVAL, "approval": None}
            )
        }
    )
    rejected = decide(_pending(), ApprovalDecision.REJECT, "operator:desk", decided_at=WHEN)
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    for blocked in (pending, rejected):
        with pytest.raises(ContractError):
            publish_case(
                blocked,
                docs=docs,
                gmail=gmail,
                document_id=DOC_ID,
                recipient=RECIPIENT,
                state_path=tmp_path / "state.json",
            )
    assert docs.calls == []
    assert gmail.calls == []
    assert rejected.run.state is WorkflowState.REJECTED


def test_pii_is_not_written(tmp_path: Path) -> None:
    clean = _approved()
    leaked = f"Call {PHONE} today."
    result = clean.result.model_copy(
        update={"reply": CustomerReply(text=leaked, sentence_count=count_sentences(leaked))}
    )
    from supportdesk.decisions import content_digest

    digest = content_digest(result)
    approval = clean.run.approval.model_copy(update={"content_hash": digest})
    run = clean.run.model_copy(update={"content_hash": digest, "approval": approval})
    case = clean.model_copy(update={"run": run, "result": result, "accepted_hash": digest})
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    with pytest.raises(ContractError, match="PII"):
        publish_case(
            case,
            docs=docs,
            gmail=gmail,
            document_id=DOC_ID,
            recipient=RECIPIENT,
            state_path=tmp_path / "state.json",
        )
    assert docs.calls == []
    assert gmail.calls == []
    assert not (tmp_path / "state.json").exists()
