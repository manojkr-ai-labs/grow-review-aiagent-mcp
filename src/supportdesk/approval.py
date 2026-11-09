"""Content hash and approval binding.

The human approval flow lives in ``supportdesk.decisions``. This module
defines the record and the rule that approval applies to one exact version.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from supportdesk.enums import ApprovalDecision, McpActionKind
from supportdesk.ids import (
    CASE_ID_PATTERN,
    SHA256_PATTERN,
    is_case_id,
    is_sha256,
    sha256_text,
)

_APPROVER_REF = r"^[A-Za-z0-9_.:-]{1,64}$"


class ApprovalRecord(BaseModel):
    """Explicit approve or reject decision for one content hash."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    decision: ApprovalDecision
    content_hash: str = Field(pattern=SHA256_PATTERN)
    decided_at: datetime
    approver_ref: str = Field(pattern=_APPROVER_REF)

    @field_validator("decided_at")
    @classmethod
    def decided_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        return value


def content_hash(*, reply: str, routing_note: str) -> str:
    """Hash the exact customer reply and routing note.

    Key order is fixed. A change to either string changes the digest.
    """
    payload = json.dumps(
        {"reply": reply, "routing_note": routing_note},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(payload)


def approval_matches(approval: ApprovalRecord | None, digest: str) -> bool:
    """True only for an approve decision bound to this digest."""
    if approval is None or not is_sha256(digest):
        return False
    return (
        approval.decision is ApprovalDecision.APPROVE
        and approval.content_hash == digest
    )


def mcp_idempotency_key(case_id: str, digest: str, kind: McpActionKind) -> str:
    """Stable action key. It contains ids and a hash prefix, not message text."""
    if not is_case_id(case_id):
        raise ValueError("case_id is not a support-desk case id")
    if not is_sha256(digest):
        raise ValueError("content hash must be sha256 hex")
    return f"desk:{case_id}:{digest[:16]}:{kind.value}"
