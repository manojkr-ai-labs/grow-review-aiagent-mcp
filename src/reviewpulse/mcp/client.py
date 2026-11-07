"""MCP client (Phase 4 stdio + Phase 5 Streamable HTTP).

This is the only code path to Google Docs and Gmail. The servers own OAuth;
this module opens a session, checks the configured tool names exist, and calls
them. Transport and 5xx-shaped failures retry; auth, validation, and mutating
hosted tools (`append_to_google_doc`, `draft_email`, `send_email`) do not.

`langchain-mcp-adapters` is an optional alternative (architecture ADR-6) and is
not used: one client, native SDK, so contract tests can speak stdio to a fake
without dragging LangChain into the publish path.

The hosted Railway server (`gmail-docs-mcp`) is Streamable HTTP at `/mcp` with
a bearer token. It exposes `draft_email`, `send_email`, and
`append_to_google_doc`. Interactive runs draft only; `--send` / schedule may
call `send_email`.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from reviewpulse.config import (
    FORBIDDEN_SEND_TOOLS,
    HOSTED_APPEND_TOOL,
    HOSTED_DRAFT_TOOL,
    HOSTED_SEND_TOOL,
    McpServerSettings,
    McpSettings,
)

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.25
HTTP_TIMEOUT_SECONDS = 60.0

# Hosted gmail-docs-mcp is explicit: do not retry append/send after an uncertain
# error because the side effect may already have landed. Drafts are also a write.
NO_RETRY_TOOLS = frozenset(
    {HOSTED_APPEND_TOOL, HOSTED_DRAFT_TOOL, *FORBIDDEN_SEND_TOOLS}
)

# Semantic keys we know how to send, mapped onto whatever the server named them.
_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "document_title", "documentTitle"),
    "text": ("text", "content", "body", "markdown", "html"),
    "document_id": (
        "document_id",
        "documentId",
        "doc_id",
        "docId",
        "file_id",
        "fileId",
        "id",
    ),
    "to": ("to", "recipient", "email", "to_email", "toEmail"),
    "subject": ("subject", "title"),
    "body": ("body", "text", "content", "message", "htmlBody", "html_body"),
    "query": ("query", "q", "search", "title", "subject"),
    "draft_id": ("draft_id", "draftId", "id"),
    "prepend_newline": ("prependNewline", "prepend_newline"),
}


class MCPError(RuntimeError):
    """Any MCP failure we surface to the orchestrator."""


class MCPConfigError(MCPError):
    """Settings are incomplete or still the example placeholders."""


class MCPTransportError(MCPError):
    """Spawn, initialize, or session transport failed."""


class MCPToolMismatchError(MCPError):
    """Configured tool names are not on the server."""


class MCPToolError(MCPError):
    """The server ran the tool and returned an error payload."""


class MCPAuthError(MCPToolError):
    """OAuth/auth failure inside the MCP server — not ours to fix."""


class ToolClient(Protocol):
    """What the publishers need; tests inject a fake, production uses MCP."""

    def list_tools(self) -> list[ToolInfo]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class ToolInfo:
    name: str
    schema: dict[str, Any] = field(default_factory=dict)


def _schema_type(prop: dict[str, Any] | None) -> str | None:
    if not isinstance(prop, dict):
        return None
    wanted = prop.get("type")
    if isinstance(wanted, list):
        return next((item for item in wanted if isinstance(item, str)), None)
    return wanted if isinstance(wanted, str) else None


def _coerce_value(prop: dict[str, Any] | None, value: Any) -> Any:
    """Align a semantic value with the JSON Schema type the tool advertised."""
    wanted = _schema_type(prop)
    if wanted == "array" and not isinstance(value, list):
        return [value]
    if wanted == "boolean" and isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value


def bind_arguments(schema: dict[str, Any] | None, semantic: dict[str, Any]) -> dict[str, Any]:
    """Map our field names onto the tool's input schema.

    Servers disagree about `document_id` vs `documentId` vs `fileId`. Matching
    against the advertised properties is what keeps one publisher working
    against more than one MCP package. Hosted gmail-docs-mcp wants `to` as an
    array and `content` / `documentId` on append — those are schema-driven here,
    not special-cased in the publisher.
    """
    properties = (schema or {}).get("properties") or {}
    bound: dict[str, Any] = {}
    for key, value in semantic.items():
        if value is None or value == "":
            continue
        aliases = _ALIASES.get(key, (key,))
        if properties:
            match = next((alias for alias in aliases if alias in properties), None)
            if match is None and key in properties:
                match = key
            if match is None:
                continue
            bound[match] = _coerce_value(properties.get(match), value)
        else:
            bound[aliases[0]] = value
    return bound


def extract_id(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    nested = (
        payload.get("data")
        or payload.get("document")
        or payload.get("draft")
        or payload.get("file")
    )
    if isinstance(nested, dict):
        return extract_id(nested, *keys)
    return None


def extract_url(payload: dict[str, Any]) -> str | None:
    return extract_id(
        payload, "url", "document_url", "documentUrl", "webViewLink", "web_view_link"
    )


def is_auth_error(message: str) -> bool:
    lowered = message.lower()
    needles = (
        "unauthenticated",
        "unauthorized",
        "invalid_grant",
        "invalid grant",
        "oauth",
        "auth error",
        "auth_required",
        "auth_expired",
        "re-auth",
        "reauth",
        "login required",
        "forbidden",
        "insufficient_scope",
        "401",
    )
    return any(needle in lowered for needle in needles)


def is_retryable(message: str) -> bool:
    if is_auth_error(message):
        return False
    lowered = message.lower()
    if any(
        needle in lowered
        for needle in ("invalid", "not found", "unknown tool", "required", "schema")
    ):
        return False
    return any(
        needle in lowered
        for needle in (
            "timeout",
            "temporar",
            "unavailable",
            "rate_limited",
            "429",
            "500",
            "502",
            "503",
            "504",
        )
    )


def _content_text(result) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _result_is_error(result) -> bool:
    return bool(getattr(result, "isError", None) or getattr(result, "is_error", None))


def _tool_input_schema(item) -> dict[str, Any]:
    schema = getattr(item, "inputSchema", None)
    if schema is None:
        schema = getattr(item, "input_schema", None)
    if isinstance(schema, dict):
        return dict(schema)
    dump = getattr(schema, "model_dump", None)
    if callable(dump):
        dumped = dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    return {}


def _bearer_token(settings: McpSettings) -> str:
    token = (settings.auth_token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token:
        return token
    header = (settings.gdocs.headers.get("Authorization") or "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return header


def _token_looks_set(token: str) -> bool:
    value = (token or "").strip()
    return bool(value) and "<" not in value and "MCP_AUTH" not in value and not value.startswith("${")


def hosted_health_url(mcp_url: str) -> str:
    raw = (mcp_url or "").strip().rstrip("/")
    if raw.endswith("/mcp"):
        raw = raw[:-4]
    return f"{raw.rstrip('/')}/health"


def hosted_server_http_up(mcp_url: str) -> bool:
    """Unauthenticated GET /health on the hosted MCP origin (no Google call)."""
    url = hosted_health_url(mcp_url)
    if not url.startswith("http"):
        return False
    try:
        import httpx

        response = httpx.get(url, timeout=8.0, follow_redirects=True)
        return response.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _parse_json_value(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _raise_tool_failure(payload: dict[str, Any], fallback: str) -> None:
    error = payload.get("error")
    code = ""
    message = fallback or "MCP tool returned an error"
    if isinstance(error, dict):
        code = str(error.get("code") or "")
        message = str(error.get("message") or message)
    elif isinstance(error, str) and error.strip():
        message = error
    blob = f"{code} {message}".strip()
    if is_auth_error(blob) or code in {
        "AUTH_REQUIRED",
        "AUTH_EXPIRED",
        "INSUFFICIENT_SCOPE",
    }:
        raise MCPAuthError(blob or "MCP server returned an authentication error")
    raise MCPToolError(blob)


def flatten_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap `{success, data}` from gmail-docs-mcp into a flat dict of ids."""
    if payload.get("success") is False:
        _raise_tool_failure(payload, "MCP tool returned success=false")
    data = payload.get("data")
    if payload.get("success") is True and isinstance(data, dict):
        merged = dict(data)
        for key, value in payload.items():
            if key not in {"data", "success"}:
                merged.setdefault(key, value)
        return merged
    if isinstance(data, dict) and "success" not in payload:
        return dict(data)
    return payload


def unwrap_tool_result(result) -> dict[str, Any]:
    """Turn a CallToolResult into a dict, or raise a typed MCP error."""
    text = _content_text(result)
    parsed = _parse_json_value(text)
    if _result_is_error(result):
        payload = parsed if isinstance(parsed, dict) else {"text": text}
        _raise_tool_failure(payload, text or "MCP tool returned an error")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return flatten_tool_payload(structured)
    if isinstance(parsed, dict):
        return flatten_tool_payload(parsed)
    if isinstance(parsed, list):
        return {"items": parsed}
    if text:
        return {"text": text}
    return {}


def refuse_send_tool(name: str, *, allow_send: bool = False) -> None:
    """Block send tools unless this run opted in (`--send` / schedule)."""
    if allow_send:
        return
    if name in FORBIDDEN_SEND_TOOLS:
        raise MCPConfigError(
            f"refusing to call {name!r}: this agent creates Gmail drafts only "
            f"unless --send or [schedule] send_email is set. "
            f"Use {HOSTED_DRAFT_TOOL!r} for drafts."
        )


def _is_unauthorized(exc: BaseException) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in {401, 403}:
        return True
    return is_auth_error(str(exc))


class MCPClient:
    """One MCP server over stdio or Streamable HTTP.

    A weekly run makes a handful of tool calls. Opening a fresh session per
    call is slower than a long-lived session and much easier to reason about
    when a server crashes between Docs and Gmail. The hosted Railway server is
    stateless HTTP, so a new session per call is also what it expects.
    """

    def __init__(
        self,
        settings: McpServerSettings,
        *,
        name: str = "mcp",
        allow_send: bool = False,
    ) -> None:
        self.settings = settings
        self.name = name
        self.allow_send = allow_send
        self._schemas: dict[str, dict[str, Any]] = {}

    def list_tools(self) -> list[ToolInfo]:
        return self._run(self._list_tools())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        refuse_send_tool(name, allow_send=self.allow_send)
        return self._run(self._call_with_retry(name, arguments))

    def verify(self, required: list[str]) -> list[ToolInfo]:
        forbidden = [
            name
            for name in required
            if name in FORBIDDEN_SEND_TOOLS and not self.allow_send
        ]
        if forbidden:
            raise MCPConfigError(
                f"{self.name} is configured to call send tool(s) {forbidden}; "
                f"this agent drafts only ({HOSTED_DRAFT_TOOL}) unless --send "
                f"or [schedule] send_email is set"
            )
        tools = self.list_tools()
        available = {tool.name for tool in tools}
        missing = [name for name in required if name and name not in available]
        if missing:
            listed = ", ".join(sorted(available)) or "(none)"
            raise MCPToolMismatchError(
                f"{self.name} MCP server is missing tool(s) {missing}; "
                f"configured endpoint is {self._endpoint_display()!r}; "
                f"available: {listed}"
            )
        return tools

    def _endpoint_display(self) -> str:
        if self.settings.url.strip():
            return self.settings.url.strip()
        return " ".join([self.settings.command, *self.settings.args]).strip()

    def _run(self, coro):
        try:
            return asyncio.run(coro)
        except MCPError:
            raise
        except Exception as exc:  # noqa: BLE001 - spawn failures are the point
            if _is_unauthorized(exc):
                raise MCPAuthError(
                    f"{self.name} MCP endpoint rejected the bearer token "
                    f"({self._endpoint_display()!r}). Set MCP_AUTH_TOKEN in .env."
                ) from exc
            raise MCPTransportError(
                f"failed to start {self.name} MCP server "
                f"({self._endpoint_display()!r}): {exc}"
            ) from exc

    async def _list_tools(self) -> list[ToolInfo]:
        async with self._session() as session:
            return await self._load_tools(session)

    async def _call_with_retry(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        attempts = 1 if name in NO_RETRY_TOOLS else MAX_ATTEMPTS
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await self._call_once(name, arguments)
            except MCPAuthError:
                raise
            except MCPToolMismatchError:
                raise
            except MCPConfigError:
                raise
            except (MCPTransportError, MCPToolError) as exc:
                last_error = exc
                if attempt >= attempts or not is_retryable(str(exc)):
                    raise
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                delay += random.uniform(0, delay / 2)
                time.sleep(delay)
        raise last_error or MCPError(f"{name} failed")

    async def _call_once(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        refuse_send_tool(name, allow_send=self.allow_send)
        try:
            async with self._session() as session:
                tools = await self._load_tools(session)
                by_name = {tool.name: tool for tool in tools}
                if name not in by_name:
                    available = ", ".join(sorted(by_name)) or "(none)"
                    raise MCPToolMismatchError(
                        f"{self.name} has no tool {name!r}; available: {available}"
                    )
                payload = bind_arguments(by_name[name].schema, arguments)
                result = await session.call_tool(name, payload)
                return unwrap_tool_result(result)
        except MCPError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_unauthorized(exc):
                raise MCPAuthError(
                    f"{self.name} tool {name!r} unauthorized: {exc}"
                ) from exc
            raise MCPTransportError(
                f"{self.name} tool {name!r} failed: {exc}"
            ) from exc

    async def _load_tools(self, session) -> list[ToolInfo]:
        listed = await session.list_tools()
        tools = [
            ToolInfo(name=item.name, schema=_tool_input_schema(item))
            for item in listed.tools
        ]
        self._schemas = {tool.name: tool.schema for tool in tools}
        return tools

    def _session(self):
        if self.settings.url.strip():
            return self._http_session()
        return self._stdio_session()

    def _stdio_session(self):
        from contextlib import asynccontextmanager

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.settings.command,
            args=list(self.settings.args),
            env=self._child_env(),
            cwd=self.settings.cwd,
        )

        @asynccontextmanager
        async def _opened():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

        return _opened()

    def _http_session(self):
        from contextlib import asynccontextmanager

        from mcp import ClientSession

        url = self.settings.url.strip()
        headers = dict(self.settings.headers)

        @asynccontextmanager
        async def _opened():
            async with _streamable_http_streams(url, headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

        return _opened()

    def _child_env(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if value is not None}
        env.update(self.settings.env)
        return env


# Phase 4 name: stdio was the only transport. HTTP is selected by settings.url.
StdioMCPClient = MCPClient


def make_mcp_client(
    settings: McpServerSettings, *, name: str, allow_send: bool = False
) -> MCPClient:
    return MCPClient(settings, name=name, allow_send=allow_send)


def _config_error_message() -> str:
    return (
        "MCP servers are not configured: copy config/settings.example.toml "
        "to config/settings.toml and fill either the hosted [mcp] url + "
        "MCP_AUTH_TOKEN + mcp.gdocs.document_id, or [mcp.gdocs]/[mcp.gmail] "
        "stdio commands. OAuth stays in the MCP server, not in this repo. "
        "Interactive runs never call send_email; --send / schedule may."
    )


def _require_endpoint(settings: McpSettings) -> None:
    """URL + bearer (HTTP) or spawn command (stdio). Notebook id is not required to ping."""
    if settings.transport == "http":
        url = (settings.url or settings.gdocs.url or settings.gmail.url).strip()
        if not url.startswith("http") or "<" in url:
            raise MCPConfigError(_config_error_message())
        if not _token_looks_set(_bearer_token(settings)):
            raise MCPConfigError(
                "MCP_AUTH_TOKEN is not set on this API service. Use the same "
                "bearer value as the MCP Railway service (not a Google token)."
            )
        token = _bearer_token(settings)
        bearer = {"Authorization": f"Bearer {token}"}
        if "Authorization" not in settings.gdocs.headers:
            settings.gdocs.headers = {**bearer, **settings.gdocs.headers}
        if "Authorization" not in settings.gmail.headers:
            settings.gmail.headers = {**bearer, **settings.gmail.headers}
        if not settings.gdocs.url.strip():
            settings.gdocs.url = url
        if not settings.gmail.url.strip():
            settings.gmail.url = url
        return
    if not settings.gdocs.configured or not settings.gmail.configured:
        raise MCPConfigError(_config_error_message())


def _assert_tool_config(settings: McpSettings) -> None:
    forbidden = settings.gdocs.tools.forbidden() + settings.gmail.tools.forbidden()
    if forbidden:
        raise MCPConfigError(
            f"refusing send tool(s) {forbidden}; set tools.create_draft = "
            f"{HOSTED_DRAFT_TOOL!r} and map send to tools.send, not create_draft"
        )


def _require_notebook(settings: McpSettings) -> None:
    if settings.transport == "http" and not settings.gdocs.document_id.strip():
        raise MCPConfigError(
            "mcp.gdocs.document_id is required: the hosted server can only "
            "append to an existing Google Doc (it cannot create one). "
            "Create a blank Doc and paste the ID from "
            "/document/d/{id}/ in the URL."
        )


def verify_publish_servers(settings: McpSettings, *, allow_send: bool = False) -> None:
    """Fail before any LLM or ingest spend on a live publish run."""
    _require_endpoint(settings)
    _assert_tool_config(settings)
    _require_notebook(settings)
    send_tool = settings.gmail.tools.send or HOSTED_SEND_TOOL
    if settings.transport == "http":
        shared = make_mcp_client(settings.gdocs, name="gmail-docs", allow_send=allow_send)
        required = settings.gdocs.tools.required_docs() + settings.gmail.tools.required_gmail()
        if allow_send:
            required = required + [send_tool]
        shared.verify(required)
        return
    docs = make_mcp_client(settings.gdocs, name="gdocs")
    mail = make_mcp_client(settings.gmail, name="gmail", allow_send=allow_send)
    docs.verify(settings.gdocs.tools.required_docs())
    required_mail = settings.gmail.tools.required_gmail()
    if allow_send:
        required_mail = required_mail + [send_tool]
    mail.verify(required_mail)


def inspect_publish_servers(settings: McpSettings) -> dict[str, Any]:
    """Ping the live server and list tools. Notebook id is reported, not required."""
    _require_endpoint(settings)
    _assert_tool_config(settings)
    if settings.transport == "http":
        client = make_mcp_client(settings.gdocs, name="gmail-docs")
        required = settings.gdocs.tools.required_docs() + settings.gmail.tools.required_gmail()
        tools = client.verify(required)
        names = [tool.name for tool in tools]
        return {
            "transport": "http",
            "url": settings.url or settings.gdocs.url,
            "document_id": settings.gdocs.document_id,
            "tools": names,
            "publish_ready": bool(settings.gdocs.document_id.strip()),
            "send_email_present": any(name in FORBIDDEN_SEND_TOOLS for name in names),
            "draft_tool": settings.gmail.tools.create_draft,
            "send_tool": settings.gmail.tools.send or HOSTED_SEND_TOOL,
            "append_tool": settings.gdocs.tools.append,
        }
    docs = make_mcp_client(settings.gdocs, name="gdocs")
    mail = make_mcp_client(settings.gmail, name="gmail")
    return {
        "transport": "stdio",
        "gdocs_tools": [tool.name for tool in docs.list_tools()],
        "gmail_tools": [tool.name for tool in mail.list_tools()],
        "send_email_present": False,
        "publish_ready": True,
    }


def mcp_probe_status(settings: McpSettings) -> dict[str, Any]:
    """Console chip payload: CONNECTED means tools/list succeeded, not that publish is ready."""
    url = (settings.url or settings.gdocs.url or settings.gmail.url or "").strip() or None
    document_id = settings.gdocs.document_id.strip() or None
    try:
        info = inspect_publish_servers(settings)
        detail = None
        if info.get("transport") == "http" and not info.get("document_id"):
            detail = (
                "MCP tools reachable. Set Google Doc id in Settings to publish "
                "(the server can only append to an existing Doc)."
            )
        return {
            "ok": True,
            "label": "CONNECTED",
            "detail": detail,
            "url": info.get("url") or url,
            "document_id": info.get("document_id") or document_id,
        }
    except MCPAuthError as exc:
        return {
            "ok": False,
            "label": "AUTH",
            "detail": str(exc),
            "url": url,
            "document_id": document_id,
        }
    except MCPConfigError as exc:
        return {
            "ok": False,
            "label": "NOT_CONFIGURED",
            "detail": str(exc),
            "url": url,
            "document_id": document_id,
        }
    except MCPToolMismatchError as exc:
        return {
            "ok": False,
            "label": "MISMATCH",
            "detail": str(exc),
            "url": url,
            "document_id": document_id,
        }
    except MCPError as exc:
        detail = str(exc)
        if url and hosted_server_http_up(url):
            detail = f"{detail} Hosted /health is up; the MCP session failed."
        return {
            "ok": False,
            "label": "UNREACHABLE",
            "detail": detail,
            "url": url,
            "document_id": document_id,
        }
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        if url and hosted_server_http_up(url):
            detail = f"{detail} Hosted /health is up; the MCP session failed."
        return {
            "ok": False,
            "label": "UNREACHABLE",
            "detail": detail,
            "url": url,
            "document_id": document_id,
        }


def _streamable_http_streams(url: str, headers: dict[str, str]):
    """Open Streamable HTTP read/write streams for mcp v1 or v2."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _opened():
        v2 = None
        v1 = None
        try:
            from mcp.client.streamable_http import streamable_http_client as v2
        except ImportError:
            v2 = None
        try:
            from mcp.client.streamable_http import streamablehttp_client as v1
        except ImportError:
            v1 = None
        if v2 is not None:
            try:
                import httpx as httpx_mod
            except ImportError:
                import httpx2 as httpx_mod
            timeout = httpx_mod.Timeout(30.0, read=HTTP_TIMEOUT_SECONDS)
            async with httpx_mod.AsyncClient(
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as http_client:
                async with v2(url, http_client=http_client) as streams:
                    yield streams[0], streams[1]
            return
        if v1 is None:
            raise MCPTransportError(
                "mcp package has no Streamable HTTP client "
                "(need streamable_http_client or streamablehttp_client)"
            )
        async with v1(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS) as streams:
            yield streams[0], streams[1]

    return _opened()
