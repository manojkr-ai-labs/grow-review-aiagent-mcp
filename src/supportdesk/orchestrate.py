"""Parallel dispatch, customer reply, and internal routing note.

Facts, Pattern, and Compliance run concurrently. Each call gets its own
session copy, so a timeout cannot write flags back onto the caller.
An agent timeout or exception becomes an error result with no citation.
The customer reply never includes the raw message, a review count, or a
recommendation. Reviewer gates and MCP calls are later phases.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from supportdesk.compliance import ComplianceInspection, ComplianceSession
from supportdesk.contracts import (
    AgentExecution,
    AnalysisWindow,
    ComplianceResult,
    CustomerReply,
    FactClaim,
    FactsResult,
    OrchestratorResult,
    PatternResult,
    RoutingNote,
    WorkflowRun,
    count_sentences,
)
from supportdesk.enums import (
    AgentExecutionStatus,
    AgentName,
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    PatternSignal,
    PatternStatus,
    Priority,
    WorkflowState,
)
from supportdesk.facts import FactsAgentOutput, Retriever, answer_facts
from supportdesk.ids import new_case_id, new_execution_id, sha256_text
from supportdesk.pattern import PatternAgentOutput, answer_pattern
from supportdesk.privacy import contains_pii
from supportdesk.workflow import new_workflow_run, transition

_ALLOWED_HOSTS = frozenset({"groww.in", "www.groww.in"})
_REFUSAL = (
    "I can't provide an investment recommendation or a performance expectation. "
    "Published product information is on the official Groww pages."
)
_NOT_COVERED = (
    "Thanks for contacting us. "
    "I don't have an answer for that in the approved sources."
)
_FACTS_FAILED = (
    "Thanks for contacting us. "
    "I couldn't confirm that from the approved sources."
)
_EMPTY_HASH = sha256_text("")
_POSITIVE = frozenset({PatternSignal.RECURRING, PatternSignal.RISING})

FactsRunner = Callable[[], FactsAgentOutput]
PatternRunner = Callable[[], PatternAgentOutput]
ComplianceRunner = Callable[[], ComplianceInspection]


class OrchestrationOutcome(BaseModel):
    """Final draft, or a blocked run with no reply."""

    model_config = ConfigDict(extra="forbid")

    run: WorkflowRun
    result: OrchestratorResult | None = None
    states: list[WorkflowState]
    agent_details: list[str]


@dataclass
class _Done:
    execution: AgentExecution
    detail: str
    facts: FactsResult | None = None
    pattern: PatternResult | None = None
    inspection: ComplianceInspection | None = None


async def orchestrate(
    message: str,
    *,
    session: ComplianceSession,
    case_id: str | None = None,
    round_index: int = 0,
    rework_index: int = 0,
    timeout_seconds: float = 30.0,
    facts: FactsRunner | None = None,
    pattern: PatternRunner | None = None,
    compliance: ComplianceRunner | None = None,
    retriever: Retriever | None = None,
    project1_root: Path | None = None,
    csv_path: Path | None = None,
    runs_dir: Path | None = None,
    run_dir: Path | None = None,
    db_path: Path | None = None,
) -> OrchestrationOutcome:
    """Run the three agents together and stop at DRAFTED or BLOCKED."""
    case_id = case_id or new_case_id()
    run = new_workflow_run(case_id)
    states = [run.state, WorkflowState.SANITIZING]
    run = transition(run, WorkflowState.SANITIZING)
    own_compliance = compliance is None

    facts_session = ComplianceSession.from_state(session.export_state())
    pattern_session = ComplianceSession.from_state(session.export_state())
    compliance_session = ComplianceSession.from_state(session.export_state())
    facts_id = new_execution_id()
    pattern_id = new_execution_id()
    compliance_id = new_execution_id()

    facts_call = facts or (
        lambda: answer_facts(
            message,
            session=facts_session,
            case_id=case_id,
            execution_id=facts_id,
            project1_root=project1_root,
            retriever=retriever,
        )
    )
    pattern_call = pattern or (
        lambda: answer_pattern(
            message,
            session=pattern_session,
            case_id=case_id,
            execution_id=pattern_id,
            csv_path=csv_path,
            runs_dir=runs_dir,
            run_dir=run_dir,
            db_path=db_path,
        )
    )
    compliance_call = compliance or (
        lambda: compliance_session.inspect(
            message,
            case_id=case_id,
            execution_id=compliance_id,
        )
    )

    facts_done, pattern_done, compliance_done = await asyncio.gather(
        _invoke(
            AgentName.FACTS,
            facts_call,
            facts_id,
            run,
            round_index,
            rework_index,
            timeout_seconds,
            _facts_timeout,
        ),
        _invoke(
            AgentName.PATTERN,
            pattern_call,
            pattern_id,
            run,
            round_index,
            rework_index,
            timeout_seconds,
            _pattern_timeout,
        ),
        _invoke(
            AgentName.COMPLIANCE,
            compliance_call,
            compliance_id,
            run,
            round_index,
            rework_index,
            timeout_seconds,
            _compliance_timeout,
        ),
    )
    if own_compliance and compliance_done.inspection is not None:
        session.advice_requested = compliance_session.advice_requested
        session.performance_requested = compliance_session.performance_requested

    safe_hash = (
        compliance_done.inspection.input_hash
        if compliance_done.inspection is not None
        else _EMPTY_HASH
    )
    done = [facts_done, pattern_done, compliance_done]
    for item in done:
        if item.execution.input_hash == _EMPTY_HASH:
            item.execution = item.execution.model_copy(update={"input_hash": safe_hash})

    inspection = compliance_done.inspection
    decision = (
        inspection.result.decision
        if inspection is not None
        else ComplianceDecision.BLOCK
    )
    details = [item.detail for item in done]
    executions = [item.execution for item in done]

    if inspection is None or decision is ComplianceDecision.BLOCK:
        run = _advance(run, states, WorkflowState.BLOCKED)
        return _outcome(run, states, executions, details, None)

    assert facts_done.facts is not None
    assert pattern_done.pattern is not None
    facts_result = facts_done.facts
    pattern_result = pattern_done.pattern
    if _stored_pii(facts_result, pattern_result):
        details.append("draft withheld because agent text matched a PII pattern")
        run = _advance(
            run,
            states,
            WorkflowState.AGENTS_RUNNING,
            WorkflowState.AGENT_ERROR,
            WorkflowState.BLOCKED,
        )
        return _outcome(run, states, executions, details, None)

    facts_done.execution = facts_done.execution.model_copy(
        update={"status": _facts_status(facts_result, decision)}
    )
    pattern_done.execution = pattern_done.execution.model_copy(
        update={"status": _pattern_status(pattern_result, decision)}
    )
    executions = [item.execution for item in done]
    reply, note, disagreements, withheld = _draft(
        facts_result,
        pattern_result,
        inspection,
    )
    if withheld or contains_pii(reply) or _note_has_pii(note):
        details.append("draft withheld because the reply or note matched a PII pattern")
        run = _advance(
            run,
            states,
            WorkflowState.AGENTS_RUNNING,
            WorkflowState.AGENT_ERROR,
            WorkflowState.BLOCKED,
        )
        return _outcome(run, states, executions, details, None)

    mid = _middle_state(decision, facts_done.execution.status, pattern_result)
    if mid is WorkflowState.ORCHESTRATED:
        run = _advance(run, states, WorkflowState.AGENTS_RUNNING, WorkflowState.ORCHESTRATED)
    else:
        run = _advance(
            run,
            states,
            WorkflowState.AGENTS_RUNNING,
            mid,
            WorkflowState.ORCHESTRATED,
        )
    run = _advance(run, states, WorkflowState.DRAFTED)
    result = OrchestratorResult(
        case_id=case_id,
        reply=CustomerReply(text=reply, sentence_count=count_sentences(reply)),
        routing_note=note,
        facts=facts_result,
        pattern=pattern_result,
        compliance=inspection.result,
        disagreements=disagreements,
    )
    return _outcome(run, states, executions, details, result)


async def _invoke(
    agent: AgentName,
    call: Callable[[], object],
    execution_id: str,
    run: WorkflowRun,
    round_index: int,
    rework_index: int,
    timeout_seconds: float,
    on_timeout: Callable[[str], object],
) -> _Done:
    started = _now()
    try:
        value = await asyncio.wait_for(asyncio.to_thread(call), timeout_seconds)
    except TimeoutError:
        return _failed(
            agent,
            execution_id,
            run,
            round_index,
            rework_index,
            started,
            on_timeout(execution_id),
            f"{agent.value}: timed out",
        )
    except Exception as exc:
        failed = on_timeout(execution_id)
        detail = f"{agent.value}: failed: {type(exc).__name__}"
        return _failed(
            agent,
            execution_id,
            run,
            round_index,
            rework_index,
            started,
            _with_limitation(failed, detail),
            detail,
        )
    ended = _now()
    return _succeeded(
        agent,
        run,
        round_index,
        rework_index,
        started,
        ended,
        value,
        execution_id,
    )


def _failed(
    agent: AgentName,
    execution_id: str,
    run: WorkflowRun,
    round_index: int,
    rework_index: int,
    started: datetime,
    value: object,
    detail: str,
) -> _Done:
    ended = _now()
    if agent is AgentName.COMPLIANCE:
        inspection = value if isinstance(value, ComplianceInspection) else None
        return _Done(
            _execution(
                execution_id,
                AgentName.COMPLIANCE,
                AgentExecutionStatus.ERROR,
                run,
                round_index,
                rework_index,
                started,
                ended,
                _EMPTY_HASH,
            ),
            detail,
            inspection=inspection,
        )
    status = AgentExecutionStatus.ERROR
    if isinstance(value, FactsAgentOutput):
        return _Done(
            _execution(
                value.result.execution_id,
                agent,
                status,
                run,
                round_index,
                rework_index,
                started,
                ended,
                _EMPTY_HASH,
            ),
            detail,
            facts=value.result,
        )
    if isinstance(value, PatternAgentOutput):
        return _Done(
            _execution(
                value.result.execution_id,
                agent,
                status,
                run,
                round_index,
                rework_index,
                started,
                ended,
                _EMPTY_HASH,
            ),
            detail,
            pattern=value.result,
        )
    raise TypeError(f"unexpected {agent.value} failure payload")


def _succeeded(
    agent: AgentName,
    run: WorkflowRun,
    round_index: int,
    rework_index: int,
    started: datetime,
    ended: datetime,
    value: object,
    fallback_id: str,
) -> _Done:
    if agent is AgentName.FACTS:
        if not isinstance(value, FactsAgentOutput):
            raise TypeError("facts runner must return FactsAgentOutput")
        status = _facts_status(value.result, value.inspection.result.decision)
        return _Done(
            _execution(
                value.result.execution_id,
                agent,
                status,
                run,
                round_index,
                rework_index,
                started,
                ended,
                value.inspection.input_hash,
            ),
            f"facts: {value.result.status.value}",
            facts=value.result,
        )
    if agent is AgentName.PATTERN:
        if not isinstance(value, PatternAgentOutput):
            raise TypeError("pattern runner must return PatternAgentOutput")
        status = _pattern_status(value.result, value.inspection.result.decision)
        return _Done(
            _execution(
                value.result.execution_id,
                agent,
                status,
                run,
                round_index,
                rework_index,
                started,
                ended,
                value.inspection.input_hash,
            ),
            f"pattern: {value.result.status.value}",
            pattern=value.result,
        )
    if not isinstance(value, ComplianceInspection):
        raise TypeError("compliance runner must return ComplianceInspection")
    status = (
        AgentExecutionStatus.BLOCKED
        if value.result.decision is ComplianceDecision.BLOCK
        else AgentExecutionStatus.SUCCESS
    )
    return _Done(
        _execution(
            value.result.execution_id or fallback_id,
            agent,
            status,
            run,
            round_index,
            rework_index,
            started,
            ended,
            value.input_hash,
        ),
        f"compliance: {value.result.decision.value}",
        inspection=value,
    )


def is_template_reply(text: str) -> bool:
    """True for the fixed replies that do not state a retrieved fact."""
    return text in {_REFUSAL, _NOT_COVERED, _FACTS_FAILED}


def draft_from_agents(
    facts: FactsResult,
    pattern: PatternResult,
    compliance: ComplianceResult,
) -> tuple[str, RoutingNote, list[str], bool]:
    """Rebuild a reply from stored agent results. Does not retrieve or read reviews."""
    from supportdesk.compliance import ComplianceInspection

    inspection = ComplianceInspection(
        result=compliance,
        redacted_text="",
        input_hash=sha256_text(""),
        request=None,
    )
    return _draft(facts, pattern, inspection)


def _draft(
    facts: FactsResult,
    pattern: PatternResult,
    inspection: ComplianceInspection,
) -> tuple[str, RoutingNote, list[str], bool]:
    """Return reply, note, disagreements, and whether PII forced a block."""
    decision = inspection.result.decision
    claim = _usable_claim(facts)
    reply, cited = _reply_text(facts, claim, decision)
    if contains_pii(reply):
        return reply, _note(facts, pattern, inspection, [], None, _NOT_COVERED), [], True
    disagreements: list[str] = []
    disagreement = None
    limitations = [*facts.limitations, *pattern.limitations]
    if facts.status is FactsStatus.SUPPORTED and not cited:
        limitations.append("the fact claim was not copied into the reply")
    if cited and claim is not None and pattern.signal in _POSITIVE:
        disagreement = (
            f"Facts coverage is covered. Pattern signal is {pattern.signal.value} "
            f"with matching count {pattern.matching_count}. "
            "The reply uses the cited fact. The pattern signal stays in this note."
        )
        disagreements.append(disagreement)
    if decision is ComplianceDecision.REFUSE and not cited:
        limitations.append(inspection.result.safe_handling)
    if facts.status is FactsStatus.ERROR and decision is not ComplianceDecision.REFUSE:
        limitations.append("facts agent did not return evidence; the reply does not cite a source")
    if cited and claim is not None and claim.last_checked is None:
        limitations.append("last_checked unavailable")
    note = _note(
        facts,
        pattern,
        inspection,
        [claim.source_url] if cited and claim is not None else [],
        disagreement,
        _next_action(decision, cited, pattern.signal, facts.status),
        limitations,
    )
    return reply, note, disagreements, contains_pii(reply) or _note_has_pii(note)


def _reply_text(
    facts: FactsResult,
    claim: FactClaim | None,
    decision: ComplianceDecision,
) -> tuple[str, bool]:
    if claim is not None:
        text = _cited(claim)
        if count_sentences(text) <= 3 and not contains_pii(text):
            return text, True
    if decision is ComplianceDecision.REFUSE:
        return _REFUSAL, False
    if facts.status is FactsStatus.ERROR:
        return _FACTS_FAILED, False
    return _NOT_COVERED, False


def _cited(claim: FactClaim) -> str:
    sentence = claim.claim.strip()
    if sentence[-1] not in ".!?":
        sentence = f"{sentence}."
    source = f"Source: {claim.source_url}"
    if claim.last_checked is not None:
        source = f"{source}, last checked {claim.last_checked.isoformat()}"
    return f"{sentence} {source}."


def _usable_claim(facts: FactsResult) -> FactClaim | None:
    if facts.status is not FactsStatus.SUPPORTED or not facts.answer_facts:
        return None
    claim = facts.answer_facts[0]
    if contains_pii(claim.claim) or contains_pii(claim.evidence) or contains_pii(claim.source_title):
        return None
    if not _approved_url(claim.source_url):
        return None
    if claim.source_url not in facts.searched_sources and facts.searched_sources:
        return None
    sentence = claim.claim.strip()
    if count_sentences(sentence) > 1:
        return None
    if sentence not in claim.evidence and sentence not in claim.claim:
        return None
    return claim


def _note(
    facts: FactsResult,
    pattern: PatternResult,
    inspection: ComplianceInspection,
    citation_refs: list[str],
    disagreement: str | None,
    next_action: str,
    limitations: list[str] | None = None,
) -> RoutingNote:
    labels = _labels(pattern.matched_themes)
    team, team_reason = _team(labels)
    priority = _priority(pattern.signal)
    reason = (
        f"{team_reason} Priority is {priority.value} because the pattern signal "
        f"is {pattern.signal.value} with matching count {pattern.matching_count}."
    )
    return RoutingNote(
        team=team,
        priority=priority,
        reason=reason,
        pattern_signal=pattern.signal,
        matching_count=pattern.matching_count,
        analysis_window=pattern.analysis_window,
        facts_coverage=facts.coverage,
        citation_refs=citation_refs,
        compliance_flags=list(inspection.result.flags),
        disagreement=disagreement,
        limitations=limitations if limitations is not None else [*facts.limitations, *pattern.limitations],
        next_action=next_action,
    )


def _labels(themes: list[str]) -> list[str]:
    labels: list[str] = []
    for item in themes:
        labels.append(item.split(": ", 1)[1] if ": " in item else item)
    return labels


def _team(labels: list[str]) -> tuple[str, str]:
    if not labels:
        return "general support", "No theme matched the message."
    blob = " ".join(labels).casefold()
    named = labels[0]
    if _word(blob, "kyc"):
        return "KYC", f"Matched theme {named}."
    if any(_word(blob, word) for word in ("payment", "payments", "brokerage", "fee", "fees", "charge", "charges")):
        return "payments", f"Matched theme {named}."
    if any(_word(blob, word) for word in ("chart", "charting", "stability", "crash", "crashes")):
        return "technical support", f"Matched theme {named}."
    if _word(blob, "login") or _word(blob, "password") or (_word(blob, "account") and _word(blob, "access")):
        return "account access", f"Matched theme {named}."
    return "general support", f"Matched theme {named}."


def _word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _priority(signal: PatternSignal) -> Priority:
    if signal is PatternSignal.RISING:
        return Priority.HIGH
    if signal is PatternSignal.RECURRING:
        return Priority.NORMAL
    return Priority.LOW


def _next_action(
    decision: ComplianceDecision,
    cited: bool,
    signal: PatternSignal,
    facts_status: FactsStatus,
) -> str:
    if decision is ComplianceDecision.REFUSE and not cited:
        return (
            "Do not add an investment recommendation or a performance expectation."
        )
    if cited and signal in _POSITIVE:
        return "Send the cited fact and investigate the pattern signal."
    if cited:
        return "Send the cited fact."
    if facts_status is FactsStatus.ERROR:
        return "Do not cite a source. Facts retrieval did not succeed."
    if signal in _POSITIVE:
        return "Investigate the pattern signal. Do not invent a product answer."
    return "Tell the customer the question is not covered by the approved sources."


def _middle_state(
    decision: ComplianceDecision,
    facts_status: AgentExecutionStatus,
    pattern: PatternResult,
) -> WorkflowState:
    if facts_status is AgentExecutionStatus.ERROR or pattern.status is PatternStatus.ERROR:
        return WorkflowState.AGENT_ERROR
    if decision is ComplianceDecision.REFUSE:
        return WorkflowState.ORCHESTRATED
    if (
        facts_status is AgentExecutionStatus.NOT_COVERED
        and pattern.signal is PatternSignal.INSUFFICIENT_DATA
    ):
        return WorkflowState.INSUFFICIENT_EVIDENCE
    return WorkflowState.ORCHESTRATED


def _facts_status(result: FactsResult, decision: ComplianceDecision) -> AgentExecutionStatus:
    if result.status is FactsStatus.SUPPORTED:
        return AgentExecutionStatus.SUCCESS
    if result.status is FactsStatus.NOT_COVERED:
        return AgentExecutionStatus.NOT_COVERED
    if decision in {ComplianceDecision.REFUSE, ComplianceDecision.BLOCK}:
        return AgentExecutionStatus.BLOCKED
    return AgentExecutionStatus.ERROR


def _pattern_status(result: PatternResult, decision: ComplianceDecision) -> AgentExecutionStatus:
    if result.status is PatternStatus.SUCCESS:
        return AgentExecutionStatus.SUCCESS
    if result.status is PatternStatus.INSUFFICIENT_DATA:
        return AgentExecutionStatus.NOT_COVERED
    if decision is ComplianceDecision.BLOCK:
        return AgentExecutionStatus.BLOCKED
    return AgentExecutionStatus.ERROR


def _facts_timeout(execution_id: str) -> FactsAgentOutput:
    result = FactsResult(
        status=FactsStatus.ERROR,
        coverage=Coverage.NOT_COVERED,
        answer_facts=[],
        limitations=["facts agent timed out"],
        execution_id=execution_id,
    )
    return FactsAgentOutput(result=result, inspection=_blank_inspection(execution_id))


def _pattern_timeout(execution_id: str) -> PatternAgentOutput:
    result = PatternResult(
        status=PatternStatus.ERROR,
        signal=PatternSignal.INSUFFICIENT_DATA,
        matching_count=0,
        analysis_window=AnalysisWindow(),
        method="Pattern matching did not run.",
        limitations=["pattern agent timed out"],
        execution_id=execution_id,
    )
    return PatternAgentOutput(result=result, inspection=_blank_inspection(execution_id))


def _compliance_timeout(execution_id: str) -> ComplianceInspection:
    return _blank_inspection(execution_id, blocked=True, detail="compliance agent timed out")


def _with_limitation(value: object, detail: str) -> object:
    if isinstance(value, FactsAgentOutput):
        facts = value.result.model_copy(
            update={"limitations": [detail.split(": ", 1)[-1]]}
        )
        return value.model_copy(update={"result": facts})
    if isinstance(value, PatternAgentOutput):
        pattern = value.result.model_copy(
            update={"limitations": [detail.split(": ", 1)[-1]]}
        )
        return value.model_copy(update={"result": pattern})
    if isinstance(value, ComplianceInspection):
        result = value.result.model_copy(update={"safe_handling": "Block the case. The compliance check failed."})
        return value.model_copy(update={"result": result})
    return value


def _blank_inspection(execution_id: str, *, blocked: bool = False, detail: str = "") -> ComplianceInspection:
    from supportdesk.contracts import ComplianceResult

    handling = detail or "Block the case. The compliance check did not finish."
    result = ComplianceResult(
        status=ComplianceStatus.ERROR if blocked else ComplianceStatus.SUCCESS,
        pii_detected=False,
        pii_categories=[],
        sanitized=False,
        advice_request_detected=False,
        performance_claim_risk=False,
        decision=ComplianceDecision.BLOCK,
        flags=["agent_error"] if blocked else [],
        safe_handling=handling,
        execution_id=execution_id,
    )
    return ComplianceInspection(result=result, redacted_text="", input_hash=_EMPTY_HASH, request=None)


def _stored_pii(facts: FactsResult, pattern: PatternResult) -> bool:
    for claim in facts.answer_facts:
        if contains_pii(claim.claim) or contains_pii(claim.evidence) or contains_pii(claim.source_title):
            return True
    for item in pattern.evidence:
        if item.snippet and contains_pii(item.snippet):
            return True
    return False


def _note_has_pii(note: RoutingNote) -> bool:
    parts = [
        note.team,
        note.reason,
        note.next_action,
        note.disagreement or "",
        *note.limitations,
        *note.citation_refs,
        *note.compliance_flags,
    ]
    return contains_pii(" ".join(parts))


def _approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.lower() in _ALLOWED_HOSTS


def _execution(
    execution_id: str,
    agent: AgentName,
    status: AgentExecutionStatus,
    run: WorkflowRun,
    round_index: int,
    rework_index: int,
    started: datetime,
    ended: datetime,
    input_hash: str,
) -> AgentExecution:
    return AgentExecution(
        execution_id=execution_id,
        case_id=run.case_id,
        run_id=run.run_id,
        agent=agent,
        status=status,
        started_at=started,
        ended_at=ended,
        input_hash=input_hash,
        round_index=round_index,
        rework_index=rework_index,
    )


def _advance(run: WorkflowRun, states: list[WorkflowState], *targets: WorkflowState) -> WorkflowRun:
    for target in targets:
        run = transition(run, target)
        states.append(target)
    return run


def _outcome(
    run: WorkflowRun,
    states: list[WorkflowState],
    executions: list[AgentExecution],
    details: list[str],
    result: OrchestratorResult | None,
) -> OrchestrationOutcome:
    return OrchestrationOutcome(
        run=run.model_copy(update={"executions": executions}),
        result=result,
        states=list(states),
        agent_details=details,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
