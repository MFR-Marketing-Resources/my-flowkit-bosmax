from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Literal

from agent.config import BASE_DIR
from agent.services.ai_provider_model_catalog import (
    LANE_LABELS,
    LANES,
    get_model_entry,
    is_known_lane,
    is_provider_in_catalog,
    model_supports_lane,
    summarize_model_catalog,
    supported_lanes_for_provider,
    validate_provider_model_for_lane,
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
# V3: lanes are EXPLICIT and default to NOT_CONFIGURED (no hidden provider/model
# default). V1/V2 files migrate forward; keys are always preserved. A V2 lane that
# was only the old hardcoded seed default AND has no stored key is downgraded to
# NOT_CONFIGURED; a V2 lane the operator meaningfully set (non-default provider,
# or a provider that has a stored key) is preserved as configured_by_user.
AI_PROVIDER_STATE_VERSION = 3
ACTIVE_PROVIDER_ENV_VAR = "BOSMAX_ACTIVE_AI_PROVIDER"
VISION_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_VISION_PROVIDER"
TEXT_ASSIST_PROVIDER_ENV_VAR = "PRODUCT_TEXT_ASSIST_PROVIDER"
LANE_EXECUTION_ENV_VARS: dict[str, str] = {
    "vision": "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED",
    "text_assist": "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED",
}
# No lane auto-enables on a fresh install — both default OFF (fail closed).
LANE_EXECUTION_DEFAULTS: dict[str, bool] = {
    "vision": False,
    "text_assist": False,
}

# The exact hardcoded seed defaults PR #202 (V2) baked in. Used ONLY to detect a
# never-touched seeded V2 lane during migration (so it downgrades to NOT_CONFIGURED).
_V2_SEED_LANE_DEFAULTS: dict[str, tuple[str, str]] = {
    "text_assist": ("qwen", "qwen-plus"),
    "vision": ("anthropic", "claude-sonnet-5"),
}

# Lane status codes surfaced to the UI.
LANE_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
LANE_STATUS_MODEL_MISSING = "MODEL_MISSING"
LANE_STATUS_MODEL_DISABLED = "MODEL_DISABLED"
LANE_STATUS_KEY_MISSING = "KEY_MISSING"
LANE_STATUS_EXECUTION_DISABLED = "EXECUTION_DISABLED"
LANE_STATUS_READY = "READY"


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


def _not_configured_lane() -> dict:
    return {
        "provider_id": None,
        "model_id": None,
        "execution_enabled": False,
        "configured_by_user": False,
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
                "default_model": None,
            }
            for provider_id in PROVIDER_IDS
        },
        "lanes": {lane: _not_configured_lane() for lane in LANES},
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


def _migrate_lanes(raw: dict, providers_payload: dict) -> dict:
    """Deterministic lane migration → V3.
    - V3 file: preserve explicit lane fields.
    - V2 file: preserve a lane iff (its provider has a stored key) OR (it deviates
      from the old hardcoded seed default). Otherwise → NOT_CONFIGURED.
    - V1/absent lanes: NOT_CONFIGURED.
    """
    raw_version = raw.get("version")
    raw_lanes = raw.get("lanes") if isinstance(raw.get("lanes"), dict) else {}
    lanes: dict = {}

    for lane in LANES:
        entry = raw_lanes.get(lane) if isinstance(raw_lanes.get(lane), dict) else None
        if entry is None:
            lanes[lane] = _not_configured_lane()
            continue

        provider_id = str(entry.get("provider_id") or "").strip().lower() or None
        model_id = entry.get("model_id")
        execution_enabled = bool(entry.get("execution_enabled"))

        if raw_version and int(raw_version) >= 3:
            # Already V3 — preserve explicit intent verbatim (normalized).
            lanes[lane] = {
                "provider_id": provider_id if provider_id in PROVIDER_IDS else None,
                "model_id": str(model_id) if (provider_id in PROVIDER_IDS and model_id) else None,
                "execution_enabled": execution_enabled,
                "configured_by_user": bool(entry.get("configured_by_user")),
            }
            continue

        # V2 heuristic.
        if provider_id not in PROVIDER_IDS or not model_id:
            lanes[lane] = _not_configured_lane()
            continue
        has_key = bool(
            str(providers_payload.get(provider_id, {}).get("api_key") or "").strip()
        )
        is_seed_default = (provider_id, str(model_id)) == _V2_SEED_LANE_DEFAULTS.get(lane)
        if has_key or not is_seed_default:
            lanes[lane] = {
                "provider_id": provider_id,
                "model_id": str(model_id),
                "execution_enabled": execution_enabled,
                "configured_by_user": True,
            }
        else:
            lanes[lane] = _not_configured_lane()

    return lanes


def _load_payload() -> dict:
    """Load provider settings, migrating V1/V2 → V3 IN MEMORY. api_key / updated_at
    / activated_at are always preserved. First-run/unconfigured lanes are explicit
    NOT_CONFIGURED. A plain read never rewrites a valid existing file."""
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

    raw_version = raw.get("version")
    payload = {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": raw.get("active_provider"),
        "providers": {},
        "lanes": {},
    }
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    for provider_id in PROVIDER_IDS:
        entry = raw_providers.get(provider_id) if isinstance(raw_providers.get(provider_id), dict) else {}
        api_key = str(entry.get("api_key") or "")
        raw_default_model = entry.get("default_model")
        # default_model is a provider-card convenience only (it does NOT drive any
        # runtime lane, so it is not a "hidden default" risk). Preserve it whenever
        # it is still a valid, enabled catalog model; otherwise drop to None.
        default_model = None
        if isinstance(raw_default_model, str) and raw_default_model.strip():
            model_entry = get_model_entry(provider_id, raw_default_model)
            if model_entry and model_entry.get("enabled"):
                default_model = raw_default_model
        payload["providers"][provider_id] = {
            "api_key": api_key,
            "updated_at": entry.get("updated_at"),
            "activated_at": entry.get("activated_at"),
            "default_model": default_model,
        }

    payload["lanes"] = _migrate_lanes(raw, payload["providers"])

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
    if isinstance(stored, str) and stored.strip():
        model_entry = get_model_entry(normalized, stored)
        if model_entry and model_entry.get("enabled"):
            return stored
    return None


def get_lane_provider(lane: str) -> str | None:
    """Return the operator-configured provider for a lane, or None if the lane is
    NOT_CONFIGURED. NO hidden default."""
    if not is_known_lane(lane):
        return None
    payload = _load_payload()
    lane_state = payload.get("lanes", {}).get(lane)
    if isinstance(lane_state, dict) and lane_state.get("provider_id") in PROVIDER_IDS:
        return lane_state["provider_id"]
    return None


def get_lane_model(lane: str) -> str | None:
    """Return the operator-configured model for a lane ONLY if it still validates
    against the catalog (exists, enabled, supports the lane). Else None. NO default."""
    if not is_known_lane(lane):
        return None
    payload = _load_payload()
    lane_state = payload.get("lanes", {}).get(lane)
    if isinstance(lane_state, dict):
        provider_id = lane_state.get("provider_id")
        model_id = lane_state.get("model_id")
        if provider_id in PROVIDER_IDS and model_id and model_supports_lane(
            provider_id, model_id, lane
        ):
            return model_id
    return None


def get_lane_api_key(lane: str) -> str | None:
    """API key for the lane's configured provider. Fail-closed: None when the lane
    is unconfigured or the provider has no key."""
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
    otherwise the operator-stored toggle; otherwise OFF (fail closed)."""
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

    # Publish the resolved lane provider id ONLY when the lane is configured + keyed.
    vision_provider = get_lane_provider("vision")
    if vision_provider and get_lane_api_key("vision"):
        os.environ[VISION_PROVIDER_ENV_VAR] = vision_provider
    else:
        os.environ.pop(VISION_PROVIDER_ENV_VAR, None)

    text_provider = get_lane_provider("text_assist")
    if text_provider and get_lane_api_key("text_assist"):
        os.environ[TEXT_ASSIST_PROVIDER_ENV_VAR] = text_provider
    else:
        os.environ.pop(TEXT_ASSIST_PROVIDER_ENV_VAR, None)


def _lane_status(lane: str, lane_state: dict) -> dict:
    provider_id = lane_state.get("provider_id") if isinstance(lane_state, dict) else None
    model_id = lane_state.get("model_id") if isinstance(lane_state, dict) else None
    execution_enabled = bool(lane_state.get("execution_enabled")) if isinstance(lane_state, dict) else False
    configured_by_user = bool(lane_state.get("configured_by_user")) if isinstance(lane_state, dict) else False

    key_present = bool(get_lane_api_key(lane))
    model_entry = get_model_entry(provider_id, model_id) if (provider_id and model_id) else None
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

    return {
        "lane": lane,
        "label": LANE_LABELS.get(lane, lane),
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
        "configured_by_user": configured_by_user,
        "key_present": key_present,
        "model_valid": model_valid,
        "status": status,
        "configured": status == LANE_STATUS_READY,
    }


def _summarize_lanes(payload: dict) -> list[dict]:
    lanes_state = payload.get("lanes", {}) if isinstance(payload.get("lanes"), dict) else {}
    return [_lane_status(lane, lanes_state.get(lane) or {}) for lane in LANES]


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
        "model_catalog": summarize_model_catalog()["providers"],
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
    """Set a provider's default model (provider-card convenience; does NOT drive
    runtime lanes). Fail closed if the model is not a known, enabled model."""
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
) -> dict:
    """Explicitly configure a lane's provider+model (+ optional execution toggle).
    Validated against the mutable catalog (existence, enabled, lane + transport).
    Records configured_by_user=True. Fails closed on any mismatch."""
    validate_provider_model_for_lane(provider_id, model_id, lane)
    normalized = _normalize_provider_id(provider_id)

    payload = _load_payload()
    lanes = payload.setdefault("lanes", {})
    lane_state = lanes.get(lane) if isinstance(lanes.get(lane), dict) else {}
    lane_state["provider_id"] = normalized
    lane_state["model_id"] = str(model_id).strip()
    lane_state["configured_by_user"] = True
    if execution_enabled is not None:
        lane_state["execution_enabled"] = bool(execution_enabled)
    elif not isinstance(lane_state.get("execution_enabled"), bool):
        lane_state["execution_enabled"] = False
    lanes[lane] = lane_state

    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def clear_lane_settings(lane: str) -> dict:
    """Reset a lane back to NOT_CONFIGURED (explicit operator clear)."""
    if not is_known_lane(lane):
        raise ValueError(f"UNSUPPORTED_LANE:{lane}")
    payload = _load_payload()
    lanes = payload.setdefault("lanes", {})
    lanes[lane] = _not_configured_lane()
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
