"""Typed request and response contracts.

These models describe agent outputs. They do not retrieve, classify, or call MCP.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from supportdesk.approval import (
    ApprovalRecord,
    approval_matches,
    mcp_idempotency_key,
)
from supportdesk.enums import (
    AgentExecutionStatus,
    AgentName,
    ApprovalDecision,
    ComplianceDecision,
    ComplianceStatus,
    Coverage,
    FactsStatus,
    McpActionKind,
    McpActionStatus,
    PatternSignal,
    PatternStatus,
    PiiCategory,
    Priority,
    ReviewerDecision,
    ReviewerFindingCode,
    WorkflowState,
)
from supportdesk.ids import (
    CASE_ID_PATTERN,
    EXECUTION_ID_PATTERN,
    RUN_ID_PATTERN,
    SESSION_ID_PATTERN,
    SHA256_PATTERN,
)

_SENTENCE_END = re.compile(r"[.!?]+")
_HTTPS = re.compile(r"^https://\S+$")
_POSITIVE_SIGNALS = frozenset({PatternSignal.RECURRING, PatternSignal.RISING})


def count_sentences(text: str) -> int:
    """Count sentence-like chunks. Phase 6 may tighten abbreviation handling."""
    parts = [part.strip() for part in _SENTENCE_END.split(text.strip())]
    return len([part for part in parts if part])


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactClaim(ContractModel):
    claim: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str
    evidence: str = Field(min_length=1)
    last_checked: date | None = None

    @field_validator("source_url")
    @classmethod
    def source_url_is_https(cls, value: str) -> str:
        if _HTTPS.fullmatch(value) is None:
            raise ValueError("source_url must be an https URL")
        return value


class FactsResult(ContractModel):
    agent: AgentName = AgentName.FACTS
    status: FactsStatus
    coverage: Coverage
    answer_facts: list[FactClaim] = Field(default_factory=list)
    searched_sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    execution_id: str = Field(pattern=EXECUTION_ID_PATTERN)

    @model_validator(mode="after")
    def status_matches_claims(self) -> FactsResult:
        if self.agent is not AgentName.FACTS:
            raise ValueError("facts result agent must be facts")
        if self.status is FactsStatus.SUPPORTED:
            if self.coverage is not Coverage.COVERED:
                raise ValueError("supported facts require coverage=covered")
            if not self.answer_facts:
                raise ValueError("supported facts require at least one claim")
        if self.status is FactsStatus.NOT_COVERED:
            if self.coverage is not Coverage.NOT_COVERED:
                raise ValueError("not_covered status requires coverage=not_covered")
            if self.answer_facts:
                raise ValueError("not_covered facts cannot include claims")
        if self.status is FactsStatus.ERROR and self.answer_facts:
            raise ValueError("an error result cannot include factual claims")
        return self


class AnalysisWindow(ContractModel):
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> AnalysisWindow:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("analysis window end is before start")
        return self


class PatternEvidence(ContractModel):
    theme_id: str | None = None
    review_id: str | None = None
    snippet: str | None = Field(default=None, max_length=280)


class PatternResult(ContractModel):
    agent: AgentName = AgentName.PATTERN
    status: PatternStatus
    signal: PatternSignal
    matching_count: int = Field(ge=0)
    analysis_window: AnalysisWindow
    matched_themes: list[str] = Field(default_factory=list)
    evidence: list[PatternEvidence] = Field(default_factory=list)
    method: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    comparable_periods: bool = False
    execution_id: str = Field(pattern=EXECUTION_ID_PATTERN)

    @model_validator(mode="after")
    def signal_matches_measurement(self) -> PatternResult:
        if self.agent is not AgentName.PATTERN:
            raise ValueError("pattern result agent must be pattern")
        if self.signal is PatternSignal.ONE_OFF and self.matching_count != 1:
            raise ValueError("one_off requires matching_count == 1")
        if self.signal in _POSITIVE_SIGNALS and self.matching_count < 1:
            raise ValueError(f"{self.signal.value} requires a positive matching_count")
        if self.signal is PatternSignal.RISING:
            window = self.analysis_window
            if not self.comparable_periods:
                raise ValueError("rising requires comparable periods")
            if window.start is None or window.end is None:
                raise ValueError("rising requires a start and end date")
        return self


class ComplianceResult(ContractModel):
    agent: AgentName = AgentName.COMPLIANCE
    status: ComplianceStatus
    pii_detected: bool
    pii_categories: list[PiiCategory] = Field(default_factory=list)
    sanitized: bool
    advice_request_detected: bool
    performance_claim_risk: bool
    decision: ComplianceDecision
    flags: list[str] = Field(default_factory=list)
    safe_handling: str = Field(min_length=1)
    execution_id: str = Field(pattern=EXECUTION_ID_PATTERN)

    @model_validator(mode="after")
    def decision_matches_flags(self) -> ComplianceResult:
        if self.agent is not AgentName.COMPLIANCE:
            raise ValueError("compliance result agent must be compliance")
        if self.pii_detected != bool(self.pii_categories):
            raise ValueError("pii_detected must match pii_categories")
        proceeding = {
            ComplianceDecision.ALLOW,
            ComplianceDecision.REDACT_AND_ALLOW,
        }
        if self.decision in proceeding and self.advice_request_detected:
            raise ValueError("an advice request cannot be allowed")
        if self.decision in proceeding and self.performance_claim_risk:
            raise ValueError("a performance-claim request cannot be allowed")
        if self.pii_detected and not self.sanitized and self.decision in proceeding:
            raise ValueError("unsanitized PII cannot be allowed")
        if self.decision is ComplianceDecision.ALLOW and self.pii_detected:
            raise ValueError("redacted PII must use redact_and_allow")
        if self.decision is ComplianceDecision.REDACT_AND_ALLOW and not self.sanitized:
            raise ValueError("redact_and_allow requires sanitized=true")
        return self


class CustomerReply(ContractModel):
    text: str = Field(min_length=1)
    sentence_count: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def sentence_count_matches_text(self) -> CustomerReply:
        counted = count_sentences(self.text)
        if counted < 1 or counted > 3:
            raise ValueError("customer reply must be 1 to 3 sentences")
        if counted != self.sentence_count:
            raise ValueError("sentence_count does not match the reply text")
        return self


class RoutingNote(ContractModel):
    team: str = Field(min_length=1)
    priority: Priority
    reason: str = Field(min_length=1)
    pattern_signal: PatternSignal
    matching_count: int = Field(ge=0)
    analysis_window: AnalysisWindow
    facts_coverage: Coverage
    citation_refs: list[str] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)
    disagreement: str | None = None
    limitations: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)


class OrchestratorResult(ContractModel):
    """Merged draft. Agent payloads stay attached so disagreement is retained."""

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    reply: CustomerReply
    routing_note: RoutingNote
    facts: FactsResult
    pattern: PatternResult
    compliance: ComplianceResult
    disagreements: list[str] = Field(default_factory=list)


class ReviewerFinding(ContractModel):
    code: ReviewerFindingCode
    message: str = Field(min_length=1)
    repairable: bool


class ReviewerResult(ContractModel):
    decision: ReviewerDecision
    findings: list[ReviewerFinding] = Field(default_factory=list)
    rework_attempt: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def fail_has_findings(self) -> ReviewerResult:
        if self.decision is ReviewerDecision.FAIL and not self.findings:
            raise ValueError("a failed review requires at least one finding")
        if self.decision is ReviewerDecision.PASS and self.findings:
            raise ValueError("a passing review cannot carry findings")
        return self


class SanitizedRequest(ContractModel):
    """Working request. ``text`` must already be redacted.

    ``ComplianceSession.inspect`` is the writer of this model. The model
    itself does not detect PII.
    """

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    text: str = Field(min_length=1)
    input_hash: str = Field(pattern=SHA256_PATTERN)
    received_at: datetime
    pii_redacted: bool

    @field_validator("received_at")
    @classmethod
    def received_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value


class AgentExecution(ContractModel):
    execution_id: str = Field(pattern=EXECUTION_ID_PATTERN)
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    agent: AgentName
    status: AgentExecutionStatus
    started_at: datetime
    ended_at: datetime | None = None
    input_hash: str = Field(pattern=SHA256_PATTERN)
    round_index: int = Field(ge=0, le=5)
    rework_index: int = Field(ge=0, le=1)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def end_is_not_before_start(self) -> AgentExecution:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at is before started_at")
        return self


class McpActionRequest(ContractModel):
    """A Docs append or Gmail draft. Construction requires a matching approval."""

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    kind: McpActionKind
    content_hash: str = Field(pattern=SHA256_PATTERN)
    approval: ApprovalRecord
    idempotency_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def approval_gates_the_action(self) -> McpActionRequest:
        if self.approval.case_id != self.case_id:
            raise ValueError("approval case_id does not match the action")
        if not approval_matches(self.approval, self.content_hash):
            raise ValueError("MCP action requires approval of this exact content")
        expected = mcp_idempotency_key(self.case_id, self.content_hash, self.kind)
        if self.idempotency_key != expected:
            raise ValueError("idempotency key does not match the case, content, and action")
        return self


class McpActionResult(ContractModel):
    kind: McpActionKind
    status: McpActionStatus
    idempotency_key: str = Field(min_length=1)
    external_id: str | None = None
    error: str | None = None


class WorkflowRun(ContractModel):
    """One pass through the support-desk state machine."""

    run_id: str = Field(pattern=RUN_ID_PATTERN)
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    state: WorkflowState
    rework_count: int = Field(default=0, ge=0, le=1)
    refinement_round: int = Field(default=0, ge=0, le=5)
    content_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    approval: ApprovalRecord | None = None
    executions: list[AgentExecution] = Field(default_factory=list)

    @model_validator(mode="after")
    def approval_hash_agrees(self) -> WorkflowRun:
        decided = {
            WorkflowState.APPROVED,
            WorkflowState.REJECTED,
            WorkflowState.MCP_ACTIONS,
            WorkflowState.PARTIAL_FAILURE,
            WorkflowState.COMPLETED,
        }
        if self.state in decided and self.approval is None:
            raise ValueError(f"{self.state.value} requires an approval record")
        if self.approval is None:
            return self
        if self.state not in decided:
            raise ValueError("an approval record is stored only after a decision")
        if self.approval.case_id != self.case_id:
            raise ValueError("approval case_id does not match the run")
        if self.content_hash is None or self.approval.content_hash != self.content_hash:
            raise ValueError("approval content hash does not match the run")
        expected = (
            ApprovalDecision.REJECT
            if self.state is WorkflowState.REJECTED
            else ApprovalDecision.APPROVE
        )
        if self.approval.decision is not expected:
            raise ValueError(f"{self.state.value} requires decision={expected.value}")
        return self
