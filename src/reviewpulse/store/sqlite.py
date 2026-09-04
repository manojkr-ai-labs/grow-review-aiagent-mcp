"""SQLite persistence for scrubbed reviews."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path

from reviewpulse.models import RawReview, Review


class ReviewStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    rating INTEGER,
                    title_clean TEXT,
                    text_clean TEXT NOT NULL,
                    review_date TEXT NOT NULL,
                    lang TEXT,
                    scrub_flags TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(review_date)"
            )

    def upsert(self, review: Review) -> bool:
        """Insert review; return True if new row, False if duplicate."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reviews (
                    review_id, source, rating, title_clean, text_clean,
                    review_date, lang, scrub_flags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO NOTHING
                """,
                (
                    review.review_id,
                    review.source,
                    review.rating,
                    review.title_clean,
                    review.text_clean,
                    _format_datetime(review.date),
                    review.lang,
                    json.dumps(review.scrub_flags),
                ),
            )
            return cursor.rowcount > 0

    def upsert_many(self, reviews: list[Review]) -> tuple[int, int]:
        inserted = 0
        deduped = 0
        for review in reviews:
            if self.upsert(review):
                inserted += 1
            else:
                deduped += 1
        return inserted, deduped

    def get_reviews(self, window_start: date, window_end: date) -> list[Review]:
        start = _format_date(window_start)
        end = _format_date(window_end)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reviews
                WHERE substr(review_date, 1, 10) >= ?
                  AND substr(review_date, 1, 10) <= ?
                ORDER BY review_date DESC
                """,
                (start, end),
            ).fetchall()
        return [_row_to_review(row) for row in rows]

    def get_all(self) -> list[Review]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reviews ORDER BY review_date DESC"
            ).fetchall()
        return [_row_to_review(row) for row in rows]

    def get_by_id(self, review_id: str) -> Review | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return _row_to_review(row) if row else None

    def get_by_ids(self, review_ids: Sequence[str]) -> list[Review]:
        ids = [rid for rid in review_ids if rid]
        if not ids:
            return []
        found: dict[str, Review] = {}
        with self._connect() as conn:
            for offset in range(0, len(ids), 400):
                chunk = ids[offset : offset + 400]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT * FROM reviews WHERE review_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    review = _row_to_review(row)
                    found[review.review_id] = review
        return [found[rid] for rid in ids if rid in found]

    def rating_histogram(self, review_ids: Sequence[str]) -> dict[int, int]:
        counts = {star: 0 for star in range(1, 6)}
        ids = [rid for rid in review_ids if rid]
        if not ids:
            return counts
        with self._connect() as conn:
            for offset in range(0, len(ids), 400):
                chunk = ids[offset : offset + 400]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""
                    SELECT rating, COUNT(*) AS c FROM reviews
                    WHERE review_id IN ({placeholders})
                    GROUP BY rating
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    rating = row["rating"]
                    if rating in counts:
                        counts[int(rating)] += int(row["c"])
        return counts

    def query_reviews(
        self,
        *,
        q: str | None = None,
        rating: int | None = None,
        review_ids: Sequence[str] | None = None,
        window_start: date | None = None,
        window_end: date | None = None,
        scrubbed: bool | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Review], str | None, int]:
        """Cursor-paginated scrubbed reviews. Never returns an author column."""
        limit = max(1, min(int(limit), 100))
        where: list[str] = ["1=1"]
        params: list[object] = []

        if review_ids is not None:
            ids = [rid for rid in review_ids if rid]
            if not ids:
                return [], None, 0
            placeholders = ",".join("?" * len(ids))
            where.append(f"review_id IN ({placeholders})")
            params.extend(ids)
        if window_start is not None:
            where.append("substr(review_date, 1, 10) >= ?")
            params.append(window_start.isoformat())
        if window_end is not None:
            where.append("substr(review_date, 1, 10) <= ?")
            params.append(window_end.isoformat())
        if rating is not None:
            where.append("rating = ?")
            params.append(int(rating))
        if scrubbed is True:
            where.append("scrub_flags NOT IN ('[]', 'null', '')")
        elif scrubbed is False:
            where.append("scrub_flags IN ('[]', 'null', '')")
        if q and q.strip():
            like = f"%{_escape_like(q.strip())}%"
            where.append(
                "(text_clean LIKE ? ESCAPE '\\' OR review_id LIKE ? ESCAPE '\\')"
            )
            params.extend([like, like])

        cursor_clause = ""
        cursor_params: list[object] = []
        decoded = _decode_cursor(cursor)
        if decoded:
            cursor_date, cursor_id = decoded
            cursor_clause = (
                " AND (review_date < ? OR (review_date = ? AND review_id < ?))"
            )
            cursor_params = [cursor_date, cursor_date, cursor_id]

        where_sql = " AND ".join(where)
        count_sql = f"SELECT COUNT(*) AS c FROM reviews WHERE {where_sql}"
        page_sql = (
            f"SELECT * FROM reviews WHERE {where_sql}{cursor_clause} "
            "ORDER BY review_date DESC, review_id DESC LIMIT ?"
        )
        with self._connect() as conn:
            total = int(conn.execute(count_sql, params).fetchone()["c"])
            rows = conn.execute(
                page_sql, [*params, *cursor_params, limit + 1]
            ).fetchall()
        reviews = [_row_to_review(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and reviews:
            last = reviews[-1]
            next_cursor = _encode_cursor(
                last.date.astimezone(timezone.utc).isoformat(), last.review_id
            )
        return reviews, next_cursor, total

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()
        return int(row["c"])

    def latest_review_date(self) -> date | None:
        """Newest stored review calendar date (UTC date prefix), or None if empty."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(substr(review_date, 1, 10)) AS d FROM reviews"
            ).fetchone()
        value = row["d"] if row else None
        if not value:
            return None
        return date.fromisoformat(str(value))

    def has_author_column(self) -> bool:
        with self._connect() as conn:
            rows = conn.execute("PRAGMA table_info(reviews)").fetchall()
        return any(row["name"].lower() == "author" for row in rows)


def compute_review_id(raw: RawReview) -> str:
    if raw.external_id:
        key = f"{raw.source}|{raw.external_id}|{raw.date.astimezone(timezone.utc).isoformat()}"
    else:
        normalized_text = " ".join(raw.text.split())
        key = (
            f"{raw.source}|{normalized_text}|"
            f"{raw.date.astimezone(timezone.utc).isoformat()}"
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _row_to_review(row: sqlite3.Row) -> Review:
    return Review(
        review_id=row["review_id"],
        source=row["source"],
        rating=row["rating"],
        title_clean=row["title_clean"],
        text_clean=row["text_clean"],
        date=datetime.fromisoformat(row["review_date"]),
        lang=row["lang"],
        scrub_flags=json.loads(row["scrub_flags"]),
    )


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _format_date(value: date) -> str:
    return value.isoformat()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_cursor(review_date: str, review_id: str) -> str:
    raw = f"{review_date}\n{review_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor or not cursor.strip():
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        date_part, _, review_id = raw.partition("\n")
    except (ValueError, UnicodeDecodeError):
        return None
    if not date_part or not review_id:
        return None
    return date_part, review_id
