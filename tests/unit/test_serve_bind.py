"""Bind host/port for `reviewpulse serve` (deployment-plan.md §5.1)."""

from __future__ import annotations

import pytest

from reviewpulse.api.bind import BindError, resolve_bind
from reviewpulse.cli import main
from reviewpulse.config import Settings


@pytest.fixture(autouse=True)
def _clear_bind_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVIEWPULSE_BIND_ALL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("PORT", raising=False)


def test_loopback_default() -> None:
    bind = resolve_bind(None, None)
    assert bind.host == "127.0.0.1"
    assert bind.port == 8000


def test_cli_port_wins_over_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    bind = resolve_bind("127.0.0.1", 9000)
    assert bind.port == 9000


def test_port_env_when_cli_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8080")
    bind = resolve_bind("127.0.0.1", None)
    assert bind.port == 8080


def test_invalid_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "not-a-port")
    with pytest.raises(BindError, match="PORT"):
        resolve_bind("127.0.0.1", None)


def test_refuses_wildcard_without_opt_in() -> None:
    with pytest.raises(BindError, match="non-local"):
        resolve_bind("0.0.0.0", 8000)


def test_bind_all_allows_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWPULSE_BIND_ALL", "1")
    bind = resolve_bind("0.0.0.0", 8080)
    assert bind.host == "0.0.0.0"
    assert bind.port == 8080


def test_railway_env_upgrades_default_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("PORT", "8080")
    bind = resolve_bind(None, None)
    assert bind.host == "0.0.0.0"
    assert bind.port == 8080


def test_explicit_loopback_still_ok_with_bind_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWPULSE_BIND_ALL", "1")
    bind = resolve_bind("127.0.0.1", 8000)
    assert bind.host == "127.0.0.1"


def test_cli_serve_refuses_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reviewpulse.cli.load_settings", lambda: Settings())
    monkeypatch.setattr(
        "reviewpulse.cli.serve_api",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    assert main(["serve", "--host", "0.0.0.0"]) == 1


def test_cli_serve_bind_all_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWPULSE_BIND_ALL", "1")
    seen: dict[str, object] = {}
    monkeypatch.setattr("reviewpulse.cli.load_settings", lambda: Settings())
    monkeypatch.setattr(
        "reviewpulse.cli.serve_api",
        lambda host, port: seen.update(host=host, port=port),
    )
    assert main(["serve", "--host", "0.0.0.0", "--port", "8080"]) == 0
    assert seen == {"host": "0.0.0.0", "port": 8080}
