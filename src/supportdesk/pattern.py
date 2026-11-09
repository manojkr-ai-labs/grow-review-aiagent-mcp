"""Pattern Agent.

Counts theme membership in the filtered Project 2 export. It does not
re-cluster, and it does not treat Project 2 ``emerging`` as ``rising``.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from supportdesk.compliance import ComplianceInspection, ComplianceSession
from supportdesk.contracts import AnalysisWindow, PatternEvidence, PatternResult
from supportdesk.enums import ComplianceDecision, PatternSignal, PatternStatus
from supportdesk.ids import new_execution_id
from supportdesk.privacy import contains_pii

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "is",
        "it",
        "my",
        "me",
        "with",
        "this",
        "that",
        "was",
        "were",
        "are",
        "be",
        "been",
        "am",
        "we",
        "you",
        "at",
        "from",
        "by",
        "as",
        "if",
        "so",
        "but",
        "not",
        "no",
        "do",
        "did",
        "have",
        "has",
        "had",
        "just",
        "very",
        "please",
    }
)
_METHOD = (
    "Stemmed token overlap of at least {threshold} tokens between the redacted "
    "message and a theme label plus its keywords. The count is the number of "
    "distinct matched review_ids that are in the export CSV with a parseable "
    "date inside the artifact window. A ReviewStore, when used, must contain "
    "the same id. early/late uses dates on or before versus after "
    "window_end minus {weeks} weeks. rising requires early > 0, late > 0, "
    "count >= {floor}, and round(late/early, 2) >= {ratio}. The emerging flag "
    "is not used."
)


class PatternAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: PatternResult
    inspection: ComplianceInspection


@dataclass(frozen=True)
class _Theme:
    theme_id: str
    label: str
    tokens: frozenset[str]
    review_ids: tuple[str, ...]
    debug_early: int | None
    debug_late: int | None


@dataclass(frozen=True)
class _Window:
    start: date | None
    end: date | None
    split_end: date | None
    run_id: str


@dataclass(frozen=True)
class _Row:
    review_id: str
    reviewed_on: date | None
    text: str


def default_paths() -> tuple[Path, Path, Path]:
    """Export CSV, runs directory, and reviews database under this repository."""
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "exports" / "play_store.csv", root / "runs", root / "data" / "reviews.db"


def answer_pattern(
    message: str,
    *,
    session: ComplianceSession,
    case_id: str,
    execution_id: str | None = None,
    csv_path: Path | None = None,
    runs_dir: Path | None = None,
    run_dir: Path | None = None,
    db_path: Path | None = None,
    cluster_size_floor: int = 3,
    trend_split_weeks: int = 4,
    emerging_trend_ratio: float = 1.5,
    match_threshold: int = 2,
) -> PatternAgentOutput:
    """Match ``message`` to generated themes after compliance redaction."""
    pattern_execution = execution_id or new_execution_id()
    inspection = session.inspect(message, case_id=case_id)
    if inspection.result.decision is ComplianceDecision.BLOCK or not inspection.redacted_text:
        return _done(
            inspection,
            _empty(
                pattern_execution,
                PatternStatus.ERROR,
                [inspection.result.safe_handling or "message was blocked before pattern matching"],
            ),
        )
    redacted = inspection.redacted_text
    if contains_pii(redacted):
        return _done(
            inspection,
            _empty(
                pattern_execution,
                PatternStatus.ERROR,
                ["redacted text still matched a PII pattern; reviews were not queried"],
            ),
        )

    export, runs, store = default_paths()
    csv_file = csv_path or export
    explicit = csv_path is not None or runs_dir is not None or run_dir is not None
    store_path = db_path if db_path is not None else (None if explicit else store)
    try:
        themes, window = _load_themes(run_dir=run_dir, runs_dir=runs_dir or runs)
        rows = _load_csv(csv_file)
    except FileNotFoundError as exc:
        return _done(
            inspection,
            _empty(pattern_execution, PatternStatus.INSUFFICIENT_DATA, [str(exc)]),
        )
    except (json.JSONDecodeError, ValueError, csv.Error) as exc:
        return _done(
            inspection,
            _empty(pattern_execution, PatternStatus.ERROR, [f"pattern inputs could not be read: {type(exc).__name__}"]),
        )

    return _done(
        inspection,
        _classify(
            redacted,
            themes,
            rows,
            window,
            store_path=store_path,
            floor=cluster_size_floor,
            weeks=trend_split_weeks,
            ratio=emerging_trend_ratio,
            threshold=match_threshold,
            execution_id=pattern_execution,
        ),
    )


def _classify(
    text: str,
    themes: list[_Theme],
    rows: dict[str, _Row],
    window: _Window,
    *,
    store_path: Path | None,
    floor: int,
    weeks: int,
    ratio: float,
    threshold: int,
    execution_id: str,
) -> PatternResult:
    method = _METHOD.format(threshold=threshold, weeks=weeks, floor=floor, ratio=ratio)
    limitations = [f"theme run {window.run_id}", method]
    analysis = AnalysisWindow(start=window.start, end=window.end)
    if window.start is None or window.end is None:
        limitations.append("analysis window is missing from the theme artifact")
        return _result(
            PatternStatus.INSUFFICIENT_DATA,
            PatternSignal.INSUFFICIENT_DATA,
            0,
            analysis,
            [],
            [],
            limitations,
            False,
            execution_id,
        )
    if not rows:
        limitations.append("export CSV has no review rows")
        return _result(
            PatternStatus.INSUFFICIENT_DATA,
            PatternSignal.INSUFFICIENT_DATA,
            0,
            analysis,
            [],
            [],
            limitations,
            False,
            execution_id,
        )

    asked = _tokens(text)
    scored = [(len(asked & theme.tokens), theme) for theme in themes]
    matched = [theme for score, theme in scored if score >= threshold]
    matched.sort(key=lambda theme: (-len(asked & theme.tokens), -len(theme.review_ids), theme.theme_id))
    if not matched:
        limitations.append("no theme reached the token-overlap threshold")
        return _result(
            PatternStatus.INSUFFICIENT_DATA,
            PatternSignal.INSUFFICIENT_DATA,
            0,
            analysis,
            [],
            [],
            limitations,
            False,
            execution_id,
        )

    member_ids: list[str] = []
    seen: set[str] = set()
    for theme in matched:
        for review_id in theme.review_ids:
            if review_id not in seen:
                seen.add(review_id)
                member_ids.append(review_id)

    owners = {review_id: theme.theme_id for theme in reversed(matched) for review_id in theme.review_ids}
    missing_from_csv = 0
    undated = 0
    outside = 0
    counted: list[tuple[str, _Row]] = []
    for review_id in member_ids:
        row = rows.get(review_id)
        if row is None:
            missing_from_csv += 1
            continue
        if row.reviewed_on is None:
            undated += 1
            continue
        if row.reviewed_on < window.start or row.reviewed_on > window.end:
            outside += 1
            continue
        counted.append((owners[review_id], row))

    if store_path is not None and not store_path.is_file():
        limitations.append("review store was not available; count is from the export CSV only")
    elif store_path is not None:
        counted, dropped = _apply_store(counted, store_path)
        if dropped:
            limitations.append(f"{dropped} csv ids were not in the review store")
    if missing_from_csv:
        limitations.append(f"{missing_from_csv} theme member ids were not in the export CSV")
    if undated:
        limitations.append(f"{undated} matched rows had no parseable review date")
    if outside:
        limitations.append(f"{outside} matched rows were outside the analysis window")

    names = [f"{theme.theme_id}: {theme.label}" for theme in matched]
    evidence = _evidence(counted, asked)
    count = len(counted)
    early, late, split_on = _periods(counted, window.split_end or window.end, weeks)
    comparable = early > 0 and late > 0
    trend = round(late / early, 2) if early else None
    limitations.append(
        f"early={early} late={late} split={split_on.isoformat()} "
        f"ratio={'none' if trend is None else trend}"
    )
    primary = matched[0]
    if primary.debug_early is not None or primary.debug_late is not None:
        limitations.append(
            "cluster_debug counts are not the rising test; "
            f"debug early={primary.debug_early} late={primary.debug_late}"
        )

    signal = _signal(count, floor, comparable, trend, ratio)
    status = (
        PatternStatus.INSUFFICIENT_DATA
        if signal is PatternSignal.INSUFFICIENT_DATA
        else PatternStatus.SUCCESS
    )
    if signal is PatternSignal.RECURRING and not comparable:
        limitations.append("early period is empty, so the theme is not classified as rising")
    return _result(
        status,
        signal,
        count,
        analysis,
        names,
        evidence,
        limitations,
        comparable,
        execution_id,
    )


def _signal(
    count: int,
    floor: int,
    comparable: bool,
    trend: float | None,
    ratio: float,
) -> PatternSignal:
    if count <= 0:
        return PatternSignal.INSUFFICIENT_DATA
    if count == 1:
        return PatternSignal.ONE_OFF
    if count < floor:
        return PatternSignal.INSUFFICIENT_DATA
    if comparable and trend is not None and trend >= ratio:
        return PatternSignal.RISING
    return PatternSignal.RECURRING


def _periods(rows: list[tuple[str, _Row]], split_end: date, weeks: int) -> tuple[int, int, date]:
    split_on = split_end - timedelta(weeks=weeks)
    late = sum(1 for _theme, row in rows if row.reviewed_on is not None and row.reviewed_on > split_on)
    early = len(rows) - late
    return early, late, split_on


def _apply_store(
    rows: list[tuple[str, _Row]],
    store_path: Path,
) -> tuple[list[tuple[str, _Row]], int]:
    from reviewpulse.store.sqlite import ReviewStore

    found = {
        review.review_id
        for review in ReviewStore(store_path).get_by_ids([row.review_id for _theme, row in rows])
    }
    kept = [item for item in rows if item[1].review_id in found]
    return kept, len(rows) - len(kept)


def _evidence(rows: list[tuple[str, _Row]], asked: set[str]) -> list[PatternEvidence]:
    ranked = sorted(
        rows,
        key=lambda item: (-len(asked & _tokens(item[1].text)), item[1].review_id),
    )
    evidence: list[PatternEvidence] = []
    for theme_id, row in ranked:
        if len(evidence) == 3:
            break
        snippet = row.text.strip()
        if len(snippet) > 280:
            snippet = snippet[:280]
        if not snippet or contains_pii(snippet):
            evidence.append(PatternEvidence(theme_id=theme_id, review_id=row.review_id, snippet=None))
            continue
        evidence.append(PatternEvidence(theme_id=theme_id, review_id=row.review_id, snippet=snippet))
    return evidence


def _load_themes(*, run_dir: Path | None, runs_dir: Path) -> tuple[list[_Theme], _Window]:
    directory = run_dir or _latest_run(runs_dir)
    if directory is None or not (directory / "clusters.json").is_file():
        raise FileNotFoundError("theme artifact is missing")
    payload = json.loads((directory / "clusters.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("clusters.json is not an object")
    debug = _debug_counts(directory / "cluster_debug.json")
    window_raw = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    start = _date(window_raw.get("actual_start")) or _date(window_raw.get("requested_start"))
    end = _date(window_raw.get("actual_end")) or _date(window_raw.get("requested_end"))
    split_end = _date(window_raw.get("requested_end")) or end
    themes: list[_Theme] = []
    for raw in payload.get("themes") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        theme_id = str(raw.get("theme_id") or raw.get("cluster_key") or label)
        keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
        review_ids = raw.get("review_ids") if isinstance(raw.get("review_ids"), list) else []
        key = str(raw.get("cluster_key") or "")
        early, late = debug.get(key) or debug.get(label.casefold()) or (None, None)
        themes.append(
            _Theme(
                theme_id=theme_id,
                label=label or theme_id,
                tokens=_tokens(" ".join([label, *[str(word) for word in keywords]])),
                review_ids=tuple(str(review_id) for review_id in review_ids if review_id),
                debug_early=early,
                debug_late=late,
            )
        )
    if not themes:
        raise ValueError("clusters.json has no themes")
    return themes, _Window(start=start, end=end, split_end=split_end, run_id=directory.name)


def _debug_counts(path: Path) -> dict[str, tuple[int | None, int | None]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, tuple[int | None, int | None]] = {}
    clusters = payload.get("clusters") if isinstance(payload, dict) else None
    if not isinstance(clusters, list):
        return {}
    for raw in clusters:
        if not isinstance(raw, dict):
            continue
        pair = (_optional_int(raw.get("early_count")), _optional_int(raw.get("late_count")))
        key = str(raw.get("cluster_key") or "")
        label = str(raw.get("label") or "").casefold()
        if key:
            found[key] = pair
        if label:
            found[label] = pair
    return found


def _latest_run(runs_dir: Path) -> Path | None:
    if not runs_dir.is_dir():
        return None
    found = [path for path in runs_dir.iterdir() if (path / "clusters.json").is_file()]
    if not found:
        return None
    return max(found, key=lambda path: path.name)


def _load_csv(path: Path) -> dict[str, _Row]:
    if not path.is_file():
        raise FileNotFoundError("export CSV is missing")
    rows: dict[str, _Row] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "review_id" not in reader.fieldnames:
            raise ValueError("export CSV has no review_id column")
        for raw in reader:
            review_id = str(raw.get("review_id") or "").strip()
            if not review_id or review_id in rows:
                continue
            rows[review_id] = _Row(
                review_id=review_id,
                reviewed_on=_date(raw.get("review_date")),
                text=str(raw.get("text_clean") or ""),
            )
    return rows


def _tokens(text: str) -> set[str]:
    stems: set[str] = set()
    for token in _TOKEN.findall(text.casefold()):
        if token in _STOP or len(token) < 3:
            continue
        stems.add(_stem(token))
    return stems


def _stem(token: str) -> str:
    for suffix in ("ing", "es", "ed", "s", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _empty(execution_id: str, status: PatternStatus, limitations: list[str]) -> PatternResult:
    signal = PatternSignal.INSUFFICIENT_DATA
    return _result(status, signal, 0, AnalysisWindow(), [], [], limitations, False, execution_id)


def _result(
    status: PatternStatus,
    signal: PatternSignal,
    count: int,
    window: AnalysisWindow,
    themes: list[str],
    evidence: list[PatternEvidence],
    limitations: list[str],
    comparable: bool,
    execution_id: str,
) -> PatternResult:
    return PatternResult(
        status=status,
        signal=signal,
        matching_count=count,
        analysis_window=window,
        matched_themes=themes,
        evidence=evidence,
        method=limitations[1] if len(limitations) > 1 and status is not PatternStatus.ERROR else _short_method(limitations),
        limitations=limitations,
        comparable_periods=comparable,
        execution_id=execution_id,
    )


def _short_method(limitations: list[str]) -> str:
    for item in limitations:
        if item.startswith("Stemmed token overlap"):
            return item
    return "Pattern matching did not run."


def _done(inspection: ComplianceInspection, result: PatternResult) -> PatternAgentOutput:
    return PatternAgentOutput(result=result, inspection=inspection)
