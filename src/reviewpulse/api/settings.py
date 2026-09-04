"""Redacted settings DTO and allowlisted PATCH."""

from __future__ import annotations

from reviewpulse.api.dto import SettingsDTO, SettingsPatch
from reviewpulse.config import (
    WEEKDAYS,
    Settings,
    load_settings,
    normalize_document_id,
    patch_settings_file,
    settings_file_path,
    validate_email,
)
from reviewpulse.llm.factory import api_key, llm_configured


def _hint(value: str) -> str | None:
    if len(value) < 8:
        return None
    return f"••••{value[-4:]}"


def settings_dto(settings: Settings) -> SettingsDTO:
    groq_key = api_key("groq")
    gemini_key = api_key("gemini")
    token = (settings.mcp.auth_token or "").strip()
    return SettingsDTO(
        package_id=settings.package_id,
        window_weeks=settings.default_window_weeks,
        min_words=settings.min_words,
        english_only=settings.english_only,
        operator_initials=settings.console.operator_initials,
        recipient_alias=settings.pulse.recipient_alias,
        document_id=settings.mcp.gdocs.document_id,
        mcp_url=settings.mcp.url or settings.mcp.gdocs.url,
        mcp_configured=settings.mcp.configured,
        mcp_token_configured=bool(token) and "<" not in token and "MCP_AUTH" not in token,
        groq_configured=llm_configured("groq"),
        gemini_configured=llm_configured("gemini"),
        groq_model=settings.llm.model,
        gemini_model=settings.pulse.llm.model,
        groq_hint=_hint(groq_key) if groq_key else None,
        gemini_hint=_hint(gemini_key) if gemini_key else None,
        embedding_model=settings.clustering.embedding_model,
        linkage=settings.clustering.linkage,
        store="SQLite",
        schedule_weekday=settings.schedule.weekday,
        schedule_hour=settings.schedule.hour,
        schedule_minute=settings.schedule.minute,
        schedule_timezone=settings.schedule.timezone,
        schedule_window_weeks=settings.schedule.window_weeks,
        schedule_send_email=settings.schedule.send_email,
        schedule_skip_if_no_new=settings.schedule.skip_if_no_new,
        api_host=settings.console.api_host,
        api_port=settings.console.api_port,
    )


def apply_settings_patch(patch: SettingsPatch) -> Settings:
    updates: dict[tuple[str, str], object] = {}
    if patch.window_weeks is not None:
        if patch.window_weeks < 1 or patch.window_weeks > 52:
            raise ValueError("window_weeks must be 1–52")
        updates[("app", "default_window_weeks")] = patch.window_weeks
    if patch.min_words is not None:
        if patch.min_words < 1:
            raise ValueError("min_words must be ≥ 1")
        updates[("ingest", "min_words")] = patch.min_words
    if patch.english_only is not None:
        updates[("ingest", "english_only")] = patch.english_only
    if patch.operator_initials is not None:
        initials = patch.operator_initials.strip()[:4].upper()
        if not initials:
            raise ValueError("operator_initials cannot be empty")
        updates[("console", "operator_initials")] = initials
    if patch.recipient_alias is not None:
        updates[("gmail", "recipient_alias")] = validate_email(patch.recipient_alias)
    if patch.document_id is not None:
        updates[("mcp.gdocs", "document_id")] = normalize_document_id(patch.document_id)
    if patch.schedule_weekday is not None:
        weekday = patch.schedule_weekday.strip().lower()
        if weekday not in WEEKDAYS:
            raise ValueError(f"schedule_weekday must be one of {', '.join(WEEKDAYS)}")
        updates[("schedule", "weekday")] = weekday
    if patch.schedule_hour is not None:
        if patch.schedule_hour < 0 or patch.schedule_hour > 23:
            raise ValueError("schedule_hour must be 0–23")
        updates[("schedule", "hour")] = patch.schedule_hour
    if patch.schedule_minute is not None:
        if patch.schedule_minute < 0 or patch.schedule_minute > 59:
            raise ValueError("schedule_minute must be 0–59")
        updates[("schedule", "minute")] = patch.schedule_minute
    if patch.schedule_timezone is not None:
        updates[("schedule", "timezone")] = patch.schedule_timezone.strip()
    if patch.schedule_window_weeks is not None:
        if patch.schedule_window_weeks < 1 or patch.schedule_window_weeks > 52:
            raise ValueError("schedule_window_weeks must be 1–52")
        updates[("schedule", "window_weeks")] = patch.schedule_window_weeks
    if patch.schedule_send_email is not None:
        updates[("schedule", "send_email")] = patch.schedule_send_email
    if patch.schedule_skip_if_no_new is not None:
        updates[("schedule", "skip_if_no_new")] = patch.schedule_skip_if_no_new
    if updates:
        patch_settings_file(updates)
    return load_settings(settings_file_path())
