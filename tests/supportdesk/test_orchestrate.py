"""Parallel dispatch, reply drafting, and routing notes."""

from __future__ import annotations

import asyncio
import csv
import json
import time
from datetime import date
from pathlib import Path

from supportdesk.advice import requests_advice, requests_performance
from supportdesk.compliance import ComplianceSession
from supportdesk.contracts import AnalysisWindow, FactsResult, PatternResult
from supportdesk.enums import (
    Coverage,
    FactsStatus,
    PatternSignal,
    PatternStatus,
    Priority,
    WorkflowState,
)
from supportdesk.facts import FactsAgentOutput, RetrievalBundle, answer_facts
from supportdesk.ids import new_case_id, new_execution_id
from supportdesk.orchestrate import orchestrate
from supportdesk.pattern import PatternAgentOutput, answer_pattern
from supportdesk.privacy import contains_pii
from supportdesk.reviewer import content_has_pii

CHUNK = {
    "text": (
        "The scheme was launched in 1994. "
        "Expense ratio is listed on this page. "
        "Past results vary."
    ),
    "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    "source_title": "HDFC Large Cap Fund",
    "retrieved_on": "2026-09-01",
}
URL = CHUNK["source_url"]
PAN = "ABCDE1234F"
PHONE = "9876543210"


def _hit() -> RetrievalBundle:
    return RetrievalBundle(
        status="hit",
        chunks=[dict(CHUNK)],
        lane="A",
        scheme_id="hdfc-large-cap-direct-growth",
        fact_type="expense_ratio",
        resolution_status="resolved",
    )


def _not_found() -> RetrievalBundle:
    return RetrievalBundle(status="not_found", chunks=[])


def _write_pattern(root: Path, review_ids: list[str]) -> tuple[Path, Path]:
    csv_path = root / "reviews.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["review_id", "review_date", "text_clean"])
        writer.writeheader()
        dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-08-20"]
        for review_id, reviewed in zip(review_ids, dates, strict=False):
            writer.writerow(
                {
                    "review_id": review_id,
                    "review_date": reviewed,
                    "text_clean": "The customer support team is slow.",
                }
            )
    run_dir = root / "run"
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
                        "review_ids": review_ids,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "cluster_debug.json").write_text(
        json.dumps(
            {
                "clusters": [
                    {
                        "cluster_key": "c1",
                        "label": "Customer support responsiveness",
                        "early_count": 0,
                        "late_count": 4,
                        "emerging": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return csv_path, run_dir


def _pattern(
    signal: PatternSignal,
    count: int,
    themes: list[str],
    *,
    status: PatternStatus = PatternStatus.SUCCESS,
) -> PatternResult:
    return PatternResult(
        status=status,
        signal=signal,
        matching_count=count,
        analysis_window=AnalysisWindow(start=date(2026, 6, 1), end=date(2026, 9, 1)),
        matched_themes=themes,
        method="stub",
        comparable_periods=signal is PatternSignal.RISING,
        execution_id=new_execution_id(),
    )


def _wrap_pattern(message: str, case_id: str, result: PatternResult) -> PatternAgentOutput:
    inspection = ComplianceSession().inspect(message, case_id=case_id)
    return PatternAgentOutput(result=result, inspection=inspection)


def _wrap_facts(message: str, case_id: str, result: FactsResult) -> FactsAgentOutput:
    inspection = ComplianceSession().inspect(message, case_id=case_id)
    return FactsAgentOutput(result=result, inspection=inspection)


def test_three_agents_overlap() -> None:
    case_id = new_case_id()
    message = "Where is the contract note?"

    def facts() -> FactsAgentOutput:
        time.sleep(0.4)
        result = FactsResult(
            status=FactsStatus.NOT_COVERED,
            coverage=Coverage.NOT_COVERED,
            limitations=["stub"],
            execution_id=new_execution_id(),
        )
        return _wrap_facts(message, case_id, result)

    def pattern() -> PatternAgentOutput:
        time.sleep(0.4)
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.INSUFFICIENT_DATA, 0, [], status=PatternStatus.INSUFFICIENT_DATA),
        )

    def compliance():
        time.sleep(0.4)
        return ComplianceSession().inspect(message, case_id=case_id)

    started = time.perf_counter()
    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            case_id=case_id,
            facts=facts,
            pattern=pattern,
            compliance=compliance,
        )
    )
    elapsed = time.perf_counter() - started
    executions = outcome.run.executions
    starts = [item.started_at for item in executions]
    ends = [item.ended_at for item in executions if item.ended_at is not None]
    assert len(executions) == 3
    assert len(ends) == 3
    assert max(starts) < min(ends)
    assert elapsed < 1.0
    assert outcome.run.state is WorkflowState.DRAFTED
    assert WorkflowState.INSUFFICIENT_EVIDENCE in outcome.states


def test_timeout_is_not_cited() -> None:
    case_id = new_case_id()
    message = "What is the expense ratio of HDFC Large Cap Fund?"

    def facts() -> FactsAgentOutput:
        time.sleep(1.0)
        from supportdesk.contracts import FactClaim

        return _wrap_facts(
            message,
            case_id,
            FactsResult(
                status=FactsStatus.SUPPORTED,
                coverage=Coverage.COVERED,
                answer_facts=[
                    FactClaim(
                        claim="Expense ratio is listed on this page.",
                        source_title="HDFC Large Cap Fund",
                        source_url=URL,
                        evidence="Expense ratio is listed on this page.",
                        last_checked=date(2026, 9, 1),
                    )
                ],
                searched_sources=[URL],
                execution_id=new_execution_id(),
            ),
        )

    def pattern() -> PatternAgentOutput:
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.INSUFFICIENT_DATA, 0, [], status=PatternStatus.INSUFFICIENT_DATA),
        )

    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            case_id=case_id,
            timeout_seconds=0.15,
            facts=facts,
            pattern=pattern,
        )
    )
    assert outcome.result is not None
    assert outcome.result.facts.answer_facts == []
    assert outcome.result.facts.status is FactsStatus.ERROR
    assert "timed out" in " ".join(outcome.result.facts.limitations)
    assert URL not in outcome.result.reply.text
    assert "https://" not in outcome.result.reply.text
    assert outcome.result.routing_note.citation_refs == []
    assert WorkflowState.AGENT_ERROR in outcome.states
    assert outcome.run.state is WorkflowState.DRAFTED


def test_compliance_timeout_blocks_and_does_not_set_session_flags() -> None:
    case_id = new_case_id()
    session = ComplianceSession()
    message = "Should I buy this fund?"

    def compliance():
        time.sleep(1.0)
        return ComplianceSession().inspect(message, case_id=case_id)

    def facts() -> FactsAgentOutput:
        from supportdesk.contracts import FactClaim

        return _wrap_facts(
            message,
            case_id,
            FactsResult(
                status=FactsStatus.SUPPORTED,
                coverage=Coverage.COVERED,
                answer_facts=[
                    FactClaim(
                        claim="Expense ratio is listed on this page.",
                        source_title="HDFC Large Cap Fund",
                        source_url=URL,
                        evidence="Expense ratio is listed on this page.",
                        last_checked=date(2026, 9, 1),
                    )
                ],
                searched_sources=[URL],
                execution_id=new_execution_id(),
            ),
        )

    def pattern() -> PatternAgentOutput:
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.RECURRING, 4, ["t1: Customer support responsiveness"]),
        )

    outcome = asyncio.run(
        orchestrate(
            message,
            session=session,
            case_id=case_id,
            timeout_seconds=0.15,
            facts=facts,
            pattern=pattern,
            compliance=compliance,
        )
    )
    assert outcome.result is None
    assert outcome.run.state is WorkflowState.BLOCKED
    assert session.advice_requested is False
    dumped = outcome.model_dump_json()
    assert URL not in dumped
    assert "Should I buy" not in dumped


def test_exception_text_is_dropped() -> None:
    case_id = new_case_id()
    message = "What is the expense ratio of HDFC Large Cap Fund?"

    def facts() -> FactsAgentOutput:
        raise RuntimeError("secret-token-xyz")

    def pattern() -> PatternAgentOutput:
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.INSUFFICIENT_DATA, 0, [], status=PatternStatus.INSUFFICIENT_DATA),
        )

    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            case_id=case_id,
            facts=facts,
            pattern=pattern,
        )
    )
    dumped = outcome.model_dump_json()
    assert "secret-token-xyz" not in dumped
    assert "RuntimeError" in dumped
    assert outcome.result is not None
    assert "https://" not in outcome.result.reply.text


def test_blank_message_does_not_retrieve_or_draft(tmp_path: Path) -> None:
    seen: list[str] = []

    def retriever(question: str) -> RetrievalBundle:
        seen.append(question)
        return _hit()

    outcome = asyncio.run(
        orchestrate(
            "   ",
            session=ComplianceSession(),
            retriever=retriever,
            csv_path=tmp_path / "missing.csv",
            run_dir=tmp_path / "missing-run",
        )
    )
    assert seen == []
    assert outcome.result is None
    assert outcome.run.state is WorkflowState.BLOCKED
    assert outcome.states == [
        WorkflowState.RECEIVED,
        WorkflowState.SANITIZING,
        WorkflowState.BLOCKED,
    ]
    dumped = outcome.model_dump_json()
    assert "export CSV" not in dumped
    assert "theme artifact" not in dumped


def test_pan_claim_is_not_stored() -> None:
    case_id = new_case_id()
    message = "Where is the contract note?"

    def facts() -> FactsAgentOutput:
        from supportdesk.contracts import FactClaim

        result = FactsResult(
            status=FactsStatus.SUPPORTED,
            coverage=Coverage.COVERED,
            answer_facts=[
                FactClaim(
                    claim=f"Account PAN {PAN} is on file.",
                    source_title="HDFC Large Cap Fund",
                    source_url=URL,
                    evidence=f"Account PAN {PAN} is on file.",
                    last_checked=date(2026, 9, 1),
                )
            ],
            searched_sources=[URL],
            execution_id=new_execution_id(),
        )
        return _wrap_facts(message, case_id, result)

    def pattern() -> PatternAgentOutput:
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.INSUFFICIENT_DATA, 0, [], status=PatternStatus.INSUFFICIENT_DATA),
        )

    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            case_id=case_id,
            facts=facts,
            pattern=pattern,
        )
    )
    assert outcome.result is None
    assert outcome.run.state is WorkflowState.BLOCKED
    assert PAN not in outcome.model_dump_json()
    assert contains_pii(" ".join(outcome.agent_details)) is False


def test_disagreement_keeps_the_fact_and_hides_the_count(tmp_path: Path) -> None:
    csv_path, run_dir = _write_pattern(tmp_path, ["r1", "r2", "r3", "r4"])
    seen: list[str] = []

    def retriever(question: str) -> RetrievalBundle:
        seen.append(question)
        return _hit()

    message = (
        "What is the expense ratio of HDFC Large Cap Fund? "
        f"The customer support team is not responding. Call {PHONE}."
    )
    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            retriever=retriever,
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert outcome.result is not None
    reply = outcome.result.reply.text
    note = outcome.result.routing_note
    assert reply == (
        "Expense ratio is listed on this page. "
        f"Source: {URL}, last checked 2026-09-01."
    )
    assert outcome.result.reply.sentence_count == 3
    assert PHONE not in reply
    assert "not responding" not in reply
    assert "4" not in reply.split("Source:", 1)[0]
    assert note.pattern_signal is PatternSignal.RECURRING
    assert note.matching_count == 4
    assert note.priority is Priority.NORMAL
    assert note.team == "general support"
    assert note.facts_coverage is Coverage.COVERED
    assert note.citation_refs == [URL]
    assert note.analysis_window.start == date(2026, 6, 1)
    assert note.analysis_window.end == date(2026, 9, 1)
    assert outcome.result.disagreements
    assert "recurring" in (note.disagreement or "")
    assert seen and PHONE not in seen[0]
    assert content_has_pii(outcome.result) is False
    assert outcome.run.state is WorkflowState.DRAFTED
    assert {item.agent.value for item in outcome.run.executions} == {"facts", "pattern", "compliance"}


def test_advice_flag_does_not_become_a_recommendation(tmp_path: Path) -> None:
    csv_path, run_dir = _write_pattern(tmp_path, ["r1", "r2", "r3", "r4"])
    seen: list[str] = []
    session = ComplianceSession()

    def retriever(question: str) -> RetrievalBundle:
        seen.append(question)
        return _hit()

    first = asyncio.run(
        orchestrate(
            "Should I buy this fund?",
            session=session,
            retriever=retriever,
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert seen == []
    assert session.advice_requested is True
    assert first.result is not None
    assert "https://" not in first.result.reply.text
    assert requests_advice(first.result.reply.text) is False
    assert requests_performance(first.result.reply.text) is False
    assert "Should I buy" not in first.model_dump_json()

    second = asyncio.run(
        orchestrate(
            "What is the expense ratio of HDFC Large Cap Fund?",
            session=session,
            retriever=retriever,
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert second.result is not None
    assert "session_advice_context" in second.result.routing_note.compliance_flags
    assert URL in second.result.reply.text
    assert "Expense ratio is listed on this page." in second.result.reply.text
    assert requests_advice(second.result.reply.text) is False
    assert requests_performance(second.result.reply.text) is False
    assert "should" not in second.result.reply.text.casefold()
    assert seen and "should" not in seen[0].casefold()


def test_rising_brokerage_sets_priority_without_quoting_the_count() -> None:
    case_id = new_case_id()
    message = "Brokerage fees were charged twice."

    def facts() -> FactsAgentOutput:
        return _wrap_facts(
            message,
            case_id,
            FactsResult(
                status=FactsStatus.NOT_COVERED,
                coverage=Coverage.NOT_COVERED,
                limitations=["no retrieved chunk supports an answer"],
                execution_id=new_execution_id(),
            ),
        )

    def pattern() -> PatternAgentOutput:
        return _wrap_pattern(
            message,
            case_id,
            _pattern(PatternSignal.RISING, 17, ["t3: Brokerage fees"]),
        )

    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            case_id=case_id,
            facts=facts,
            pattern=pattern,
        )
    )
    assert outcome.result is not None
    note = outcome.result.routing_note
    assert note.team == "payments"
    assert note.priority is Priority.HIGH
    assert note.matching_count == 17
    assert "17" not in outcome.result.reply.text
    assert outcome.result.disagreements == []
    assert "https://" not in outcome.result.reply.text


def test_missing_fact_and_pattern_is_insufficient_evidence(tmp_path: Path) -> None:
    csv_path, run_dir = _write_pattern(tmp_path, ["r1", "r2", "r3", "r4"])
    outcome = asyncio.run(
        orchestrate(
            "What is the expense ratio of HDFC Large Cap Fund?",
            session=ComplianceSession(),
            retriever=lambda _question: _not_found(),
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert outcome.result is not None
    assert outcome.result.facts.status is FactsStatus.NOT_COVERED
    assert outcome.result.pattern.signal is PatternSignal.INSUFFICIENT_DATA
    assert WorkflowState.INSUFFICIENT_EVIDENCE in outcome.states
    assert outcome.run.state is WorkflowState.DRAFTED
    assert "https://" not in outcome.result.reply.text
    assert "approved sources" in outcome.result.reply.text


def test_callables_are_the_real_agents(tmp_path: Path) -> None:
    """Default runners are answer_facts and answer_pattern, not a second implementation."""
    csv_path, run_dir = _write_pattern(tmp_path, ["r1"])
    seen: list[str] = []

    def retriever(question: str) -> RetrievalBundle:
        seen.append(question)
        return _not_found()

    message = "The customer support team is not responding."
    outcome = asyncio.run(
        orchestrate(
            message,
            session=ComplianceSession(),
            retriever=retriever,
            csv_path=csv_path,
            run_dir=run_dir,
        )
    )
    assert outcome.result is not None
    assert outcome.result.pattern.signal is PatternSignal.ONE_OFF
    assert outcome.result.pattern.matching_count == 1
    direct_facts = answer_facts(
        message,
        session=ComplianceSession(),
        case_id=new_case_id(),
        retriever=retriever,
    )
    direct_pattern = answer_pattern(
        message,
        session=ComplianceSession(),
        case_id=new_case_id(),
        csv_path=csv_path,
        run_dir=run_dir,
    )
    assert direct_facts.result.status is FactsStatus.NOT_COVERED
    assert direct_pattern.result.signal is PatternSignal.ONE_OFF
    assert seen
