"""Fee-theme selection, factual bullets, and the explainer file.

Theme selection reads ``clusters.json`` and does not retrieve. Factual
bullets call ``answer_facts`` with an injected retriever. The last bullet
quotes the not-covered ledger. A failed gate writes no file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator

from capstone.contracts import Explainer, ExplainerBullet, LedgerRow
from supportdesk.advice import requests_advice, requests_performance
from supportdesk.compliance import ComplianceSession
from supportdesk.enums import Coverage
from supportdesk.facts import RetrievalBundle, answer_facts
from supportdesk.privacy import contains_pii

FEE_LEXICON = (
    "exit load",
    "expense ratio",
    "brokerage",
    "charges",
    "charge",
    "fees",
    "fee",
    "demat",
    "amc",
)
FEE_FLOOR = 3
NO_FEE_THEME_SENTENCE = "No fee theme met the bar."
MAX_FACT_LINKS = 5
MAX_BULLETS = 6
UNAVAILABLE_LAST_CHECKED = "unavailable"
EMPTY_LEDGER_SENTENCE = "No queued question in this week was outside the corpus."
# The desk checker matches a customer's "i should". An explainer sentence is
# "you should", so that wording is checked here as well.
_EXPLAINER_INSTRUCTION = re.compile(
    r"\byou should (?:buy|sell|hold|redeem|exit|invest)\b",
    re.IGNORECASE,
)
_FACT_CASE_ID = "case_" + "ab" * 16
_GROWW_HOSTS = frozenset({"groww.in", "www.groww.in"})

# Fee questions written in the sibling mutual-fund-faq-assistant catalog.
# Exit load first, then expense ratio in the golden-set scheme order.
FEE_QUESTIONS: tuple[str, ...] = (
    "What is the exit load on HDFC Mid Cap Fund Direct Growth?",
    "What is the exit load on HDFC Gold ETF Fund of Fund Direct Plan Growth?",
    "What is the exit load on HDFC Large Cap Fund Direct Growth?",
    "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?",
    "What is the expense ratio of HDFC Small Cap Fund Direct Growth?",
    "What is the expense ratio of HDFC Gold ETF Fund of Fund Direct Plan Growth?",
    "What is the expense ratio of HDFC Large Cap Fund Direct Growth?",
    "What is the expense ratio of HDFC ELSS Tax Saver Fund Direct Plan Growth?",
)

_TERM = re.compile(
    "|".join(rf"\b{re.escape(term)}\b" for term in FEE_LEXICON),
    re.IGNORECASE,
)


class FeeThemeResult(BaseModel):
    """Winning theme id, or null when no theme met the bar."""

    model_config = ConfigDict(extra="forbid")

    fee_theme: str | None
    sentence: str | None = None


def select_fee_theme(clusters_path: Path) -> FeeThemeResult:
    """Read ``clusters.json`` and return the winning fee theme, or null."""
    path = Path(clusters_path)
    if path.is_dir():
        path = path / "clusters.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("clusters.json is not an object")
    themes = payload.get("themes")
    if not isinstance(themes, list):
        themes = []

    winner: str | None = None
    winner_count = FEE_FLOOR - 1
    for raw in themes:
        if not isinstance(raw, dict):
            continue
        theme_id = _theme_id(raw)
        count = _member_count(raw)
        if theme_id is None or count < FEE_FLOOR or not _is_fee_theme(raw):
            continue
        if count > winner_count:
            winner = theme_id
            winner_count = count
    if winner is None:
        return FeeThemeResult(fee_theme=None, sentence=NO_FEE_THEME_SENTENCE)
    return FeeThemeResult(fee_theme=winner, sentence=None)


def factual_bullets(
    retriever: Callable[[str], RetrievalBundle],
    *,
    questions: Sequence[str] = FEE_QUESTIONS,
) -> list[ExplainerBullet]:
    """Keep covered, in-passage, Groww-hosted claims. Stop at five links."""
    session = ComplianceSession()
    bullets: list[ExplainerBullet] = []
    for question in questions:
        if len(bullets) >= MAX_FACT_LINKS:
            break
        passages: list[str] = []

        def remembering(text: str, retriever: Callable[[str], RetrievalBundle] = retriever) -> RetrievalBundle:
            bundle = retriever(text)
            for chunk in bundle.chunks:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    passages.append(chunk["text"])
            return bundle

        output = answer_facts(
            question,
            session=session,
            case_id=_FACT_CASE_ID,
            retriever=remembering,
        )
        result = output.result
        if result.coverage is not Coverage.COVERED:
            continue
        for claim in result.answer_facts:
            if len(bullets) >= MAX_FACT_LINKS:
                break
            if not _groww_https(claim.source_url):
                continue
            if not any(claim.claim in passage for passage in passages):
                continue
            checked = (
                claim.last_checked.isoformat()
                if claim.last_checked is not None
                else UNAVAILABLE_LAST_CHECKED
            )
            bullets.append(
                ExplainerBullet(
                    text=claim.claim,
                    url=claim.source_url,
                    last_checked=checked,
                )
            )
    return bullets


class ExplainerOutcome(BaseModel):
    """Whether ``explainer.json`` was written, and the failing gate codes."""

    model_config = ConfigDict(extra="forbid")

    written: bool
    codes: list[str]
    path: str | None = None

    @model_validator(mode="after")
    def path_follows_the_write(self) -> ExplainerOutcome:
        if self.written and (not self.path or self.codes):
            raise ValueError("a written explainer has a path and no failing codes")
        if not self.written and (self.path is not None or not self.codes):
            raise ValueError("a rejected explainer names codes and has no path")
        return self


def ledger_bullet(rows: Sequence[LedgerRow]) -> ExplainerBullet:
    """One last bullet. Empty weeks use the exact corpus sentence."""
    if not rows:
        return ExplainerBullet(text=EMPTY_LEDGER_SENTENCE)
    lines: list[str] = []
    for row in rows:
        lines.append(f"{row.case_id}: {row.sanitized_text}")
        lines.extend(url for url in row.searched_urls if url not in lines)
    return ExplainerBullet(
        text="\n".join(lines),
        case_ids=[row.case_id for row in rows],
    )


def write_explainer(
    run_dir: Path,
    *,
    week_id: str,
    fee_theme: str | None,
    factual: Sequence[ExplainerBullet],
    ledger: Sequence[LedgerRow],
) -> ExplainerOutcome:
    """Write ``explainer.json`` only when every gate passes."""
    bullets = [*factual, ledger_bullet(ledger)]
    codes = bullet_gate_codes(bullets)
    if codes:
        return ExplainerOutcome(written=False, codes=codes)
    explainer = Explainer(week_id=week_id, fee_theme=fee_theme, bullets=bullets)
    path = Path(run_dir) / "explainer.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(explainer.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ExplainerOutcome(written=True, codes=[], path=str(path))


def bullet_gate_codes(bullets: Sequence[ExplainerBullet]) -> list[str]:
    codes: list[str] = []
    for bullet in bullets:
        if requests_advice(bullet.text) or _EXPLAINER_INSTRUCTION.search(bullet.text):
            _add_code(codes, "advice")
        if requests_performance(bullet.text):
            _add_code(codes, "performance")
        if contains_pii(bullet.text):
            _add_code(codes, "pii")
    link_count = sum(1 for bullet in bullets if bullet.url is not None)
    if link_count > MAX_FACT_LINKS:
        _add_code(codes, "links")
    if len(bullets) > MAX_BULLETS:
        _add_code(codes, "bullets")
    return codes


def _add_code(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def _groww_https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "") in _GROWW_HOSTS


def _theme_id(theme: dict) -> str | None:
    for key in ("theme_id", "cluster_key"):
        value = theme.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _member_count(theme: dict) -> int:
    size = theme.get("size")
    if isinstance(size, int) and not isinstance(size, bool):
        return size
    member_count = theme.get("member_count")
    if isinstance(member_count, int) and not isinstance(member_count, bool):
        return member_count
    review_ids = theme.get("review_ids")
    if isinstance(review_ids, list):
        return len([review_id for review_id in review_ids if review_id])
    return 0


def _is_fee_theme(theme: dict) -> bool:
    label = theme.get("label")
    keywords = theme.get("keywords") if isinstance(theme.get("keywords"), list) else []
    parts = [label if isinstance(label, str) else "", *[str(word) for word in keywords]]
    return _TERM.search(" ".join(parts)) is not None
