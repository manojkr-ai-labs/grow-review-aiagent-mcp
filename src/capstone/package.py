"""Canonical JSON and the weekly package hash.

The hash covers the exact bytes of ``note.md``, ``explainer.json``, and
``support_signals.json`` in that order. The note body is not stored again.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """UTF-8 JSON with sorted keys and compact separators."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def package_hash(note: bytes, explainer: bytes, signals: bytes) -> str:
    """SHA-256 of the three package files in note, explainer, signals order."""
    digest = hashlib.sha256()
    digest.update(note)
    digest.update(explainer)
    digest.update(signals)
    return digest.hexdigest()
