"""AI Copy Assist — provider adapter boundary (candidate copy only).

Thin, disabled-by-default boundary between the AI Copy Assist service and a text
LLM provider. It REUSES the existing on-main lane provider abstraction
(`ai_provider_settings_service`, the canonical TEXT lane) for enablement + key +
provider selection — no new secrets, no new settings UI.

Hard rules:
- Disabled by default: with no configured/enabled TEXT lane key, every call fails
  closed with `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED`.
- This adapter ONLY produces candidate copy JSON. It never generates final
  engine-facing prompts and is never on the deterministic compiler path.
- No hardcoded keys. The key is read from the existing provider settings store.
- `generate_candidate` is the single mockable seam for tests.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from agent.services.ai_provider_model_catalog import (
    DEFAULT_CHAT_REQUEST_CONTRACT,
    TRANSPORT_ANTHROPIC_MESSAGES,
    TRANSPORT_OPENAI_COMPATIBLE,
    canonical_lane_id,
    get_model_request_contract,
    get_provider_transport,
    model_supports_lane,
)
from agent.services.ai_provider_settings_service import (
    get_provider_api_key,
    get_lane_api_key_for_execution,
    get_lane_model,
    get_lane_provider,
    get_structure_fallback,
    is_lane_execution_enabled,
)

LANE = "text"

# The operator's UI-selected lane model is the ONLY model source (with an optional
# deployment env override). There is NO hardcoded model fallback — an unconfigured
# lane resolves to None and the call fails closed. Base URLs below are transport
# endpoints (not model choices) and may be overridden per deployment.
_LANE_BASE_URL_ENVS: dict[str, tuple[str, ...]] = {
    "text": ("PRODUCT_TEXT_BASE_URL", "PRODUCT_TEXT_ASSIST_BASE_URL"),
    "structure": ("PRODUCT_STRUCTURE_BASE_URL",),
}
_LANE_MODEL_ENVS: dict[str, tuple[str, ...]] = {
    "text": ("PRODUCT_TEXT_MODEL", "PRODUCT_TEXT_ASSIST_MODEL"),
    "structure": ("PRODUCT_STRUCTURE_MODEL",),
}
# A completion of ~1.3k tokens does not reliably finish inside 30s. Measured on the live
# DeepSeek text_assist lane (2026-07-31): one call landed at ~29s and succeeded, then every
# subsequent call exceeded 30s and failed `AI_COPY_ASSIST_CALL_FAILED: The read operation
# timed out` (HTTP 502) — the lane was configured correctly and the provider was healthy;
# only this ceiling was too tight. Kept well under the caller's own request timeout.
_TIMEOUT_SECONDS = 120.0
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 1024
# The current repository catalog declares provider/model identity and transport,
# but no per-model output-token capability.  These are therefore explicit
# structured-output transport ceilings, not invented provider claims.  Callers
# must govern their request within this seam; the adapter clamps again at the
# actual transport boundary.
OPENAI_COMPATIBLE_JSON_MAX_TOKENS = 4096
ANTHROPIC_JSON_MAX_TOKENS = _ANTHROPIC_MAX_TOKENS
_JSON_OUTPUT_PROVIDER_IDS = frozenset({"deepseek", "openai"})
_DEEPSEEK_THINKING_MODE_MODELS = frozenset(
    {"deepseek-v4-pro", "deepseek-v4-flash"}
)
_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    # Anthropic uses its native /v1/messages transport (NOT OpenAI-compatible).
    "anthropic": "https://api.anthropic.com",
}

ERR_NOT_CONFIGURED = "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"
ERR_RESPONSE_INVALID = "AI_COPY_ASSIST_RESPONSE_INVALID"
ERR_CALL_FAILED = "AI_COPY_ASSIST_CALL_FAILED"

DIAGNOSTIC_EMPTY_CONTENT = "EMPTY_CONTENT"
DIAGNOSTIC_JSON_PARSE_FAILED = "JSON_PARSE_FAILED"
DIAGNOSTIC_NON_OBJECT_JSON = "NON_OBJECT_JSON"
DIAGNOSTIC_TRUNCATED_RESPONSE = "TRUNCATED_RESPONSE"
DIAGNOSTIC_CONTENT_EXTRACTION_FAILED = "CONTENT_EXTRACTION_FAILED"

_provider_call_lock = threading.Lock()
_provider_call_count = 0
# COPY-CORRECTIVE: reliable per-call token usage under concurrency. The single
# "last call" receipt races when provider calls run in a thread pool, so usage is
# also recorded keyed by the unique call_id and drained by generate_candidate.
_usage_by_call_id: dict[int, dict[str, float]] = {}
_provider_call_receipt_by_id: dict[int, dict[str, Any]] = {}
_last_provider_call_receipt: dict[str, Any] | None = None


class AICopyProviderNotConfigured(Exception):
    """Raised when a requested text/structure lane is not configured/enabled."""

    code = ERR_NOT_CONFIGURED


class AICopyProviderError(Exception):
    """Raised when a configured provider call fails or returns invalid JSON."""

    def __init__(
        self,
        code: str,
        detail: Any = None,
        *,
        diagnostic_category: str | None = None,
        diagnostic_metadata: dict[str, object] | None = None,
        http_status: int | None = None,
        finish_reason: str | None = None,
        usage: dict[str, int | float] | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.diagnostic_category = diagnostic_category
        self.diagnostic_metadata = dict(diagnostic_metadata or {})
        self.http_status = http_status
        self.finish_reason = finish_reason
        self.usage = dict(usage or {})
        # Populated only after a real call has been started.  These fields are
        # secret-free provenance for callers that must persist a failed call
        # even when no parsed JSON is returned.
        self.call_id: int | None = None
        self.provider_receipt: dict[str, Any] = {}


def provider_call_receipt() -> dict[str, Any]:
    """Return process-local, secret-free evidence for the latest HTTP call."""

    with _provider_call_lock:
        last_call = (
            dict(_last_provider_call_receipt)
            if _last_provider_call_receipt is not None
            else None
        )
        if last_call is not None:
            last_call["usage"] = dict(last_call.get("usage") or {})
        return {
            "request_count_since_process_start": _provider_call_count,
            "last_call": last_call,
        }


def _begin_provider_call(
    *,
    lane: str,
    provider_id: str,
    model: str,
    transport: str,
    structured_output_requested: bool,
    json_output_mode: str | None,
    requested_output_tokens: int | None = None,
    effective_output_tokens: int | None = None,
) -> int:
    global _provider_call_count, _last_provider_call_receipt
    with _provider_call_lock:
        _provider_call_count += 1
        call_id = _provider_call_count
        receipt = {
            "call_id": call_id,
            "lane": lane,
            "provider_id": provider_id,
            "model_id": model,
            "transport": transport,
            "structured_output_requested": structured_output_requested,
            "json_output_mode": json_output_mode,
            "started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            ),
            "response_status": "IN_FLIGHT",
            "http_status": None,
            "finish_reason": None,
            "json_parse_status": None,
            "diagnostic_category": None,
            "diagnostic_metadata": {},
            "usage": {},
        }
        if requested_output_tokens is not None or effective_output_tokens is not None:
            receipt.update(
                {
                    "requested_output_tokens": requested_output_tokens,
                    "effective_output_tokens": effective_output_tokens,
                }
            )
        _provider_call_receipt_by_id[call_id] = dict(receipt)
        while len(_provider_call_receipt_by_id) > 512:
            _provider_call_receipt_by_id.pop(next(iter(_provider_call_receipt_by_id)))
        _last_provider_call_receipt = receipt
        return call_id


def _finish_provider_call(
    call_id: int,
    *,
    response_status: str,
    http_status: int | None,
    usage: dict[str, int | float] | None = None,
    finish_reason: str | None = None,
) -> None:
    global _last_provider_call_receipt
    with _provider_call_lock:
        # Always record usage keyed by call_id (concurrency-safe), independent of
        # whether this is still the process-global "last call".
        normalized_usage = normalize_usage(usage)
        _usage_by_call_id[call_id] = dict(normalized_usage)
        # B3 backstop: bound the map so provider-exception paths that never drain
        # cannot grow it without limit in a long-running process.
        while len(_usage_by_call_id) > 512:
            _usage_by_call_id.pop(next(iter(_usage_by_call_id)))
        completed_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        )
        exact_receipt = _provider_call_receipt_by_id.get(call_id)
        if exact_receipt is not None:
            _provider_call_receipt_by_id[call_id] = {
                **exact_receipt,
                "completed_at": completed_at,
                "response_status": response_status,
                "http_status": http_status,
                "finish_reason": finish_reason,
                "usage": dict(normalized_usage),
            }
        if (
            _last_provider_call_receipt is None
            or _last_provider_call_receipt.get("call_id") != call_id
        ):
            return
        _last_provider_call_receipt = {
            **_last_provider_call_receipt,
            "completed_at": completed_at,
            "response_status": response_status,
            "http_status": http_status,
            "finish_reason": finish_reason,
            "usage": dict(normalized_usage),
        }


def _record_json_parse_result(
    call_id: int,
    *,
    status: str,
    diagnostic_category: str | None = None,
    diagnostic_metadata: dict[str, object] | None = None,
) -> None:
    global _last_provider_call_receipt
    with _provider_call_lock:
        exact_receipt = _provider_call_receipt_by_id.get(call_id)
        if exact_receipt is not None:
            _provider_call_receipt_by_id[call_id] = {
                **exact_receipt,
                "json_parse_status": status,
                "diagnostic_category": diagnostic_category,
                "diagnostic_metadata": dict(diagnostic_metadata or {}),
            }
        if (
            _last_provider_call_receipt is None
            or _last_provider_call_receipt.get("call_id") != call_id
        ):
            return
        _last_provider_call_receipt = {
            **_last_provider_call_receipt,
            "json_parse_status": status,
            "diagnostic_category": diagnostic_category,
            "diagnostic_metadata": dict(diagnostic_metadata or {}),
        }


def _record_provider_diagnostics(
    call_id: int,
    *,
    diagnostic_category: str | None,
    diagnostic_metadata: dict[str, object] | None,
) -> None:
    """Record secret-safe provider diagnostics (e.g. a non-2xx HTTP error body)
    into the call receipt without altering json_parse_status."""
    global _last_provider_call_receipt
    with _provider_call_lock:
        exact_receipt = _provider_call_receipt_by_id.get(call_id)
        if exact_receipt is not None:
            _provider_call_receipt_by_id[call_id] = {
                **exact_receipt,
                "diagnostic_category": diagnostic_category,
                "diagnostic_metadata": dict(diagnostic_metadata or {}),
            }
        if (
            _last_provider_call_receipt is None
            or _last_provider_call_receipt.get("call_id") != call_id
        ):
            return
        _last_provider_call_receipt = {
            **_last_provider_call_receipt,
            "diagnostic_category": diagnostic_category,
            "diagnostic_metadata": dict(diagnostic_metadata or {}),
        }


def normalize_usage(payload: object) -> dict[str, int | float]:
    """Return canonical token telemetry while retaining provider raw fields.

    Provider APIs use different names for the same token dimensions.  The
    canonical fields are deliberately explicit: ``total_tokens`` is never
    treated as ``output_tokens`` because it includes the prompt on providers
    that report a combined total.
    """

    if not isinstance(payload, dict):
        return {}
    raw = {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    normalized = dict(raw)

    def first_value(*keys: str) -> int | float | None:
        for key in keys:
            value = raw.get(key)
            if value is not None:
                return value
        return None

    input_tokens = first_value("input_tokens", "prompt_tokens")
    output_tokens = first_value("output_tokens", "completion_tokens")
    total_tokens = first_value("total_tokens")
    if input_tokens is not None:
        normalized["input_tokens"] = input_tokens
    if output_tokens is not None:
        normalized["output_tokens"] = output_tokens
    if total_tokens is not None:
        normalized["total_tokens"] = total_tokens
    elif input_tokens is not None and output_tokens is not None:
        normalized["total_tokens"] = input_tokens + output_tokens
    return normalized


def _safe_usage(payload: object) -> dict[str, int | float]:
    """Bounded provider telemetry with canonical token dimensions."""

    return normalize_usage(payload)


def _canonical_text_structure_lane(lane: str | None) -> str:
    canonical = canonical_lane_id(lane or LANE)
    if canonical not in {"text", "structure"}:
        raise ValueError(f"UNSUPPORTED_TEXT_PROVIDER_LANE:{lane}")
    return canonical


def is_configured(lane: str = LANE) -> bool:
    """True only when a TEXT or STRUCTURE lane has provider, model, key and gate."""
    try:
        canonical = _canonical_text_structure_lane(lane)
    except ValueError:
        return False
    try:
        return (
            bool(get_lane_api_key_for_execution(canonical))
            and bool(get_lane_model(canonical))
            and bool(is_lane_execution_enabled(canonical))
        )
    except Exception:
        return False


def provider_status(lane: str = LANE) -> dict[str, Any]:
    canonical = _canonical_text_structure_lane(lane)
    provider_id = None
    model_id = None
    execution_enabled = False
    try:
        provider_id = get_lane_provider(canonical)
    except Exception:
        provider_id = None
    try:
        model_id = _resolve_model(provider_id, canonical)
    except Exception:
        model_id = None
    try:
        execution_enabled = bool(is_lane_execution_enabled(canonical))
    except Exception:
        execution_enabled = False
    return {
        "lane": canonical,
        "configured": is_configured(canonical),
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
    }


def _resolve_base_url(provider_id: str | None, lane: str = LANE) -> str | None:
    canonical = _canonical_text_structure_lane(lane)
    for env_name in _LANE_BASE_URL_ENVS[canonical]:
        env = str(os.environ.get(env_name, "")).strip().rstrip("/")
        if env:
            return env
    return _DEFAULT_BASE_URLS.get(str(provider_id or "").lower())


def _resolve_model(provider_id: str | None, lane: str = LANE) -> str | None:
    # UI-selected lane model is the ONLY source (optional env override). No
    # hardcoded per-provider default — unconfigured resolves to None (fail closed).
    canonical = _canonical_text_structure_lane(lane)
    try:
        lane_model = get_lane_model(canonical)
    except Exception:
        lane_model = None
    if lane_model:
        return lane_model
    for env_name in _LANE_MODEL_ENVS[canonical]:
        env = str(os.environ.get(env_name, "")).strip()
        if env:
            return env
    return None


def structured_output_token_limit(
    provider_id: str | None,
    model_id: str | None = None,
) -> int:
    """Return the repository-declared structured-output transport ceiling.

    The mutable model catalog currently declares no per-model output-token
    capability.  ``model_id`` is accepted so a future catalog capability can be
    added without changing the call contract; today the selected provider's
    transport ceiling is the only supported limit we can prove locally.
    """

    del model_id
    transport = get_provider_transport(str(provider_id or "").lower())
    if transport == TRANSPORT_OPENAI_COMPATIBLE:
        return OPENAI_COMPATIBLE_JSON_MAX_TOKENS
    if transport == TRANSPORT_ANTHROPIC_MESSAGES:
        return ANTHROPIC_JSON_MAX_TOKENS
    raise AICopyProviderError(
        ERR_CALL_FAILED,
        detail="structured output transport limit is not declared",
    )


def clamp_structured_output_tokens(
    requested: int | None,
    *,
    provider_id: str | None,
    model_id: str | None,
) -> int:
    """Clamp one governed request to the selected lane's known safe ceiling."""

    limit = structured_output_token_limit(provider_id, model_id)
    if requested is None:
        return limit
    try:
        requested_value = int(requested)
    except (TypeError, ValueError) as exc:
        raise AICopyProviderError(
            ERR_CALL_FAILED,
            detail="structured output token budget must be an integer",
        ) from exc
    if requested_value < 1:
        raise AICopyProviderError(
            ERR_CALL_FAILED,
            detail="structured output token budget must be positive",
        )
    return min(requested_value, limit)


def _extract_json_object(
    text: str,
    *,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Parse one JSON object, allowing only a lossless full-message code fence."""

    safe_finish_reason = str(finish_reason or "").strip() or None
    if safe_finish_reason == "length":
        raise AICopyProviderError(
            ERR_RESPONSE_INVALID,
            diagnostic_category=DIAGNOSTIC_TRUNCATED_RESPONSE,
            diagnostic_metadata={"finish_reason": "length"},
            finish_reason="length",
        )
    raw = str(text or "").strip()
    if not raw:
        raise AICopyProviderError(
            ERR_RESPONSE_INVALID,
            diagnostic_category=DIAGNOSTIC_EMPTY_CONTENT,
            diagnostic_metadata={"finish_reason": safe_finish_reason},
            finish_reason=safe_finish_reason,
        )
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL | re.I)
    candidate = fenced.group(1) if fenced else raw
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError) as exc:
        raise AICopyProviderError(
            ERR_RESPONSE_INVALID,
            diagnostic_category=DIAGNOSTIC_JSON_PARSE_FAILED,
            diagnostic_metadata={"finish_reason": safe_finish_reason},
            finish_reason=safe_finish_reason,
        ) from exc
    if not isinstance(parsed, dict):
        raise AICopyProviderError(
            ERR_RESPONSE_INVALID,
            diagnostic_category=DIAGNOSTIC_NON_OBJECT_JSON,
            diagnostic_metadata={"finish_reason": safe_finish_reason},
            finish_reason=safe_finish_reason,
        )
    return parsed


def build_messages(brief: str) -> list[dict[str, str]]:
    """System + user messages. The system prompt bans unsafe claims, metadata
    leakage, and any final/engine prompt output — candidates only."""
    system = (
        "You are a Malay/English direct-response COPY CANDIDATE generator for a "
        "commercial UGC pipeline. You produce ONLY draft marketing copy candidates "
        "for human review. You NEVER produce final video prompts, NEVER produce "
        "9-section or engine-specific output, and NEVER include internal metadata "
        "(ids, provenance, system names). "
        "Ground every candidate in the brief. The brief may include product signals "
        "(product_class, sensitivity, product_family, copy_trigger, copy_formula, "
        "silo, claim_gate, claim_risk_level, route_type, strategy). Treat these as "
        "STRATEGY GUIDANCE to shape the angle, tone and buyer psychology — but NEVER "
        "print any signal code or id (e.g. trigger ids, silo/formula codes) in the "
        "copy itself. Honour route_type and the strategy field. "
        "METHOD (angle-first): the brief carries a customer avatar (avatar_audience, "
        "avatar_desires, avatar_fears, avatar_pains, avatar_objections, "
        "avatar_triggers, tone, pronoun) and product knowledge (product_benefits, "
        "product_usps, product_description, target_customer). Pick ONE specific buyer "
        "pain or desire from the avatar (or the given target_angle_strategy) and "
        "derive a human-readable angle from it; then build hook -> subhook -> USPs -> "
        "CTA from THAT one angle + the avatar. Match the pronoun and tone. Ground USP "
        "lines in product_benefits/product_usps when present; if none are given, keep "
        "USPs to safe product-format/usage truths and invent no outcomes. Each "
        "candidate must express a DIFFERENT angle. "
        "If sensitivity is STEALTH or route_type is STEALTH: this is a "
        "privacy-sensitive product — NEVER name the body part, medical condition, or "
        "intimate/sexual function explicitly; sell through wrapped metaphor, ego / "
        "maruah (masculine pride & dignity) and self-confidence pressure, and "
        "everyday-routine framing; keep every line dialogue-safe. "
        "If claim_risk_level is HIGH, be extra conservative — no health/medical "
        "outcomes and no performance or cure implications of any kind. "
        "Hard safety rules — DO NOT write medical/cure/treat/heal claims, guaranteed "
        "results, universal-safety ('no side effects', 'safe for everyone'), "
        "before/after implications, or clinical-authority claims. "
        "Return STRICT JSON ONLY, no markdown, with keys: angle, hook, subhook, "
        "usp_set (array of up to 3 strings), cta, formula_family, rationale, "
        "risk_notes (array of strings)."
    )
    user = (
        "Generate ONE safe copy candidate as JSON for this brief. "
        "Ground it in the product truth; invent no facts.\n\n" + str(brief)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _split_system_and_turns(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """Anthropic /v1/messages takes `system` at the top level and only
    user/assistant turns in `messages`."""
    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
        else:
            turns.append({"role": role, "content": content})
    return "\n\n".join(system_parts), turns


def _sanitize_provider_text(text: object, limit: int = 500) -> str:
    """Bounded, secret-scrubbed provider text for safe diagnostics."""
    if not isinstance(text, str):
        text = str(text or "")
    # Defensive: never let an accidental key/bearer token survive into diagnostics.
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9._\-]{8,}", "[REDACTED]", text)
    return text.strip()[:limit]


def _provider_request_id(response: Any) -> str | None:
    """Extract a safe provider request-id header (never a credential)."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name in (
        "x-request-id",
        "x-requestid",
        "openai-request-id",
        "request-id",
        "cf-ray",
    ):
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value:
            return _sanitize_provider_text(value, 200) or None
    return None


def _raise_for_provider_status(
    response: Any, *, provider_id: str, model: str
) -> None:
    """Raise a secret-safe ``AICopyProviderError`` on a non-2xx provider response.

    Unlike ``response.raise_for_status()`` this first captures the provider's safe
    error diagnostics (``type``/``code``/``message``/``request_id``) so a failed
    call leaves durable evidence instead of a bare status code.  Never persists
    Authorization / API keys / cookies / request headers or the request body; the
    message is bounded and scrubbed.
    """
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or status < 400:
        return
    provider_error_type = provider_error_code = provider_error_message = None
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            provider_error_type = error.get("type")
            provider_error_code = error.get("code")
            provider_error_message = error.get("message")
        else:
            provider_error_message = body.get("message") or body.get("detail")
    if provider_error_message is None:
        provider_error_message = _sanitize_provider_text(
            getattr(response, "text", "") or ""
        )
    diagnostic_metadata = {
        "provider_error_type": (
            _sanitize_provider_text(provider_error_type, 120)
            if provider_error_type is not None
            else None
        ),
        "provider_error_code": (
            _sanitize_provider_text(provider_error_code, 120)
            if provider_error_code is not None
            else None
        ),
        "provider_error_message": _sanitize_provider_text(provider_error_message, 500)
        or None,
        "provider_request_id": _provider_request_id(response),
    }
    raise AICopyProviderError(
        ERR_CALL_FAILED,
        detail=f"{provider_id} provider returned HTTP {status}",
        diagnostic_category="PROVIDER_HTTP_ERROR",
        diagnostic_metadata=diagnostic_metadata,
        http_status=status,
    )


def _complete_anthropic(
    messages: list[dict[str, str]],
    api_key: str,
    base_url: str,
    model: str,
    *,
    max_output_tokens: int | None = None,
) -> tuple[str, int | None, dict[str, int | float], str | None]:
    """Native Anthropic Messages transport (/v1/messages). Scoped to the
    text_assist lane; disabled by default and exercised only via unit tests."""
    import httpx  # local import — only when actually executing a configured call

    system, turns = _split_system_and_turns(messages)
    response = httpx.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": min(
                int(max_output_tokens or ANTHROPIC_JSON_MAX_TOKENS),
                ANTHROPIC_JSON_MAX_TOKENS,
            ),
            "temperature": 0.5,
            "system": system,
            "messages": turns,
        },
        timeout=_TIMEOUT_SECONDS,
    )
    _raise_for_provider_status(response, provider_id="anthropic", model=model)
    data = response.json()
    blocks = data.get("content") or []
    for block in blocks:
        if isinstance(block, dict) and str(block.get("type") or "") == "text":
            return (
                str(block.get("text") or ""),
                getattr(response, "status_code", None),
                _safe_usage(data.get("usage")),
                str(data.get("stop_reason") or "").strip() or None,
            )
    raise AICopyProviderError(
        ERR_RESPONSE_INVALID,
        diagnostic_category=DIAGNOSTIC_CONTENT_EXTRACTION_FAILED,
        http_status=getattr(response, "status_code", None),
        finish_reason=str(data.get("stop_reason") or "").strip() or None,
        usage=_safe_usage(data.get("usage")),
    )


def _complete_openai_compatible(
    messages: list[dict[str, str]],
    api_key: str,
    base_url: str,
    model: str,
    *,
    provider_id: str,
    json_output_enabled: bool,
    max_output_tokens: int | None = None,
    request_contract: dict[str, Any] | None = None,
) -> tuple[str, int | None, dict[str, int | float], str | None]:
    """OpenAI-compatible /chat/completions transport (qwen/openai/gemini/deepseek).
    Mirrors the proven product_knowledge_service httpx pattern.

    ``request_contract`` (resolved from the model catalog) governs the
    family-specific request shape: which output-token parameter to send and
    whether to send an explicit temperature.  It defaults to the pre-existing
    behavior (explicit temperature 0.5, ``max_tokens``) so DeepSeek / Qwen /
    Gemini / gpt-4o are byte-for-byte unchanged, while GPT-5.x models send
    ``max_completion_tokens`` and omit temperature per their official contract."""
    import httpx  # local import — only when actually executing a configured call

    contract = request_contract or DEFAULT_CHAT_REQUEST_CONTRACT
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
    }
    # Temperature policy: GPT-5.x reasoning models reject a non-default temperature,
    # so their contract omits it; every other model keeps the explicit value.
    if str(contract.get("temperature_policy") or "explicit") == "explicit":
        payload["temperature"] = contract.get("temperature_value", 0.5)
    if json_output_enabled:
        payload["response_format"] = {"type": "json_object"}
        output_token_parameter = str(
            contract.get("output_token_parameter") or "max_tokens"
        )
        if output_token_parameter not in {"max_tokens", "max_completion_tokens"}:
            output_token_parameter = "max_tokens"
        payload[output_token_parameter] = min(
            int(max_output_tokens or OPENAI_COMPATIBLE_JSON_MAX_TOKENS),
            OPENAI_COMPATIBLE_JSON_MAX_TOKENS,
        )
        if (
            provider_id == "deepseek"
            and model in _DEEPSEEK_THINKING_MODE_MODELS
        ):
            payload["thinking"] = {"type": "disabled"}

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_TIMEOUT_SECONDS,
    )
    _raise_for_provider_status(response, provider_id=provider_id, model=model)
    data = response.json()
    usage = _safe_usage(data.get("usage")) if isinstance(data, dict) else {}
    http_status = getattr(response, "status_code", None)
    choices = data.get("choices") if isinstance(data, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else None
    finish_reason = (
        str(first_choice.get("finish_reason") or "").strip() or None
        if isinstance(first_choice, dict)
        else None
    )
    message = first_choice.get("message") if isinstance(first_choice, dict) else None
    if not isinstance(message, dict) or "content" not in message:
        raise AICopyProviderError(
            ERR_RESPONSE_INVALID,
            diagnostic_category=DIAGNOSTIC_CONTENT_EXTRACTION_FAILED,
            diagnostic_metadata={"finish_reason": finish_reason},
            http_status=http_status,
            finish_reason=finish_reason,
            usage=usage,
        )
    return (
        str(message.get("content") or ""),
        http_status,
        usage,
        finish_reason,
    )


def _complete(
    messages: list[dict[str, str]],
    *,
    lane: str = LANE,
    structured_output: bool = False,
    max_output_tokens: int | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    api_key_override: str | None = None,
) -> tuple[str, str | None, int]:
    """Execute one provider call for TEXT or STRUCTURE.

    ``provider_override`` is used only by the single STRUCTURE fallback attempt;
    it never changes persisted lane ownership or consults ``active_provider``.
    """
    canonical = _canonical_text_structure_lane(lane)
    if provider_override:
        provider_id = str(provider_override).strip().lower()
        api_key = api_key_override or get_provider_api_key(provider_id)
    else:
        provider_id = str(get_lane_provider(canonical) or "").lower()
        api_key = get_lane_api_key_for_execution(canonical)
    base_url = _resolve_base_url(provider_id, canonical)
    model = model_override or _resolve_model(provider_id, canonical)
    transport = get_provider_transport(provider_id)
    request_contract = get_model_request_contract(provider_id, model) if model else None
    if not api_key or not base_url or not model:
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail=f"{canonical} key/base_url/model unresolved"
        )
    if transport not in {
        TRANSPORT_ANTHROPIC_MESSAGES,
        TRANSPORT_OPENAI_COMPATIBLE,
    }:
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail=f"unsupported transport for {provider_id}: {transport}"
        )
    json_output_enabled = (
        structured_output
        and transport == TRANSPORT_OPENAI_COMPATIBLE
        and provider_id in _JSON_OUTPUT_PROVIDER_IDS
    )
    effective_output_tokens = (
        clamp_structured_output_tokens(
            max_output_tokens,
            provider_id=provider_id,
            model_id=model,
        )
        if structured_output
        else None
    )
    call_id = _begin_provider_call(
        lane=canonical,
        provider_id=provider_id,
        model=model,
        transport=transport,
        structured_output_requested=structured_output,
        json_output_mode="json_object" if json_output_enabled else None,
        requested_output_tokens=max_output_tokens if structured_output else None,
        effective_output_tokens=effective_output_tokens,
    )
    try:
        if transport == TRANSPORT_ANTHROPIC_MESSAGES:
            text, http_status, usage, finish_reason = _complete_anthropic(
                messages,
                api_key,
                base_url,
                model,
                max_output_tokens=effective_output_tokens,
            )
        else:
            text, http_status, usage, finish_reason = _complete_openai_compatible(
                messages,
                api_key,
                base_url,
                model,
                provider_id=provider_id,
                json_output_enabled=json_output_enabled,
                max_output_tokens=effective_output_tokens,
                request_contract=request_contract,
            )
        _finish_provider_call(
            call_id,
            response_status="SUCCEEDED",
            http_status=http_status,
            usage=usage,
            finish_reason=finish_reason,
        )
        return text, finish_reason, call_id
    except AICopyProviderError as exc:
        _finish_provider_call(
            call_id,
            response_status=(
                "INVALID_RESPONSE"
                if exc.code == ERR_RESPONSE_INVALID
                else "FAILED"
            ),
            http_status=exc.http_status,
            usage=exc.usage,
            finish_reason=exc.finish_reason,
        )
        if exc.code == ERR_RESPONSE_INVALID:
            _record_json_parse_result(
                call_id,
                status="INVALID",
                diagnostic_category=exc.diagnostic_category,
                diagnostic_metadata=exc.diagnostic_metadata,
            )
        elif exc.diagnostic_category is not None or exc.diagnostic_metadata:
            # Non-2xx provider HTTP error (e.g. GPT-5.x 400 unsupported_parameter,
            # or a 429): persist the safe provider diagnostics into the receipt.
            _record_provider_diagnostics(
                call_id,
                diagnostic_category=exc.diagnostic_category,
                diagnostic_metadata=exc.diagnostic_metadata,
            )
        exc.call_id = call_id
        exc.provider_receipt = _snapshot_provider_call_receipt(call_id)
        raise
    except Exception as exc:  # network / shape / auth — fail closed
        response = getattr(exc, "response", None)
        _finish_provider_call(
            call_id,
            response_status="FAILED",
            http_status=getattr(response, "status_code", None),
        )
        error = AICopyProviderError(ERR_CALL_FAILED, detail=str(exc))
        error.call_id = call_id
        error.provider_receipt = _snapshot_provider_call_receipt(call_id)
        raise error from exc


def _pop_usage(call_id: int) -> dict[str, float]:
    with _provider_call_lock:
        return _usage_by_call_id.pop(call_id, {})


def _snapshot_provider_call_receipt(call_id: int) -> dict[str, Any]:
    """Copy one exact call receipt without removing it from the drain map."""

    with _provider_call_lock:
        receipt = dict(_provider_call_receipt_by_id.get(call_id, {}))
        if receipt:
            receipt["usage"] = dict(receipt.get("usage") or {})
            receipt["diagnostic_metadata"] = dict(
                receipt.get("diagnostic_metadata") or {}
            )
        return receipt


def _pop_provider_call_receipt(call_id: int) -> dict[str, Any]:
    """Drain and return the secret-free receipt for one exact provider call."""

    with _provider_call_lock:
        receipt = dict(_provider_call_receipt_by_id.pop(call_id, {}))
        if receipt:
            receipt["usage"] = dict(receipt.get("usage") or {})
            receipt["diagnostic_metadata"] = dict(
                receipt.get("diagnostic_metadata") or {}
            )
        return receipt


def generate_candidate(brief: str, *, lane: str = "text") -> dict[str, Any]:
    """Single mockable natural-language candidate seam.

    Candidate generation is TEXT by contract; the explicit lane parameter keeps
    the routing boundary visible to callers while rejecting STRUCTURE/IMAGE/
    VIDEO misuse at the adapter boundary.
    """
    canonical = _canonical_text_structure_lane(lane)
    if not is_configured(canonical):
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    message_text, finish_reason, call_id = _complete(
        build_messages(brief), lane=canonical
    )
    try:
        obj = _extract_json_object(message_text, finish_reason=finish_reason)
    except Exception:
        _pop_usage(call_id)  # B3: drain on parse failure — never leak
        _pop_provider_call_receipt(call_id)
        raise
    usage = _pop_usage(call_id)
    _pop_provider_call_receipt(call_id)
    if isinstance(obj, dict):
        obj["__usage__"] = usage
    return obj


def _fallback_is_eligible(error: AICopyProviderError) -> bool:
    """Allow fallback only for provider capability/nonconformance failures."""

    if error.code == ERR_RESPONSE_INVALID:
        return True
    return error.code == ERR_CALL_FAILED and error.http_status in {400, 404, 415, 422}


def _structure_fallback_target() -> tuple[str, str, str] | None:
    """Resolve one secret-free fallback target, or return ``None`` fail-closed."""

    if not is_lane_execution_enabled("structure"):
        return None
    primary_provider = str(get_lane_provider("structure") or "").strip().lower()
    primary_model = str(get_lane_model("structure") or "").strip()
    configured = get_structure_fallback()
    provider_id = str(configured.get("provider_id") or "").strip().lower()
    model_id = str(configured.get("model_id") or "").strip()
    if not configured.get("enabled") or not provider_id or not model_id:
        return None
    if provider_id == primary_provider and model_id == primary_model:
        return None
    if not model_supports_lane(provider_id, model_id, "structure"):
        return None
    try:
        api_key = get_provider_api_key(provider_id)
    except Exception:
        return None
    if not api_key:
        return None
    return provider_id, model_id, api_key


def _finish_json_attempt(
    text: str,
    finish_reason: str | None,
    call_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any], AICopyProviderError | None]:
    """Parse and drain exactly one call into a secret-free receipt."""

    try:
        parsed = _extract_json_object(text, finish_reason=finish_reason)
    except AICopyProviderError as exc:
        _record_json_parse_result(
            call_id,
            status="INVALID",
            diagnostic_category=exc.diagnostic_category,
            diagnostic_metadata=exc.diagnostic_metadata,
        )
        usage = _pop_usage(call_id)
        receipt = _pop_provider_call_receipt(call_id)
        if usage:
            receipt["usage"] = usage
            exc.usage = dict(usage)
        exc.call_id = call_id
        exc.provider_receipt = receipt
        return None, receipt, exc
    _record_json_parse_result(call_id, status="VALID")
    usage = _pop_usage(call_id)
    receipt = _pop_provider_call_receipt(call_id)
    receipt["usage"] = usage
    return parsed, receipt, None


def _attach_fallback_receipts(
    selected_receipt: dict[str, Any],
    primary_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Make the primary/fallback relationship explicit without duplicating secrets."""

    result = dict(selected_receipt)
    result["fallback_used"] = True
    result["primary_receipt"] = dict(primary_receipt)
    result["fallback_receipt"] = dict(selected_receipt)
    return result


def complete_json_with_receipt(
    system: str,
    user: str,
    *,
    max_output_tokens: int | None = None,
    lane: str = LANE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return parsed JSON plus provenance for the exact call that produced it.

    The process-global latest-call receipt remains available for diagnostics, but
    production lineage must use this per-call return value so concurrent requests
    cannot be associated with one another.
    """

    canonical = _canonical_text_structure_lane(lane)
    if not is_configured(canonical):
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    primary_receipt: dict[str, Any] = {}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        text, finish_reason, call_id = _complete(
            messages,
            lane=canonical,
            structured_output=True,
            max_output_tokens=max_output_tokens,
        )
    except AICopyProviderError as exc:
        # _complete has already finished the exact call.  Drain its usage and
        # receipt here so provider transport failures are observable without
        # relying on the process-global "last call" under concurrency.
        call_id = getattr(exc, "call_id", None)
        if call_id is not None:
            primary_receipt = _pop_provider_call_receipt(call_id)
            usage = _pop_usage(call_id)
            if usage:
                primary_receipt["usage"] = usage
                exc.usage = dict(usage)
            exc.provider_receipt = primary_receipt
        if canonical == "structure" and _fallback_is_eligible(exc):
            target = _structure_fallback_target()
            if target:
                provider_id, model_id, api_key = target
                try:
                    fallback_text, fallback_finish, fallback_call_id = _complete(
                        messages,
                        lane=canonical,
                        structured_output=True,
                        max_output_tokens=max_output_tokens,
                        provider_override=provider_id,
                        model_override=model_id,
                        api_key_override=api_key,
                    )
                except AICopyProviderError as fallback_error:
                    fallback_receipt = getattr(fallback_error, "provider_receipt", {})
                    fallback_call_id = getattr(fallback_error, "call_id", None)
                    if fallback_call_id is not None:
                        fallback_receipt = _pop_provider_call_receipt(fallback_call_id)
                        usage = _pop_usage(fallback_call_id)
                        if usage:
                            fallback_receipt["usage"] = usage
                            fallback_error.usage = dict(usage)
                    fallback_error.provider_receipt = {
                        "primary_receipt": primary_receipt,
                        "fallback_receipt": fallback_receipt,
                    }
                    raise fallback_error
                parsed, fallback_receipt, fallback_error = _finish_json_attempt(
                    fallback_text, fallback_finish, fallback_call_id
                )
                if fallback_error is not None:
                    fallback_error.provider_receipt = {
                        "primary_receipt": primary_receipt,
                        "fallback_receipt": fallback_receipt,
                    }
                    raise fallback_error
                return parsed or {}, _attach_fallback_receipts(fallback_receipt, primary_receipt)
        raise
    parsed, primary_receipt, parse_error = _finish_json_attempt(
        text, finish_reason, call_id
    )
    if parse_error is not None:
        if canonical == "structure" and _fallback_is_eligible(parse_error):
            target = _structure_fallback_target()
            if target:
                provider_id, model_id, api_key = target
                try:
                    fallback_text, fallback_finish, fallback_call_id = _complete(
                        messages,
                        lane=canonical,
                        structured_output=True,
                        max_output_tokens=max_output_tokens,
                        provider_override=provider_id,
                        model_override=model_id,
                        api_key_override=api_key,
                    )
                except AICopyProviderError as fallback_error:
                    fallback_receipt = getattr(fallback_error, "provider_receipt", {})
                    fallback_call_id = getattr(fallback_error, "call_id", None)
                    if fallback_call_id is not None:
                        fallback_receipt = _pop_provider_call_receipt(fallback_call_id)
                        usage = _pop_usage(fallback_call_id)
                        if usage:
                            fallback_receipt["usage"] = usage
                            fallback_error.usage = dict(usage)
                    fallback_error.provider_receipt = {
                        "primary_receipt": primary_receipt,
                        "fallback_receipt": fallback_receipt,
                    }
                    raise fallback_error
                parsed_fallback, fallback_receipt, fallback_error = _finish_json_attempt(
                    fallback_text, fallback_finish, fallback_call_id
                )
                if fallback_error is not None:
                    fallback_error.provider_receipt = {
                        "primary_receipt": primary_receipt,
                        "fallback_receipt": fallback_receipt,
                    }
                    raise fallback_error
                return parsed_fallback or {}, _attach_fallback_receipts(
                    fallback_receipt, primary_receipt
                )
        raise parse_error
    return parsed or {}, primary_receipt


def complete_json(
    system: str,
    user: str,
    *,
    max_output_tokens: int | None = None,
    lane: str = LANE,
) -> dict[str, Any]:
    """Generic structured-JSON call via the configured TEXT/STRUCTURE lane. Fail-closed
    when the lane is unconfigured (raises AICopyProviderNotConfigured). Reuses the
    SAME provider/key/model/transport as copy — no new secrets, no hardcoded model."""
    parsed, _receipt = complete_json_with_receipt(
        system,
        user,
        max_output_tokens=max_output_tokens,
        lane=lane,
    )
    return parsed
