"""Human refinement and version-bound approval.

A case accepts at most five refinements. Each round stores the redacted
instruction, the agents that actually ran, and their execution ids.
The reviewer runs again. Approval and rejection apply only to the hash of
the reply and routing note that passed review. Rejection has no MCP path.
This module does not call MCP.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from supportdesk.approval import ApprovalRecord, content_hash
from supportdesk.compliance import ComplianceSession
from supportdesk.contracts import (
    AgentExecution,
    ComplianceResult,
    CustomerReply,
    FactsResult,
    OrchestratorResult,
    PatternResult,
    ReviewerResult,
    WorkflowRun,
    count_sentences,
)
from supportdesk.enums import (
    AgentExecutionStatus,
    AgentName,
    ApprovalDecision,
    ComplianceDecision,
    FactsStatus,
    PatternStatus,
    ReviewerDecision,
    WorkflowState,
)
from supportdesk.facts import Retriever, answer_facts
from supportdesk.ids import new_execution_id, sha256_text
from supportdesk.orchestrate import draft_from_agents
from supportdesk.pattern import answer_pattern
from supportdesk.privacy import contains_pii, redact_pii
from supportdesk.reviewer import ReviewedCase, content_has_pii, review
from supportdesk.workflow import (
    ContractError,
    bind_content,
    next_refinement_round,
    transition,
)

_APPROVER_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_INSTRUCTION_LIMIT = 280
_FACTS_WORDS = ("fact", "facts", "source", "citation", "scheme", "corpus")
_PATTERN_WORDS = (
    "pattern",
    "review",
    "reviews",
    "complaint",
    "theme",
    "trend",
    "recurring",
    "rising",
)
_COMPLIANCE_WORDS = ("compliance", "advice", "privacy", "redact", "pii")
_DRAFT_WORDS = ("reply", "wording", "sentence", "tone", "shorter", "routing", "team", "priority")

FactsRunner = Callable[[str], object]
PatternRunner = Callable[[str], object]


class RefinementRecord(BaseModel):
    """One human refinement. The instruction is already redacted."""

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1, le=5)
    instruction: str = Field(min_length=1)
    agents: list[AgentName]
    stages: list[str]
    execution_ids: list[str]
    started_at: datetime
    ended_at: datetime
    accepted: bool
    content_hash: str

    def model_post_init(self, _context: object) -> None:
        if contains_pii(self.instruction):
            raise ValueError("refinement instruction still matches a PII pattern")


class DeskCase(BaseModel):
    """Pending or decided case. ``accepted_hash`` is the version a human may approve."""

    model_config = ConfigDict(extra="forbid")

    run: WorkflowRun
    result: OrchestratorResult
    reviews: list[ReviewerResult]
    refinements: list[RefinementRecord] = Field(default_factory=list)
    accepted_hash: str | None = None


class ApprovalPacket(BaseModel):
    """What a person sees before approve or reject. It is one content hash."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    reply: str
    team: str
    priority: str
    reason: str
    citation_refs: list[str]
    facts_coverage: str
    pattern_signal: str
    matching_count: int
    reviewer_decision: str
    content_hash: str
    refinement_round: int


def affected_work(instruction: str) -> tuple[set[AgentName], list[str]]:
    """Map a redacted instruction to agents and downstream stages."""
    folded = instruction.casefold()
    agents: set[AgentName] = set()
    if _any_word(folded, _FACTS_WORDS):
        agents.add(AgentName.FACTS)
    if _any_word(folded, _PATTERN_WORDS):
        agents.add(AgentName.PATTERN)
    if _any_word(folded, _COMPLIANCE_WORDS):
        agents.add(AgentName.COMPLIANCE)
    stages = [agent.value for agent in (AgentName.COMPLIANCE, AgentName.FACTS, AgentName.PATTERN) if agent in agents]
    if agents or _any_word(folded, _DRAFT_WORDS) or not stages:
        if "draft" not in stages:
            stages.append("draft")
    if "review" not in stages:
        stages.append("review")
    return agents, stages


def content_digest(result: OrchestratorResult) -> str:
    """Hash the reply and a canonical routing note."""
    note = json.dumps(
        result.routing_note.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return content_hash(reply=result.reply.text, routing_note=note)


def open_case(reviewed: ReviewedCase) -> DeskCase:
    """Bind the reviewed draft's hash. The case must already be pending."""
    if reviewed.run.state is not WorkflowState.PENDING_APPROVAL or reviewed.result is None:
        raise ContractError("only a pending reviewed draft can be opened")
    if reviewed.reviews[-1].decision is not ReviewerDecision.PASS:
        raise ContractError("only a passing review can be opened")
    if content_has_pii(reviewed.result):
        raise ContractError("draft contains PII and cannot be opened")
    digest = content_digest(reviewed.result)
    run = reviewed.run
    if run.content_hash is None:
        run = bind_content(run, digest)
    elif run.content_hash != digest:
        raise ContractError("pending content does not match the reviewed draft")
    return DeskCase(
        run=run,
        result=reviewed.result,
        reviews=list(reviewed.reviews),
        accepted_hash=digest,
    )


def refine(
    case: DeskCase,
    instruction: str,
    *,
    message: str | None = None,
    reply: str | None = None,
    session: ComplianceSession | None = None,
    retriever: Retriever | None = None,
    project1_root: Path | None = None,
    csv_path: Path | None = None,
    runs_dir: Path | None = None,
    run_dir: Path | None = None,
    db_path: Path | None = None,
    facts_runner: FactsRunner | None = None,
    pattern_runner: PatternRunner | None = None,
) -> DeskCase:
    """Apply one refinement, then review that version again."""
    if case.run.state not in {WorkflowState.PENDING_APPROVAL, WorkflowState.APPROVED}:
        raise ContractError("only a pending or approved case can be refined")
    stored_instruction = _store_instruction(instruction)
    agents, stages = affected_work(stored_instruction)
    if agents and message is None:
        raise ContractError("an affected agent requires a message, and none was provided")
    if not agents and reply is None:
        raise ContractError("no agent was named and no replacement reply was provided")
    next_round = next_refinement_round(case.run.refinement_round)
    started = _now()
    result, executions, ran = _produce(
        case,
        agents=agents,
        message=message,
        reply=None if agents else reply,
        session=session,
        retriever=retriever,
        project1_root=project1_root,
        csv_path=csv_path,
        runs_dir=runs_dir,
        run_dir=run_dir,
        db_path=db_path,
        facts_runner=facts_runner,
        pattern_runner=pattern_runner,
        round_index=next_round,
    )
    if content_has_pii(result):
        raise ContractError("refinement output matched a PII pattern")
    ended = _now()
    attempt = content_digest(result)
    verdict = review(result, rework_attempt=0)
    if AgentName.COMPLIANCE in ran and AgentName.COMPLIANCE.value not in stages:
        stages = [AgentName.COMPLIANCE.value, *stages]
    run = transition(case.run, WorkflowState.REVIEWING)
    run = run.model_copy(
        update={
            "refinement_round": next_round,
            "executions": [*run.executions, *executions],
        }
    )
    record = RefinementRecord(
        round_index=next_round,
        instruction=stored_instruction,
        agents=ran,
        stages=stages,
        execution_ids=[item.execution_id for item in executions],
        started_at=started,
        ended_at=ended,
        accepted=verdict.decision is ReviewerDecision.PASS,
        content_hash=attempt,
    )
    reviews = [*case.reviews, verdict]
    if verdict.decision is ReviewerDecision.PASS:
        run = bind_content(run, attempt)
        run = transition(run, WorkflowState.PENDING_APPROVAL)
        return DeskCase(
            run=run,
            result=result,
            reviews=reviews,
            refinements=[*case.refinements, record],
            accepted_hash=attempt,
        )
    if case.accepted_hash is not None:
        run = bind_content(run, case.accepted_hash)
        run = transition(run, WorkflowState.PENDING_APPROVAL)
    return DeskCase(
        run=run,
        result=case.result,
        reviews=reviews,
        refinements=[*case.refinements, record],
        accepted_hash=case.accepted_hash,
    )


def approval_packet(case: DeskCase) -> ApprovalPacket:
    """Return the exact version a person can approve or reject."""
    _require_pending_version(case)
    note = case.result.routing_note
    passed = _latest_pass(case.reviews)
    return ApprovalPacket(
        case_id=case.run.case_id,
        reply=case.result.reply.text,
        team=note.team,
        priority=note.priority.value,
        reason=note.reason,
        citation_refs=list(note.citation_refs),
        facts_coverage=note.facts_coverage.value,
        pattern_signal=note.pattern_signal.value,
        matching_count=note.matching_count,
        reviewer_decision=passed.decision.value,
        content_hash=case.accepted_hash or "",
        refinement_round=case.run.refinement_round,
    )


def decide(
    case: DeskCase,
    decision: ApprovalDecision,
    approver_ref: str,
    *,
    decided_at: datetime | None = None,
) -> DeskCase:
    """Approve or reject the accepted version. Rejection cannot start MCP."""
    _require_pending_version(case)
    if _APPROVER_REF.fullmatch(approver_ref) is None:
        raise ContractError("approver_ref is not a privacy-safe reference")
    digest = content_digest(case.result)
    if digest != case.accepted_hash or digest != case.run.content_hash:
        raise ContractError("approval is not bound to this content")
    target = (
        WorkflowState.APPROVED
        if decision is ApprovalDecision.APPROVE
        else WorkflowState.REJECTED
    )
    record = ApprovalRecord(
        case_id=case.run.case_id,
        decision=decision,
        content_hash=digest,
        decided_at=decided_at or _now(),
        approver_ref=approver_ref,
    )
    run = transition(case.run, target, approval=record, content_hash=digest)
    return case.model_copy(update={"run": run})


def _produce(
    case: DeskCase,
    *,
    agents: set[AgentName],
    message: str | None,
    reply: str | None,
    session: ComplianceSession | None,
    retriever: Retriever | None,
    project1_root: Path | None,
    csv_path: Path | None,
    runs_dir: Path | None,
    run_dir: Path | None,
    db_path: Path | None,
    facts_runner: FactsRunner | None,
    pattern_runner: PatternRunner | None,
    round_index: int,
) -> tuple[OrchestratorResult, list[AgentExecution], list[AgentName]]:
    if message is None:
        if reply is None:
            raise ContractError("no replacement reply was provided")
        updated = case.result.model_copy(update={"reply": _human_reply(reply)})
        return updated, [], []
    compliance_session = session or ComplianceSession()
    started = _now()
    inspection = compliance_session.inspect(message, case_id=case.run.case_id)
    compliance_execution = _execution(
        case,
        AgentName.COMPLIANCE,
        AgentExecutionStatus.BLOCKED
        if inspection.result.decision is ComplianceDecision.BLOCK
        else AgentExecutionStatus.SUCCESS,
        inspection.result.execution_id,
        inspection.input_hash,
        round_index,
        started,
        _now(),
    )
    if inspection.result.decision is ComplianceDecision.BLOCK or not inspection.redacted_text:
        raise ContractError("refinement message was blocked")
    facts: FactsResult = case.result.facts
    pattern: PatternResult = case.result.pattern
    compliance: ComplianceResult = inspection.result
    executions = [compliance_execution]
    ran = [AgentName.COMPLIANCE]
    redacted = inspection.redacted_text
    if AgentName.FACTS in agents:
        facts, execution = _run_facts(
            case,
            redacted,
            inspection.input_hash,
            round_index,
            session=ComplianceSession.from_state(compliance_session.export_state()),
            retriever=retriever,
            project1_root=project1_root,
            runner=facts_runner,
        )
        executions.append(execution)
        ran.append(AgentName.FACTS)
    if AgentName.PATTERN in agents:
        pattern, execution = _run_pattern(
            case,
            redacted,
            inspection.input_hash,
            round_index,
            session=ComplianceSession.from_state(compliance_session.export_state()),
            csv_path=csv_path,
            runs_dir=runs_dir,
            run_dir=run_dir,
            db_path=db_path,
            runner=pattern_runner,
        )
        executions.append(execution)
        ran.append(AgentName.PATTERN)
    reply_text, note, disagreements, withheld = draft_from_agents(facts, pattern, compliance)
    if withheld or contains_pii(reply_text):
        raise ContractError("refinement draft was withheld")
    result = OrchestratorResult(
        case_id=case.run.case_id,
        reply=_customer_reply(reply_text),
        routing_note=note,
        facts=facts,
        pattern=pattern,
        compliance=compliance,
        disagreements=disagreements,
    )
    return result, executions, ran


def _run_facts(
    case: DeskCase,
    redacted: str,
    input_hash: str,
    round_index: int,
    *,
    session: ComplianceSession,
    retriever: Retriever | None,
    project1_root: Path | None,
    runner: FactsRunner | None,
) -> tuple[FactsResult, AgentExecution]:
    started = _now()
    execution_id = new_execution_id()
    try:
        if runner is not None:
            value = runner(redacted)
        else:
            value = answer_facts(
                redacted,
                session=session,
                case_id=case.run.case_id,
                execution_id=execution_id,
                retriever=retriever,
                project1_root=project1_root,
            )
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"refinement agent failed: {type(exc).__name__}") from None
    from supportdesk.facts import FactsAgentOutput

    if not isinstance(value, FactsAgentOutput):
        raise ContractError("facts refinement did not return a facts result")
    status = AgentExecutionStatus.SUCCESS
    if value.result.status is FactsStatus.NOT_COVERED:
        status = AgentExecutionStatus.NOT_COVERED
    elif value.result.status is FactsStatus.ERROR:
        status = AgentExecutionStatus.ERROR
    return value.result, _execution(
        case,
        AgentName.FACTS,
        status,
        value.result.execution_id,
        input_hash,
        round_index,
        started,
        _now(),
    )


def _run_pattern(
    case: DeskCase,
    redacted: str,
    input_hash: str,
    round_index: int,
    *,
    session: ComplianceSession,
    csv_path: Path | None,
    runs_dir: Path | None,
    run_dir: Path | None,
    db_path: Path | None,
    runner: PatternRunner | None,
) -> tuple[PatternResult, AgentExecution]:
    started = _now()
    execution_id = new_execution_id()
    try:
        if runner is not None:
            value = runner(redacted)
        else:
            value = answer_pattern(
                redacted,
                session=session,
                case_id=case.run.case_id,
                execution_id=execution_id,
                csv_path=csv_path,
                runs_dir=runs_dir,
                run_dir=run_dir,
                db_path=db_path,
            )
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"refinement agent failed: {type(exc).__name__}") from None
    from supportdesk.pattern import PatternAgentOutput

    if not isinstance(value, PatternAgentOutput):
        raise ContractError("pattern refinement did not return a pattern result")
    status = AgentExecutionStatus.SUCCESS
    if value.result.status is PatternStatus.INSUFFICIENT_DATA:
        status = AgentExecutionStatus.NOT_COVERED
    elif value.result.status is PatternStatus.ERROR:
        status = AgentExecutionStatus.ERROR
    return value.result, _execution(
        case,
        AgentName.PATTERN,
        status,
        value.result.execution_id,
        input_hash,
        round_index,
        started,
        _now(),
    )


def _execution(
    case: DeskCase,
    agent: AgentName,
    status: AgentExecutionStatus,
    execution_id: str,
    input_hash: str,
    round_index: int,
    started: datetime,
    ended: datetime,
) -> AgentExecution:
    return AgentExecution(
        execution_id=execution_id,
        case_id=case.run.case_id,
        run_id=case.run.run_id,
        agent=agent,
        status=status,
        started_at=started,
        ended_at=ended,
        input_hash=input_hash,
        round_index=round_index,
        rework_index=0,
    )


def _require_pending_version(case: DeskCase) -> None:
    if case.run.state is not WorkflowState.PENDING_APPROVAL:
        raise ContractError("approval requires a pending case")
    if case.accepted_hash is None or case.run.content_hash != case.accepted_hash:
        raise ContractError("approval is not bound to this content")
    if content_digest(case.result) != case.accepted_hash:
        raise ContractError("approval is not bound to this content")
    if content_has_pii(case.result):
        raise ContractError("approval content matched a PII pattern")


def _latest_pass(reviews: list[ReviewerResult]) -> ReviewerResult:
    for item in reversed(reviews):
        if item.decision is ReviewerDecision.PASS:
            return item
    raise ContractError("approval requires a passing review")


def _store_instruction(instruction: str) -> str:
    if not instruction or not instruction.strip():
        raise ContractError("refinement instruction is empty")
    redacted = redact_pii(instruction)
    if not redacted.sanitized or contains_pii(redacted.text) or not redacted.text.strip():
        raise ContractError("refinement instruction could not be sanitized")
    text = redacted.text.strip()
    if len(text) > _INSTRUCTION_LIMIT:
        return f"sha256:{sha256_text(text)}"
    return text


def _human_reply(text: str) -> CustomerReply:
    redacted = redact_pii(text)
    if not redacted.sanitized or contains_pii(redacted.text) or not redacted.text.strip():
        raise ContractError("replacement reply could not be sanitized")
    return _customer_reply(redacted.text)


def _customer_reply(text: str) -> CustomerReply:
    try:
        return CustomerReply(text=text, sentence_count=count_sentences(text))
    except ValueError as exc:
        raise ContractError("replacement reply must be 1 to 3 sentences") from exc


def _any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) is not None for word in words)


def _now() -> datetime:
    return datetime.now(timezone.utc)
