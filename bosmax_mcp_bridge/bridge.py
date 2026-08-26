"""Authenticated, allow-listed BOSMAX Flow MCP bridge.

This module intentionally contains no provider client, browser automation, or
generation implementation.  It is a small HTTP client for the existing
authenticated BOSMAX API and a normalized MCP tool dispatcher around it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8100"
SESSION_COOKIE_NAME = "bosmax_session"
CSRF_COOKIE_NAME = "bosmax_csrf"

_AUTH_PATH = "/api/auth/login"
_READINESS_PATH = "/api/flow/direct-video-readiness"
_GENERATE_PATH = "/api/flow/generate"
_JOB_PATH_RE = re.compile(
    r"^/api/flow/generate-job/([A-Za-z0-9][A-Za-z0-9._:-]{0,199})"
    r"(?:/reretrieve-media)?$"
)
_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|cookie|set[-_]?cookie|authorization|credential|api[-_]?key|session)",
    re.IGNORECASE,
)
_SECRET_TEXT_RE = re.compile(
    r"(?i)(?:bosmax_(?:session|csrf)|set-cookie|authorization\s*:\s*bearer)\s*[=:]\s*[^;\s,}]+"
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class BridgeConfigError(ValueError):
    """Raised when the bridge cannot construct a safe operator configuration."""


class BridgeInputError(ValueError):
    """Raised when a caller asks for an unsupported route or invalid arguments."""


class BridgeRequestError(RuntimeError):
    """Safe HTTP failure; it deliberately does not carry response text."""

    def __init__(self, code: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class BridgeConfig:
    """Environment-derived bridge settings.

    The credential fields are excluded from repr so accidental diagnostic
    output cannot print the operator password or email.
    """

    base_url: str
    bot_email: str = field(repr=False)
    bot_password: str = field(repr=False)

    def __post_init__(self) -> None:
        normalized = _validate_base_url(self.base_url)
        email = str(self.bot_email or "").strip()
        password = str(self.bot_password or "")
        if not email:
            raise BridgeConfigError("BOSMAX_BOT_EMAIL is required")
        if not password:
            raise BridgeConfigError("BOSMAX_BOT_PASSWORD is required")
        object.__setattr__(self, "base_url", normalized)
        object.__setattr__(self, "bot_email", email)
        object.__setattr__(self, "bot_password", password)

    def __repr__(self) -> str:  # pragma: no cover - defensive logging guard
        return f"BridgeConfig(base_url={self.base_url!r}, credentials=<private>)"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "BridgeConfig":
        env = os.environ if environ is None else environ
        raw_base_url = str(env.get("BOSMAX_BASE_URL") or "").strip()
        if not raw_base_url:
            # The loopback default is deliberately opt-in.  A missing base URL
            # must not silently turn a production process into a local caller.
            if str(env.get("BOSMAX_LOCAL_USE") or "").strip() != "1":
                raise BridgeConfigError(
                    "BOSMAX_BASE_URL is required (set BOSMAX_LOCAL_USE=1 for the loopback default)"
                )
            raw_base_url = DEFAULT_LOCAL_BASE_URL
        return cls(
            base_url=raw_base_url,
            bot_email=str(env.get("BOSMAX_BOT_EMAIL") or ""),
            bot_password=str(env.get("BOSMAX_BOT_PASSWORD") or ""),
        )


def _validate_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise BridgeConfigError("BOSMAX_BASE_URL is required")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise BridgeConfigError("BOSMAX_BASE_URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BridgeConfigError("BOSMAX_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BridgeConfigError("BOSMAX_BASE_URL cannot contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise BridgeConfigError("BOSMAX_BASE_URL must point to the BOSMAX origin")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise BridgeConfigError("non-loopback BOSMAX_BASE_URL must use HTTPS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise BridgeConfigError("BOSMAX_BASE_URL has an invalid port") from exc
    netloc = parsed.hostname
    if ":" in netloc and not parsed.netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parsed.scheme}://{netloc}"


class ReadinessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "F2V"
    source_mode: str | None = None
    model: str | None = None
    duration_s: int | None = None
    aspect: str = "9:16"
    ref_count: int = Field(default=1, ge=0)
    count: int = Field(default=1, ge=1)


class JobArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=200)


def _generate_request_model():
    # Importing the canonical model (rather than copying its fields) keeps this
    # bridge aligned with the existing /api/flow/generate contract.
    from agent.api.flow import GenerateRequest

    return GenerateRequest


def _generate_schema() -> dict[str, Any]:
    model = _generate_request_model()
    schema = model.model_json_schema()
    # GenerateRequest historically allowed Pydantic's default extra-ignore
    # behavior.  The MCP boundary is stricter: it must not accept an arbitrary
    # provider parameter and silently drop it.
    schema["additionalProperties"] = False
    return schema


def _validate_generate_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise BridgeInputError("GENERATE_ARGUMENTS_MUST_BE_OBJECT")
    model = _generate_request_model()
    unknown = sorted(set(arguments) - set(model.model_fields))
    if unknown:
        raise BridgeInputError("GENERATE_ARGUMENT_NOT_IN_GENERATE_REQUEST")
    try:
        validated = model.model_validate(dict(arguments))
    except ValidationError as exc:
        # Pydantic's error text can echo caller input.  Return only a stable
        # boundary code; never expose a request body in MCP output.
        raise BridgeInputError("GENERATE_REQUEST_INVALID") from exc
    # Excluding None preserves server defaults while avoiding invented values.
    return validated.model_dump(mode="json", exclude_none=True)


def _job_path(job_id: str, *, reretrieve: bool = False) -> str:
    value = str(job_id or "").strip()
    if not value or _CONTROL_CHAR_RE.search(value) or "/" in value or "\\" in value:
        raise BridgeInputError("JOB_ID_INVALID")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", value):
        raise BridgeInputError("JOB_ID_INVALID")
    suffix = "/reretrieve-media" if reretrieve else ""
    return f"/api/flow/generate-job/{quote(value, safe='')}{suffix}"


def _route_allowed(path: str) -> bool:
    if path in {_AUTH_PATH, _READINESS_PATH, _GENERATE_PATH}:
        return True
    return _JOB_PATH_RE.fullmatch(path) is not None


def _secret_values(config: BridgeConfig, cookies: httpx.Cookies) -> set[str]:
    values = {config.bot_email, config.bot_password}
    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
        try:
            token = cookies.get(name)
        except (KeyError, httpx.CookieConflict):
            token = None
        if token:
            values.add(str(token))
    return {value for value in values if value}


def _sanitize(value: Any, secrets: set[str], *, key: str | None = None) -> Any:
    """Remove secret-bearing fields and values from a JSON-compatible object."""

    if key and _SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(k): _sanitize(v, secrets, key=str(k))
            for k, v in value.items()
            if not _SECRET_KEY_RE.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = _SECRET_TEXT_RE.sub("[REDACTED]", value)
        for secret in secrets:
            if secret and secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    if isinstance(value, (bytes, bytearray)):
        return "[BINARY_OMITTED]"
    return value


def _safe_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class _ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


BOSMAX_FLOW_TOOLS = (
    _ToolSpec(
        "bosmax_flow_readiness",
        "Read provider-free BOSMAX Flow route readiness through the authenticated API.",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "default": "F2V"},
                "source_mode": {"type": ["string", "null"]},
                "model": {"type": ["string", "null"]},
                "duration_s": {"type": ["integer", "null"]},
                "aspect": {"type": "string", "default": "9:16"},
                "ref_count": {"type": "integer", "minimum": 0, "default": 1},
                "count": {"type": "integer", "minimum": 1, "default": 1},
            },
        },
    ),
    _ToolSpec(
        "bosmax_flow_generate",
        "Submit only the canonical BOSMAX /api/flow/generate GenerateRequest contract.",
        _generate_schema(),
    ),
    _ToolSpec(
        "bosmax_flow_job_status",
        "Read one existing BOSMAX Flow generation job status.",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id"],
            "properties": {"job_id": {"type": "string", "minLength": 1, "maxLength": 200}},
        },
    ),
    _ToolSpec(
        "bosmax_flow_reretrieve_media",
        "Re-retrieve already-rendered media through the canonical BOSMAX recovery route.",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id"],
            "properties": {"job_id": {"type": "string", "minLength": 1, "maxLength": 200}},
        },
    ),
)


class BosmaxMcpBridge:
    """One persistent authenticated BOSMAX session and four fixed MCP tools."""

    def __init__(
        self,
        config: BridgeConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not isinstance(config, BridgeConfig):
            raise BridgeConfigError("BRIDGE_CONFIG_REQUIRED")
        self._config = config
        seed_cookies = httpx.Cookies()
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            cookies=seed_cookies,
            headers={"Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        # httpx copies an initial Cookies object into the client.  Keep a
        # private reference to the actual persistent jar used by requests.
        self._cookies = self._client.cookies
        self._authenticated = False
        self._login_lock = asyncio.Lock()

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> "BosmaxMcpBridge":
        return cls(BridgeConfig.from_env(environ), transport=transport, timeout=timeout)

    async def __aenter__(self) -> "BosmaxMcpBridge":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [spec.as_dict() for spec in BOSMAX_FLOW_TOOLS]

    async def _login(self) -> None:
        async with self._login_lock:
            # Another concurrent request may have completed the login while this
            # waiter was asleep.
            if self._authenticated and self._has_auth_cookies():
                return
            self._client.cookies.clear()
            origin = self._config.base_url
            try:
                response = await self._client.post(
                    _AUTH_PATH,
                    json={"email": self._config.bot_email, "password": self._config.bot_password},
                    headers={"Origin": origin, "Referer": f"{origin}/"},
                )
            except httpx.RequestError as exc:
                self._authenticated = False
                raise BridgeRequestError("BOSMAX_LOGIN_UNAVAILABLE") from exc
            if response.status_code != 200:
                self._authenticated = False
                self._client.cookies.clear()
                if response.status_code == 403:
                    raise BridgeRequestError("BOSMAX_LOGIN_FORBIDDEN", 403)
                raise BridgeRequestError("BOSMAX_LOGIN_FAILED", response.status_code)
            if not self._has_auth_cookies():
                self._authenticated = False
                self._client.cookies.clear()
                raise BridgeRequestError("BOSMAX_LOGIN_COOKIE_MISSING")
            self._authenticated = True

    def _has_auth_cookies(self) -> bool:
        try:
            return bool(self._client.cookies.get(SESSION_COOKIE_NAME)) and bool(
                self._client.cookies.get(CSRF_COOKIE_NAME)
            )
        except (KeyError, httpx.CookieConflict):
            return False

    def _csrf_token(self) -> str:
        try:
            token = self._client.cookies.get(CSRF_COOKIE_NAME)
        except (KeyError, httpx.CookieConflict):
            token = None
        if not token:
            raise BridgeRequestError("BOSMAX_CSRF_COOKIE_MISSING")
        return str(token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        mutation: bool = False,
        _allow_reauth: bool = True,
    ) -> Any:
        if not _route_allowed(path):
            raise BridgeInputError("ENDPOINT_NOT_ALLOWED")
        if path == _AUTH_PATH:
            raise BridgeInputError("AUTH_ROUTE_NOT_EXPOSED")
        await self._login()
        headers: dict[str, str] = {}
        if mutation:
            headers["x-csrf-token"] = self._csrf_token()
        try:
            response = await self._client.request(
                method.upper(), path, params=dict(params or {}), json=json_body, headers=headers
            )
        except httpx.RequestError as exc:
            raise BridgeRequestError("BOSMAX_REQUEST_UNAVAILABLE") from exc
        if response.status_code == 401:
            self._authenticated = False
            if _allow_reauth:
                await self._login()
                return await self._request(
                    method,
                    path,
                    params=params,
                    json_body=json_body,
                    mutation=mutation,
                    _allow_reauth=False,
                )
            raise BridgeRequestError("BOSMAX_UNAUTHORIZED", 401)
        if response.status_code == 403:
            raise BridgeRequestError("BOSMAX_FORBIDDEN", 403)
        if response.status_code >= 400:
            raise BridgeRequestError("BOSMAX_REQUEST_REJECTED", response.status_code)
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise BridgeRequestError("BOSMAX_INVALID_JSON", response.status_code) from exc

    async def readiness(self, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if arguments is not None and not isinstance(arguments, Mapping):
            raise BridgeInputError("READINESS_ARGUMENTS_MUST_BE_OBJECT")
        args = ReadinessArguments.model_validate(dict(arguments or {}))
        params = args.model_dump(mode="json", exclude_none=True)
        payload = await self._request("GET", _READINESS_PATH, params=params)
        safe_payload = _sanitize(payload, _secret_values(self._config, self._client.cookies))
        return {
            "ok": True,
            "endpoint": _READINESS_PATH,
            "payload": safe_payload,
            "credentials_exposed": False,
            "cookies_exposed": False,
            "generation_called": False,
            "credits_spent": 0,
        }

    async def generate(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        payload = _validate_generate_arguments(arguments)
        result = await self._request(
            "POST", _GENERATE_PATH, json_body=payload, mutation=True
        )
        return {
            "ok": True,
            "endpoint": _GENERATE_PATH,
            "payload": _sanitize(result, _secret_values(self._config, self._client.cookies)),
            "credentials_exposed": False,
            "cookies_exposed": False,
        }

    async def job_status(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            raise BridgeInputError("JOB_ARGUMENTS_MUST_BE_OBJECT")
        args = JobArguments.model_validate(dict(arguments))
        path = _job_path(args.job_id)
        result = await self._request("GET", path)
        return {
            "ok": True,
            "endpoint": "/api/flow/generate-job/{job_id}",
            "payload": _sanitize(result, _secret_values(self._config, self._client.cookies)),
            "credentials_exposed": False,
            "cookies_exposed": False,
        }

    async def reretrieve_media(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            raise BridgeInputError("JOB_ARGUMENTS_MUST_BE_OBJECT")
        args = JobArguments.model_validate(dict(arguments))
        path = _job_path(args.job_id, reretrieve=True)
        result = await self._request("POST", path, json_body={}, mutation=True)
        return {
            "ok": True,
            "endpoint": "/api/flow/generate-job/{job_id}/reretrieve-media",
            "payload": _sanitize(result, _secret_values(self._config, self._client.cookies)),
            "credentials_exposed": False,
            "cookies_exposed": False,
        }

    async def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if arguments is not None and not isinstance(arguments, Mapping):
            raise BridgeInputError("TOOL_ARGUMENTS_MUST_BE_OBJECT")
        args = arguments or {}
        try:
            if name == "bosmax_flow_readiness":
                result = await self.readiness(args)
            elif name == "bosmax_flow_generate":
                result = await self.generate(args)
            elif name == "bosmax_flow_job_status":
                result = await self.job_status(args)
            elif name == "bosmax_flow_reretrieve_media":
                result = await self.reretrieve_media(args)
            else:
                raise BridgeInputError("TOOL_NOT_FOUND")
            return {
                "content": [{"type": "text", "text": _safe_json_text(result)}],
                "structuredContent": result,
                "isError": False,
            }
        except (BridgeConfigError, BridgeInputError, BridgeRequestError, ValidationError) as exc:
            code = getattr(exc, "code", None) or (
                "INPUT_INVALID" if isinstance(exc, ValidationError) else "BRIDGE_INPUT_INVALID"
            )
            error = {"ok": False, "error": str(code), "credentials_exposed": False, "cookies_exposed": False}
            return {
                "content": [{"type": "text", "text": _safe_json_text(error)}],
                "structuredContent": error,
                "isError": True,
            }
        except Exception:
            # The MCP boundary must never echo arbitrary exception text, which
            # could contain an HTTP URL, cookie value, or request body.
            error = {
                "ok": False,
                "error": "BRIDGE_INTERNAL_ERROR",
                "credentials_exposed": False,
                "cookies_exposed": False,
            }
            return {
                "content": [{"type": "text", "text": _safe_json_text(error)}],
                "structuredContent": error,
                "isError": True,
            }

    async def handle_jsonrpc(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle the newline-delimited JSON-RPC subset required by MCP stdio."""

        if not isinstance(message, Mapping):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "initialize":
            params = message.get("params")
            if not isinstance(params, Mapping):
                params = {}
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "bosmax-mcp-bridge", "version": "0.1.0"},
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tool_definitions()}}
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, Mapping) or not isinstance(params.get("name"), str):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "Invalid tools/call parameters"},
                }
            result = await self.call_tool(params["name"], params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
