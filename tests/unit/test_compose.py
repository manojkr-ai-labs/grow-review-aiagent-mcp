"""Pulse composition tests (Phase 3 tasks 3.3-3.5)."""

from __future__ import annotations

import re
from datetime import date

import pytest

from reviewpulse.models import ActionIdea, PulseDraft, Quote, Theme, ThemeLine
from reviewpulse.prompts import load_prompt
from reviewpulse.pulse.compose import (
    ComposeStats,
    compose_draft,
    format_quotes,
    format_stats,
    format_themes,
    heuristic_draft,
)

WINDOW_START = date(2026, 7, 6)
WINDOW_END = date(2026, 8, 29)


def make_theme(index: int, label: str, *, emerging: bool = False) -> Theme:
    return Theme(
        theme_id=f"t{index}",
        label=label,
        summary="",
        review_ids=[f"r{index}{n}" for n in range(12)],
        size=12,
        mean_rating=1.5,
        rank=index,
        neg_share=0.8,
        priority=10.0,
        trend=2.0 if emerging else 1.0,
        emerging=emerging,
        keywords=["customer care", "customer support", "ticket", "refund"],
    )


THEMES = [
    make_theme(1, "Customer support responsiveness", emerging=True),
    make_theme(2, "Brokerage charges"),
    make_theme(3, "Withdrawal delays"),
]

QUOTES = [
    Quote(review_id=f"r{i}0", theme_id=f"t{i}", text=f"Quote {i}", rating=1)
    for i in (1, 2, 3)
]


class StubChain:
    """Stands in for `prompt | llm.with_structured_output(PulseDraft)`."""

    def __init__(self, *rounds) -> None:
        self.rounds = list(rounds)
        self.calls: list[dict] = []

    def invoke(self, payload: dict) -> PulseDraft:
        self.calls.append(payload)
        answer = self.rounds.pop(0) if self.rounds else None
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, PulseDraft):
            return answer
        return PulseDraft(
            theme_lines=[
                ThemeLine(theme_id=t.theme_id, line=f"Model line for {t.label}")
                for t in THEMES
            ],
            actions=[
                ActionIdea(text=f"Model action {i}", theme_ids=[f"t{i}"])
                for i in (1, 2, 3)
            ],
        )

    @staticmethod
    def theme_ids(payload: dict) -> list[str]:
        return re.findall(r"\[(t\d+)\]", payload["themes"])


def compose(**kwargs):
    return compose_draft(
        THEMES,
        QUOTES,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        review_count=855,
        mean_rating=2.1,
        theme_count=5,
        **kwargs,
    )


def test_no_chain_yields_a_deterministic_frame() -> None:
    draft, stats = compose()
    assert stats.source == "heuristic"
    assert stats.llm_calls == 0
    assert len(draft.actions) == 3
    assert len(draft.theme_lines) == 3


def test_heuristic_actions_are_grounded_in_distinct_themes() -> None:
    draft = heuristic_draft(THEMES, QUOTES)
    cited = [action.theme_ids for action in draft.actions]
    assert cited == [["t1"], ["t2"], ["t3"]]


def test_heuristic_line_does_not_repeat_an_overlapping_anchor_term() -> None:
    """"customer care" and "customer support" would spend the line on one word."""
    line = heuristic_draft(THEMES, QUOTES).theme_lines[0].line
    assert line.count("customer") == 1


def test_heuristic_line_flags_an_emerging_theme() -> None:
    draft = heuristic_draft(THEMES, QUOTES)
    assert "rising" in draft.theme_lines[0].line
    assert "rising" not in draft.theme_lines[1].line


def test_model_output_is_used_when_it_is_usable() -> None:
    draft, stats = compose(chain=StubChain())
    assert stats.source == "llm"
    assert stats.llm_calls == 1
    assert draft.actions[0].text == "Model action 1"
    assert draft.theme_lines[0].line == "Model line for Customer support responsiveness"


def test_the_whole_note_is_composed_in_one_call() -> None:
    chain = StubChain()
    compose(chain=chain)
    assert len(chain.calls) == 1
    assert chain.theme_ids(chain.calls[0]) == ["t1", "t2", "t3"]


def test_prompt_carries_stats_themes_and_quotes() -> None:
    chain = StubChain()
    compose(chain=chain)
    payload = chain.calls[0]
    assert set(payload) == {"stats", "themes", "quotes"}
    assert "855" in payload["stats"]
    assert "Customer support responsiveness" in payload["themes"]
    assert "Quote 1" in payload["quotes"]


def test_tighter_retry_uses_the_retry_chain() -> None:
    chain = StubChain()
    retry_chain = StubChain()
    stats = ComposeStats()
    compose(chain=chain, retry_chain=retry_chain, tighter=True, stats=stats)

    assert chain.calls == []
    assert len(retry_chain.calls) == 1
    assert stats.retries == 1


def test_a_skipped_theme_line_is_filled_in_deterministically() -> None:
    partial = PulseDraft(
        theme_lines=[ThemeLine(theme_id="t1", line="Only this one")],
        actions=[ActionIdea(text=f"Action {i}", theme_ids=[f"t{i}"]) for i in (1, 2, 3)],
    )
    draft, _ = compose(chain=StubChain(partial))

    assert [line.theme_id for line in draft.theme_lines] == ["t1", "t2", "t3"]
    assert draft.theme_lines[0].line == "Only this one"
    assert draft.theme_lines[1].line.startswith("Complaints centre on")


def test_ungrounded_actions_are_passed_through_for_the_gate_to_judge() -> None:
    """Repairing them here would make `actions_grounded` vacuous."""
    bad = PulseDraft(
        theme_lines=[],
        actions=[ActionIdea(text="Do something", theme_ids=["t9"])],
    )
    draft, stats = compose(chain=StubChain(bad))

    assert stats.source == "llm"
    assert [a.theme_ids for a in draft.actions] == [["t9"]]


def test_an_answer_with_no_actions_falls_back_rather_than_shipping_empty() -> None:
    empty = PulseDraft(theme_lines=[], actions=[])
    draft, stats = compose(chain=StubChain(empty))

    assert len(draft.actions) == 3
    assert stats.source == "heuristic"
    assert "no usable actions" in stats.errors[0]


def test_llm_error_degrades_to_the_deterministic_frame() -> None:
    draft, stats = compose(chain=StubChain(RuntimeError("api down")))

    assert stats.source == "heuristic"
    assert len(draft.actions) == 3
    assert "api down" in stats.errors[0]


def test_theme_block_is_keyed_by_the_id_the_model_echoes_back() -> None:
    block = format_themes(THEMES)
    assert re.findall(r"\[(t\d+)\]", block) == ["t1", "t2", "t3"]
    assert "rising in the recent half" in block
    assert "customer care" in block


def test_stats_block_states_the_window_and_the_population() -> None:
    block = format_stats(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        review_count=855,
        mean_rating=2.1,
        theme_count=5,
        top_count=3,
    )
    assert "2026-07-06 to 2026-08-29" in block
    assert "855" in block
    assert "2.1 out of 5" in block


def test_quotes_block_ties_each_quote_to_its_theme() -> None:
    assert '- [t1] "Quote 1" (1*)' in format_quotes(QUOTES)


def test_prompt_forbids_the_model_from_authoring_quotes() -> None:
    spec = load_prompt("compose_pulse.yaml")
    assert "Do not quote or paraphrase any review sentence" in spec.system
    assert "verbatim" in spec.system


def test_prompt_forbids_restating_counts_the_renderer_prints() -> None:
    spec = load_prompt("compose_pulse.yaml")
    assert "Never restate counts" in spec.system


def test_prompt_requires_every_action_to_cite_a_theme() -> None:
    spec = load_prompt("compose_pulse.yaml")
    assert "cite at least one theme id" in spec.system
    assert spec.retry_suffix.strip()


@pytest.mark.parametrize("variable", ["stats", "themes", "quotes"])
def test_prompt_declares_its_inputs(variable: str) -> None:
    spec = load_prompt("compose_pulse.yaml")
    assert variable in spec.input_variables
    assert "{" + variable + "}" in spec.human
