"""Twenty real Project 2 reviews, stored only after redaction.

Selection uses the filtered export and the latest theme artifact. It does
not invent review text. A row that still matches a PII pattern after
redaction is counted and left out.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from supportdesk.enums import FactsStatus, PatternSignal, WorkflowState
from supportdesk.ids import sha256_text
from supportdesk.pattern import default_paths
from supportdesk.privacy import contains_pii, redact_pii
from supportdesk.reviewer import content_has_pii
from supportdesk.workflow import ContractError

SELECTION_METHOD = (
    "Latest runs directory that contains clusters.json, by directory name. "
    "Window is that file's actual_start through actual_end. "
    "Candidates are theme review_ids that are also in data/exports/play_store.csv "
    "with review_date inside the window, using text_clean. "
    "Themes are ordered by theme_id. Review ids inside a theme are sorted. "
    "Selection round-robins one row per theme. "
    "Empty text and text that still matches a PII pattern after redaction are skipped "
    "and not stored. If theme members run out before 20, the rest are the remaining "
    "in-window CSV rows in review_id order, with the same redaction rule. "
    "Stored text is the redacted text only."
)
EXAMPLE_COUNT = 20
_SOURCE_CSV = "data/exports/play_store.csv"


class SanitizedExample(BaseModel):
    """One real review after redaction. The CSV cell is not retained."""

    model_config = ConfigDict(extra="forbid")

    source_review_id: str = Field(min_length=1)
    review_date: date
    theme_id: str = Field(min_length=1)
    theme_label: str = Field(min_length=1)
    sanitized_text: str = Field(min_length=1)

    def model_post_init(self, _context: object) -> None:
        if contains_pii(self.sanitized_text):
            raise ValueError("sanitized example still matches a PII pattern")


class ExampleSet(BaseModel):
    """The evaluation set and the window it was drawn from."""

    model_config = ConfigDict(extra="forbid")

    selection_method: str
    run_id: str
    window_start: date
    window_end: date
    source_csv: str
    skipped_residual_pii: int = Field(ge=0)
    skipped_empty: int = Field(ge=0)
    examples: list[SanitizedExample]

    def model_post_init(self, _context: object) -> None:
        if len(self.examples) != EXAMPLE_COUNT:
            raise ValueError(f"evaluation set must contain {EXAMPLE_COUNT} examples")
        ids = [item.source_review_id for item in self.examples]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation set repeated a review id")
        for item in self.examples:
            if item.review_date < self.window_start or item.review_date > self.window_end:
                raise ValueError("example date is outside the analysis window")


class MeasuredExample(BaseModel):
    """Safety and routing outcome. Reply text and review text are omitted."""

    model_config = ConfigDict(extra="forbid")

    source_review_id: str
    case_id: str
    input_sha256: str
    workflow_state: str
    facts_status: str | None = None
    facts_coverage: str | None = None
    citation_urls: list[str] = Field(default_factory=list)
    pattern_signal: str | None = None
    matching_count: int | None = None
    window_start: date | None = None
    window_end: date | None = None
    compliance_decision: str | None = None
    reviewer_decision: str | None = None
    rework_count: int = 0
    parallel: bool
    passed: bool
    limitations: list[str] = Field(default_factory=list)


def select_examples(
    *,
    csv_path: Path | None = None,
    runs_dir: Path | None = None,
    run_dir: Path | None = None,
) -> ExampleSet:
    """Choose 20 redacted reviews. Raises if the export or themes are missing."""
    export, runs, _db = default_paths()
    csv_file = csv_path or export
    run_dir = run_dir or _latest_run(runs_dir or runs)
    if run_dir is None:
        raise FileNotFoundError("theme artifact is missing")
    payload = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))
    window_raw = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    start = _date(window_raw.get("actual_start"))
    end = _date(window_raw.get("actual_end"))
    if start is None or end is None:
        raise ContractError("theme artifact has no analysis window")
    themes = _themes(payload)
    rows = _load_csv(csv_file)
    picked, skipped_pii, skipped_empty = _round_robin(themes, rows, start, end)
    if len(picked) < EXAMPLE_COUNT:
        extra, extra_pii, extra_empty = _fill(rows, start, end, {item.source_review_id for item in picked})
        picked.extend(extra)
        skipped_pii += extra_pii
        skipped_empty += extra_empty
    return ExampleSet(
        selection_method=SELECTION_METHOD,
        run_id=run_dir.name,
        window_start=start,
        window_end=end,
        source_csv=_SOURCE_CSV,
        skipped_residual_pii=skipped_pii,
        skipped_empty=skipped_empty,
        examples=picked[:EXAMPLE_COUNT],
    )


async def measure(selected: ExampleSet, *, run_dir: Path | None = None) -> list[MeasuredExample]:
    """Run each sanitized review through orchestration and review."""
    from supportdesk.compliance import ComplianceSession
    from supportdesk.orchestrate import orchestrate
    from supportdesk.reviewer import review_case

    _export, runs, db_path = default_paths()
    directory = run_dir or _latest_run(runs)
    measured: list[MeasuredExample] = []
    for example in selected.examples:
        outcome = await orchestrate(
            example.sanitized_text,
            session=ComplianceSession(),
            run_dir=directory,
            db_path=db_path if db_path.is_file() else None,
        )
        reviewed = review_case(outcome) if outcome.run.state is WorkflowState.DRAFTED else None
        measured.append(_measure_one(example, outcome, reviewed))
    return measured


def _measure_one(example: SanitizedExample, outcome: object, reviewed: object | None) -> MeasuredExample:
    from supportdesk.orchestrate import OrchestrationOutcome
    from supportdesk.reviewer import ReviewedCase

    if not isinstance(outcome, OrchestrationOutcome):
        raise ContractError("measurement expected an orchestration outcome")
    result = outcome.result
    state = outcome.run.state
    rework = outcome.run.rework_count
    reviewer_decision = None
    if isinstance(reviewed, ReviewedCase):
        state = reviewed.run.state
        rework = reviewed.run.rework_count
        result = reviewed.result if reviewed.result is not None else result
        if reviewed.reviews:
            reviewer_decision = reviewed.reviews[-1].decision.value
    limitations: list[str] = []
    if contains_pii(example.sanitized_text):
        limitations.append("input still matches a PII pattern")
    if contains_pii(" ".join(outcome.agent_details)):
        limitations.append("agent detail matched a PII pattern")
    facts_status = None
    coverage = None
    citations: list[str] = []
    signal = None
    count = None
    window_start = None
    window_end = None
    compliance = None
    if result is None:
        if state is not WorkflowState.BLOCKED:
            limitations.append("no reply was stored and the run is not blocked")
    else:
        if content_has_pii(result):
            limitations.append("stored agent prose matches a PII pattern")
        if result.reply.sentence_count > 3:
            limitations.append("reply exceeds three sentences")
        facts = result.facts
        facts_status = facts.status.value
        coverage = facts.coverage.value
        citations = [claim.source_url for claim in facts.answer_facts]
        if facts.status is FactsStatus.SUPPORTED:
            if not facts.answer_facts:
                limitations.append("supported facts have no claim")
            for claim in facts.answer_facts:
                if claim.claim not in claim.evidence:
                    limitations.append("claim is not contained in the evidence")
                if not claim.source_url.startswith("https://groww.in/") and not claim.source_url.startswith(
                    "https://www.groww.in/"
                ):
                    limitations.append("citation host is not approved")
        elif facts.status is FactsStatus.NOT_COVERED and facts.answer_facts:
            limitations.append("not_covered facts include a claim")
        pattern = result.pattern
        signal = pattern.signal.value
        count = pattern.matching_count
        window_start = pattern.analysis_window.start
        window_end = pattern.analysis_window.end
        if pattern.signal is PatternSignal.RISING and (
            not pattern.comparable_periods or window_start is None or window_end is None
        ):
            limitations.append("rising without comparable periods")
        compliance = result.compliance.decision.value
    parallel = _parallel(outcome.run.executions)
    if not parallel:
        limitations.append("execution intervals did not overlap")
    return MeasuredExample(
        source_review_id=example.source_review_id,
        case_id=outcome.run.case_id,
        input_sha256=sha256_text(example.sanitized_text),
        workflow_state=state.value,
        facts_status=facts_status,
        facts_coverage=coverage,
        citation_urls=citations,
        pattern_signal=signal,
        matching_count=count,
        window_start=window_start,
        window_end=window_end,
        compliance_decision=compliance,
        reviewer_decision=reviewer_decision,
        rework_count=rework,
        parallel=parallel,
        passed=not limitations,
        limitations=limitations,
    )


def _parallel(executions: list[object]) -> bool:
    if len(executions) < 3:
        return False
    starts: list[datetime] = []
    ends: list[datetime] = []
    for item in executions:
        started = getattr(item, "started_at", None)
        ended = getattr(item, "ended_at", None)
        if not isinstance(started, datetime) or not isinstance(ended, datetime):
            return False
        starts.append(started)
        ends.append(ended)
    return max(starts) <= min(ends)


def _round_robin(
    themes: list[tuple[str, str, list[str]]],
    rows: dict[str, tuple[date | None, str]],
    start: date,
    end: date,
) -> tuple[list[SanitizedExample], int, int]:
    buckets: list[tuple[str, str, list[tuple[str, date, str]]]] = []
    for theme_id, label, review_ids in themes:
        members: list[tuple[str, date, str]] = []
        for review_id in review_ids:
            row = rows.get(review_id)
            if row is None or row[0] is None or row[0] < start or row[0] > end:
                continue
            members.append((review_id, row[0], row[1]))
        if members:
            buckets.append((theme_id, label, members))
    picked: list[SanitizedExample] = []
    skipped_pii = 0
    skipped_empty = 0
    cursors = [0] * len(buckets)
    while len(picked) < EXAMPLE_COUNT:
        progressed = False
        for index, (theme_id, label, members) in enumerate(buckets):
            if cursors[index] >= len(members):
                continue
            review_id, reviewed_on, text = members[cursors[index]]
            cursors[index] += 1
            progressed = True
            example, pii, empty = _accept(review_id, reviewed_on, text, theme_id, label)
            skipped_pii += pii
            skipped_empty += empty
            if example is not None:
                picked.append(example)
            if len(picked) == EXAMPLE_COUNT:
                break
        if not progressed:
            break
    return picked, skipped_pii, skipped_empty


def _fill(
    rows: dict[str, tuple[date | None, str]],
    start: date,
    end: date,
    seen: set[str],
) -> tuple[list[SanitizedExample], int, int]:
    picked: list[SanitizedExample] = []
    skipped_pii = 0
    skipped_empty = 0
    for review_id in sorted(rows):
        if review_id in seen:
            continue
        reviewed_on, text = rows[review_id]
        if reviewed_on is None or reviewed_on < start or reviewed_on > end:
            continue
        example, pii, empty = _accept(review_id, reviewed_on, text, "unassigned", "no theme")
        skipped_pii += pii
        skipped_empty += empty
        if example is None:
            continue
        picked.append(example)
        seen.add(review_id)
        if len(picked) == EXAMPLE_COUNT:
            break
    return picked, skipped_pii, skipped_empty


def _accept(
    review_id: str,
    reviewed_on: date,
    text: str,
    theme_id: str,
    label: str,
) -> tuple[SanitizedExample | None, int, int]:
    if not text.strip():
        return None, 0, 1
    redaction = redact_pii(text)
    if not redaction.sanitized or not redaction.text.strip() or contains_pii(redaction.text):
        return None, 1, 0
    return (
        SanitizedExample(
            source_review_id=review_id,
            review_date=reviewed_on,
            theme_id=theme_id,
            theme_label=label,
            sanitized_text=redaction.text,
        ),
        0,
        0,
    )


def _themes(payload: object) -> list[tuple[str, str, list[str]]]:
    if not isinstance(payload, dict):
        raise ContractError("clusters.json is not an object")
    found: list[tuple[str, str, list[str]]] = []
    for raw in payload.get("themes") or []:
        if not isinstance(raw, dict):
            continue
        theme_id = str(raw.get("theme_id") or raw.get("cluster_key") or "").strip()
        label = str(raw.get("label") or theme_id).strip()
        review_ids = raw.get("review_ids") if isinstance(raw.get("review_ids"), list) else []
        ids = sorted({str(item) for item in review_ids if item})
        if theme_id and ids:
            found.append((theme_id, label or theme_id, ids))
    found.sort(key=lambda item: item[0])
    if not found:
        raise ContractError("clusters.json has no themes")
    return found


def _load_csv(path: Path) -> dict[str, tuple[date | None, str]]:
    if not path.is_file():
        raise FileNotFoundError("export CSV is missing")
    rows: dict[str, tuple[date | None, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "review_id" not in reader.fieldnames:
            raise ValueError("export CSV has no review_id column")
        if "text_clean" not in reader.fieldnames:
            raise ValueError("export CSV has no text_clean column")
        for raw in reader:
            review_id = str(raw.get("review_id") or "").strip()
            if not review_id or review_id in rows:
                continue
            rows[review_id] = (_date(raw.get("review_date")), str(raw.get("text_clean") or ""))
    return rows


def _latest_run(runs_dir: Path) -> Path | None:
    if not runs_dir.is_dir():
        return None
    found = [path for path in runs_dir.iterdir() if (path / "clusters.json").is_file()]
    if not found:
        return None
    return max(found, key=lambda path: path.name)


def _date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
