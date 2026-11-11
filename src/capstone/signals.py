"""Five-times queue signals from the question log.

Review volume in ``clusters.json`` cannot create a signal. This module does
not call a model, edit ``note.md``, or change a customer draft.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from capstone.contracts import PatternWindow, QuestionLogRow, SupportSignal
from capstone.identity import counts_for_signal
from capstone.log import LogStore

SIGNAL_TEMPLATE = (
    'Support was asked "{question_key}" {count} times in {week_id}. '
    "This line is the question log, not review volume."
)


def render_signal(signal: SupportSignal) -> str:
    """Fill the fixed template from the queue record. No model call."""
    return SIGNAL_TEMPLATE.format(
        question_key=signal.question_key,
        count=signal.count,
        week_id=signal.week_id,
    )


def queue_signals(
    rows: Sequence[QuestionLogRow],
    *,
    cases: Mapping[str, Mapping[str, object] | None] | None = None,
    clusters: object | None = None,
) -> list[SupportSignal]:
    """Group one week's log rows. ``clusters`` is ignored: it is not queue evidence."""
    del clusters
    if not rows:
        return []
    grouped: dict[str, list[QuestionLogRow]] = defaultdict(list)
    for row in rows:
        if not counts_for_signal(row.question_key):
            continue
        grouped[row.question_key].append(row)
    signals: list[SupportSignal] = []
    for key in sorted(grouped):
        group = grouped[key]
        if len(group) < 5:
            continue
        signals.append(_signal(group, cases or {}))
    return signals


def queue_signals_for_week(
    store: LogStore,
    week_id: str,
    *,
    clusters: object | None = None,
) -> list[SupportSignal]:
    """Read one week from the log and build queue signals."""
    rows = store.list_by_week(week_id)
    cases = {row.case_id: store.fetch_case(row.case_id) for row in rows}
    return queue_signals(rows, cases=cases, clusters=clusters)


def write_support_signals(run_dir: Path, signals: Sequence[SupportSignal]) -> Path:
    """Write ``support_signals.json``. An empty list is a valid file."""
    path = run_dir / "support_signals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [signal.model_dump(mode="json") for signal in signals]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_support_signals(path: Path) -> list[SupportSignal]:
    """Load a signal file through the contract model."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("support_signals.json must be a list")
    return [SupportSignal.model_validate(item) for item in loaded]


def _signal(
    group: Sequence[QuestionLogRow],
    cases: Mapping[str, Mapping[str, object] | None],
) -> SupportSignal:
    week_id = group[0].week_id
    key = group[0].question_key
    theme_ids = {row.theme_id for row in group}
    theme_id = next(iter(theme_ids)) if len(theme_ids) == 1 and None not in theme_ids else None
    pattern_signal, pattern_count, window = _shared_pattern(group, cases)
    return SupportSignal(
        week_id=week_id,
        question_key=key,
        count=len(group),
        case_ids=sorted(row.case_id for row in group),
        theme_id=theme_id,
        evidence_type="queue",
        pattern_signal=pattern_signal,
        pattern_count=pattern_count,
        analysis_window=window,
    )


def _shared_pattern(
    group: Sequence[QuestionLogRow],
    cases: Mapping[str, Mapping[str, object] | None],
) -> tuple[str | None, int | None, PatternWindow | None]:
    views = [_pattern_view(cases.get(row.case_id)) for row in group]
    if any(view is None for view in views):
        return None, None, None
    first = views[0]
    if any(view != first for view in views):
        return None, None, None
    assert first is not None
    return first


def _pattern_view(
    payload: Mapping[str, object] | None,
) -> tuple[str, int, PatternWindow | None] | None:
    if not isinstance(payload, Mapping):
        return None
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return None
    pattern = result.get("pattern")
    if not isinstance(pattern, Mapping):
        return None
    if "signal" not in pattern or "matching_count" not in pattern or "analysis_window" not in pattern:
        return None
    signal = pattern.get("signal")
    count = pattern.get("matching_count")
    window = pattern.get("analysis_window")
    if not isinstance(signal, str) or isinstance(count, bool) or not isinstance(count, int):
        return None
    if window is None:
        return signal, count, None
    if not isinstance(window, Mapping):
        return None
    start = window.get("start")
    end = window.get("end")
    if start is not None and not isinstance(start, str):
        return None
    if end is not None and not isinstance(end, str):
        return None
    return signal, count, PatternWindow(start=start, end=end)
