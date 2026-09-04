"""Prompt templates and a loader for them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@dataclass
class PromptSpec:
    """A system/human prompt pair loaded from YAML."""

    system: str
    human: str
    input_variables: list[str]
    retry_suffix: str = ""

    def to_chat_prompt(self):
        from langchain_core.prompts import ChatPromptTemplate

        return ChatPromptTemplate.from_messages(
            [("system", self.system), ("human", self.human)]
        )

    def to_retry_chat_prompt(self):
        from langchain_core.prompts import ChatPromptTemplate

        return ChatPromptTemplate.from_messages(
            [("system", self.system + self.retry_suffix), ("human", self.human)]
        )


def load_prompt(name: str) -> PromptSpec:
    import yaml

    path = PROMPT_DIR / name if name.endswith(".yaml") else PROMPT_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptSpec(
        system=data["system"],
        human=data["human"],
        input_variables=list(data.get("input_variables", [])),
        retry_suffix=data.get("retry_suffix", ""),
    )
