"""Play Store public export adapter (CSV / JSON).

Default column mapping (Google Play Console-style exports):
  Review ID      -> external_id
  Review Title   -> title
  Review Text    -> text
  Star Rating    -> rating
  Review Date    -> date
  Reviewer Name  -> author (dropped at scrub stage, never stored)

Override headers via config/settings.toml [ingest.columns].
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from reviewpulse.config import ColumnMapping
from reviewpulse.models import RawReview
from reviewpulse.sources.base import ReviewSource
from reviewpulse.sources.normalize import filter_window, normalize_raw_review


class PlayExportSource:
    """Read reviews from a local Play Store export file."""

    def __init__(self, path: Path, columns: ColumnMapping | None = None) -> None:
        self.path = path
        self.columns = columns or ColumnMapping()

    def fetch(self, window_start: date, window_end: date) -> Iterable[RawReview]:
        for raw in self.parse_all():
            if filter_window(raw, window_start, window_end):
                yield raw

    def parse_all(self) -> Iterable[RawReview]:
        """Parse every valid row from the export (no window filter)."""
        for row in self._load_rows():
            raw = self._row_to_raw(row)
            if raw is None:
                continue
            normalized = normalize_raw_review(raw)
            if normalized is None:
                continue
            yield normalized

    def _load_rows(self) -> list[dict[str, Any]]:
        suffix = self.path.suffix.lower()
        if suffix == ".json":
            return self._load_json()
        if suffix == ".csv":
            return self._load_csv()
        raise ValueError(
            f"Unsupported export format '{suffix}'. Use .csv or .json: {self.path}"
        )

    def _load_csv(self) -> list[dict[str, str]]:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                with self.path.open(encoding=encoding, newline="") as handle:
                    reader = csv.DictReader(handle)
                    if not reader.fieldnames:
                        raise ValueError(f"CSV has no header row: {self.path}")
                    return [dict(row) for row in reader]
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode CSV with supported encodings: {self.path}")

    def _load_json(self) -> list[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("reviews"), list):
            return [item for item in payload["reviews"] if isinstance(item, dict)]
        raise ValueError(f"JSON export must be a list or {{'reviews': [...]}}: {self.path}")

    def _row_to_raw(self, row: dict[str, Any]) -> RawReview | None:
        mapping = self._resolve_columns(row)
        text = _clean_str(row.get(mapping.text))
        title = _clean_str(row.get(mapping.title))
        if not text and title:
            text = title
        if not text:
            return None

        rating = _parse_rating(row.get(mapping.rating))
        review_date = _parse_date(row.get(mapping.date))
        if review_date is None:
            return None

        return RawReview(
            source="play",
            external_id=_clean_str(row.get(mapping.external_id)),
            rating=rating,
            title=title,
            text=text,
            date=review_date,
            author=_clean_str(row.get(mapping.author)),
        )

    def _resolve_columns(self, row: dict[str, Any]) -> ColumnMapping:
        """Match configured columns to actual row keys (case-insensitive)."""
        lower_map = {key.lower(): key for key in row}
        cols = self.columns

        def resolve(name: str) -> str:
            if name in row:
                return name
            return lower_map.get(name.lower(), name)

        return ColumnMapping(
            text=resolve(cols.text),
            title=resolve(cols.title),
            rating=resolve(cols.rating),
            date=resolve(cols.date),
            external_id=resolve(cols.external_id),
            author=resolve(cols.author),
        )


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_rating(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        rating = int(float(str(value).strip()))
    except ValueError:
        return None
    return max(1, min(5, rating))


def _parse_date(value: Any):
    from reviewpulse.sources.normalize import parse_datetime

    if value is None or value == "":
        return None
    return parse_datetime(str(value).strip())


# Satisfy structural typing for ReviewSource users.
def as_review_source(source: PlayExportSource) -> ReviewSource:
    return source
