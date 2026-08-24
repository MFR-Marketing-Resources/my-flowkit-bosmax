from __future__ import annotations

"""Secret-safe, operator-owned AI provider settings.

V4 has four canonical persisted lanes: ``text``, ``structure``, ``image`` and
``video``. The old ``text_assist`` and ``vision`` names are accepted only by
read/migration helpers so older callers can fail closed while they move to the
new authority. No lane ever consults ``active_provider`` for routing.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from agent.config import BASE_DIR
from agent.services.ai_provider_model_catalog import (
    LANES,
    LANE_LABELS,
    canonical_lane_id,
    get_model_entry,
    model_supports_lane,
    summarize_model_catalog,
    supported_lanes_for_provider,
    validate_provider_model_for_lane,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]

PROVIDER_IDS: tuple[ProviderId, ...] = (
    "qwen", "anthropic", "openai", "gemini", "deepseek"
)
PROVIDER_LABELS: dict[ProviderId, str] = {
    "qwen": "Qwen", "anthropic": "Anthropic", "openai": "OpenAI",
    "gemini": "Gemini", "deepseek": "DeepSeek",
}
PROVIDER_ENV_VARS: dict[ProviderId, str] = {
    "qwen": "DASHSCOPE_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
PROVIDER_SCOPES: dict[ProviderId, str] = {
    "qwen": "REGISTRY_ONLY", "anthropic": "LIVE_NOW", "openai": "REGISTRY_ONLY",
    "gemini": "REGISTRY_ONLY", "deepseek": "REGISTRY_ONLY",
}
PROVIDER_CAPABILITIES: dict[ProviderId, list[str]] = {
    provider_id: ["Model capabilities are declared per catalog entry"]
    for provider_id in PROVIDER_IDS
}

AI_PROVIDER_STATE_DIR = BASE_DIR / ".local-agent"
AI_PROVIDER_SETTINGS_FILE = AI_PROVIDER_STATE_DIR / "ai-provider-settings.json"
AI_PROVIDER_STATE_VERSION = 4
ACTIVE_PROVIDER_ENV_VAR = "BOSMAX_ACTIVE_AI_PROVIDER"

LANE_EXECUTION_ENV_VARS: dict[str, str] = {
    "text": "BOSMAX_TEXT_EXECUTION_ENABLED",
    "structure": "BOSMAX_STRUCTURE_EXECUTION_ENABLED",
    "image": "BOSMAX_IMAGE_EXECUTION_ENABLED",
    "video": "BOSMAX_VIDEO_EXECUTION_ENABLED",
}
# Compatibility reads only; no V4 payload writes these names.
LEGACY_LANE_EXECUTION_ENV_VARS: dict[str, str] = {
    "text": "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED",
    "image": "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED",
}
LANE_EXECUTION_DEFAULTS: dict[str, bool] = {lane: False for lane in LANES}

TEXT_PROVIDER_ENV_VAR = "PRODUCT_TEXT_PROVIDER"
STRUCTURE_PROVIDER_ENV_VAR = "PRODUCT_STRUCTURE_PROVIDER"
IMAGE_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_PROVIDER"
VIDEO_PROVIDER_ENV_VAR = "PRODUCT_VIDEO_PROVIDER"
TEXT_ASSIST_PROVIDER_ENV_VAR = "PRODUCT_TEXT_ASSIST_PROVIDER"
VISION_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_VISION_PROVIDER"

_V2_SEED_LANE_DEFAULTS: dict[str, tuple[str, str]] = {
    "text": ("qwen", "qwen-plus"),
    "structure": ("qwen", "qwen-plus"),
    "image": ("anthropic", "claude-sonnet-5"),
}

LANE_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
LANE_STATUS_MODEL_MISSING = "MODEL_MISSING"
LANE_STATUS_MODEL_DISABLED = "MODEL_DISABLED"
LANE_STATUS_KEY_MISSING = "KEY_MISSING"
LANE_STATUS_EXECUTION_DISABLED = "EXECUTION_DISABLED"
LANE_STATUS_FALLBACK_INVALID = "FALLBACK_INVALID"
LANE_STATUS_READY = "READY"
_UNSET = object()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_provider_id(value: str) -> ProviderId:
    normalized = str(value or "").strip().lower()
    if normalized not in PROVIDER_IDS:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{value}")
    return normalized  # type: ignore[return-value]


def _mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"


def _ensure_state_dir() -> None:
    AI_PROVIDER_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _canonical_lane_or_error(lane: str) -> str:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES:
        raise ValueError(f"UNSUPPORTED_LANE:{lane}")
    return canonical


def _not_configured_lane(lane: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider_id": None, "model_id": None, "execution_enabled": False,
        "configured_by_user": False,
    }
    if lane == "structure":
        payload.update({
            "fallback_provider_id": None,
            "fallback_model_id": None,
            "fallback_enabled": False,
        })
    if lane == "video":
        payload["engine_id"] = None
    return payload


def _default_payload() -> dict[str, Any]:
    return {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": None,
        "providers": {
            provider_id: {
                "api_key": "", "updated_at": None, "activated_at": None,
                "default_model": None,
            }
            for provider_id in PROVIDER_IDS
        },
        "lanes": {lane: _not_configured_lane(lane) for lane in LANES},
    }


def _safe_version(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _raw_lane(raw_lanes: dict[str, Any], *names: str) -> dict[str, Any] | None:
    for name in names:
        entry = raw_lanes.get(name)
        if isinstance(entry, dict):
            return entry
    return None


def _lane_values(entry: dict[str, Any] | None) -> tuple[str | None, str | None, bool]:
    if not isinstance(entry, dict):
        return None, None, False
    provider_id = str(entry.get("provider_id") or "").strip().lower() or None
    model_id = str(entry.get("model_id") or "").strip() or None
    return provider_id, model_id, bool(entry.get("execution_enabled"))


def _copy_explicit_lane(entry: dict[str, Any] | None, lane: str) -> dict[str, Any]:
    provider_id, model_id, execution_enabled = _lane_values(entry)
    if provider_id not in PROVIDER_IDS or not model_id:
        return _not_configured_lane(lane)
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
        "configured_by_user": bool(entry.get("configured_by_user")) if isinstance(entry, dict) else False,
    }
    if lane == "structure" and isinstance(entry, dict):
        fallback_provider = str(entry.get("fallback_provider_id") or "").strip().lower() or None
        fallback_model = str(entry.get("fallback_model_id") or "").strip() or None
        result.update({
            "fallback_provider_id": fallback_provider if fallback_provider in PROVIDER_IDS else None,
            "fallback_model_id": fallback_model if fallback_provider in PROVIDER_IDS and fallback_model else None,
            "fallback_enabled": bool(entry.get("fallback_enabled")),
        })
    if lane == "video" and isinstance(entry, dict):
        result["engine_id"] = str(entry.get("engine_id") or "").strip() or None
    return result


def _migrate_v2_lane(entry: dict[str, Any] | None, lane: str) -> dict[str, Any]:
    provider_id, model_id, execution_enabled = _lane_values(entry)
    if provider_id not in PROVIDER_IDS or not model_id:
        return _not_configured_lane(lane)
    if (provider_id, model_id) == _V2_SEED_LANE_DEFAULTS.get(lane):
        return _not_configured_lane(lane)
    result: dict[str, Any] = {
        "provider_id": provider_id, "model_id": model_id,
        "execution_enabled": execution_enabled, "configured_by_user": True,
    }
    if lane == "structure":
        result.update({"fallback_provider_id": None, "fallback_model_id": None, "fallback_enabled": False})
    return result


def _migrate_lanes(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return canonical V4 lanes without rewriting the source file.

    V3 ``text_assist`` mixed multiple responsibilities. Only an explicit
    ``configured_by_user=true`` entry is copied, and it is copied to both TEXT
    and STRUCTURE. V3 ``vision`` maps to IMAGE. VIDEO is never inferred.
    """
    raw_version = _safe_version(raw.get("version"))
    raw_lanes = raw.get("lanes") if isinstance(raw.get("lanes"), dict) else {}
    old_text = _raw_lane(raw_lanes, "text_assist", "text")
    old_image = _raw_lane(raw_lanes, "vision", "image")
    result: dict[str, dict[str, Any]] = {}

    if raw_version >= 4:
        for lane in LANES:
            result[lane] = _copy_explicit_lane(raw_lanes.get(lane), lane)
        # A partially upgraded V4 file may contain only the old aliases.  Treat
        # that as a migration seam, not as a reason to strand an explicit lane.
        if result["text"]["provider_id"] is None and isinstance(old_text, dict):
            if bool(old_text.get("configured_by_user")):
                result["text"] = _copy_explicit_lane(old_text, "text")
                if result["structure"]["provider_id"] is None:
                    result["structure"] = _copy_explicit_lane(old_text, "structure")
        if result["image"]["provider_id"] is None and isinstance(old_image, dict):
            result["image"] = _copy_explicit_lane(old_image, "image")
        return result

    if raw_version >= 3:
        text_entry = _not_configured_lane("text")
        structure_entry = _not_configured_lane("structure")
        if isinstance(old_text, dict) and bool(old_text.get("configured_by_user")):
            text_entry = _copy_explicit_lane(old_text, "text")
            structure_entry = _copy_explicit_lane(old_text, "structure")
            structure_entry.update({"fallback_provider_id": None, "fallback_model_id": None, "fallback_enabled": False})
        result["text"] = text_entry
        result["structure"] = structure_entry
        if isinstance(old_image, dict) and (
            bool(old_image.get("configured_by_user"))
            or bool(old_image.get("provider_id"))
            or bool(old_image.get("model_id"))
        ):
            result["image"] = _copy_explicit_lane(old_image, "image")
        else:
            result["image"] = _not_configured_lane("image")
        result["video"] = _not_configured_lane("video")
        return result

    if raw_version == 2:
        result["text"] = _migrate_v2_lane(old_text, "text")
        result["structure"] = _migrate_v2_lane(old_text, "structure")
        result["image"] = _migrate_v2_lane(old_image, "image")
        result["video"] = _not_configured_lane("video")
        return result

    return {lane: _not_configured_lane(lane) for lane in LANES}


def _load_payload() -> dict[str, Any]:
    """Load and idempotently upgrade legacy state to one canonical V4 payload.

    The upgrade is performed only after the secret-bearing fields have been
    copied into the in-memory payload.  It never logs or returns the key, and
    it leaves already-canonical V4 files untouched.
    """
    _ensure_state_dir()
    default_payload = _default_payload()
    if not AI_PROVIDER_SETTINGS_FILE.exists():
        AI_PROVIDER_SETTINGS_FILE.write_text(json.dumps(default_payload, indent=2) + "\n", encoding="utf-8")
        return default_payload
    try:
        raw = json.loads(AI_PROVIDER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        AI_PROVIDER_SETTINGS_FILE.write_text(json.dumps(default_payload, indent=2) + "\n", encoding="utf-8")
        return default_payload
    if not isinstance(raw, dict):
        AI_PROVIDER_SETTINGS_FILE.write_text(json.dumps(default_payload, indent=2) + "\n", encoding="utf-8")
        return default_payload

    raw_version = _safe_version(raw.get("version"))
    raw_lanes = raw.get("lanes") if isinstance(raw.get("lanes"), dict) else {}
    needs_canonical_write = raw_version != AI_PROVIDER_STATE_VERSION or any(
        alias in raw_lanes for alias in ("text_assist", "vision")
    )
    payload: dict[str, Any] = {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": raw.get("active_provider"),
        "providers": {},
        "lanes": _migrate_lanes(raw),
    }
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    for provider_id in PROVIDER_IDS:
        entry = raw_providers.get(provider_id) if isinstance(raw_providers.get(provider_id), dict) else {}
        raw_key = entry.get("api_key") or ""
        payload["providers"][provider_id] = {
            "api_key": raw_key if isinstance(raw_key, str) else str(raw_key),
            "updated_at": entry.get("updated_at"),
            "activated_at": entry.get("activated_at"),
            # Preserve custom/temporarily unavailable model metadata; lane
            # resolution still fails closed if the model is not catalogued.
            "default_model": str(entry.get("default_model")).strip() if entry.get("default_model") else None,
    }
    if payload["active_provider"] not in PROVIDER_IDS:
        payload["active_provider"] = None
    if needs_canonical_write:
        _save_payload(payload)
    return payload


def _save_payload(payload: dict[str, Any]) -> None:
    _ensure_state_dir()
    payload["version"] = AI_PROVIDER_STATE_VERSION
    payload["lanes"] = {
        lane: payload.get("lanes", {}).get(lane) or _not_configured_lane(lane)
        for lane in LANES
    }
    AI_PROVIDER_SETTINGS_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def get_provider_api_key(provider_id: str) -> str:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    stored_key = str(payload["providers"][normalized].get("api_key") or "").strip()
    return stored_key or str(os.environ.get(PROVIDER_ENV_VARS[normalized], "")).strip()


def get_provider_default_model(provider_id: str) -> str | None:
    normalized = _normalize_provider_id(provider_id)
    value = _load_payload()["providers"][normalized].get("default_model")
    return str(value).strip() if value else None


def get_lane_provider(lane: str) -> str | None:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES:
        return None
    state = _load_payload().get("lanes", {}).get(canonical)
    provider_id = state.get("provider_id") if isinstance(state, dict) else None
    return provider_id if provider_id in PROVIDER_IDS else None


def get_lane_model(lane: str) -> str | None:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES:
        return None
    state = _load_payload().get("lanes", {}).get(canonical)
    if not isinstance(state, dict):
        return None
    provider_id, model_id = state.get("provider_id"), state.get("model_id")
    if provider_id in PROVIDER_IDS and model_id and model_supports_lane(provider_id, model_id, canonical):
        return str(model_id)
    return None


def get_lane_api_key(lane: str) -> str | None:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES:
        return None
    provider_id = get_lane_provider(canonical)
    if not provider_id:
        return None
    try:
        key = get_provider_api_key(provider_id)
    except (ValueError, OSError):
        return None
    return key or None


def is_lane_execution_enabled(lane: str) -> bool:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES:
        return False
    current_name = LANE_EXECUTION_ENV_VARS[canonical]
    legacy_name = {"text": "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", "image": "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED"}.get(canonical)
    if str(os.environ.get(current_name, "")).strip():
        return _env_bool(current_name, False)
    if legacy_name and str(os.environ.get(legacy_name, "")).strip():
        return _env_bool(legacy_name, False)
    state = _load_payload().get("lanes", {}).get(canonical)
    if isinstance(state, dict) and isinstance(state.get("execution_enabled"), bool):
        return bool(state["execution_enabled"])
    return LANE_EXECUTION_DEFAULTS[canonical]


def get_lane_api_key_for_execution(lane: str) -> str | None:
    canonical = canonical_lane_id(lane)
    if canonical not in LANES or not is_lane_execution_enabled(canonical):
        return None
    return get_lane_api_key(canonical)


def get_structure_fallback() -> dict[str, Any]:
    """Return the operator's bounded STRUCTURE fallback without any secret.

    The fallback is deliberately separate from the primary lane.  Callers must
    still check ``enabled``, model capability, the shared STRUCTURE execution
    gate, and the provider key before making the one permitted fallback call.
    """

    state = _load_payload().get("lanes", {}).get("structure")
    if not isinstance(state, dict):
        return {
            "provider_id": None,
            "model_id": None,
            "enabled": False,
        }
    provider_id = state.get("fallback_provider_id")
    model_id = state.get("fallback_model_id")
    return {
        "provider_id": provider_id if provider_id in PROVIDER_IDS else None,
        "model_id": str(model_id).strip() if model_id else None,
        "enabled": bool(state.get("fallback_enabled")),
    }


def get_active_provider_id() -> ProviderId | None:
    active_provider = _load_payload().get("active_provider")
    if active_provider in PROVIDER_IDS:
        return active_provider  # type: ignore[return-value]
    value = str(os.environ.get(ACTIVE_PROVIDER_ENV_VAR, "")).strip().lower()
    return value if value in PROVIDER_IDS else None  # type: ignore[return-value]


def _is_provider_runtime_enabled(provider_id: str) -> bool:
    # Legacy environment projection only. Runtime adapters read lane state.
    if str(provider_id).lower() == "anthropic":
        return is_lane_execution_enabled("image") or is_lane_execution_enabled("video")
    return True


def apply_runtime_provider_environment(payload: dict | None = None) -> None:
    resolved = payload or _load_payload()
    for provider_id in PROVIDER_IDS:
        key = str(resolved.get("providers", {}).get(provider_id, {}).get("api_key") or "").strip()
        env_var = PROVIDER_ENV_VARS[provider_id]
        if key and _is_provider_runtime_enabled(provider_id):
            os.environ[env_var] = key
        else:
            os.environ.pop(env_var, None)
    active_provider = resolved.get("active_provider")
    if active_provider in PROVIDER_IDS:
        os.environ[ACTIVE_PROVIDER_ENV_VAR] = active_provider
    else:
        os.environ.pop(ACTIVE_PROVIDER_ENV_VAR, None)
    env_pairs = {
        "text": (TEXT_PROVIDER_ENV_VAR, TEXT_ASSIST_PROVIDER_ENV_VAR),
        "structure": (STRUCTURE_PROVIDER_ENV_VAR,),
        "image": (IMAGE_PROVIDER_ENV_VAR, VISION_PROVIDER_ENV_VAR),
        "video": (VIDEO_PROVIDER_ENV_VAR,),
    }
    for lane, names in env_pairs.items():
        provider_id = get_lane_provider(lane)
        value = provider_id if provider_id and get_lane_api_key(lane) else None
        for name in names:
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _fallback_summary(state: dict[str, Any]) -> dict[str, Any]:
    provider_id = state.get("fallback_provider_id")
    model_id = state.get("fallback_model_id")
    enabled = bool(state.get("fallback_enabled"))
    model_valid = bool(provider_id and model_id and model_supports_lane(provider_id, model_id, "structure"))
    key_present = bool(provider_id in PROVIDER_IDS and get_provider_api_key(provider_id))
    if not provider_id or not model_id:
        status = LANE_STATUS_NOT_CONFIGURED
    elif not model_valid:
        status = LANE_STATUS_MODEL_MISSING
    elif not key_present:
        status = LANE_STATUS_KEY_MISSING
    elif not enabled:
        status = LANE_STATUS_EXECUTION_DISABLED
    else:
        status = LANE_STATUS_READY
    return {
        "provider_id": provider_id if provider_id in PROVIDER_IDS else None,
        "model_id": model_id if provider_id in PROVIDER_IDS and model_id else None,
        "enabled": enabled, "key_present": key_present,
        "model_valid": model_valid, "status": status,
    }


def _lane_status(lane: str, state: dict[str, Any]) -> dict[str, Any]:
    provider_id = state.get("provider_id") if isinstance(state, dict) else None
    model_id = state.get("model_id") if isinstance(state, dict) else None
    execution_enabled = bool(state.get("execution_enabled")) if isinstance(state, dict) else False
    configured_by_user = bool(state.get("configured_by_user")) if isinstance(state, dict) else False
    key_present = bool(get_lane_api_key(lane))
    model_entry = get_model_entry(provider_id, model_id) if provider_id and model_id else None
    model_valid = bool(provider_id and model_id and model_supports_lane(provider_id, model_id, lane))
    if not provider_id or not model_id:
        status = LANE_STATUS_NOT_CONFIGURED
    elif model_entry is None:
        status = LANE_STATUS_MODEL_MISSING
    elif not model_entry.get("enabled"):
        status = LANE_STATUS_MODEL_DISABLED
    elif not model_valid:
        status = LANE_STATUS_MODEL_MISSING
    elif not key_present:
        status = LANE_STATUS_KEY_MISSING
    elif not execution_enabled:
        status = LANE_STATUS_EXECUTION_DISABLED
    else:
        status = LANE_STATUS_READY
    result: dict[str, Any] = {
        "lane": lane, "label": LANE_LABELS[lane],
        "provider_id": provider_id if provider_id in PROVIDER_IDS else None,
        "model_id": model_id if provider_id in PROVIDER_IDS and model_id else None,
        "execution_enabled": execution_enabled, "configured_by_user": configured_by_user,
        "key_present": key_present, "model_valid": model_valid,
        "status": status, "configured": status == LANE_STATUS_READY,
    }
    if lane == "structure":
        fallback = _fallback_summary(state)
        result.update({
            "fallback_provider_id": fallback["provider_id"],
            "fallback_model_id": fallback["model_id"],
            "fallback_enabled": fallback["enabled"],
            "fallback_key_present": fallback["key_present"],
            "fallback_model_valid": fallback["model_valid"],
            "fallback_status": fallback["status"],
        })
        if status == LANE_STATUS_READY and fallback["enabled"] and fallback["status"] != LANE_STATUS_READY:
            result["status"] = LANE_STATUS_FALLBACK_INVALID
            result["configured"] = False
    if lane == "video":
        result["engine_id"] = state.get("engine_id") if isinstance(state, dict) else None
    return result


def summarize_provider_settings() -> dict[str, Any]:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    providers: list[dict[str, Any]] = []
    for provider_id in PROVIDER_IDS:
        key = get_provider_api_key(provider_id)
        has_key = bool(key)
        is_active = active_provider == provider_id
        providers.append({
            "provider_id": provider_id, "label": PROVIDER_LABELS[provider_id],
            "env_var": PROVIDER_ENV_VARS[provider_id], "has_key": has_key,
            "masked_key": _mask_api_key(key),
            "status": "ACTIVE" if is_active and has_key else "READY" if has_key else "KEY_MISSING",
            "is_active": is_active,
            "updated_at": payload["providers"][provider_id].get("updated_at"),
            "activated_at": payload["providers"][provider_id].get("activated_at"),
            "activation_scope": PROVIDER_SCOPES[provider_id],
            "current_capabilities": PROVIDER_CAPABILITIES[provider_id],
            "default_model": get_provider_default_model(provider_id),
            "supported_lanes": supported_lanes_for_provider(provider_id),
        })
    return {
        "active_provider": active_provider if active_provider in PROVIDER_IDS else None,
        "providers": providers,
        "model_catalog": summarize_model_catalog()["providers"],
        "lanes": [_lane_status(lane, payload.get("lanes", {}).get(lane) or {}) for lane in LANES],
    }


def update_provider_key(provider_id: str, api_key: str) -> dict[str, Any]:
    normalized = _normalize_provider_id(provider_id)
    cleaned_key = str(api_key or "").strip()
    if not cleaned_key:
        raise ValueError("API_KEY_REQUIRED")
    payload = _load_payload()
    payload["providers"][normalized]["api_key"] = cleaned_key
    payload["providers"][normalized]["updated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def clear_provider_key(provider_id: str) -> dict[str, Any]:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    payload["providers"][normalized]["api_key"] = ""
    payload["providers"][normalized]["updated_at"] = _iso_now()
    payload["providers"][normalized]["activated_at"] = None
    if payload.get("active_provider") == normalized:
        payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def update_provider_default_model(provider_id: str, model_id: str) -> dict[str, Any]:
    normalized = _normalize_provider_id(provider_id)
    cleaned_model = str(model_id or "").strip()
    model_entry = get_model_entry(normalized, cleaned_model)
    if not model_entry:
        raise ValueError(f"MODEL_NOT_FOUND:{normalized}:{cleaned_model}")
    if not model_entry.get("enabled"):
        raise ValueError(f"MODEL_DISABLED:{normalized}:{cleaned_model}")
    payload = _load_payload()
    payload["providers"][normalized]["default_model"] = cleaned_model
    payload["providers"][normalized]["updated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def update_lane_settings(
    lane: str,
    provider_id: str,
    model_id: str,
    execution_enabled: bool | None = None,
    *,
    fallback_provider_id: str | None | object = _UNSET,
    fallback_model_id: str | None | object = _UNSET,
    fallback_enabled: bool | None | object = _UNSET,
    engine_id: str | None | object = _UNSET,
) -> dict[str, Any]:
    """Configure a lane and, for STRUCTURE, at most one bounded fallback."""
    canonical = _canonical_lane_or_error(lane)
    validate_provider_model_for_lane(provider_id, model_id, canonical)
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    lanes = payload.setdefault("lanes", {})
    state = lanes.get(canonical) if isinstance(lanes.get(canonical), dict) else _not_configured_lane(canonical)
    state.update({"provider_id": normalized, "model_id": str(model_id).strip(), "configured_by_user": True})
    if execution_enabled is not None:
        state["execution_enabled"] = bool(execution_enabled)
    elif not isinstance(state.get("execution_enabled"), bool):
        state["execution_enabled"] = False

    fallback_args_used = any(value is not _UNSET for value in (fallback_provider_id, fallback_model_id, fallback_enabled))
    if canonical != "structure" and fallback_args_used:
        raise ValueError("FALLBACK_ONLY_SUPPORTED_FOR_STRUCTURE")
    if canonical == "structure" and fallback_args_used:
        if fallback_provider_id is None or fallback_model_id is None:
            fallback_pid, fallback_mid, fallback_on = None, None, False
        else:
            fallback_pid = str(state.get("fallback_provider_id") if fallback_provider_id is _UNSET else fallback_provider_id).strip().lower() or None
            fallback_mid = str(state.get("fallback_model_id") if fallback_model_id is _UNSET else fallback_model_id).strip() or None
            fallback_on = bool(state.get("fallback_enabled") if fallback_enabled is _UNSET else fallback_enabled)
        if (fallback_pid is None) != (fallback_mid is None):
            raise ValueError("FALLBACK_PROVIDER_MODEL_REQUIRED")
        if fallback_pid and fallback_mid:
            validate_provider_model_for_lane(fallback_pid, fallback_mid, "structure")
            if fallback_pid == normalized and fallback_mid == str(model_id).strip():
                raise ValueError("FALLBACK_MUST_DIFFER_FROM_PRIMARY")
        if fallback_on and not (fallback_pid and fallback_mid):
            raise ValueError("FALLBACK_CONFIGURATION_REQUIRED")
        state.update({"fallback_provider_id": fallback_pid, "fallback_model_id": fallback_mid, "fallback_enabled": fallback_on})
    if canonical == "video":
        if engine_id is not _UNSET:
            state["engine_id"] = str(engine_id or "").strip() or None
    elif engine_id is not _UNSET and engine_id:
        raise ValueError("ENGINE_ONLY_SUPPORTED_FOR_VIDEO")

    lanes[canonical] = state
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def clear_lane_settings(lane: str) -> dict[str, Any]:
    canonical = _canonical_lane_or_error(lane)
    payload = _load_payload()
    payload.setdefault("lanes", {})[canonical] = _not_configured_lane(canonical)
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def activate_provider(provider_id: str) -> dict[str, Any]:
    normalized = _normalize_provider_id(provider_id)
    if not get_provider_api_key(normalized):
        raise ValueError("API_KEY_MISSING_FOR_PROVIDER")
    payload = _load_payload()
    payload["active_provider"] = normalized
    payload["providers"][normalized]["activated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def deactivate_provider() -> dict[str, Any]:
    payload = _load_payload()
    payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()
