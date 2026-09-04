"""Keyword taxonomy loading and single-label assignment (Phase 2 task 2.9).

Fallback only. On the real corpus the buckets leave ~35% of reviews unmatched and
330 reviews match two or more buckets, so this cannot be the primary clusterer
(implementation-plan.md §4.2 F7). Assignment is single-label by ascending
`priority`, and unmatched reviews go to `other`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from reviewpulse.config import taxonomy_path
from reviewpulse.models import Review

OTHER_BUCKET_ID = "other"
OTHER_BUCKET_LABEL = "Unbucketed feedback"


@dataclass
class Bucket:
    id: str
    label: str
    priority: int
    keywords: list[str] = field(default_factory=list)
    patterns: list[re.Pattern[str]] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in self.keywords):
            return True
        return any(pattern.search(lowered) for pattern in self.patterns)

    def anchor_terms(self, limit: int = 8) -> list[str]:
        return self.keywords[:limit]


def load_taxonomy(path: Path | None = None) -> list[Bucket]:
    path = path or taxonomy_path()
    if not path.is_file():
        raise FileNotFoundError(f"Taxonomy file not found: {path}")

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    buckets: list[Bucket] = []
    for index, entry in enumerate(data.get("themes", [])):
        buckets.append(
            Bucket(
                id=entry["id"],
                label=entry.get("label", entry["id"].replace("_", " ").title()),
                priority=int(entry.get("priority", index + 1)),
                keywords=[k.lower() for k in entry.get("keywords", [])],
                patterns=[
                    re.compile(p, re.IGNORECASE) for p in entry.get("patterns", [])
                ],
            )
        )

    buckets.sort(key=lambda bucket: bucket.priority)
    return buckets


def assign_bucket(review: Review, buckets: list[Bucket]) -> Bucket | None:
    """First bucket by priority that matches; None means the `other` bucket."""
    for bucket in buckets:
        if bucket.matches(review.text_clean):
            return bucket
    return None


def assign_all(
    reviews: list[Review],
    buckets: list[Bucket],
) -> tuple[dict[str, list[int]], dict[str, Bucket]]:
    """Map bucket id -> member indices, keeping bucket metadata alongside."""
    groups: dict[str, list[int]] = {}
    used: dict[str, Bucket] = {}
    for index, review in enumerate(reviews):
        bucket = assign_bucket(review, buckets)
        key = bucket.id if bucket else OTHER_BUCKET_ID
        groups.setdefault(key, []).append(index)
        if bucket:
            used[key] = bucket
    return groups, used
