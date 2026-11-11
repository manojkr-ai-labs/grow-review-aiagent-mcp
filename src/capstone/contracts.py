"""Record shapes for the capstone log, ledger, signals, and weekly package.

These models check field names and a few stored values. They do not open
SQLite, classify a question, or call a model.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from capstone.identity import question_key

_CASE_ID = re.compile(r"^case_[0-9a-f]{32}$")
_WEEK_ID = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HTTPS = re.compile(r"^https://\S+$")

PACKAGE_FILES = ("note.md", "explainer.json", "support_signals.json")

FactsCoverage = Literal["covered", "not_covered"]


class CapstoneModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _case_ids(values: list[str]) -> list[str]:
    for case_id in values:
        if _CASE_ID.fullmatch(case_id) is None:
            raise ValueError("case_id must be case_ plus 32 hex characters")
    return values


class QuestionLogRow(CapstoneModel):
    """One sanitized question. There is no raw-message field."""

    case_id: str = Field(pattern=_CASE_ID.pattern)
    week_id: str = Field(pattern=_WEEK_ID.pattern)
    question_key: str
    sanitized_text: str
    facts_coverage: FactsCoverage
    searched_urls: list[str] = Field(default_factory=list)
    theme_id: str | None = None
    created_at: datetime

    @field_validator("theme_id")
    @classmethod
    def theme_id_is_null_or_set(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("theme_id is null when no theme matched")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def key_matches_sanitized_text(self) -> QuestionLogRow:
        if self.question_key != question_key(self.sanitized_text):
            raise ValueError("question_key must come from identity.question_key")
        return self


class LedgerRow(CapstoneModel):
    """A not-covered question copied from the log in the same transaction."""

    case_id: str = Field(pattern=_CASE_ID.pattern)
    week_id: str = Field(pattern=_WEEK_ID.pattern)
    sanitized_text: str
    searched_urls: list[str] = Field(default_factory=list)
    theme_id: str | None = None

    @field_validator("theme_id")
    @classmethod
    def theme_id_is_null_or_set(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("theme_id is null when no theme matched")
        return value


class PatternWindow(CapstoneModel):
    """Analysis window copied from a stored pattern result. Dates stay as stored."""

    start: str | None = None
    end: str | None = None


class SupportSignal(CapstoneModel):
    """A five-times queue signal. Review volume cannot use another evidence type.

    ``count`` is the number of log rows. Pattern signal, pattern count, and
    analysis window are copied only when every row in the group shares them.
    """

    week_id: str = Field(pattern=_WEEK_ID.pattern)
    question_key: str = Field(min_length=1)
    count: int = Field(ge=5)
    case_ids: list[str]
    theme_id: str | None = None
    evidence_type: Literal["queue"]
    pattern_signal: str | None = None
    pattern_count: int | None = None
    analysis_window: PatternWindow | None = None

    @field_validator("case_ids")
    @classmethod
    def case_ids_are_ids(cls, value: list[str]) -> list[str]:
        return _case_ids(value)

    @field_validator("theme_id")
    @classmethod
    def theme_id_is_null_or_set(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("theme_id is null when no theme matched")
        return value

    @model_validator(mode="after")
    def group_matches_the_log(self) -> SupportSignal:
        if self.question_key != question_key(self.question_key):
            raise ValueError("question_key must already be an identity key")
        if len(self.case_ids) != self.count:
            raise ValueError("count is the number of case ids")
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids are unique")
        if self.case_ids != sorted(self.case_ids):
            raise ValueError("case_ids are sorted")
        return self


class ExplainerBullet(CapstoneModel):
    """One factual link or the ledger bullet. last_checked is copied, never filled in."""

    text: str = Field(min_length=1)
    url: str | None = None
    case_ids: list[str] = Field(default_factory=list)
    last_checked: str | None = None

    @field_validator("url")
    @classmethod
    def url_is_https(cls, value: str | None) -> str | None:
        if value is not None and _HTTPS.fullmatch(value) is None:
            raise ValueError("url must be an https URL")
        return value

    @field_validator("case_ids")
    @classmethod
    def case_ids_are_ids(cls, value: list[str]) -> list[str]:
        return _case_ids(value)


class Explainer(CapstoneModel):
    """At most six bullets and at most five official links."""

    week_id: str = Field(pattern=_WEEK_ID.pattern)
    fee_theme: str | None = None
    bullets: list[ExplainerBullet]

    @model_validator(mode="after")
    def within_bullet_and_link_caps(self) -> Explainer:
        if len(self.bullets) > 6:
            raise ValueError("an explainer has at most six bullets")
        link_count = sum(1 for bullet in self.bullets if bullet.url is not None)
        if link_count > 5:
            raise ValueError("an explainer has at most five official links")
        return self


class WeeklyPackageManifest(CapstoneModel):
    """Hash and file names for one weekly package. The note body is not stored here."""

    package_hash: str = Field(pattern=_SHA256.pattern)
    fee_theme: str | None = None
    files: list[str]

    @model_validator(mode="after")
    def files_are_the_package(self) -> WeeklyPackageManifest:
        if tuple(self.files) != PACKAGE_FILES:
            raise ValueError(
                "files must be note.md, explainer.json, support_signals.json in that order"
            )
        return self
