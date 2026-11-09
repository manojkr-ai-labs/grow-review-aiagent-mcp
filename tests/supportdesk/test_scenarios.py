"""The ten required functional scenarios, each named and automated."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from supportdesk.compliance import ComplianceSession
from supportdesk.decisions import decide, open_case
from supportdesk.enums import (
    ApprovalDecision,
    FactsStatus,
    McpActionStatus,
    PatternSignal,
    WorkflowState,
)
from supportdesk.facts import answer_facts
from supportdesk.ids import new_case_id
from supportdesk.orchestrate import orchestrate
from supportdesk.pattern import answer_pattern, default_paths
from supportdesk.privacy import contains_pii
from supportdesk.publish import publish_case
from supportdesk.reviewer import review_case
from supportdesk.workflow import ContractError, assert_mcp_permitted
from tests.contract.fake_mcp import hosted_docs_client, hosted_gmail_client
from tests.supportdesk.test_publish import _approved, _pending
from tests.supportdesk.test_reviewer import _drafted, _facts, _result

PHONE = "9876543210"
WHEN = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
PROJECT1 = Path(__file__).resolve().parents[2].parent / "mutual-fund-faq-assistant"


def test_scenario_corpus_covered() -> None:
    if not (PROJECT1 / "app" / "pipeline" / "retrieve.py").is_file():
        pytest.skip("Project 1 checkout is absent")
    covered = answer_facts(
        "What is the expense ratio of HDFC Large Cap Fund?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=PROJECT1,
    )
    claim = covered.result.answer_facts[0]
    assert covered.result.status is FactsStatus.SUPPORTED
    assert claim.claim in claim.evidence
    assert claim.source_url.startswith("https://groww.in/")


def test_scenario_not_covered() -> None:
    if not (PROJECT1 / "app" / "pipeline" / "retrieve.py").is_file():
        pytest.skip("Project 1 checkout is absent")
    missing = answer_facts(
        "Why was my stock delivery charge different yesterday?",
        session=ComplianceSession(),
        case_id=new_case_id(),
        project1_root=PROJECT1,
    )
    assert missing.result.status is FactsStatus.NOT_COVERED
    assert missing.result.answer_facts == []


def test_scenario_recurring_theme() -> None:
    csv_path, runs_dir, db_path = default_paths()
    if not csv_path.is_file() or not runs_dir.is_dir():
        pytest.skip("local review export or runs directory is absent")
    runs = [path for path in runs_dir.iterdir() if (path / "clusters.json").is_file()]
    if not runs:
        pytest.skip("no cluster artifact")
    output = answer_pattern(
        "The customer support team is not responding.",
        session=ComplianceSession(),
        case_id=new_case_id(),
        csv_path=csv_path,
        run_dir=max(runs, key=lambda path: path.name),
        db_path=db_path if db_path.is_file() else None,
    )
    assert output.result.signal is PatternSignal.RECURRING
    assert output.result.matching_count >= 3
    assert output.result.analysis_window.start is not None
    assert output.result.analysis_window.end is not None


def test_scenario_pii_is_redacted_before_the_draft(tmp_path: Path) -> None:
    outcome = asyncio.run(
        orchestrate(
            f"My phone is {PHONE}. The app will not open.",
            session=ComplianceSession(),
            csv_path=tmp_path / "missing.csv",
            run_dir=tmp_path / "absent",
        )
    )
    assert outcome.result is not None
    dumped = outcome.model_dump_json()
    assert PHONE not in dumped
    assert contains_pii(outcome.result.reply.text) is False
    assert "[phone]" in outcome.result.compliance.safe_handling or outcome.result.compliance.pii_detected


def test_scenario_disagreement_keeps_the_escalation_signal(tmp_path: Path) -> None:
    if not (PROJECT1 / "app" / "pipeline" / "retrieve.py").is_file():
        pytest.skip("Project 1 checkout is absent")
    csv_path, runs_dir, db_path = default_paths()
    if not csv_path.is_file() or not runs_dir.is_dir():
        pytest.skip("local review export or runs directory is absent")
    runs = [path for path in runs_dir.iterdir() if (path / "clusters.json").is_file()]
    outcome = asyncio.run(
        orchestrate(
            "What is the expense ratio of HDFC Large Cap Fund? Customer support is not responding.",
            session=ComplianceSession(),
            project1_root=PROJECT1,
            csv_path=csv_path,
            run_dir=max(runs, key=lambda path: path.name),
            db_path=db_path if db_path.is_file() else None,
        )
    )
    assert outcome.result is not None
    assert outcome.result.facts.status is FactsStatus.SUPPORTED
    assert outcome.result.pattern.signal in {PatternSignal.RECURRING, PatternSignal.RISING}
    assert outcome.result.routing_note.disagreement
    assert outcome.result.reply.sentence_count <= 3
    assert "https://groww.in/" in outcome.result.reply.text


def test_scenario_first_reviewer_failure_reworks_once() -> None:
    original = _result(new_case_id())
    broken = original.model_copy(
        update={
            "reply": original.reply.model_copy(
                update={"text": "You should buy this fund.", "sentence_count": 1}
            )
        }
    )
    reviewed = review_case(_drafted(broken))
    assert reviewed.reviews[0].decision.value == "fail"
    assert reviewed.run.rework_count == 1
    assert reviewed.run.state is WorkflowState.PENDING_APPROVAL
    assert reviewed.result is not None
    assert "should" not in reviewed.result.reply.text.casefold()


def test_scenario_second_reviewer_failure_blocks_without_mcp() -> None:
    result = _result(new_case_id(), facts=_facts("You should buy this fund."))
    reviewed = review_case(_drafted(result))
    assert reviewed.run.state is WorkflowState.BLOCKED
    assert reviewed.run.rework_count == 1
    with pytest.raises(ContractError):
        assert_mcp_permitted(reviewed.run)


def test_scenario_human_rejection_does_not_write(tmp_path: Path) -> None:
    rejected = decide(_pending(), ApprovalDecision.REJECT, "operator:desk", decided_at=WHEN)
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    with pytest.raises(ContractError):
        publish_case(
            rejected,
            docs=docs,
            gmail=gmail,
            document_id="support-doc-1",
            recipient="desk@example.test",
            state_path=tmp_path / "state.json",
        )
    assert docs.calls == []
    assert gmail.calls == []


def test_scenario_human_approval_appends_and_drafts(tmp_path: Path) -> None:
    approved = _approved()
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    outcome = publish_case(
        approved,
        docs=docs,
        gmail=gmail,
        document_id="support-doc-1",
        recipient="desk@example.test",
        state_path=tmp_path / "state.json",
    )
    assert outcome.run.state is WorkflowState.COMPLETED
    assert [name for name, _args in gmail.calls] == ["draft_email"]
    pending = open_case(review_case(_drafted(_result(new_case_id()))))
    assert pending.run.state is WorkflowState.PENDING_APPROVAL


def test_scenario_mcp_partial_failure_retries_the_draft_only(tmp_path: Path) -> None:
    approved = _approved()
    docs = hosted_docs_client()
    gmail = hosted_gmail_client()
    gmail.fail_next = "draft_email"
    gmail.fail_message = "503 unavailable"
    state = tmp_path / "state.json"
    first = publish_case(
        approved,
        docs=docs,
        gmail=gmail,
        document_id="support-doc-1",
        recipient="desk@example.test",
        state_path=state,
    )
    assert first.run.state is WorkflowState.PARTIAL_FAILURE
    assert first.actions[1].status is McpActionStatus.FAILED
    text = docs.store["docs"]["support-doc-1"]["text"]
    second = publish_case(
        approved.model_copy(update={"run": first.run}),
        docs=docs,
        gmail=gmail,
        document_id="support-doc-1",
        recipient="desk@example.test",
        state_path=state,
    )
    assert second.run.state is WorkflowState.COMPLETED
    assert docs.store["docs"]["support-doc-1"]["text"] == text
    assert second.actions[0].status is McpActionStatus.SKIPPED_DUPLICATE
    assert [name for name, _args in gmail.calls] == ["draft_email", "draft_email"]
