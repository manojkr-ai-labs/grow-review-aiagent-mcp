"""SQLite question log, not-covered ledger, and desk-case durability.

The default file is ``data/capstone.db``. Tests pass a temporary path.
This module does not call the facts agent or write an explainer.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from capstone.contracts import LedgerRow, QuestionLogRow

DEFAULT_DB_PATH = Path("data/capstone.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS question_log (
    case_id TEXT PRIMARY KEY,
    week_id TEXT NOT NULL,
    question_key TEXT NOT NULL,
    sanitized_text TEXT NOT NULL,
    facts_coverage TEXT NOT NULL CHECK (facts_coverage IN ('covered', 'not_covered')),
    searched_urls TEXT NOT NULL,
    theme_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS not_covered_ledger (
    case_id TEXT PRIMARY KEY,
    week_id TEXT NOT NULL,
    sanitized_text TEXT NOT NULL,
    searched_urls TEXT NOT NULL,
    theme_id TEXT,
    FOREIGN KEY (case_id) REFERENCES question_log(case_id)
);

CREATE TABLE IF NOT EXISTS desk_cases (
    case_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class LogStore:
    """Append sanitized questions and read them back by week or case id."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def append(self, row: QuestionLogRow) -> None:
        """Insert or update one log row. A not-covered row copies the ledger in the same transaction."""
        if not isinstance(row, QuestionLogRow):
            row = QuestionLogRow.model_validate(row)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO question_log (
                    case_id, week_id, question_key, sanitized_text,
                    facts_coverage, searched_urls, theme_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    week_id = excluded.week_id,
                    question_key = excluded.question_key,
                    sanitized_text = excluded.sanitized_text,
                    facts_coverage = excluded.facts_coverage,
                    searched_urls = excluded.searched_urls,
                    theme_id = excluded.theme_id,
                    created_at = excluded.created_at
                """,
                (
                    row.case_id,
                    row.week_id,
                    row.question_key,
                    row.sanitized_text,
                    row.facts_coverage,
                    _dump_urls(row.searched_urls),
                    row.theme_id,
                    row.created_at.isoformat(),
                ),
            )
            if row.facts_coverage == "not_covered":
                conn.execute(
                    """
                    INSERT INTO not_covered_ledger (
                        case_id, week_id, sanitized_text, searched_urls, theme_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET
                        week_id = excluded.week_id,
                        sanitized_text = excluded.sanitized_text,
                        searched_urls = excluded.searched_urls,
                        theme_id = excluded.theme_id
                    """,
                    (
                        row.case_id,
                        row.week_id,
                        row.sanitized_text,
                        _dump_urls(row.searched_urls),
                        row.theme_id,
                    ),
                )
            else:
                conn.execute(
                    "DELETE FROM not_covered_ledger WHERE case_id = ?",
                    (row.case_id,),
                )

    def list_by_week(self, week_id: str) -> list[QuestionLogRow]:
        with self._connect() as conn:
            found = conn.execute(
                """
                SELECT case_id, week_id, question_key, sanitized_text,
                       facts_coverage, searched_urls, theme_id, created_at
                FROM question_log
                WHERE week_id = ?
                ORDER BY created_at, case_id
                """,
                (week_id,),
            ).fetchall()
        return [_log_row(item) for item in found]

    def fetch(self, case_id: str) -> QuestionLogRow | None:
        with self._connect() as conn:
            found = conn.execute(
                """
                SELECT case_id, week_id, question_key, sanitized_text,
                       facts_coverage, searched_urls, theme_id, created_at
                FROM question_log
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()
        if found is None:
            return None
        return _log_row(found)

    def fetch_ledger(self, case_id: str) -> LedgerRow | None:
        with self._connect() as conn:
            found = conn.execute(
                """
                SELECT case_id, week_id, sanitized_text, searched_urls, theme_id
                FROM not_covered_ledger
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()
        if found is None:
            return None
        return _ledger_row(found)

    def list_ledger(self, week_id: str) -> list[LedgerRow]:
        with self._connect() as conn:
            found = conn.execute(
                """
                SELECT case_id, week_id, sanitized_text, searched_urls, theme_id
                FROM not_covered_ledger
                WHERE week_id = ?
                ORDER BY case_id
                """,
                (week_id,),
            ).fetchall()
        return [_ledger_row(item) for item in found]

    def save_case(self, payload: Mapping[str, object], *, updated_at: datetime) -> str:
        """Store one sanitized case blob. The desk model is imported only to validate it."""
        if updated_at.tzinfo is None or updated_at.tzinfo.utcoffset(updated_at) is None:
            raise ValueError("updated_at must be timezone-aware")
        from supportdesk.decisions import DeskCase

        case = DeskCase.model_validate(payload)
        body = json.dumps(
            case.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        case_id = case.run.case_id
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO desk_cases (case_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (case_id, body, updated_at.isoformat()),
            )
        return case_id

    def list_case_ids(self) -> list[str]:
        """Case ids in the desk table, oldest update first. The schema is unchanged."""
        with self._connect() as conn:
            found = conn.execute(
                "SELECT case_id FROM desk_cases ORDER BY updated_at, case_id"
            ).fetchall()
        return [str(row["case_id"]) for row in found]

    def fetch_case(self, case_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            found = conn.execute(
                "SELECT payload FROM desk_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if found is None:
            return None
        loaded = json.loads(found["payload"])
        if not isinstance(loaded, dict):
            raise ValueError("desk case payload must be a JSON object")
        return loaded

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _dump_urls(urls: list[str]) -> str:
    return json.dumps(urls, ensure_ascii=False, separators=(",", ":"))


def _log_row(row: sqlite3.Row) -> QuestionLogRow:
    return QuestionLogRow(
        case_id=row["case_id"],
        week_id=row["week_id"],
        question_key=row["question_key"],
        sanitized_text=row["sanitized_text"],
        facts_coverage=row["facts_coverage"],
        searched_urls=json.loads(row["searched_urls"]),
        theme_id=row["theme_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _ledger_row(row: sqlite3.Row) -> LedgerRow:
    return LedgerRow(
        case_id=row["case_id"],
        week_id=row["week_id"],
        sanitized_text=row["sanitized_text"],
        searched_urls=json.loads(row["searched_urls"]),
        theme_id=row["theme_id"],
    )
