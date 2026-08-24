"""AI Copy Assist — provider adapter boundary (candidate copy only).

Thin, disabled-by-default boundary between the AI Copy Assist service and a text
LLM provider. It REUSES the existing on-main lane provider abstraction
(`ai_provider_settings_service`, the "text_assist" lane) for enablement + key +
provider selection — no new secrets, no new settings UI.

Hard rules:
- Disabled by default: with no configured/enabled text_assist lane key, every
  call fails closed with `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED`.
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
    TRANSPORT_ANTHROPIC_MESSAGES,
    TRANSPORT_OPENAI_COMPATIBLE,
    get_provider_transport,
)
from agent.services.ai_provider_settings_service import (
    get_lane_api_key,
    get_lane_model,
    get_lane_provider,
    is_lane_execution_enabled,
)

LANE = "text_assist"

# The operator's UI-selected lane model is the ONLY model source (with an optional
# deployment env override). There is NO hardcoded model fallback — an unconfigured
# lane resolves to None and the call fails closed. Base URLs below are transport
# endpoints (not model choices) and may be overridden per deployment.
_BASE_URL_ENV = "PRODUCT_TEXT_ASSIST_BASE_URL"
_MODEL_ENV = "PRODUCT_TEXT_ASSIST_MODEL"
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
    """Raised when the text_assist lane is not configured/enabled (default)."""

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
            "lane": LANE,
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


def is_configured() -> bool:
    """True only when the text_assist lane has a configured provider+model, a key,
    AND execution is enabled. Fail closed everywhere else (no hidden default)."""
    try:
        return (
            bool(get_lane_api_key(LANE))
            and bool(get_lane_model(LANE))
            and bool(is_lane_execution_enabled(LANE))
        )
    except Exception:
        return False


def provider_status() -> dict[str, Any]:
    provider_id = None
    model_id = None
    execution_enabled = False
    try:
        provider_id = get_lane_provider(LANE)
    except Exception:
        provider_id = None
    try:
        model_id = _resolve_model(provider_id)
    except Exception:
        model_id = None
    try:
        execution_enabled = bool(is_lane_execution_enabled(LANE))
    except Exception:
        execution_enabled = False
    return {
        "lane": LANE,
        "configured": is_configured(),
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
    }


def _resolve_base_url(provider_id: str | None) -> str | None:
    env = str(os.environ.get(_BASE_URL_ENV, "")).strip().rstrip("/")
    if env:
        return env
    return _DEFAULT_BASE_URLS.get(str(provider_id or "").lower())


def _resolve_model(provider_id: str | None) -> str | None:
    # UI-selected lane model is the ONLY source (optional env override). No
    # hardcoded per-provider default — unconfigured resolves to None (fail closed).
    try:
        lane_model = get_lane_model(LANE)
    except Exception:
        lane_model = None
    if lane_model:
        return lane_model
    env = str(os.environ.get(_MODEL_ENV, "")).strip()
    return env or None


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
    response.raise_for_status()
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
) -> tuple[str, int | None, dict[str, int | float], str | None]:
    """OpenAI-compatible /chat/completions transport (qwen/openai/gemini/deepseek).
    Mirrors the proven product_knowledge_service httpx pattern."""
    import httpx  # local import — only when actually executing a configured call

    payload: dict[str, object] = {
        "model": model,
        "temperature": 0.5,
        "messages": messages,
    }
    if json_output_enabled:
        payload["response_format"] = {"type": "json_object"}
        payload["max_tokens"] = min(
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
    response.raise_for_status()
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
    structured_output: bool = False,
    max_output_tokens: int | None = None,
) -> tuple[str, str | None, int]:
    """Execute a chat completion via the configured text_assist lane. Anthropic
    speaks its native /v1/messages shape; every other provider is OpenAI-compatible.
    Never reached in tests (disabled by default)."""
    api_key = get_lane_api_key(LANE)
    provider_id = str(get_lane_provider(LANE) or "").lower()
    base_url = _resolve_base_url(provider_id)
    model = _resolve_model(provider_id)
    transport = get_provider_transport(provider_id)
    if not api_key or not base_url or not model:
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail="text_assist key/base_url/model unresolved"
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


def generate_candidate(brief: str) -> dict[str, Any]:
    """Single mockable seam. Fail closed when unconfigured; otherwise call the
    provider and return the parsed candidate JSON dict (with reliable __usage__)."""
    if not is_configured():
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    message_text, finish_reason, call_id = _complete(build_messages(brief))
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


def complete_json_with_receipt(
    system: str,
    user: str,
    *,
    max_output_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return parsed JSON plus provenance for the exact call that produced it.

    The process-global latest-call receipt remains available for diagnostics, but
    production lineage must use this per-call return value so concurrent requests
    cannot be associated with one another.
    """

    if not is_configured():
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    try:
        text, finish_reason, call_id = _complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            structured_output=True,
            max_output_tokens=max_output_tokens,
        )
    except AICopyProviderError as exc:
        # _complete has already finished the exact call.  Drain its usage and
        # receipt here so provider transport failures are observable without
        # relying on the process-global "last call" under concurrency.
        call_id = getattr(exc, "call_id", None)
        if call_id is not None:
            receipt = _pop_provider_call_receipt(call_id)
            usage = _pop_usage(call_id)
            if usage:
                receipt["usage"] = usage
                exc.usage = dict(usage)
            exc.provider_receipt = receipt
        raise
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
        raise
    _record_json_parse_result(call_id, status="VALID")
    usage = _pop_usage(call_id)
    receipt = _pop_provider_call_receipt(call_id)
    receipt["usage"] = usage
    return parsed, receipt


def complete_json(
    system: str,
    user: str,
    *,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Generic structured-JSON call via the configured text_assist lane. Fail-closed
    when the lane is unconfigured (raises AICopyProviderNotConfigured). Reuses the
    SAME provider/key/model/transport as copy — no new secrets, no hardcoded model."""
    parsed, _receipt = complete_json_with_receipt(
        system,
        user,
        max_output_tokens=max_output_tokens,
    )
    return parsed
