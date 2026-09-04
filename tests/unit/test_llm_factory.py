"""Chat model factory and free-tier pacing (Phase 2 task 2.12).

The provider split arrived in Phase 3: labeling stays on Groq, composition
moves to Gemini, and each stage carries its own key, model and quotas.
"""

from __future__ import annotations

import pytest

from reviewpulse.config import LLMSettings, gemini_defaults, load_settings
from reviewpulse.llm import factory
from reviewpulse.llm.rate_limit import DailyBudgetExhausted, FreeTierRateLimiter
from reviewpulse.models import ThemeLabel

FREE_TIER = LLMSettings()
GEMINI_TIER = gemini_defaults()
_REAL_LOAD_ENV = factory.load_env_file


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Keep the developer's real .env and exported keys out of these tests."""
    for var in factory.API_KEY_VARS + tuple(factory.PROVIDER_MODEL_VAR.values()):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(factory, "load_env_file", lambda path=None: None)


def test_free_tier_defaults_match_published_quotas() -> None:
    assert FREE_TIER.provider == "groq"
    assert FREE_TIER.model == "openai/gpt-oss-120b"
    assert FREE_TIER.requests_per_minute == 30
    assert FREE_TIER.requests_per_day == 1_000
    assert FREE_TIER.tokens_per_minute == 8_000
    assert FREE_TIER.tokens_per_day == 200_000


def test_load_env_file_strips_unquoted_inline_comments(monkeypatch, tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "LLM_MODEL=openai/gpt-oss-120b       # groq labeling\n"
        'GEMINI_MODEL="gemini-3.6-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    _REAL_LOAD_ENV(env)
    assert factory.os.environ["LLM_MODEL"] == "openai/gpt-oss-120b"
    assert factory.os.environ["GEMINI_MODEL"] == "gemini-3.6-flash"


def test_placeholder_key_counts_as_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_your-key-here")
    assert factory.llm_configured() is False


def test_real_key_is_picked_up(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_live123")
    assert factory.api_key() == "gsk_live123"
    assert factory.llm_configured() is True


def test_legacy_llm_api_key_still_works(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "gsk_legacy")
    assert factory.api_key() == "gsk_legacy"


def test_build_chat_model_without_key_is_unavailable() -> None:
    with pytest.raises(factory.LLMUnavailable, match="GROQ_API_KEY"):
        factory.build_chat_model()


def test_build_chat_model_is_paced_and_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_live123")
    llm = factory.build_chat_model(settings=FREE_TIER)

    assert llm.model_name == "openai/gpt-oss-120b"
    # Groq rejects a literal 0, so ChatGroq substitutes its own epsilon.
    assert llm.temperature == pytest.approx(0.0, abs=1e-6)
    assert isinstance(llm.rate_limiter, FreeTierRateLimiter)
    # Reasoning is billed against the same token quota as the prompt.
    assert llm.reasoning_effort == "low"


def test_env_model_overrides_settings(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_live123")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    llm = factory.build_chat_model(settings=FREE_TIER)

    assert llm.model_name == "llama-3.3-70b-versatile"
    # reasoning_effort is a gpt-oss parameter; other models reject it.
    assert llm.reasoning_effort is None


def test_phase3_composes_on_gemini_by_default() -> None:
    """The whole point of the split: Phase 2 is Groq, Phase 3 is Gemini."""
    settings = load_settings()

    assert settings.llm.provider == "groq"
    assert settings.pulse.llm.provider == "gemini"
    assert settings.pulse.llm.model.startswith("gemini-")


def test_gemini_model_is_paced_and_deterministic(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaLive123")
    llm = factory.build_chat_model(settings=GEMINI_TIER)

    assert llm.model.endswith("gemini-3.6-flash")
    assert llm.temperature == pytest.approx(0.0)
    assert isinstance(llm.rate_limiter, FreeTierRateLimiter)


def test_gemini_key_does_not_satisfy_groq_or_the_reverse(monkeypatch) -> None:
    """A key for one stage must never make the other look configured."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaLive123")

    assert factory.llm_configured("gemini") is True
    assert factory.llm_configured("groq") is False
    assert factory.unavailable_reason(FREE_TIER) == "GROQ_API_KEY not configured"
    assert factory.unavailable_reason(GEMINI_TIER) is None


def test_google_api_key_is_accepted_as_an_alias(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaAlias")
    assert factory.api_key("gemini") == "AIzaAlias"


def test_gemini_placeholder_key_counts_as_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-your-key-here")
    assert factory.llm_configured("gemini") is False


def test_model_override_is_scoped_to_one_provider(monkeypatch) -> None:
    """LLM_MODEL must not silently repoint the composition model as well."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")

    assert factory.resolved_model(GEMINI_TIER) == "gemini-2.0-flash"
    assert factory.resolved_model(FREE_TIER) == "llama-3.3-70b-versatile"


def test_gemini_build_without_key_names_the_right_variable(monkeypatch) -> None:
    with pytest.raises(factory.LLMUnavailable, match="GEMINI_API_KEY"):
        factory.build_chat_model(settings=GEMINI_TIER)


def test_unknown_provider_is_reported_not_guessed() -> None:
    settings = LLMSettings(provider="anthropic")

    assert "unknown llm provider" in factory.unavailable_reason(settings)
    with pytest.raises(factory.LLMUnavailable, match="unknown llm provider"):
        factory.build_chat_model(settings=settings)


def test_gemini_free_tier_pacing_is_bound_by_requests_not_tokens() -> None:
    limiter = factory.build_rate_limiter(GEMINI_TIER)

    # Gemini's token ceiling is generous; the request cap is what binds.
    assert limiter.calls_per_minute == GEMINI_TIER.requests_per_minute
    assert limiter.calls_per_day == GEMINI_TIER.requests_per_day


def test_a_whole_compose_stage_starts_without_waiting() -> None:
    """One draft plus the single bounded retry; neither should be paced."""
    limiter = factory.build_rate_limiter(GEMINI_TIER)

    assert limiter.acquire(blocking=False) is True
    assert limiter.acquire(blocking=False) is True
    assert limiter.calls_made == 2


def test_structured_output_uses_groq_constrained_decoding(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_live123")
    bound = factory.structured_output(
        factory.build_chat_model(settings=FREE_TIER), ThemeLabel
    )
    response_format = bound.first.kwargs["response_format"]

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_structured_output_stops_at_the_strictest_binding_offered() -> None:
    """A client that takes json_schema but not strict must not fall to tools."""

    class NoStrictModel:
        def __init__(self) -> None:
            self.methods: list[str] = []

        def with_structured_output(self, schema, **kwargs):
            if kwargs.get("strict"):
                raise TypeError("unexpected keyword argument 'strict'")
            self.methods.append(kwargs.get("method", "default"))
            return schema

    model = NoStrictModel()
    assert factory.structured_output(model, ThemeLabel) is ThemeLabel
    assert model.methods == ["json_schema"]


def test_structured_output_falls_back_when_method_unsupported() -> None:
    class LegacyModel:
        def __init__(self) -> None:
            self.methods: list[str] = []

        def with_structured_output(self, schema, **kwargs):
            if kwargs:
                raise TypeError("unexpected keyword argument")
            self.methods.append("default")
            return schema

    model = LegacyModel()
    assert factory.structured_output(model, ThemeLabel) is ThemeLabel
    assert model.methods == ["default"]


def test_pacing_follows_the_token_quota_not_the_request_quota() -> None:
    limiter = FreeTierRateLimiter(
        requests_per_minute=FREE_TIER.requests_per_minute,
        requests_per_day=FREE_TIER.requests_per_day,
        tokens_per_minute=FREE_TIER.tokens_per_minute,
        tokens_per_day=FREE_TIER.tokens_per_day,
        tokens_per_request=FREE_TIER.tokens_per_request,
    )
    # A batched call is ~2.5K tokens, so tokens run out well before requests do.
    assert limiter.calls_per_minute == pytest.approx(8000 / 2500)
    assert limiter.calls_per_day == 200_000 // 2500


def test_a_whole_labeling_stage_starts_without_waiting() -> None:
    limiter = FreeTierRateLimiter(
        requests_per_minute=FREE_TIER.requests_per_minute,
        requests_per_day=FREE_TIER.requests_per_day,
        tokens_per_minute=FREE_TIER.tokens_per_minute,
        tokens_per_day=FREE_TIER.tokens_per_day,
        tokens_per_request=FREE_TIER.tokens_per_request,
    )
    # Labeling is one batched call plus at most one retry; both go straight out.
    assert limiter.acquire(blocking=False) is True
    assert limiter.acquire(blocking=False) is True
    assert limiter.calls_made == 2


def test_daily_budget_stops_a_runaway_loop() -> None:
    limiter = FreeTierRateLimiter(
        requests_per_minute=30,
        requests_per_day=2,
        tokens_per_minute=8_000,
        tokens_per_day=200_000,
        tokens_per_request=100,
    )
    assert limiter.acquire(blocking=False) is True
    assert limiter.acquire(blocking=False) is True
    with pytest.raises(DailyBudgetExhausted):
        limiter.acquire(blocking=False)
