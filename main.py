"""Railpack/Railway entrypoint. Local use remains `reviewpulse serve`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn


def main() -> None:
    os.environ.setdefault("REVIEWPULSE_BIND_ALL", "1")
    port = int(os.environ.get("PORT") or "8080")
    uvicorn.run(
        "reviewpulse.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
