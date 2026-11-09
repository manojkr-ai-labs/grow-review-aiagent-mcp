"""Status and workflow enums for the support desk."""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    RECEIVED = "received"
    SANITIZING = "sanitizing"
    AGENTS_RUNNING = "agents_running"
    AGENT_ERROR = "agent_error"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ORCHESTRATED = "orchestrated"
    DRAFTED = "drafted"
    REVIEWING = "reviewing"
    REWORK_ONCE = "rework_once"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    MCP_ACTIONS = "mcp_actions"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"


class AgentName(str, Enum):
    FACTS = "facts"
    PATTERN = "pattern"
    COMPLIANCE = "compliance"


class AgentExecutionStatus(str, Enum):
    SUCCESS = "success"
    NOT_COVERED = "not_covered"
    BLOCKED = "blocked"
    ERROR = "error"


class Coverage(str, Enum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"


class FactsStatus(str, Enum):
    SUPPORTED = "supported"
    NOT_COVERED = "not_covered"
    ERROR = "error"


class PatternSignal(str, Enum):
    RECURRING = "recurring"
    RISING = "rising"
    ONE_OFF = "one_off"
    INSUFFICIENT_DATA = "insufficient_data"


class PatternStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    INSUFFICIENT_DATA = "insufficient_data"


class PiiCategory(str, Enum):
    PAN = "pan"
    AADHAAR = "aadhaar"
    ACCOUNT = "account"
    PHONE = "phone"
    EMAIL = "email"
    OTP = "otp"


class ComplianceStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ComplianceDecision(str, Enum):
    ALLOW = "allow"
    REDACT_AND_ALLOW = "redact_and_allow"
    REFUSE = "refuse"
    BLOCK = "block"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReviewerDecision(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ReviewerFindingCode(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_CITATION = "missing_citation"
    CITATION_NOT_RETRIEVED = "citation_not_retrieved"
    CITATION_DOMAIN = "citation_domain"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    INVESTMENT_ADVICE = "investment_advice"
    PERFORMANCE_CLAIM = "performance_claim"
    PII = "pii"
    HIDDEN_DISAGREEMENT = "hidden_disagreement"
    SENTENCE_LIMIT = "sentence_limit"
    ILLEGAL_TRANSITION = "illegal_transition"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class McpActionKind(str, Enum):
    """External writes Project 3 may request. Email send is intentionally absent."""

    DOCS_APPEND = "docs_append"
    GMAIL_DRAFT = "gmail_draft"


class McpActionStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED_DUPLICATE = "skipped_duplicate"
