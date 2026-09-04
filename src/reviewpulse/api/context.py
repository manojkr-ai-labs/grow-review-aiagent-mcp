"""Request-scoped paths and settings for the console API (overridable in tests)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reviewpulse.config import Settings, load_settings, runs_dir
from reviewpulse.store.sqlite import ReviewStore


@dataclass
class ApiContext:
    settings: Settings
    runs_dir: Path
    db_path: Path
    publish_state_path: Path
    lock_path: Path
    settings_path: Path | None = None

    def store(self) -> ReviewStore:
        return ReviewStore(self.db_path)


def build_context(settings: Settings | None = None) -> ApiContext:
    settings = settings or load_settings()
    data = settings.db_path.parent
    return ApiContext(
        settings=settings,
        runs_dir=runs_dir(),
        db_path=settings.db_path,
        publish_state_path=data / "publish-state.json",
        lock_path=data / "schedule.lock",
    )


@lru_cache(maxsize=1)
def default_context() -> ApiContext:
    return build_context()


def reset_default_context() -> None:
    default_context.cache_clear()


def get_context() -> ApiContext:
    return default_context()
