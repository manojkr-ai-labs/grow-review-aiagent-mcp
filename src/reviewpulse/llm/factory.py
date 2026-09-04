"""Chat model factory (Phase 2 task 2.12; provider split added in Phase 3).

Two stages call an LLM and they no longer share a provider: labeling (Phase 2)
runs on Groq, composition (Phase 3) on Gemini. Each stage passes its own
`LLMSettings`, so the provider is a property of the settings block rather than a
global — `[llm]` configures Groq, `[pulse.llm]` configures Gemini.

Both providers are used on their free tier, which shapes three choices here:

* every model is built with the pacer from `llm/rate_limit.py` attached, so the
  per-minute quotas are respected before a request leaves the process;
* `max_retries` is raised, because a quota breach comes back as a 429 with a
  `Retry-After` the SDK already honours — one slow call beats a lost label;
* reasoning effort is turned down on the Groq side, since reasoning tokens are
  billed against the same 8K-per-minute ceiling as the prompt and naming a theme
  needs little of it.
"""

from __future__ import annotations

import os
from pathlib import Path

from reviewpulse.config import PROJECT_ROOT, LLMSettings, load_settings

GROQ = "groq"
GEMINI = "gemini"

# Ordered by precedence; the first non-placeholder value wins. The first entry
# is also the name used in "not configured" messages.
PROVIDER_KEY_VARS: dict[str, tuple[str, ...]] = {
    GROQ: ("GROQ_API_KEY", "LLM_API_KEY"),
    GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}

# Per-provider single-run model override, so pointing Phase 3 at a different
# Gemini model cannot silently repoint Phase 2's Groq model as well.
PROVIDER_MODEL_VAR: dict[str, str] = {
    GROQ: "LLM_MODEL",
    GEMINI: "GEMINI_MODEL",
}

API_KEY_VARS = tuple(var for names in PROVIDER_KEY_VARS.values() for var in names)
PLACEHOLDER_KEYS = ("gsk_your-key", "sk-your-key", "AIza-your-key")

# Both providers answer a quota breach with 429 + Retry-After; leave room to
# ride it out rather than losing the call.
MAX_RETRIES = 5

# reasoning_effort is a gpt-oss parameter; other Groq models reject it.
REASONING_MODEL_PREFIX = "openai/gpt-oss"


class LLMUnavailable(RuntimeError):
    """Raised when no usable chat model can be constructed."""


def load_env_file(path: Path | None = None) -> None:
    """Populate os.environ from a .env file without adding a dependency.

    Existing environment variables win, so an exported key is never overwritten.
    """
    path = path or (PROJECT_ROOT / ".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Unquoted values treat ` #` as an inline comment, same as dotenv.
        # Quoted values keep their contents, then the wrapping quotes come off.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_provider(provider: str | None) -> str:
    """Canonical provider name, or "" when it is not one we can build."""
    name = (provider or "").strip().lower()
    return name if name in PROVIDER_KEY_VARS else ""


def key_var_name(provider: str) -> str:
    """The environment variable a user is expected to set for this provider."""
    return PROVIDER_KEY_VARS[normalize_provider(provider) or GROQ][0]


def api_key(provider: str = GROQ) -> str:
    """The configured key for `provider`, or "" when only a placeholder is set."""
    name = normalize_provider(provider)
    if not name:
        return ""
    load_env_file()
    for var in PROVIDER_KEY_VARS[name]:
        value = (os.environ.get(var) or "").strip()
        if value and not value.startswith(PLACEHOLDER_KEYS):
            return value
    return ""


def llm_configured(provider: str = GROQ) -> bool:
    return bool(api_key(provider))


def unavailable_reason(settings: LLMSettings) -> str | None:
    """Why this stage cannot call its model, or None when it can.

    Returned as a sentence fragment so the orchestrator can append the fallback
    it is about to use instead — a missing key is a normal offline condition,
    not an error.
    """
    name = normalize_provider(settings.provider)
    if not name:
        supported = ", ".join(sorted(PROVIDER_KEY_VARS))
        return f"unknown llm provider {settings.provider!r} (expected one of {supported})"
    if not api_key(name):
        return f"{key_var_name(name)} not configured"
    return None


def resolved_model(settings: LLMSettings) -> str:
    """The model this settings block will actually use, env override included."""
    name = normalize_provider(settings.provider)
    override = os.environ.get(PROVIDER_MODEL_VAR[name]) if name else None
    return override or settings.model


def build_rate_limiter(settings: LLMSettings):
    from reviewpulse.llm.rate_limit import FreeTierRateLimiter

    return FreeTierRateLimiter(
        requests_per_minute=settings.requests_per_minute,
        requests_per_day=settings.requests_per_day,
        tokens_per_minute=settings.tokens_per_minute,
        tokens_per_day=settings.tokens_per_day,
        tokens_per_request=settings.tokens_per_request,
    )


def build_chat_model(*, temperature: float = 0.0, settings: LLMSettings | None = None):
    """Build a deterministic, rate-limited chat model for `settings.provider`.

    Defaults to the `[llm]` block — Phase 2's Groq model. Phase 3 passes
    `settings=load_settings().pulse.llm` to get Gemini instead.
    """
    settings = settings or load_settings().llm
    provider = normalize_provider(settings.provider)
    if not provider:
        supported = ", ".join(sorted(PROVIDER_KEY_VARS))
        raise LLMUnavailable(
            f"unknown llm provider {settings.provider!r}; expected one of {supported}"
        )

    key = api_key(provider)
    if not key:
        raise LLMUnavailable(
            f"{key_var_name(provider)} is not set (see .env.example); "
            "run with --no-llm to take the deterministic path"
        )

    model = resolved_model(settings)
    builder = _build_gemini if provider == GEMINI else _build_groq
    return builder(model=model, temperature=temperature, key=key, settings=settings)


def _build_groq(*, model: str, temperature: float, key: str, settings: LLMSettings):
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LLMUnavailable(f"langchain-groq is not installed: {exc}") from exc

    extra = {}
    if model.startswith(REASONING_MODEL_PREFIX):
        # "hidden" keeps the reasoning trace out of the message content, which
        # would otherwise sit in front of the JSON the label chain parses.
        extra = {
            "reasoning_effort": settings.reasoning_effort,
            "reasoning_format": "hidden",
        }

    return ChatGroq(
        model=model,
        temperature=temperature,
        api_key=key,
        max_retries=MAX_RETRIES,
        rate_limiter=build_rate_limiter(settings),
        **extra,
    )


def _build_gemini(*, model: str, temperature: float, key: str, settings: LLMSettings):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LLMUnavailable(
            f"langchain-google-genai is not installed: {exc}"
        ) from exc

    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=key,
        max_retries=MAX_RETRIES,
        rate_limiter=build_rate_limiter(settings),
    )


# Tried in order: the strictest binding a client supports is the cheapest and
# the least likely to return unparseable JSON.
_STRUCTURED_METHODS = (
    {"method": "json_schema", "strict": True},
    {"method": "json_schema"},
    {},
)


def structured_output(llm, schema):
    """Bind `schema` to `llm`, preferring provider-native constrained decoding.

    `json_schema` with `strict` guarantees a parseable answer and costs fewer
    tokens than wrapping the schema in a tool call. Both current provider
    clients take it, so in practice the first rung wins for Groq and Gemini
    alike; the ladder is what stops a client that supports less — an older
    version, a future provider, a test stub — from turning an unsupported
    keyword into a failed run instead of a function call.
    """
    error: Exception | None = None
    for kwargs in _STRUCTURED_METHODS:
        try:
            return llm.with_structured_output(schema, **kwargs)
        except (TypeError, ValueError, NotImplementedError) as exc:
            error = exc
    raise error  # pragma: no cover - the last rung takes no arguments
