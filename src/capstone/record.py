"""Record one reviewed desk case into the question log.

Call this only after ``review_case`` or ``decide`` returns. It does not
orchestrate, and it does not publish.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

from capstone.contracts import QuestionLogRow
from capstone.identity import question_key
from capstone.log import LogStore
from supportdesk.contracts import PatternResult, SanitizedRequest
from supportdesk.decisions import DeskCase, open_case
from supportdesk.enums import ComplianceDecision, PatternSignal, PatternStatus
from supportdesk.privacy import contains_pii
from supportdesk.reviewer import ReviewedCase

KOLKATA = ZoneInfo("Asia/Kolkata")


class RecordResult(BaseModel):
    """Whether the case was written. A blocked redaction records nothing."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    case_id: str | None = None
    week_id: str | None = None

    @model_validator(mode="after")
    def ids_match_the_outcome(self) -> RecordResult:
        if self.recorded and (self.case_id is None or self.week_id is None):
            raise ValueError("a recorded case has a case id and week id")
        if not self.recorded and (self.case_id is not None or self.week_id is not None):
            raise ValueError("a skipped case has no stored id")
        return self


def record_case(
    case: DeskCase | ReviewedCase,
    request: SanitizedRequest | None,
    *,
    store: LogStore,
    clock: datetime | None = None,
) -> RecordResult:
    """Append the log row, the ledger when the question is not covered, and the case blob."""
    if _redaction_blocked(case, request):
        return RecordResult(recorded=False)
    assert request is not None
    assert case.result is not None
    if request.case_id != case.run.case_id or case.result.case_id != case.run.case_id:
        raise ValueError("case_id does not match the sanitized request")

    when = _aware_clock(clock)
    week_id = week_id_for(when)
    result = case.result
    row = QuestionLogRow(
        case_id=request.case_id,
        week_id=week_id,
        question_key=question_key(request.text),
        sanitized_text=request.text,
        facts_coverage=result.facts.coverage.value,
        searched_urls=list(result.facts.searched_sources),
        theme_id=theme_id_from_pattern(result.pattern),
        created_at=when,
    )
    desk = case if isinstance(case, DeskCase) else open_case(case)
    store.append(row)
    store.save_case(desk.model_dump(mode="json"), updated_at=when)
    return RecordResult(recorded=True, case_id=row.case_id, week_id=week_id)


def week_id_for(clock: datetime) -> str:
    """ISO week of ``clock`` in Asia/Kolkata, formatted ``YYYY-Www``."""
    local = _aware_clock(clock).astimezone(KOLKATA)
    iso = local.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def theme_id_from_pattern(pattern: PatternResult) -> str | None:
    """Copy a theme id only when the pattern match is real."""
    if (
        pattern.signal is PatternSignal.INSUFFICIENT_DATA
        or pattern.status is PatternStatus.INSUFFICIENT_DATA
    ):
        return None
    for item in pattern.evidence:
        if item.theme_id and item.theme_id.strip():
            return item.theme_id.strip()
    if not pattern.matched_themes:
        return None
    token = pattern.matched_themes[0].split(":", 1)[0].strip()
    return token or None


def _redaction_blocked(
    case: DeskCase | ReviewedCase,
    request: SanitizedRequest | None,
) -> bool:
    if request is None or contains_pii(request.text):
        return True
    result = case.result
    if result is None:
        return True
    compliance = result.compliance
    return (
        compliance.decision is ComplianceDecision.BLOCK and not compliance.sanitized
    )


def _aware_clock(clock: datetime | None) -> datetime:
    when = clock if clock is not None else datetime.now(KOLKATA)
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("clock must be timezone-aware")
    return when
