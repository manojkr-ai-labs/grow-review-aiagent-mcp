"""LangChain theme-labeling chain (Phase 2 task 2.14)."""

from __future__ import annotations

from reviewpulse.llm.factory import build_chat_model, structured_output
from reviewpulse.models import ThemeLabels
from reviewpulse.prompts import load_prompt

PROMPT_NAME = "label_themes.yaml"


def build_label_chain(llm=None, *, retry: bool = False):
    """Prompt | structured-output model, naming every theme in one call.

    `retry=True` appends the correction instruction used after a label is
    rejected for describing sentiment instead of a product surface; that call
    carries only the rejected themes.
    """
    spec = load_prompt(PROMPT_NAME)
    llm = llm if llm is not None else build_chat_model()
    prompt = spec.to_retry_chat_prompt() if retry else spec.to_chat_prompt()
    return prompt | structured_output(llm, ThemeLabels)
