"""Pydantic response/request models for the console API. No secrets, no author."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WindowDTO(BaseModel):
    weeks: int
    requested_start: str | None = None
    requested_end: str | None = None
    actual_start: str | None = None
    actual_end: str | None = None
    actual_weeks: float | None = None


class CountsDTO(BaseModel):
    window_reviews: int = 0
    clustered: int = 0
    dropped_low_signal: int = 0
    themes: int = 0
    negative: int = 0


class ThemeDTO(BaseModel):
    theme_id: str
    rank: int
    label: str
    summary: str = ""
    line: str | None = None
    size: int
    mean_rating: float | None = None
    neg_share: float = 0.0
    priority: float = 0.0
    trend: float | None = None
    emerging: bool = False
    in_note: bool = False
    keywords: list[str] = Field(default_factory=list)
    top_terms: list[str] = Field(default_factory=list)
    label_source: str | None = None


class QuoteDTO(BaseModel):
    review_id: str
    theme_id: str
    text: str
    rating: int | None = None
    words: int | None = None


class ActionDTO(BaseModel):
    text: str
    theme_ids: list[str] = Field(default_factory=list)


class GateDTO(BaseModel):
    gate: str
    passed: bool
    detail: str = ""


class StageDTO(BaseModel):
    id: str
    label: str
    status: str
    detail: str = ""


class PublishSummaryDTO(BaseModel):
    mode: str = "none"
    published: bool = False
    idempotency_key: str | None = None
    doc_id: str | None = None
    doc_url: str | None = None
    draft_id: str | None = None
    message_id: str | None = None
    recipient: str | None = None
    skipped_append: bool = False
    skipped_send: bool = False
    subject: str | None = None


class McpStatusDTO(BaseModel):
    ok: bool
    label: str
    detail: str | None = None
    url: str | None = None
    document_id: str | None = None
    cached: bool = False


class StatusDTO(BaseModel):
    package_id: str
    operator_initials: str
    iso_week: str | None = None
    last_run_id: str | None = None
    last_run_at: str | None = None
    window: WindowDTO | None = None
    mcp: McpStatusDTO
    lock_held: bool = False
    store_count: int = 0
    pipeline: "JobDTO | None" = None


class PulseDTO(BaseModel):
    run_id: str
    iso_week: str | None = None
    window: WindowDTO
    counts: CountsDTO
    mean_rating: float | None = None
    word_count: int = 0
    max_words: int = 250
    compose_source: str | None = None
    compose_provider: str | None = None
    compose_model: str | None = None
    top_themes: list[ThemeDTO] = Field(default_factory=list)
    quotes: list[QuoteDTO] = Field(default_factory=list)
    actions: list[ActionDTO] = Field(default_factory=list)
    gates: list[GateDTO] = Field(default_factory=list)
    gates_passed: int = 0
    gates_total: int = 7
    all_gates_passed: bool = False
    rejected: bool = False
    publish: PublishSummaryDTO
    stages: list[StageDTO] = Field(default_factory=list)
    note_available: bool = False
    clustering: dict = Field(default_factory=dict)


class ThemeDetailDTO(BaseModel):
    run_id: str
    theme: ThemeDTO
    rating_histogram: dict[int, int] = Field(default_factory=dict)
    member_count: int = 0
    in_note: bool = False


class ReviewDTO(BaseModel):
    review_id: str
    source: str
    rating: int | None = None
    text_clean: str
    date: str
    lang: str | None = None
    scrub_flags: list[str] = Field(default_factory=list)
    theme_id: str | None = None
    theme_label: str | None = None


class ReviewListDTO(BaseModel):
    items: list[ReviewDTO]
    next_cursor: str | None = None
    total: int
    window_reviews: int = 0
    clustered: int = 0
    dropped_low_signal: int = 0
    scrub_flag_counts: dict[str, int] = Field(default_factory=dict)


class RunSummaryDTO(BaseModel):
    run_id: str
    iso_week: str | None = None
    timestamp: str | None = None
    window: WindowDTO | None = None
    counts: CountsDTO
    word_count: int | None = None
    theme_count: int = 0
    gates_passed: bool = False
    rejected: bool = False
    publish_mode: str = "none"
    artifacts: list[str] = Field(default_factory=list)
    current: bool = False


class RunDetailDTO(BaseModel):
    summary: RunSummaryDTO
    note_preview: str | None = None
    rejected: bool = False
    manifest_checks: dict = Field(default_factory=dict)
    publish: PublishSummaryDTO


class SettingsDTO(BaseModel):
    package_id: str
    window_weeks: int
    min_words: int
    english_only: bool
    operator_initials: str
    recipient_alias: str
    document_id: str
    mcp_url: str
    mcp_configured: bool
    mcp_token_configured: bool
    groq_configured: bool
    gemini_configured: bool
    groq_model: str
    gemini_model: str
    groq_hint: str | None = None
    gemini_hint: str | None = None
    embedding_model: str
    linkage: str
    store: str = "SQLite"
    schedule_weekday: str
    schedule_hour: int
    schedule_minute: int
    schedule_timezone: str
    schedule_window_weeks: int
    schedule_send_email: bool
    schedule_skip_if_no_new: bool
    api_host: str
    api_port: int


class SettingsPatch(BaseModel):
    window_weeks: int | None = None
    min_words: int | None = None
    english_only: bool | None = None
    operator_initials: str | None = None
    recipient_alias: str | None = None
    document_id: str | None = None
    schedule_weekday: str | None = None
    schedule_hour: int | None = None
    schedule_minute: int | None = None
    schedule_timezone: str | None = None
    schedule_window_weeks: int | None = None
    schedule_send_email: bool | None = None
    schedule_skip_if_no_new: bool | None = None


class PipelineRunRequest(BaseModel):
    window_weeks: int | None = None
    dry_run: bool = True
    send: bool = False


class JobDTO(BaseModel):
    job_id: str
    status: str
    dry_run: bool
    send: bool
    window_weeks: int
    error: str | None = None
    run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    log_lines: int = 0


class PublishActionRequest(BaseModel):
    run_id: str | None = None
    confirm: bool = False


class PublishActionResult(BaseModel):
    ok: bool
    skipped: bool = False
    detail: str
    publish: PublishSummaryDTO | None = None
