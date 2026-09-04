"""Load application settings from TOML."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.toml"
EXAMPLE_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.example.toml"
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "config" / "taxonomy.toml"
EXAMPLE_TAXONOMY_PATH = PROJECT_ROOT / "config" / "taxonomy.example.toml"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "reviews.db"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def data_dir() -> Path:
    """SQLite, embedding cache, publish-state, lock, raw CSVs.

    Override with `REVIEWPULSE_DATA_DIR` (Railway volume, e.g. `/persistent/data`).
    """
    return _env_path("REVIEWPULSE_DATA_DIR") or (PROJECT_ROOT / "data")


def runs_dir() -> Path:
    """Per-run artifacts (`manifest.json`, `note.md`, …).

    Override with `REVIEWPULSE_RUNS_DIR` (e.g. `/persistent/runs`).
    """
    return _env_path("REVIEWPULSE_RUNS_DIR") or (PROJECT_ROOT / "runs")


def default_db_path() -> Path:
    return data_dir() / "reviews.db"


def default_cache_dir() -> Path:
    return data_dir() / "cache"


def default_lock_path() -> Path:
    return data_dir() / "schedule.lock"


def default_state_path() -> Path:
    return data_dir() / "publish-state.json"


def default_raw_dir() -> Path:
    return data_dir() / "raw"


@dataclass
class ColumnMapping:
    text: str = "Review Text"
    title: str = "Review Title"
    rating: str = "Star Rating"
    date: str = "Review Date"
    external_id: str = "Review ID"
    author: str = "Reviewer Name"


@dataclass
class LLMSettings:
    """A chat model and the free-tier ceilings the client has to stay under.

    The defaults are Phase 2's: Groq, `openai/gpt-oss-120b`. Phase 3 composes on
    Gemini instead and gets its own block (`gemini_defaults()` below), so the
    two stages can be repointed, rate-limited and rationed independently.

    The four limits are the published per-model quotas; `tokens_per_request` is
    our own estimate of what one call costs and is what turns the token quotas
    into a call rate (see `llm/rate_limit.py`). `samples_per_theme` is the main
    lever on that cost — the samples are most of every labeling prompt.

    `reasoning_effort` and `samples_per_theme` are Groq-labeling knobs and are
    ignored on the composition path, which sends no samples and calls a model
    that has no reasoning parameter.
    """

    provider: str = "groq"
    model: str = "openai/gpt-oss-120b"
    reasoning_effort: str = "low"
    samples_per_theme: int = 6
    requests_per_minute: int = 30
    requests_per_day: int = 1_000
    tokens_per_minute: int = 8_000
    tokens_per_day: int = 200_000
    tokens_per_request: int = 2_500


def gemini_defaults() -> LLMSettings:
    """Phase 3 composition defaults: Google's Gemini free tier.

    Deliberately the conservative end of the published numbers, which differ by
    model, region and account age. Erring low only ever makes the pacer wait,
    and composition spends at most two calls a run — one draft plus the single
    bounded retry — so it never approaches any of these ceilings anyway.
    """
    return LLMSettings(
        provider="gemini",
        model="gemini-3.6-flash",
        requests_per_minute=10,
        requests_per_day=250,
        tokens_per_minute=250_000,
        tokens_per_day=1_000_000,
        tokens_per_request=2_500,
    )


@dataclass
class ClusteringSettings:
    """Phase 2 knobs. Defaults encode the findings in implementation-plan.md §4.2."""

    mode: str = "embedding"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    linkage: str = "ward"
    random_seed: int = 42
    max_cluster_share: float = 0.60
    signal_min_words: int = 20
    signal_max_rating: int = 3
    rank_by: str = "priority"
    trend_split_weeks: int = 4
    emerging_trend_ratio: float = 1.5
    label_llm: bool = True
    cache_dir: Path = field(default_factory=default_cache_dir)


@dataclass
class PulseSettings:
    """Phase 3 knobs for quote selection, composition and the gates.

    `quote_max_words` is the tight one: the note has a 250-word ceiling and
    three quotes are the only part of it not written to a budget, so the span
    selector trims to this rather than letting one review eat the header, the
    themes and the actions.

    `llm` is this stage's own provider block — Gemini — and is independent of
    the `[llm]` block that Phase 2 labels with.
    """

    max_words: int = 250
    top_themes: int = 3
    quote_count: int = 3
    quote_min_words: int = 8
    quote_max_words: int = 26
    compose_llm: bool = True
    recipient_alias: str = ""
    llm: LLMSettings = field(default_factory=gemini_defaults)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ENV_REF = re.compile(r"\$\{([^}]+)\}")


class ConfigError(ValueError):
    """Raised when settings.toml cannot be used as written."""


def validate_email(value: str, *, field: str = "gmail.recipient_alias") -> str:
    """Empty is allowed (dry-run); a non-empty value must look like an address."""
    alias = (value or "").strip()
    if not alias:
        return ""
    if not EMAIL_RE.match(alias):
        raise ConfigError(
            f"{field} is not a valid email address: {alias!r}"
        )
    return alias


def expand_env_refs(value: str) -> str:
    """Replace `${VAR}` with the process environment; missing vars become ''."""
    return _ENV_REF.sub(lambda match: os.environ.get(match.group(1), ""), value)


# Tools the hosted gmail-docs-mcp server exposes. `send_email` is on the
# server so a generic MCP host can send. Interactive `reviewpulse run` must
# never call it; Phase 6 `--send` / `[schedule] send_email` may.
HOSTED_APPEND_TOOL = "append_to_google_doc"
HOSTED_DRAFT_TOOL = "draft_email"
HOSTED_SEND_TOOL = "send_email"
FORBIDDEN_SEND_TOOLS = frozenset({"send_email", "send_message", "messages.send"})
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DOC_ID_IN_URL = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")


def normalize_document_id(value: str) -> str:
    """Accept a bare Doc ID or a full docs.google.com URL."""
    raw = (value or "").strip()
    if not raw:
        return ""
    match = DOC_ID_IN_URL.search(raw)
    return match.group(1) if match else raw


def google_doc_url(document_id: str) -> str | None:
    doc_id = normalize_document_id(document_id)
    if not doc_id:
        return None
    return f"https://docs.google.com/document/d/{doc_id}/edit"


@dataclass
class McpToolNames:
    """Configured tool names for one MCP server.

    Names are not standardized across servers, so they live in settings rather
    than in code. Empty optional names mean "this server has no such tool";
    the publisher then falls back to the local idempotency store.
    """

    create: str = ""
    append: str = ""
    find: str = ""
    replace: str = ""
    create_draft: str = ""
    find_draft: str = ""
    update_draft: str = ""
    send: str = ""

    def required_docs(self) -> list[str]:
        return [name for name in (self.create, self.append) if name]

    def required_gmail(self) -> list[str]:
        return [name for name in (self.create_draft,) if name]

    def required_send(self) -> list[str]:
        return [name for name in (self.send,) if name]

    def optional(self) -> list[str]:
        return [
            name
            for name in (self.find, self.replace, self.find_draft, self.update_draft)
            if name
        ]

    def forbidden(self) -> list[str]:
        """Draft/docs names that would send mail. `tools.send` is opt-in, not here."""
        names = (
            self.create,
            self.append,
            self.find,
            self.replace,
            self.create_draft,
            self.find_draft,
            self.update_draft,
        )
        return [name for name in names if name in FORBIDDEN_SEND_TOOLS]


@dataclass
class McpServerSettings:
    """One MCP server: stdio spawn *or* Streamable HTTP. OAuth stays inside it."""

    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    document_id: str = ""
    tools: McpToolNames = field(default_factory=McpToolNames)

    @property
    def transport(self) -> str:
        return "http" if self.url.strip() else "stdio"

    @property
    def configured(self) -> bool:
        """False while placeholders remain, or while HTTP auth/url is missing."""
        if self.url.strip():
            return self.url.startswith("http") and "<" not in self.url
        blob = " ".join([self.command, *self.args])
        return bool(self.command.strip()) and "<" not in blob


@dataclass
class McpSettings:
    """Docs + Gmail MCP access.

    The hosted Railway server is one Streamable HTTP endpoint that exposes both
    Gmail and Docs tools. `url` / `auth_token` are therefore top-level; the
    `gdocs` and `gmail` blocks still carry the tool-name mapping and the
    existing Google Doc ID (the server cannot create documents).
    """

    url: str = ""
    auth_token: str = ""
    gdocs: McpServerSettings = field(default_factory=McpServerSettings)
    gmail: McpServerSettings = field(default_factory=McpServerSettings)

    @property
    def transport(self) -> str:
        if self.url.strip() or self.gdocs.url.strip() or self.gmail.url.strip():
            return "http"
        return "stdio"

    @property
    def configured(self) -> bool:
        if self.transport == "http":
            url = self.url.strip() or self.gdocs.url.strip() or self.gmail.url.strip()
            token = self.auth_token.strip() or (
                (self.gdocs.headers.get("Authorization") or "")
                .removeprefix("Bearer")
                .strip()
            )
            return (
                bool(url)
                and url.startswith("http")
                and "<" not in url
                and bool(token)
                and bool(self.gdocs.document_id.strip())
                and bool(self.gdocs.tools.append)
                and bool(self.gmail.tools.create_draft)
                and not self.gdocs.tools.forbidden()
                and not self.gmail.tools.forbidden()
            )
        return self.gdocs.configured and self.gmail.configured


@dataclass
class ScheduleSettings:
    """Weekly unattended run (Phase 6). The job is `reviewpulse schedule --once`."""

    weekday: str = "monday"
    hour: int = 9
    minute: int = 0
    timezone: str = "Asia/Kolkata"
    window_weeks: int = 12
    send_email: bool = True
    skip_if_no_new: bool = False
    lock_timeout_minutes: int = 120


@dataclass
class ConsoleSettings:
    """Phase 7 operator console (FastAPI bind + UI initials)."""

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    operator_initials: str = "MK"


@dataclass
class Settings:
    package_id: str = "com.nextbillion.groww"
    default_window_weeks: int = 12
    min_reviews: int = 15
    k_max: int = 5
    cluster_size_floor: int = 3
    fetch_lang: str = "en"
    fetch_country: str = "in"
    min_words: int = 8
    english_only: bool = True
    columns: ColumnMapping = field(default_factory=ColumnMapping)
    db_path: Path = field(default_factory=default_db_path)
    clustering: ClusteringSettings = field(default_factory=ClusteringSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    pulse: PulseSettings = field(default_factory=PulseSettings)
    mcp: McpSettings = field(default_factory=McpSettings)
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    console: ConsoleSettings = field(default_factory=ConsoleSettings)


def _parse_llm_block(block: dict, defaults: LLMSettings) -> LLMSettings:
    """Parse one provider block against the defaults for the stage that owns it."""
    return LLMSettings(
        provider=block.get("provider", defaults.provider),
        model=block.get("model", defaults.model),
        reasoning_effort=block.get("reasoning_effort", defaults.reasoning_effort),
        samples_per_theme=int(block.get("samples_per_theme", defaults.samples_per_theme)),
        requests_per_minute=int(
            block.get("requests_per_minute", defaults.requests_per_minute)
        ),
        requests_per_day=int(block.get("requests_per_day", defaults.requests_per_day)),
        tokens_per_minute=int(block.get("tokens_per_minute", defaults.tokens_per_minute)),
        tokens_per_day=int(block.get("tokens_per_day", defaults.tokens_per_day)),
        tokens_per_request=int(
            block.get("tokens_per_request", defaults.tokens_per_request)
        ),
    )


def _parse_llm(data: dict) -> LLMSettings:
    return _parse_llm_block(data.get("llm", {}), LLMSettings())


def _parse_clustering(data: dict) -> ClusteringSettings:
    block = data.get("clustering", {})
    defaults = ClusteringSettings()
    return ClusteringSettings(
        mode=block.get("mode", defaults.mode),
        embedding_model=block.get("embedding_model", defaults.embedding_model),
        linkage=block.get("linkage", defaults.linkage),
        random_seed=int(block.get("random_seed", defaults.random_seed)),
        max_cluster_share=float(block.get("max_cluster_share", defaults.max_cluster_share)),
        signal_min_words=int(block.get("signal_min_words", defaults.signal_min_words)),
        signal_max_rating=int(block.get("signal_max_rating", defaults.signal_max_rating)),
        rank_by=block.get("rank_by", defaults.rank_by),
        trend_split_weeks=int(block.get("trend_split_weeks", defaults.trend_split_weeks)),
        emerging_trend_ratio=float(
            block.get("emerging_trend_ratio", defaults.emerging_trend_ratio)
        ),
        label_llm=bool(block.get("label_llm", defaults.label_llm)),
    )


def _parse_pulse(data: dict) -> PulseSettings:
    block = data.get("pulse", {})
    defaults = PulseSettings()
    return PulseSettings(
        max_words=int(block.get("max_words", defaults.max_words)),
        top_themes=int(block.get("top_themes", defaults.top_themes)),
        quote_count=int(block.get("quote_count", defaults.quote_count)),
        quote_min_words=int(block.get("quote_min_words", defaults.quote_min_words)),
        quote_max_words=int(block.get("quote_max_words", defaults.quote_max_words)),
        compose_llm=bool(block.get("compose_llm", defaults.compose_llm)),
        recipient_alias=validate_email(
            data.get("gmail", {}).get("recipient_alias", defaults.recipient_alias)
        ),
        llm=_parse_llm_block(block.get("llm", {}), gemini_defaults()),
    )


def _parse_tool_names(block: dict, defaults: McpToolNames) -> McpToolNames:
    tools = block.get("tools", {})
    return McpToolNames(
        create=str(tools.get("create", defaults.create)),
        append=str(tools.get("append", defaults.append)),
        find=str(tools.get("find", defaults.find)),
        replace=str(tools.get("replace", defaults.replace)),
        create_draft=str(tools.get("create_draft", defaults.create_draft)),
        find_draft=str(tools.get("find_draft", defaults.find_draft)),
        update_draft=str(tools.get("update_draft", defaults.update_draft)),
        send=str(tools.get("send", defaults.send)),
    )


def _hosted_tool_defaults(*, docs: bool) -> McpToolNames:
    """Tool names on gmail-docs-mcp (Railway). No create / replace / send."""
    if docs:
        return McpToolNames(append=HOSTED_APPEND_TOOL)
    return McpToolNames(create_draft=HOSTED_DRAFT_TOOL, send=HOSTED_SEND_TOOL)


def _stdio_tool_defaults(*, docs: bool) -> McpToolNames:
    if docs:
        return McpToolNames(
            create="create_document",
            append="insert_text",
            find="search_documents",
            replace="replace_text",
        )
    return McpToolNames(
        create_draft="create_draft",
        find_draft="list_drafts",
        update_draft="update_draft",
    )


def _parse_headers(block: dict) -> dict[str, str]:
    raw = block.get("headers") or {}
    return {
        str(key): expand_env_refs(str(value))
        for key, value in raw.items()
        if str(value).strip()
    }


def _parse_mcp_server(block: dict, *, docs: bool, hosted: bool) -> McpServerSettings:
    defaults = _hosted_tool_defaults(docs=docs) if hosted else _stdio_tool_defaults(docs=docs)
    env_block = block.get("env") or {}
    env = {
        str(key): expand_env_refs(str(value))
        for key, value in env_block.items()
    }
    cwd = block.get("cwd")
    url = expand_env_refs(str(block.get("url", "")))
    return McpServerSettings(
        command=expand_env_refs(str(block.get("command", ""))),
        args=[expand_env_refs(str(item)) for item in block.get("args", [])],
        env=env,
        cwd=str(cwd) if cwd else None,
        url=url,
        headers=_parse_headers(block),
        document_id=normalize_document_id(str(block.get("document_id", ""))),
        tools=_parse_tool_names(block, defaults),
    )


def _bearer_headers(token: str) -> dict[str, str]:
    token = token.strip()
    if not token:
        return {}
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return {"Authorization": f"Bearer {token}"}


def _parse_mcp(data: dict) -> McpSettings:
    block = data.get("mcp", {})
    url = expand_env_refs(str(block.get("url", "")))
    auth_token = expand_env_refs(str(block.get("auth_token", "")))
    hosted = bool(url.strip()) or bool(block.get("gdocs", {}).get("url")) or bool(
        block.get("gmail", {}).get("url")
    )
    gdocs = _parse_mcp_server(block.get("gdocs", {}), docs=True, hosted=hosted)
    gmail = _parse_mcp_server(block.get("gmail", {}), docs=False, hosted=hosted)
    shared_headers = _bearer_headers(auth_token)
    if url:
        gdocs.url = gdocs.url or url
        gmail.url = gmail.url or url
    if shared_headers:
        gdocs.headers = {**shared_headers, **gdocs.headers}
        gmail.headers = {**shared_headers, **gmail.headers}
    return McpSettings(
        url=url or gdocs.url or gmail.url,
        auth_token=auth_token,
        gdocs=gdocs,
        gmail=gmail,
    )


def _parse_schedule(data: dict) -> ScheduleSettings:
    block = data.get("schedule", {})
    defaults = ScheduleSettings()
    weekday = str(block.get("weekday", defaults.weekday)).strip().lower()
    if weekday not in WEEKDAYS:
        raise ConfigError(
            f"schedule.weekday must be one of {', '.join(WEEKDAYS)}; got {weekday!r}"
        )
    hour = int(block.get("hour", defaults.hour))
    minute = int(block.get("minute", defaults.minute))
    if hour < 0 or hour > 23:
        raise ConfigError(f"schedule.hour must be 0–23; got {hour}")
    if minute < 0 or minute > 59:
        raise ConfigError(f"schedule.minute must be 0–59; got {minute}")
    timeout = int(block.get("lock_timeout_minutes", defaults.lock_timeout_minutes))
    if timeout < 1:
        raise ConfigError("schedule.lock_timeout_minutes must be at least 1")
    window_weeks = int(block.get("window_weeks", defaults.window_weeks))
    if window_weeks < 1 or window_weeks > 52:
        raise ConfigError("schedule.window_weeks must be between 1 and 52")
    timezone = str(block.get("timezone", defaults.timezone)).strip() or defaults.timezone
    return ScheduleSettings(
        weekday=weekday,
        hour=hour,
        minute=minute,
        timezone=timezone,
        window_weeks=window_weeks,
        send_email=bool(block.get("send_email", defaults.send_email)),
        skip_if_no_new=bool(block.get("skip_if_no_new", defaults.skip_if_no_new)),
        lock_timeout_minutes=timeout,
    )


def _parse_console(data: dict) -> ConsoleSettings:
    block = data.get("console", {})
    defaults = ConsoleSettings()
    host = str(block.get("api_host", defaults.api_host)).strip() or defaults.api_host
    port = int(block.get("api_port", defaults.api_port))
    if port < 1 or port > 65535:
        raise ConfigError(f"console.api_port must be 1–65535; got {port}")
    initials = str(block.get("operator_initials", defaults.operator_initials)).strip()
    initials = (initials or defaults.operator_initials)[:4].upper()
    env_initials = os.environ.get("OPERATOR_INITIALS", "").strip()
    if env_initials:
        initials = env_initials[:4].upper()
    return ConsoleSettings(api_host=host, api_port=port, operator_initials=initials)


def taxonomy_path() -> Path:
    """Real taxonomy if present, else the committed example."""
    return (
        DEFAULT_TAXONOMY_PATH
        if DEFAULT_TAXONOMY_PATH.is_file()
        else EXAMPLE_TAXONOMY_PATH
    )


def _parse_columns(data: dict) -> ColumnMapping:
    columns = data.get("ingest", {}).get("columns", {})
    return ColumnMapping(
        text=columns.get("text", "Review Text"),
        title=columns.get("title", "Review Title"),
        rating=columns.get("rating", "Star Rating"),
        date=columns.get("date", "Review Date"),
        external_id=columns.get("external_id", "Review ID"),
        author=columns.get("author", "Reviewer Name"),
    )


def load_settings(path: Path | None = None) -> Settings:
    # `${MCP_AUTH_TOKEN}` and LLM keys live in `.env`; expand them before parse.
    from reviewpulse.llm.factory import load_env_file

    load_env_file()

    settings_path = path or _resolve_settings_path()
    if not settings_path.is_file():
        settings_path = EXAMPLE_SETTINGS_PATH

    with settings_path.open("rb") as handle:
        data = tomllib.load(handle)

    app = data.get("app", {})
    fetch = data.get("fetch", {})
    ingest = data.get("ingest", {})
    return Settings(
        package_id=app.get("package_id", "com.nextbillion.groww"),
        default_window_weeks=int(app.get("default_window_weeks", 12)),
        min_reviews=int(app.get("min_reviews", 15)),
        k_max=int(app.get("k_max", 5)),
        cluster_size_floor=int(app.get("cluster_size_floor", 3)),
        fetch_lang=fetch.get("lang", "en"),
        fetch_country=fetch.get("country", "in"),
        min_words=int(ingest.get("min_words", 8)),
        english_only=bool(ingest.get("english_only", True)),
        columns=_parse_columns(data),
        clustering=_parse_clustering(data),
        llm=_parse_llm(data),
        pulse=_parse_pulse(data),
        mcp=_parse_mcp(data),
        schedule=_parse_schedule(data),
        console=_parse_console(data),
    )


def _resolve_settings_path() -> Path:
    """`REVIEWPULSE_SETTINGS` > `config/settings.toml` > the example template."""
    override = _env_path("REVIEWPULSE_SETTINGS")
    if override is not None:
        return override
    if DEFAULT_SETTINGS_PATH.is_file():
        return DEFAULT_SETTINGS_PATH
    return EXAMPLE_SETTINGS_PATH


def settings_file_path() -> Path:
    """Settings path used for GET/PATCH: env overlay, local toml, or the example."""
    path = _resolve_settings_path()
    if path.is_file():
        return path
    return EXAMPLE_SETTINGS_PATH


def ensure_writable_settings() -> Path:
    """Copy the example to the writable settings path if the operator has not yet."""
    override = _env_path("REVIEWPULSE_SETTINGS")
    target = override or DEFAULT_SETTINGS_PATH
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        EXAMPLE_SETTINGS_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return target


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _upsert_toml_key(text: str, section: str, key: str, value: object) -> str:
    """Set `key = value` under `[section]`, creating the section if needed."""
    literal = _toml_literal(value)
    lines = text.splitlines(keepends=True)
    in_section = False
    section_start: int | None = None
    key_line: int | None = None
    next_section: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1]
            if in_section:
                next_section = index
                break
            if name == section:
                in_section = True
                section_start = index
            continue
        if in_section and "=" in stripped and not stripped.startswith("#"):
            left = stripped.split("=", 1)[0].strip()
            if left == key:
                key_line = index
    newline = "\n"
    replacement = f"{key} = {literal}{newline}"
    if key_line is not None:
        ending = "\n" if lines[key_line].endswith("\n") else ""
        lines[key_line] = f"{key} = {literal}{ending or newline}"
        return "".join(lines)
    if section_start is not None:
        insert_at = section_start + 1
        lines.insert(insert_at, replacement)
        return "".join(lines)
    suffix = "" if text.endswith("\n") or not text else "\n"
    return f"{text}{suffix}\n[{section}]\n{replacement}"


def patch_settings_file(updates: dict[tuple[str, str], object]) -> Path:
    """Write allowlisted keys into settings.toml. `updates` maps (section, key) → value."""
    path = ensure_writable_settings()
    text = path.read_text(encoding="utf-8")
    for (section, key), value in updates.items():
        if value is None:
            continue
        text = _upsert_toml_key(text, section, key, value)
    path.write_text(text, encoding="utf-8")
    return path
