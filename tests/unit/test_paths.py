"""REVIEWPULSE_DATA_DIR / RUNS_DIR / SETTINGS (deployment-plan.md §5.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from reviewpulse.config import (
    DEFAULT_SETTINGS_PATH,
    EXAMPLE_SETTINGS_PATH,
    PROJECT_ROOT,
    data_dir,
    default_db_path,
    default_lock_path,
    default_state_path,
    ensure_writable_settings,
    load_settings,
    runs_dir,
    settings_file_path,
)


@pytest.fixture(autouse=True)
def _clear_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVIEWPULSE_DATA_DIR", raising=False)
    monkeypatch.delenv("REVIEWPULSE_RUNS_DIR", raising=False)
    monkeypatch.delenv("REVIEWPULSE_SETTINGS", raising=False)


def test_local_defaults() -> None:
    assert data_dir() == PROJECT_ROOT / "data"
    assert runs_dir() == PROJECT_ROOT / "runs"
    assert default_db_path() == PROJECT_ROOT / "data" / "reviews.db"
    assert default_lock_path() == PROJECT_ROOT / "data" / "schedule.lock"
    assert default_state_path() == PROJECT_ROOT / "data" / "publish-state.json"


def test_volume_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "persistent" / "data"
    runs = tmp_path / "persistent" / "runs"
    monkeypatch.setenv("REVIEWPULSE_DATA_DIR", str(data))
    monkeypatch.setenv("REVIEWPULSE_RUNS_DIR", str(runs))
    assert data_dir() == data
    assert runs_dir() == runs
    assert default_db_path() == data / "reviews.db"
    settings = load_settings(EXAMPLE_SETTINGS_PATH)
    assert settings.db_path == data / "reviews.db"
    assert settings.clustering.cache_dir == data / "cache"


def test_settings_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config" / "settings.toml"
    monkeypatch.setenv("REVIEWPULSE_SETTINGS", str(target))
    assert settings_file_path() == EXAMPLE_SETTINGS_PATH
    written = ensure_writable_settings()
    assert written == target
    assert target.is_file()
    assert settings_file_path() == target


def test_settings_file_path_local_toml_unchanged() -> None:
    if DEFAULT_SETTINGS_PATH.is_file():
        assert settings_file_path() == DEFAULT_SETTINGS_PATH
    else:
        assert settings_file_path() == EXAMPLE_SETTINGS_PATH
