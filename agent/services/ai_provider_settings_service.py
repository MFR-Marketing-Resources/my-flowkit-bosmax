from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from agent.config import BASE_DIR
from agent.services.ai_provider_model_catalog import (
    LANE_LABELS,
    LANES,
    catalog_payload,
    default_model_for_provider,
    is_known_lane,
    is_model_in_provider,
    lane_default_model,
    lane_default_provider,
    model_ids_for_provider,
    model_supports_lane,
    supported_lanes_for_provider,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]

PROVIDER_IDS: tuple[ProviderId, ...] = (
    "qwen",
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
)

PROVIDER_LABELS: dict[ProviderId, str] = {
    "qwen": "Qwen",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
}

PROVIDER_ENV_VARS: dict[ProviderId, str] = {
    "qwen": "DASHSCOPE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

PROVIDER_SCOPES: dict[ProviderId, str] = {
    "qwen": "REGISTRY_ONLY",
    "anthropic": "LIVE_NOW",
    "openai": "REGISTRY_ONLY",
    "gemini": "REGISTRY_ONLY",
    "deepseek": "REGISTRY_ONLY",
}

PROVIDER_CAPABILITIES: dict[ProviderId, list[str]] = {
    "qwen": ["Stored for future BOSMAX module wiring"],
    "anthropic": ["Video review SDK", "Product image vision provider"],
    "openai": ["Stored for future BOSMAX module wiring"],
    "gemini": ["Stored for future BOSMAX module wiring"],
    "deepseek": ["Stored for future BOSMAX module wiring"],
}

AI_PROVIDER_STATE_DIR = BASE_DIR / ".local-agent"
AI_PROVIDER_SETTINGS_FILE = AI_PROVIDER_STATE_DIR / "ai-provider-settings.json"
# V2 introduces per-provider `default_model` + a `lanes` map (text_assist / vision
# provider+model+execution_enabled). V1 files load transparently (migrated in
# memory) and are only rewritten to V2 on the next explicit save — keys preserved.
AI_PROVIDER_STATE_VERSION = 2
ACTIVE_PROVIDER_ENV_VAR = "BOSMAX_ACTIVE_AI_PROVIDER"
VISION_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_VISION_PROVIDER"
TEXT_ASSIST_PROVIDER_ENV_VAR = "PRODUCT_TEXT_ASSIST_PROVIDER"
LANE_EXECUTION_ENV_VARS: dict[str, str] = {
    "vision": "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED",
    "text_assist": "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED",
}
LANE_EXECUTION_DEFAULTS: dict[str, bool] = {
    "vision": False,
    "text_assist": True,
}


def _is_provider_runtime_enabled(provider_id: str) -> bool:
    normalized = str(provider_id or "").strip().lower()
    if normalized == "anthropic":
        return is_lane_execution_enabled("vision")
    return True


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_lane_model(provider_id: str, lane: str) -> str | None:
    """Pick a catalog model that `provider_id` may serve on `lane`. Prefers the
    lane default model, then the provider's first lane-capable model."""
    default_m = lane_default_model(lane)
    if (
        default_m
        and lane_default_provider(lane) == provider_id
        and model_supports_lane(provider_id, default_m, lane)
    ):
        return default_m
    for model_id in model_ids_for_provider(provider_id):
        if model_supports_lane(provider_id, model_id, lane):
            return model_id
    return None


def _default_lane_state(lane: str) -> dict:
    provider_id = lane_default_provider(lane)
    return {
        "provider_id": provider_id,
        "model_id": lane_default_model(lane) or _safe_lane_model(provider_id, lane),
        "execution_enabled": LANE_EXECUTION_DEFAULTS.get(lane, False),
    }


def _default_payload() -> dict:
    return {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": None,
        "providers": {
            provider_id: {
                "api_key": "",
                "updated_at": None,
                "activated_at": None,
                "default_model": default_model_for_provider(provider_id),
            }
            for provider_id in PROVIDER_IDS
        },
        "lanes": {lane: _default_lane_state(lane) for lane in LANES},
    }


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


def _migrate_lane(raw_lanes: dict, lane: str) -> dict:
    entry = raw_lanes.get(lane) if isinstance(raw_lanes.get(lane), dict) else {}
    provider_id = str(entry.get("provider_id") or "").strip().lower()
    if provider_id not in PROVIDER_IDS:
        provider_id = lane_default_provider(lane)

    model_id = entry.get("model_id")
    if not (
        is_model_in_provider(provider_id, model_id)
        and model_supports_lane(provider_id, model_id, lane)
    ):
        model_id = _safe_lane_model(provider_id, lane)

    execution_enabled = entry.get("execution_enabled")
    if not isinstance(execution_enabled, bool):
        execution_enabled = LANE_EXECUTION_DEFAULTS.get(lane, False)

    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
    }


def _load_payload() -> dict:
    """Load provider settings, migrating V1 → V2 IN MEMORY. Existing api_key /
    updated_at / activated_at are always preserved. Missing new fields
    (default_model, lanes) are backfilled with catalog-safe defaults. The file is
    only (re)written when absent/corrupt; a plain read never rewrites a valid V1."""
    _ensure_state_dir()
    default_payload = _default_payload()
    if not AI_PROVIDER_SETTINGS_FILE.exists():
        AI_PROVIDER_SETTINGS_FILE.write_text(
            json.dumps(default_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return default_payload

    try:
        raw = json.loads(AI_PROVIDER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        AI_PROVIDER_SETTINGS_FILE.write_text(
            json.dumps(default_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return default_payload

    payload = {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": raw.get("active_provider"),
        "providers": {},
        "lanes": {},
    }
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    for provider_id in PROVIDER_IDS:
        entry = raw_providers.get(provider_id) if isinstance(raw_providers.get(provider_id), dict) else {}
        raw_default_model = entry.get("default_model")
        if raw_default_model not in model_ids_for_provider(provider_id):
            raw_default_model = default_model_for_provider(provider_id)
        payload["providers"][provider_id] = {
            "api_key": str(entry.get("api_key") or ""),
            "updated_at": entry.get("updated_at"),
            "activated_at": entry.get("activated_at"),
            "default_model": raw_default_model,
        }

    raw_lanes = raw.get("lanes") if isinstance(raw.get("lanes"), dict) else {}
    for lane in LANES:
        payload["lanes"][lane] = _migrate_lane(raw_lanes, lane)

    if payload["active_provider"] not in PROVIDER_IDS:
        payload["active_provider"] = None
    return payload


def _save_payload(payload: dict) -> None:
    _ensure_state_dir()
    AI_PROVIDER_SETTINGS_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def get_provider_api_key(provider_id: str) -> str:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    stored_key = str(payload["providers"][normalized].get("api_key") or "").strip()
    if stored_key:
        return stored_key
    return str(os.environ.get(PROVIDER_ENV_VARS[normalized], "")).strip()


def get_provider_default_model(provider_id: str) -> str | None:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    stored = payload["providers"][normalized].get("default_model")
    if stored in model_ids_for_provider(normalized):
        return stored
    return default_model_for_provider(normalized)


def get_lane_provider(lane: str) -> str | None:
    """Return the provider ID assigned to a given lane. Reads operator-configured
    lane state, falling back to the catalog lane default (never None for a known
    lane); returns None only for an unknown lane."""
    if not is_known_lane(lane):
        return None
    payload = _load_payload()
    lane_state = payload.get("lanes", {}).get(lane)
    if isinstance(lane_state, dict) and lane_state.get("provider_id") in PROVIDER_IDS:
        return lane_state["provider_id"]
    return lane_default_provider(lane)


def get_lane_model(lane: str) -> str | None:
    """Return the operator-selected model ID for a lane, validated against the
    catalog. Falls back to the catalog lane default; None for an unknown lane."""
    if not is_known_lane(lane):
        return None
    payload = _load_payload()
    lane_state = payload.get("lanes", {}).get(lane)
    if isinstance(lane_state, dict):
        provider_id = lane_state.get("provider_id")
        model_id = lane_state.get("model_id")
        if is_model_in_provider(provider_id, model_id) and model_supports_lane(
            provider_id, model_id, lane
        ):
            return model_id
    return lane_default_model(lane)


def get_lane_api_key(lane: str) -> str | None:
    """Return the stored API key for the provider assigned to a given lane.
    Fail-closed: returns None if lane unknown, provider unknown, or key not stored."""
    provider_id = get_lane_provider(lane)
    if not provider_id:
        return None
    try:
        key = get_provider_api_key(provider_id)
        return key or None
    except (ValueError, Exception):
        return None


def is_lane_execution_enabled(lane: str) -> bool:
    """Lane execution gate. An explicitly-set deployment env override wins;
    otherwise the operator-stored `execution_enabled` flag decides; otherwise the
    conservative lane default (vision=off, text_assist=on)."""
    env_var = LANE_EXECUTION_ENV_VARS.get(lane)
    if env_var and str(os.environ.get(env_var, "")).strip():
        return _env_bool(env_var, LANE_EXECUTION_DEFAULTS.get(lane, False))
    if not is_known_lane(lane):
        return False
    payload = _load_payload()
    lane_state = payload.get("lanes", {}).get(lane)
    if isinstance(lane_state, dict) and isinstance(lane_state.get("execution_enabled"), bool):
        return bool(lane_state["execution_enabled"])
    return LANE_EXECUTION_DEFAULTS.get(lane, False)


def get_lane_api_key_for_execution(lane: str) -> str | None:
    """Key for a lane ONLY when execution is enabled — else None (fail closed)."""
    if not is_lane_execution_enabled(lane):
        return None
    return get_lane_api_key(lane)


def get_active_provider_id() -> ProviderId | None:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    if active_provider in PROVIDER_IDS:
        return active_provider  # type: ignore[return-value]
    env_active = str(os.environ.get(ACTIVE_PROVIDER_ENV_VAR, "")).strip().lower()
    if env_active in PROVIDER_IDS:
        return env_active  # type: ignore[return-value]
    return None


def validate_provider_model_for_lane(provider_id: str, model_id: str, lane: str) -> None:
    """Raise ValueError (mapped to 422 at the API) when a provider/model/lane combo
    is not permitted by the catalog. Fail closed — never silently accept."""
    if not is_known_lane(lane):
        raise ValueError(f"UNSUPPORTED_LANE:{lane}")
    normalized = _normalize_provider_id(provider_id)
    if not is_model_in_provider(normalized, model_id):
        raise ValueError(f"UNKNOWN_MODEL_FOR_PROVIDER:{normalized}:{model_id}")
    if not model_supports_lane(normalized, model_id, lane):
        raise ValueError(f"MODEL_NOT_SUPPORTED_FOR_LANE:{normalized}:{model_id}:{lane}")


def apply_runtime_provider_environment(payload: dict | None = None) -> None:
    resolved = payload or _load_payload()
    active_provider = resolved.get("active_provider")

    for provider_id in PROVIDER_IDS:
        key = str(resolved["providers"][provider_id].get("api_key") or "").strip()
        env_var = PROVIDER_ENV_VARS[provider_id]
        if key and _is_provider_runtime_enabled(provider_id):
            os.environ[env_var] = key
        else:
            os.environ.pop(env_var, None)

    if active_provider in PROVIDER_IDS:
        os.environ[ACTIVE_PROVIDER_ENV_VAR] = active_provider
    else:
        os.environ.pop(ACTIVE_PROVIDER_ENV_VAR, None)

    # Vision lane — publish the resolved lane provider id when a key exists.
    vision_provider = get_lane_provider("vision")
    vision_key = get_lane_api_key("vision")
    if vision_provider and vision_key:
        os.environ[VISION_PROVIDER_ENV_VAR] = vision_provider
    else:
        os.environ.pop(VISION_PROVIDER_ENV_VAR, None)

    # Text-assist lane — publish the resolved lane provider id when a key exists.
    text_provider = get_lane_provider("text_assist")
    text_key = get_lane_api_key("text_assist")
    if text_provider and text_key:
        os.environ[TEXT_ASSIST_PROVIDER_ENV_VAR] = text_provider
    else:
        os.environ.pop(TEXT_ASSIST_PROVIDER_ENV_VAR, None)


def _summarize_lanes(payload: dict) -> list[dict]:
    lanes: list[dict] = []
    for lane in LANES:
        provider_id = get_lane_provider(lane)
        model_id = get_lane_model(lane)
        lane_state = payload.get("lanes", {}).get(lane) if isinstance(payload.get("lanes"), dict) else None
        execution_enabled = bool(
            lane_state.get("execution_enabled")
        ) if isinstance(lane_state, dict) else LANE_EXECUTION_DEFAULTS.get(lane, False)
        has_key = bool(get_lane_api_key(lane))
        model_valid = bool(
            provider_id
            and model_id
            and is_model_in_provider(provider_id, model_id)
            and model_supports_lane(provider_id, model_id, lane)
        )
        lanes.append(
            {
                "lane": lane,
                "label": LANE_LABELS.get(lane, lane),
                "provider_id": provider_id,
                "model_id": model_id,
                "execution_enabled": execution_enabled,
                # `configured` = credentials + a lane-valid model are in place
                # (ready to run once execution_enabled is on).
                "configured": has_key and model_valid,
            }
        )
    return lanes


def summarize_provider_settings() -> dict:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    providers: list[dict] = []

    for provider_id in PROVIDER_IDS:
        key = get_provider_api_key(provider_id)
        is_active = active_provider == provider_id
        has_key = bool(key)
        if is_active and has_key:
            status = "ACTIVE"
        elif has_key:
            status = "READY"
        else:
            status = "KEY_MISSING"

        providers.append(
            {
                "provider_id": provider_id,
                "label": PROVIDER_LABELS[provider_id],
                "env_var": PROVIDER_ENV_VARS[provider_id],
                "has_key": has_key,
                "masked_key": _mask_api_key(key),
                "status": status,
                "is_active": is_active,
                "updated_at": payload["providers"][provider_id].get("updated_at"),
                "activated_at": payload["providers"][provider_id].get("activated_at"),
                "activation_scope": PROVIDER_SCOPES[provider_id],
                "current_capabilities": PROVIDER_CAPABILITIES[provider_id],
                "default_model": get_provider_default_model(provider_id),
                "supported_lanes": supported_lanes_for_provider(provider_id),
            }
        )

    return {
        "active_provider": active_provider if active_provider in PROVIDER_IDS else None,
        "providers": providers,
        "model_catalog": catalog_payload(),
        "lanes": _summarize_lanes(payload),
    }


def update_provider_key(provider_id: str, api_key: str) -> dict:
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


def clear_provider_key(provider_id: str) -> dict:
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


def update_provider_default_model(provider_id: str, model_id: str) -> dict:
    """Set a provider's default model. Fail closed if the model is not in the
    provider's catalog (422 at the API)."""
    normalized = _normalize_provider_id(provider_id)
    cleaned_model = str(model_id or "").strip()
    if not is_model_in_provider(normalized, cleaned_model):
        raise ValueError(f"UNKNOWN_MODEL_FOR_PROVIDER:{normalized}:{cleaned_model}")

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
) -> dict:
    """Assign provider+model (and optionally the execution toggle) to a lane.
    Validates the combo against the catalog and fails closed on any mismatch."""
    validate_provider_model_for_lane(provider_id, model_id, lane)
    normalized = _normalize_provider_id(provider_id)

    payload = _load_payload()
    lanes = payload.setdefault("lanes", {})
    lane_state = lanes.get(lane) if isinstance(lanes.get(lane), dict) else {}
    lane_state["provider_id"] = normalized
    lane_state["model_id"] = str(model_id).strip()
    if execution_enabled is not None:
        lane_state["execution_enabled"] = bool(execution_enabled)
    elif not isinstance(lane_state.get("execution_enabled"), bool):
        lane_state["execution_enabled"] = LANE_EXECUTION_DEFAULTS.get(lane, False)
    lanes[lane] = lane_state

    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def activate_provider(provider_id: str) -> dict:
    normalized = _normalize_provider_id(provider_id)
    if not get_provider_api_key(normalized):
        raise ValueError("API_KEY_MISSING_FOR_PROVIDER")

    payload = _load_payload()
    payload["active_provider"] = normalized
    payload["providers"][normalized]["activated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def deactivate_provider() -> dict:
    payload = _load_payload()
    payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()
