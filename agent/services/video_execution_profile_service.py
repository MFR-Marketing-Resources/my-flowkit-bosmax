"""Shared Google Flow duration/model execution-profile authority.

Provider transport proof belongs to a *duration/model profile*, not to a
surface label.  Lane adapters still own their content, asset, and orchestration
rules; this module owns only the provider-facing tuple they are allowed to
consume.

The profile is deliberately derived from existing authorities:

* ``canonical_prompt_compiler`` supplies the prompt-block plan;
* ``video_models`` supplies model/duration orchestration truth;
* ``video_capability_matrix`` supplies the versioned single-block policy; and
* ``extend_route_planner`` supplies the authorized multi-block route.

An empty certification registry is valid and means "not yet provider-proven".
No function in this module creates a certification record or changes a model
key.  Live capture tooling must persist an exact, evidence-backed record under
the profile digest through its existing official workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from agent.config import BASE_DIR, PROVIDER_CERTIFICATION_PROFILES
from agent.services import canonical_prompt_compiler as _compiler
from agent.services import extend_route_planner as _extend
from agent.services import video_capability_matrix as _capability
from agent.services import video_models as _video_models


PROFILE_SCHEMA_VERSION = "video-execution-profile-v1"
PROVIDER_GOOGLE_FLOW = "GOOGLE_FLOW"
PROFILE_DURATIONS = (8, 10, 16, 24)
DEFAULT_AUDIO_DIALOGUE_ROUTE = "SWEETWPS_CANONICAL_COMPILER"

_ASPECT_ALIASES = {
    "9:16": "9:16",
    "16:9": "16:9",
    "VIDEO_ASPECT_RATIO_PORTRAIT": "9:16",
    "VIDEO_ASPECT_RATIO_LANDSCAPE": "16:9",
}

_LANE_ADAPTER_PATHS: dict[str, tuple[str, ...]] = {
    "HYBRID": (
        "agent/services/workspace_generation_package_service.py",
        "agent/services/flow_mode_reference_contract.py",
    ),
    "FACELESS": ("agent/services/faceless_lane_service.py",),
    "MONTAGE": (
        "agent/api/montage.py",
        "agent/services/montage_mascot_creative_grammar.py",
        "agent/services/product_mascot_service.py",
    ),
    "PRODUCTION_STUDIO_P6": (
        "agent/services/creative_production_scheduler_service.py",
        "agent/services/production_queue_service.py",
    ),
}


class ExecutionProfileError(ValueError):
    """Stable fail-closed profile error with a machine-readable code."""

    def __init__(self, code: str, message: str | None = None, *, details: Any = None):
        self.code = code
        self.details = details
        super().__init__(message or code)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _norm(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_aspect_ratio(value: str | None) -> str:
    token = _norm(value).upper()
    aspect = _ASPECT_ALIASES.get(token)
    if aspect is None:
        raise ExecutionProfileError("ASPECT_RATIO_UNSUPPORTED", f"Unsupported aspect ratio: {value}")
    return aspect


def _preferred_block_lane(duration_s: int) -> str:
    # The compiler authority has unique rows for 8/10/16/24.  The explicit
    # preference is only needed for the 16/24 8-second block plans and keeps
    # this function coupled to the authority rather than duplicating its data.
    return "8s" if int(duration_s) in (16, 24) else f"{int(duration_s)}s"


def prompt_block_plan(duration_s: int, *, engine: str = PROVIDER_GOOGLE_FLOW) -> list[int]:
    """Return the compiler-authoritative plan for one certified duration."""

    try:
        duration = int(duration_s)
    except (TypeError, ValueError) as exc:
        raise ExecutionProfileError("DURATION_INVALID", f"Invalid duration: {duration_s}") from exc
    if duration not in PROFILE_DURATIONS:
        raise ExecutionProfileError(
            "DURATION_PROFILE_UNSUPPORTED",
            f"No shared duration profile exists for {duration}s.",
        )
    try:
        return list(
            _compiler.resolve_block_plan(
                engine,
                duration,
                preferred_lane=_preferred_block_lane(duration),
            )
        )
    except ValueError as exc:
        raise ExecutionProfileError("PROMPT_BLOCK_PLAN_UNAVAILABLE", str(exc)) from exc


def derive_transport_route(
    *,
    logical_mode: str | None = None,
    source_mode: str | None = None,
    generation_mode: str = "SINGLE",
    reference_count: int | None = None,
    explicit_route: str | None = None,
) -> str:
    """Derive the provider route from the compiler/transport inputs.

    An explicit route is accepted for already-materialized packages.  Without
    one, only routes whose source-mode law is unambiguous are derived.  An
    omitted/unknown source mode therefore fails closed instead of silently
    declaring either F2V/HYBRID or T2V/T2V.
    """

    if explicit_route:
        return _norm(explicit_route).upper()

    mode = _norm(logical_mode).upper()
    source = _norm(source_mode).upper()
    if _norm(generation_mode).upper() == "EXTEND":
        return _extend.default_route_for_engine(PROVIDER_GOOGLE_FLOW)
    if mode == "T2V" and source in {"", "T2V"}:
        return "GOOGLE_FLOW_CREATION_AGENT"
    if mode in {"F2V", "HYBRID"} and source == "HYBRID":
        return "GOOGLE_FLOW_REFERENCE_FRAME_2_VIDEO"
    if mode == "I2V" and source in {"INGREDIENTS", "HYBRID"}:
        return "GOOGLE_FLOW_REFERENCE_FRAME_2_VIDEO"
    if mode == "F2V" and source == "FRAMES":
        return (
            "GOOGLE_FLOW_START_END_FRAME_2_VIDEO"
            if int(reference_count or 0) >= 2
            else "GOOGLE_FLOW_FRAME_2_VIDEO"
        )
    raise ExecutionProfileError(
        "TRANSPORT_ROUTE_REQUIRED",
        f"Cannot derive a canonical provider route from mode={logical_mode!r}, source_mode={source_mode!r}.",
    )


def _transport_key_provenance(
    *,
    model_key: str,
    route: str,
    explicit: str | None,
) -> str:
    if explicit:
        return _norm(explicit)
    if "DIRECT" in route or "REFERENCE_FRAME" in route or "FRAME_2_VIDEO" in route:
        return f"agent/models.json:direct_video_model_keys[{model_key}]"
    return f"agent/models.json:video_models[{route}]"


def _validate_capability_block(model_key: str, block_seconds: int, aspect: str) -> None:
    ok, error = _capability.validate_single(
        PROVIDER_GOOGLE_FLOW,
        model_key,
        int(block_seconds),
    )
    if not ok:
        raise ExecutionProfileError(
            "CAPABILITY_TUPLE_UNSUPPORTED",
            f"{error}:{model_key}:{block_seconds}s:{aspect}",
            details={"error": error, "model": model_key, "duration_s": block_seconds},
        )


def _profile_without_digest(
    *,
    provider: str,
    model_key: str,
    duration_s: int,
    blocks: list[int],
    aspect: str,
    audio_dialogue_route: str,
    transport_key_provenance: str,
    capability_matrix_version: str,
    transport_route: str,
    orchestration: Mapping[str, Any],
    credits_cost_rule: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "provider": provider,
        "model": model_key,
        "duration_s": int(duration_s),
        "prompt_block_count": len(blocks),
        "prompt_block_durations_s": list(blocks),
        "aspect_ratio": aspect,
        "audio_dialogue_route": _norm(audio_dialogue_route).upper(),
        "provider_transport_key_provenance": transport_key_provenance,
        "capability_matrix_version": capability_matrix_version,
        "execution_transport": transport_route,
        "generation_mode": orchestration.get("generation_mode"),
        "engine_block_duration_seconds": orchestration.get("engine_block_duration_seconds"),
        "execution_route": orchestration.get("execution_route"),
        "credits_cost_rule": dict(credits_cost_rule),
    }


def profile_digest(profile: Mapping[str, Any]) -> str:
    """Hash the canonical profile fields, excluding its stored digest."""

    fields = {key: value for key, value in dict(profile).items() if key != "profile_digest"}
    return _sha256(_stable_json(fields))


def resolve_duration_model_profile(
    *,
    provider: str = PROVIDER_GOOGLE_FLOW,
    model: str,
    duration_s: int,
    aspect_ratio: str = "9:16",
    audio_dialogue_route: str = DEFAULT_AUDIO_DIALOGUE_ROUTE,
    provider_transport_key_provenance: str | None = None,
    capability_matrix_version: str | None = None,
    transport_route: str | None = None,
    logical_mode: str | None = None,
    source_mode: str | None = None,
    generation_mode: str | None = None,
    reference_count: int | None = None,
    prompt_block_count: int | None = None,
) -> dict[str, Any]:
    """Build the one provider-facing profile consumed by every eligible lane."""

    provider_key = _norm(provider).upper().replace(" ", "_")
    if provider_key != PROVIDER_GOOGLE_FLOW:
        raise ExecutionProfileError("PROVIDER_UNSUPPORTED", provider_key)
    try:
        spec = _video_models.resolve(model)
        duration = int(duration_s)
        orchestration = _video_models.resolve_orchestration(spec["key"], duration)
    except (TypeError, ValueError) as exc:
        raise ExecutionProfileError("MODEL_DURATION_UNSUPPORTED", str(exc)) from exc

    aspect = normalize_aspect_ratio(aspect_ratio)
    blocks = prompt_block_plan(duration)
    if prompt_block_count is not None and int(prompt_block_count) != len(blocks):
        raise ExecutionProfileError(
            "PROMPT_BLOCK_COUNT_MISMATCH",
            f"{duration}s requires {len(blocks)} prompt block(s), got {prompt_block_count}.",
        )
    if int(orchestration.get("segment_count") or 0) != len(blocks):
        raise ExecutionProfileError(
            "MODEL_BLOCK_PLAN_MISMATCH",
            f"Model orchestration and compiler plan disagree for {spec['key']}:{duration}s.",
        )

    generation = _norm(generation_mode or orchestration.get("generation_mode") or "SINGLE").upper()
    route = derive_transport_route(
        logical_mode=logical_mode,
        source_mode=source_mode,
        generation_mode=generation,
        reference_count=reference_count,
        explicit_route=transport_route,
    )
    # Each profile is certified for its atomic provider block.  A 16/24 profile
    # therefore still requires the exact 8s capability, while its route and
    # block count remain distinct profile identity fields.
    _validate_capability_block(spec["key"], int(blocks[0]), aspect)
    if generation == "EXTEND":
        try:
            authorized_blocks = _extend.resolve_route_block_plan(
                _extend.default_route_for_engine(PROVIDER_GOOGLE_FLOW),
                duration,
            )
        except (TypeError, ValueError) as exc:
            raise ExecutionProfileError("EXTEND_ROUTE_UNAUTHORIZED", str(exc)) from exc
        if authorized_blocks != blocks:
            raise ExecutionProfileError(
                "EXTEND_BLOCK_PLAN_MISMATCH",
                f"Extend route plan {authorized_blocks} != compiler plan {blocks}.",
            )

    matrix_version = _norm(capability_matrix_version or _capability.CAPABILITY_MATRIX_VERSION)
    if not matrix_version:
        raise ExecutionProfileError("CAPABILITY_MATRIX_VERSION_REQUIRED")
    key_provenance = _transport_key_provenance(
        model_key=spec["key"], route=route, explicit=provider_transport_key_provenance,
    )
    try:
        unit_cost = int(_video_models.expected_cost(spec["key"], int(blocks[0])))
    except (TypeError, ValueError) as exc:
        raise ExecutionProfileError("CREDITS_RULE_UNAVAILABLE", str(exc)) from exc
    credits_rule = {
        "currency": "Flow credits",
        "unit_cost_ceiling": unit_cost,
        "profile_cost_ceiling": unit_cost * len(blocks),
        "source": "agent/services/video_models.py",
    }
    profile = _profile_without_digest(
        provider=provider_key,
        model_key=spec["key"],
        duration_s=duration,
        blocks=blocks,
        aspect=aspect,
        audio_dialogue_route=audio_dialogue_route,
        transport_key_provenance=key_provenance,
        capability_matrix_version=matrix_version,
        transport_route=route,
        orchestration=orchestration,
        credits_cost_rule=credits_rule,
    )
    profile["profile_key"] = (
        f"{provider_key}|{spec['key']}|{duration}|{len(blocks)}|{aspect}|"
        f"{profile['audio_dialogue_route']}|{route}|{matrix_version}"
    )
    profile["profile_digest"] = profile_digest(profile)
    return profile


def canonicalize_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an immutable profile embedded in an approval context."""

    value = dict(profile)
    digest = _norm(value.get("profile_digest"))
    if not digest or digest != profile_digest(value):
        raise ExecutionProfileError("PROFILE_DIGEST_MISMATCH")
    if int(value.get("duration_s") or 0) not in PROFILE_DURATIONS:
        raise ExecutionProfileError("DURATION_PROFILE_UNSUPPORTED")
    expected = prompt_block_plan(int(value["duration_s"]))
    if value.get("prompt_block_durations_s") != expected:
        raise ExecutionProfileError("PROFILE_BLOCK_PLAN_MISMATCH")
    if int(value.get("prompt_block_count") or 0) != len(expected):
        raise ExecutionProfileError("PROFILE_BLOCK_COUNT_MISMATCH")
    return value


def provider_certification_status(
    profile: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return exact-profile certification truth without creating proof."""

    canonical = canonicalize_profile(profile)
    records = PROVIDER_CERTIFICATION_PROFILES if registry is None else registry
    record = records.get(canonical["profile_digest"]) if isinstance(records, Mapping) else None
    if not isinstance(record, Mapping):
        return {
            "certified": False,
            "status": "NOT_CERTIFIED",
            "reason": "NO_PROVIDER_CERTIFICATION_FOR_PROFILE",
            "profile_digest": canonical["profile_digest"],
        }
    if _norm(record.get("profile_digest")) not in {"", canonical["profile_digest"]}:
        return {
            "certified": False,
            "status": "NOT_CERTIFIED",
            "reason": "CERTIFICATION_PROFILE_DIGEST_MISMATCH",
            "profile_digest": canonical["profile_digest"],
        }
    if _norm(record.get("status")).upper() != "CERTIFIED":
        return {
            "certified": False,
            "status": _norm(record.get("status")).upper() or "NOT_CERTIFIED",
            "reason": "PROVIDER_CERTIFICATION_NOT_ACCEPTED",
            "profile_digest": canonical["profile_digest"],
        }
    return {
        "certified": True,
        "status": "CERTIFIED",
        "reason": None,
        "profile_digest": canonical["profile_digest"],
        "record": dict(record),
    }


def lane_adapter_digest(lane: str) -> str:
    """Digest the current lane adapter implementation, not provider proof."""

    key = _norm(lane).upper().replace("-", "_")
    if key in {"P6", "PRODUCTION_STUDIO", "PRODUCTION_STUDIO__P6"}:
        key = "PRODUCTION_STUDIO_P6"
    paths = _LANE_ADAPTER_PATHS.get(key)
    if not paths:
        raise ExecutionProfileError("LANE_ADAPTER_UNKNOWN", key)
    hasher = hashlib.sha256()
    for relative in paths:
        path = BASE_DIR / relative
        if not path.is_file():
            raise ExecutionProfileError("LANE_ADAPTER_SOURCE_MISSING", relative)
        hasher.update(relative.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def source_digest(relative_path: str) -> str:
    """Digest a repository source authority for approval lineage."""

    path = BASE_DIR / relative_path
    if not path.is_file():
        raise ExecutionProfileError("AUTHORITY_SOURCE_MISSING", relative_path)
    return _sha256(path.read_bytes())


def compiler_digest() -> str:
    return source_digest("agent/services/canonical_prompt_compiler.py")


def compositor_digest() -> str:
    return source_digest("agent/services/exact_product_compositor_service.py")


def sweetwps_digest() -> str:
    return _compiler.wps_authority_digest()


def _required_digest(value: Any, key: str) -> str:
    result = _norm(value)
    if not result:
        raise ExecutionProfileError(f"{key.upper()}_DIGEST_REQUIRED")
    return result


def build_approval_context(
    profile: Mapping[str, Any],
    *,
    lane: str,
    product_digest: str,
    copy_digest: str,
    sweetwps_digest_value: str | None = None,
    compositor_digest_value: str | None = None,
    compiler_digest_value: str | None = None,
    adapter_digest: str | None = None,
) -> dict[str, Any]:
    """Build the immutable profile + current authority digests for approval."""

    canonical = canonicalize_profile(profile)
    return {
        "duration_model_profile": canonical,
        "lane": _norm(lane).upper().replace("-", "_"),
        "lane_adapter_digest": adapter_digest or lane_adapter_digest(lane),
        "product_digest": _required_digest(product_digest, "product"),
        "copy_digest": _required_digest(copy_digest, "copy"),
        "sweetwps_digest": _required_digest(
            sweetwps_digest_value or sweetwps_digest(), "sweetwps"
        ),
        "compositor_digest": _required_digest(
            compositor_digest_value or compositor_digest(), "compositor"
        ),
        "compiler_digest": _required_digest(
            compiler_digest_value or compiler_digest(), "compiler"
        ),
    }


def normalize_approval_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize context before it enters the dispatch identity hash."""

    if not isinstance(context, Mapping):
        raise ExecutionProfileError("EXECUTION_PROFILE_CONTEXT_INVALID")
    profile = context.get("duration_model_profile") or context.get("profile")
    if not isinstance(profile, Mapping):
        raise ExecutionProfileError("DURATION_MODEL_PROFILE_REQUIRED")
    canonical = canonicalize_profile(profile)
    lane = _norm(context.get("lane")).upper().replace("-", "_")
    if not lane:
        raise ExecutionProfileError("LANE_REQUIRED_FOR_PROFILE_APPROVAL")
    required = {
        "lane_adapter_digest": context.get("lane_adapter_digest"),
        "product_digest": context.get("product_digest"),
        "copy_digest": context.get("copy_digest"),
        "sweetwps_digest": context.get("sweetwps_digest"),
        "compositor_digest": context.get("compositor_digest"),
        "compiler_digest": context.get("compiler_digest"),
    }
    missing = [key for key, value in required.items() if not _norm(value)]
    if missing:
        raise ExecutionProfileError(
            "EXECUTION_PROFILE_DIGESTS_REQUIRED",
            ",".join(missing),
            details={"missing": missing},
        )
    return {
        "duration_model_profile": canonical,
        "lane": lane,
        **{key: _norm(value) for key, value in required.items()},
    }


def evaluate_lane_profile(
    profile: Mapping[str, Any],
    *,
    lane: str,
    lane_gate_passed: bool,
    lane_gate_reason: str | None = None,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine shared provider proof with one lane's independent content gate."""

    certification = provider_certification_status(profile, registry=registry)
    lane_ok = bool(lane_gate_passed)
    reason = None
    if not certification["certified"]:
        reason = certification["reason"]
    elif not lane_ok:
        reason = lane_gate_reason or "LANE_SPECIFIC_GATE_BLOCKED"
    return {
        "eligible": bool(certification["certified"] and lane_ok),
        "lane": _norm(lane).upper().replace("-", "_"),
        "profile_digest": certification["profile_digest"],
        "provider_certification": certification,
        "lane_gate_passed": lane_ok,
        "blocker": reason,
    }


# Compatibility aliases make the authority discoverable to callers without
# introducing a second implementation or a lane-specific certification API.
resolve_profile = resolve_duration_model_profile
profile_certification_status = provider_certification_status
