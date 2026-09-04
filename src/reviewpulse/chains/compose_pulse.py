"""LangChain pulse-composition chain (Phase 3 task 3.4).

Composition runs on Gemini, not on the Groq model Phase 2 labels with, so the
default model here comes from `[pulse.llm]` rather than `[llm]`.
"""

from __future__ import annotations

from reviewpulse.config import load_settings
from reviewpulse.llm.factory import build_chat_model, structured_output
from reviewpulse.models import PulseDraft
from reviewpulse.prompts import load_prompt

PROMPT_NAME = "compose_pulse.yaml"


def build_compose_chain(llm=None, *, retry: bool = False):
    """Prompt | structured-output model, returning the note's prose frame.

    `retry=True` appends the tighter word budget used for the single bounded
    retry after a recoverable gate failure (`chains/retry_policy.py`).
    """
    spec = load_prompt(PROMPT_NAME)
    if llm is None:
        llm = build_chat_model(settings=load_settings().pulse.llm)
    prompt = spec.to_retry_chat_prompt() if retry else spec.to_chat_prompt()
    return prompt | structured_output(llm, PulseDraft)
