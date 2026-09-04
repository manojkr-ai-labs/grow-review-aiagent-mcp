"""CORS allowlist for the console API (deployment-plan.md §5.2).

`CORS_ORIGINS` is a comma-separated list. Empty / unset keeps the local Next
dev origins so `npm run dev` still works without extra config.
"""

from __future__ import annotations

import os

DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


def cors_origins(raw: str | None = None) -> list[str]:
    source = raw if raw is not None else os.environ.get("CORS_ORIGINS", "")
    parts = [item.strip() for item in source.split(",") if item.strip()]
    return parts or list(DEFAULT_CORS_ORIGINS)
