"""Console API bind host/port (deployment-plan.md §5.1).

Local `reviewpulse serve` stays on loopback. Railway (or any host that sets
`REVIEWPULSE_BIND_ALL=1` / `RAILWAY_ENVIRONMENT`) may bind `0.0.0.0` and must
honor `PORT`. `--port` wins over `PORT` wins over `[console] api_port`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", "*"})


class BindError(ValueError):
    """Host or port cannot be used for `reviewpulse serve`."""


@dataclass(frozen=True)
class Bind:
    host: str
    port: int


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def bind_all_enabled() -> bool:
    """True when a non-loopback bind is explicitly allowed."""
    if _truthy(os.environ.get("REVIEWPULSE_BIND_ALL")):
        return True
    return bool(os.environ.get("RAILWAY_ENVIRONMENT", "").strip())


def parse_port(value: str, *, source: str) -> int:
    try:
        port = int(value.strip())
    except ValueError as exc:
        raise BindError(f"{source} is not an integer port: {value!r}") from exc
    if port < 1 or port > 65535:
        raise BindError(f"{source} must be 1–65535; got {port}")
    return port


def resolve_port(
    cli_port: int | None,
    *,
    settings_port: int = 8000,
) -> int:
    """`--port` > `PORT` > settings."""
    if cli_port is not None:
        if cli_port < 1 or cli_port > 65535:
            raise BindError(f"--port must be 1–65535; got {cli_port}")
        return cli_port
    raw = os.environ.get("PORT", "").strip()
    if raw:
        return parse_port(raw, source="PORT")
    if settings_port < 1 or settings_port > 65535:
        raise BindError(f"console.api_port must be 1–65535; got {settings_port}")
    return settings_port


def resolve_host(
    cli_host: str | None,
    *,
    settings_host: str = "127.0.0.1",
) -> str:
    """CLI host, else settings. Bind-all with no CLI host upgrades loopback to 0.0.0.0."""
    if cli_host is not None and cli_host.strip():
        return cli_host.strip()
    host = (settings_host or "127.0.0.1").strip() or "127.0.0.1"
    if bind_all_enabled() and host in LOCAL_HOSTS:
        return "0.0.0.0"
    return host


def assert_host_allowed(host: str) -> None:
    if host in LOCAL_HOSTS:
        return
    if host in WILDCARD_HOSTS and bind_all_enabled():
        return
    raise BindError(
        "refusing to bind a non-local host in v1 "
        f"(got {host!r}; use 127.0.0.1, or set REVIEWPULSE_BIND_ALL=1 for 0.0.0.0)"
    )


def resolve_bind(
    cli_host: str | None = None,
    cli_port: int | None = None,
    *,
    settings_host: str = "127.0.0.1",
    settings_port: int = 8000,
) -> Bind:
    host = resolve_host(cli_host, settings_host=settings_host)
    assert_host_allowed(host)
    port = resolve_port(cli_port, settings_port=settings_port)
    return Bind(host=host, port=port)


def serve_api(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise BindError(
            'serve needs the web extra: pip install -e ".[web]"'
        ) from exc
    print(f"[reviewpulse] Console API http://{host}:{port}/api/v1/health")
    print("[reviewpulse] UI: cd web && npm run dev  (proxies /api/v1 here)")
    uvicorn.run(
        "reviewpulse.api.app:app",
        host=host,
        port=port,
        reload=False,
    )
