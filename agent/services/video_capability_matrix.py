"""Canonical VIDEO CAPABILITY MATRIX (operator-policy layer, v1).

This is a *versioned product-policy layer ABOVE* the live-captured
``video_models`` registry. It does NOT modify, override or falsify the
registry — the registry stays runtime capability truth (durations captured
from Google's real fired tool args). This layer exposes the supported SUBSET
that the BOSMAX Step-1 operator UI is allowed to offer for SINGLE generation,
and enforces it fail-closed.

Resolution law (SINGLE):

    effective_durations(engine, model)
        = operator_single_duration_policy(engine)  ∩  model.allowed_durations_s

So for GOOGLE_FLOW (policy [8, 10]) against the current registry:
    - 8s  -> Veo Lite / Veo Fast / Veo Quality / Omni Flash
    - 10s -> Omni Flash only  (the only model whose allowed_durations_s has 10)

EXTEND is intentionally out of scope here: total-duration → route/block-plan
authority lives in ``extend_route_planner`` and is untouched.

ADR-007: the only executable SINGLE generation lane is Google Flow. GROK is
declared as a policy engine but is NOT runtime-integrated (no transport, no
model) — it fails closed with ``ENGINE_RUNTIME_NOT_INTEGRATED``. Do not invent
a Grok SINGLE runtime here.
"""

from __future__ import annotations

from agent.services import video_models as _vm

# Bump when the policy shape or engine set changes. The frontend receives this
# verbatim and echoes it back; the backend rejects a mismatched persisted tuple
# with CAPABILITY_MATRIX_VERSION_MISMATCH.
CAPABILITY_MATRIX_VERSION = "video-capability-v1"


# Operator policy per engine. `single_duration_policy` is the ordered list of
# durations the operator UI may expose for SINGLE; `default_single_duration`
# must be a member of it.
_ENGINES: dict[str, dict] = {
    "GOOGLE_FLOW": {
        "id": "GOOGLE_FLOW",
        "label": "Google Flow",
        "supported": True,
        "single_duration_policy": [8, 10],
        "default_single_duration": 8,
        "transport": "flow_creation_agent",
        "description": "API-first Google Flow lane (Veo / Omni Flash).",
        "unsupported_reason": None,
    },
    "GROK": {
        "id": "GROK",
        "label": "Grok",
        "supported": False,
        # Declared policy only — informs the disabled-state helper text. There
        # is no Grok SINGLE transport or model, so nothing is selectable.
        "single_duration_policy": [6, 10],
        "default_single_duration": 6,
        "transport": None,
        "description": "Grok single-video runtime.",
        "unsupported_reason": "Runtime not yet integrated.",
    },
}

# Stable error codes (contract with the frontend + tests).
ERR_UNSUPPORTED_ENGINE = "UNSUPPORTED_ENGINE"
ERR_ENGINE_RUNTIME_NOT_INTEGRATED = "ENGINE_RUNTIME_NOT_INTEGRATED"
ERR_UNSUPPORTED_ENGINE_DURATION = "UNSUPPORTED_ENGINE_DURATION"
ERR_UNSUPPORTED_ENGINE_MODEL = "UNSUPPORTED_ENGINE_MODEL"
ERR_UNSUPPORTED_MODEL_DURATION = "UNSUPPORTED_MODEL_DURATION"
ERR_CAPABILITY_MATRIX_VERSION_MISMATCH = "CAPABILITY_MATRIX_VERSION_MISMATCH"


def engine_ids() -> list[str]:
    return list(_ENGINES.keys())


def _engine(engine_id) -> dict | None:
    if not engine_id:
        return None
    return _ENGINES.get(str(engine_id).strip().upper())


def single_duration_policy(engine_id) -> list[int]:
    """Operator-policy SINGLE durations for the engine (empty if unknown)."""
    eng = _engine(engine_id)
    return list(eng["single_duration_policy"]) if eng else []


def _registry_models() -> list[dict]:
    """Video model rows from the SSOT registry (runtime capability truth)."""
    return _vm.public_list()


def models_for_engine(engine_id) -> list[dict]:
    """Registry models that support at least one duration in the engine policy.

    For an unsupported / unknown engine this returns [] (nothing selectable).
    """
    eng = _engine(engine_id)
    if not eng or not eng["supported"]:
        return []
    policy = set(eng["single_duration_policy"])
    out = []
    for m in _registry_models():
        allowed = set(m.get("allowed_durations_s") or [])
        if policy & allowed:
            out.append(m)
    return out


def models_for_single(engine_id, duration) -> list[dict]:
    """Registry models whose allowed_durations_s contains `duration`, restricted
    to the engine's SINGLE policy. Empty for an out-of-policy duration or an
    unsupported engine."""
    eng = _engine(engine_id)
    if not eng or not eng["supported"]:
        return []
    if duration not in set(eng["single_duration_policy"]):
        return []
    out = []
    for m in _registry_models():
        if duration in set(m.get("allowed_durations_s") or []):
            out.append(m)
    return out


def default_model_for_single(engine_id, duration) -> str | None:
    """Deterministic compatible model key for (engine, duration). Prefers the
    registry default model when compatible, else the first compatible model."""
    compatible = models_for_single(engine_id, duration)
    if not compatible:
        return None
    keys = [m["key"] for m in compatible]
    if _vm.DEFAULT_MODEL in keys:
        return _vm.DEFAULT_MODEL
    return keys[0]


def default_single_duration(engine_id) -> int | None:
    eng = _engine(engine_id)
    return eng["default_single_duration"] if eng else None


def _resolve_model_key(model) -> str | None:
    """Resolve a UI label / key / agent label to a registry key, or None."""
    try:
        return _vm.resolve(model)["key"]
    except ValueError:
        return None


def validate_single(engine_id, model, duration) -> tuple[bool, str | None]:
    """Fail-closed SINGLE tuple validation against operator policy ∩ registry.

    Returns (ok, error_code). error_code is one of the ERR_* constants.
    """
    eng = _engine(engine_id)
    if eng is None:
        return False, ERR_UNSUPPORTED_ENGINE
    if not eng["supported"]:
        return False, ERR_ENGINE_RUNTIME_NOT_INTEGRATED
    if duration not in set(eng["single_duration_policy"]):
        return False, ERR_UNSUPPORTED_ENGINE_DURATION
    key = _resolve_model_key(model)
    if key is None:
        return False, ERR_UNSUPPORTED_ENGINE_MODEL
    # Model must belong to this engine's selectable set (policy ∩ allowed ≠ ∅).
    if key not in {m["key"] for m in models_for_engine(engine_id)}:
        return False, ERR_UNSUPPORTED_ENGINE_MODEL
    allowed = set(_vm.resolve(key).get("allowed_durations_s") or [])
    if duration not in allowed:
        return False, ERR_UNSUPPORTED_MODEL_DURATION
    return True, None


def public_matrix() -> dict:
    """Serializable capability matrix delivered to the dashboard. The frontend
    derives ALL engine/model/duration options from this — there is no parallel
    hard-coded frontend list. Shape is version-stamped and exact-equality
    tested."""
    engines_out = []
    for eng in _ENGINES.values():
        eid = eng["id"]
        models = models_for_engine(eid) if eng["supported"] else []
        durations = list(eng["single_duration_policy"])
        by_duration = {
            str(d): [m["key"] for m in models_for_single(eid, d)]
            for d in durations
        }
        engines_out.append(
            {
                "id": eid,
                "label": eng["label"],
                "supported": eng["supported"],
                "unsupported_reason": eng["unsupported_reason"],
                "transport": eng["transport"],
                "description": eng["description"],
                "single_duration_policy": durations,
                "default_single_duration": eng["default_single_duration"],
                "models": [
                    {
                        "key": m["key"],
                        "ui_label": m["ui_label"],
                        "allowed_durations_s": m["allowed_durations_s"],
                        "default_duration_s": m["default_duration_s"],
                    }
                    for m in models
                ],
                "single_models_by_duration": by_duration,
                "default_model_by_duration": {
                    str(d): default_model_for_single(eid, d) for d in durations
                },
            }
        )
    return {
        "capability_matrix_version": CAPABILITY_MATRIX_VERSION,
        "engines": engines_out,
        "default_engine": "GOOGLE_FLOW",
    }
