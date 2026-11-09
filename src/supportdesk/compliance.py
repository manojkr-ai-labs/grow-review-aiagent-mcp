"""Compliance gate: redact, then classify advice and performance risk.

The raw message is an argument only. Session state stores two flags and a
session id. It does not store the message.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from supportdesk.advice import (
    continues_advice,
    continues_performance,
    requests_advice,
    requests_performance,
)
from supportdesk.contracts import ComplianceResult, SanitizedRequest
from supportdesk.enums import ComplianceDecision, ComplianceStatus, PiiCategory
from supportdesk.ids import SESSION_ID_PATTERN, is_sha256, new_execution_id, new_session_id, sha256_text
from supportdesk.privacy import redact_pii

_ALLOW = "No compliance block. Process the message."
_REDACT = "Process only the redacted message."
_REFUSE_ADVICE = (
    "Refuse the investment recommendation. "
    "A neutral reply may point to official product information."
)
_REFUSE_PERFORMANCE = "Refuse return predictions, guarantees, and performance claims."
_REFUSE_BOTH = f"{_REFUSE_ADVICE} {_REFUSE_PERFORMANCE}"
_BLOCK_PII = "Block the case. Sanitization could not be guaranteed."
_BLOCK_EMPTY = "Block the case. The message is empty."


class ComplianceInspection(BaseModel):
    """Safe output of one compliance check. ``request`` is absent when blocked."""

    model_config = ConfigDict(extra="forbid")

    result: ComplianceResult
    redacted_text: str = ""
    input_hash: str
    request: SanitizedRequest | None = None

    def model_post_init(self, _context: object) -> None:
        if not is_sha256(self.input_hash):
            raise ValueError("input_hash must be sha256 hex")


class ComplianceSession:
    """Remembers that this conversation already asked for advice or a return."""

    def __init__(
        self,
        session_id: str | None = None,
        *,
        advice_requested: bool = False,
        performance_requested: bool = False,
    ) -> None:
        self.session_id = session_id or new_session_id()
        if not _session_ok(self.session_id):
            raise ValueError("session_id is not a support-desk session id")
        self.advice_requested = advice_requested
        self.performance_requested = performance_requested

    def export_state(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "advice_requested": self.advice_requested,
            "performance_requested": self.performance_requested,
        }

    @classmethod
    def from_state(cls, state: dict[str, object]) -> ComplianceSession:
        session_id = state.get("session_id")
        if not isinstance(session_id, str):
            raise ValueError("session state requires a session_id")
        return cls(
            session_id,
            advice_requested=bool(state.get("advice_requested")),
            performance_requested=bool(state.get("performance_requested")),
        )

    def __repr__(self) -> str:
        return (
            "ComplianceSession("
            f"session_id={self.session_id!r}, "
            f"advice_requested={self.advice_requested}, "
            f"performance_requested={self.performance_requested})"
        )

    def inspect(
        self,
        message: str,
        *,
        case_id: str,
        received_at: datetime | None = None,
        execution_id: str | None = None,
    ) -> ComplianceInspection:
        """Classify ``message`` and update session flags. Does not retain it."""
        when = received_at or datetime.now(timezone.utc)
        execution = execution_id or new_execution_id()
        if not message or not message.strip():
            return _inspection(
                case_id=case_id,
                session_id=self.session_id,
                execution_id=execution,
                received_at=when,
                redacted_text="",
                categories=(),
                sanitized=False,
                advice=False,
                performance=False,
                decision=ComplianceDecision.BLOCK,
                handling=_BLOCK_EMPTY,
                extra_flags=[],
            )

        prior_advice = self.advice_requested
        prior_performance = self.performance_requested
        own_advice = requests_advice(message)
        own_performance = requests_performance(message)
        advice = own_advice or (prior_advice and continues_advice(message))
        performance = own_performance or (prior_performance and continues_performance(message))
        if advice:
            self.advice_requested = True
        if performance:
            self.performance_requested = True

        redaction = redact_pii(message)
        flags: list[str] = []
        if advice:
            flags.append("advice")
        elif prior_advice:
            flags.append("session_advice_context")
        if performance:
            flags.append("performance")
        elif prior_performance:
            flags.append("session_performance_context")

        if not redaction.sanitized:
            decision = ComplianceDecision.BLOCK
            handling = _BLOCK_PII
            released = ""
        elif advice or performance:
            decision = ComplianceDecision.REFUSE
            handling = _handling(advice, performance)
            released = redaction.text
        elif redaction.categories:
            decision = ComplianceDecision.REDACT_AND_ALLOW
            handling = _REDACT
            released = redaction.text
        else:
            decision = ComplianceDecision.ALLOW
            handling = _ALLOW
            released = redaction.text

        return _inspection(
            case_id=case_id,
            session_id=self.session_id,
            execution_id=execution,
            received_at=when,
            redacted_text=released,
            categories=redaction.categories,
            sanitized=redaction.sanitized and decision is not ComplianceDecision.BLOCK,
            advice=advice,
            performance=performance,
            decision=decision,
            handling=handling,
            extra_flags=flags,
        )


def _handling(advice: bool, performance: bool) -> str:
    if advice and performance:
        return _REFUSE_BOTH
    if advice:
        return _REFUSE_ADVICE
    return _REFUSE_PERFORMANCE


def _inspection(
    *,
    case_id: str,
    session_id: str,
    execution_id: str,
    received_at: datetime,
    redacted_text: str,
    categories: tuple[PiiCategory, ...],
    sanitized: bool,
    advice: bool,
    performance: bool,
    decision: ComplianceDecision,
    handling: str,
    extra_flags: list[str],
) -> ComplianceInspection:
    digest = sha256_text(redacted_text)
    request = None
    if redacted_text:
        request = SanitizedRequest(
            case_id=case_id,
            session_id=session_id,
            text=redacted_text,
            input_hash=digest,
            received_at=received_at,
            pii_redacted=bool(categories),
        )
    result = ComplianceResult(
        status=ComplianceStatus.SUCCESS,
        pii_detected=bool(categories),
        pii_categories=list(categories),
        sanitized=sanitized,
        advice_request_detected=advice,
        performance_claim_risk=performance,
        decision=decision,
        flags=extra_flags,
        safe_handling=handling,
        execution_id=execution_id,
    )
    return ComplianceInspection(
        result=result,
        redacted_text=redacted_text,
        input_hash=digest,
        request=request,
    )


def _session_ok(session_id: str) -> bool:
    return re.fullmatch(SESSION_ID_PATTERN, session_id) is not None
