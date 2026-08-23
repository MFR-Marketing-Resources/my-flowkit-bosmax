"""Shared provider-execution profile authority.

The public production lane (Hybrid, Faceless, Montage, or P6) is an adapter
around a provider capability; it is not the capability's identity.  This module
keeps that distinction explicit and gives every lane one deterministic,
provider-free way to resolve the tuple it intends to execute.

``profile_id`` and ``provider_profile_digest`` are derived only from the
provider-affecting tuple.  In particular, ``surface_lane`` and all lane-owned
state (copy, staff, custody, package, manifest, and choreography) are never
accepted into the profile identity.

Certification is deliberately conservative.  A tuple can be resolved while
remaining ``NOT_CERTIFIED``; a caller must not turn a resolved-but-unproven
profile into a paid dispatch.  The registry below contains only the durable
proof already present in this checkout: the captured Omni 10s reference route
and the Native Extend 16s chain/final artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Callable

from agent.services import video_models
from agent.services.video_surface_provenance import normalize_surface_lane


PROVIDER_EXECUTION_PROFILE_VERSION = "provider-execution-profile-v1"
PROFILE_CERTIFIED = "CERTIFIED"
PROFILE_NOT_CERTIFIED = "NOT_CERTIFIED"

ERR_PROFILE_REQUEST_INVALID = "PROVIDER_EXECUTION_PROFILE_INVALID"
ERR_PROFILE_BLOCK_COUNT_MISMATCH = "PROVIDER_EXECUTION_PROFILE_BLOCK_COUNT_MISMATCH"
ERR_PROFILE_SURFACE_INVALID = "ACTIVE_SURFACE_LANE_REQUIRED"

# This is intentionally a fixed, ordered tuple.  Adding a provider-affecting
# field is a versioned contract change, not an accidental hash change.
_IDENTITY_FIELDS = (
    "provider",
    "model",
    "duration_seconds",
    "prompt_block_count",
    "aspect_ratio",
    "output_count",
    "reference_topology",
    "generation_type",
    "execution_transport",
    "audio_dialogue_route",
    "provider_model_key",
    "capability_contract_version",
    "provider_tool",
    "provider_rpc",
)


class ProviderExecutionProfileError(ValueError):
    """Fail-closed provider-profile resolution error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}:{message}")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _token(value: Any, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or default


def _model_key(value: Any) -> str:
    if value is None or not str(value).strip():
        return video_models.DEFAULT_MODEL
    raw = str(value).strip()
    try:
        return str(video_models.resolve(raw)["key"])
    except (TypeError, ValueError):
        # The provider has distinct r2v/i2v usage keys which are not UI model
        # rows.  Keep the logical model stable and carry the provider selector
        # separately in provider_model_key.
        lowered = raw.lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "veo_3_1_r2v_lite": "veo_3_1_lite",
            "veo_3_1_r2v_fast": "veo_3_1_fast",
            "veo_3_1_r2v_fast_portrait": "veo_3_1_fast",
            "veo_3_1_i2v_lite": "veo_3_1_lite",
        }
        return aliases.get(lowered, lowered)


def _duration(request: Mapping[str, Any]) -> int:
    raw = request.get("duration_seconds", request.get("duration_s"))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "duration_seconds must be an integer"
        ) from exc
    if value <= 0:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "duration_seconds must be positive"
        )
    return value


def _count(request: Mapping[str, Any]) -> int:
    raw = request.get(
        "output_count",
        request.get("count", request.get("num_videos", request.get("desired_num", 1))),
    )
    try:
        value = int(raw or 1)
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "output_count must be an integer"
        ) from exc
    if value <= 0:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "output_count must be positive"
        )
    return value


def _reference_topology(request: Mapping[str, Any]) -> str:
    raw = request.get("reference_topology")
    if raw is None:
        raw = request.get("reference_topology_class")
    if raw is None:
        refs = request.get("reference_media_ids")
        if refs is None:
            refs = request.get("image_media_ids")
        if refs is None:
            refs = request.get("references")
        if isinstance(refs, (list, tuple, set)):
            reference_count = len([item for item in refs if item])
        else:
            try:
                reference_count = int(request.get("reference_count") or 0)
            except (TypeError, ValueError):
                reference_count = 0
        raw = (
            "NONE"
            if reference_count == 0
            else "ONE_REFERENCE"
            if reference_count == 1
            else f"MULTI_REFERENCE_{reference_count}"
        )
    value = _token(raw, default="none")
    aliases = {
        "no_reference": "none",
        "no_references": "none",
        "text_only": "none",
        "one_ref": "one_reference",
        "single_reference": "one_reference",
        "source_agnostic": "source_agnostic",
        "any_supported_source": "source_agnostic",
    }
    return aliases.get(value or "none", value or "none")


def _generation_type(request: Mapping[str, Any], *, duration: int, reference: str) -> str:
    raw = request.get("generation_type") or request.get("provider_generation_type")
    if raw:
        return _token(raw, default="unknown") or "unknown"
    if reference not in {"none", "source_agnostic"}:
        return "reference_frame_2_video"
    if duration in {16, 24}:
        return "native_extend"
    return "text_to_video"


def _transport(request: Mapping[str, Any], *, generation_type: str) -> str:
    raw = request.get("execution_transport") or request.get("transport")
    if raw:
        value = _token(raw, default="unknown") or "unknown"
        aliases = {
            "agent_stream_chat": "flow_creation_agent",
            "flowcreationagent": "flow_creation_agent",
            "flow_creation_agent_rpc": "flow_creation_agent",
            "flow_agent": "flow_creation_agent",
            "native_extend": "google_flow_native_extend",
        }
        return aliases.get(value, value)
    if generation_type == "native_extend":
        return "google_flow_native_extend"
    if generation_type == "reference_frame_2_video":
        return "flow_creation_agent"
    return "flow_creation_agent"


def _expected_block_count(duration: int) -> int | None:
    return {8: 1, 10: 1, 16: 2, 24: 3}.get(duration)


def _block_count(request: Mapping[str, Any], *, duration: int) -> int:
    raw = request.get("prompt_block_count", request.get("block_count"))
    expected = _expected_block_count(duration)
    if raw is None:
        value = expected or 1
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ProviderExecutionProfileError(
                ERR_PROFILE_REQUEST_INVALID, "prompt_block_count must be an integer"
            ) from exc
    if value <= 0:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "prompt_block_count must be positive"
        )
    if expected is not None and value != expected:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_BLOCK_COUNT_MISMATCH,
            f"{duration}s requires exactly {expected} prompt block(s), got {value}",
        )
    return value


def _normalise_identity(request: Mapping[str, Any]) -> dict[str, Any]:
    duration = _duration(request)
    model = _model_key(request.get("model", request.get("model_key")))
    reference = _reference_topology(request)
    generation_type = _generation_type(
        request, duration=duration, reference=reference,
    )
    transport = _transport(request, generation_type=generation_type)
    provider = _token(request.get("provider"), default="google_flow") or "google_flow"
    aspect = str(
        request.get("aspect_ratio", request.get("aspect", "9:16")) or "9:16"
    ).strip()
    if not aspect:
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID, "aspect_ratio is required"
        )

    exact_omni_reference_10 = (
        provider == "google_flow"
        and model == "omni_flash"
        and duration == 10
        and reference == "one_reference"
        and generation_type == "reference_frame_2_video"
        and transport == "flow_creation_agent"
        and _count(request) == 1
    )
    native_extend = generation_type == "native_extend" or duration in {16, 24}
    if duration in {16, 24} and generation_type != "native_extend":
        raise ProviderExecutionProfileError(
            ERR_PROFILE_REQUEST_INVALID,
            f"{duration}s requires the native_extend generation type",
        )

    provider_model_key = request.get("provider_model_key")
    if provider_model_key is None:
        provider_model_key = request.get("provider_model_usage_key")
    if provider_model_key is None:
        if exact_omni_reference_10:
            provider_model_key = "abra_r2v_10s"
        elif native_extend:
            provider_model_key = "veo_3_1_extension_lite"
        elif reference not in {"none", "source_agnostic"}:
            provider_model_key = f"{model}_r2v"
        else:
            provider_model_key = model

    contract = request.get("capability_contract_version") or request.get(
        "contract_version"
    )
    if not contract:
        contract = (
            "flow-agent-reference-omni10-v1"
            if exact_omni_reference_10
            else "google-flow-native-extend-v1"
            if native_extend
            else PROVIDER_EXECUTION_PROFILE_VERSION
        )

    provider_tool = request.get("provider_tool")
    provider_rpc = request.get("provider_rpc") or request.get("rpc")
    if exact_omni_reference_10:
        provider_tool = provider_tool or "generate_video_with_references"
        provider_rpc = provider_rpc or "agent_stream_chat"
    elif native_extend:
        provider_rpc = provider_rpc or "batchAsyncGenerateVideoExtendVideo"

    identity = {
        "provider": provider,
        "model": model,
        "duration_seconds": duration,
        "prompt_block_count": _block_count(request, duration=duration),
        "aspect_ratio": aspect,
        "output_count": _count(request),
        "reference_topology": reference,
        "generation_type": generation_type,
        "execution_transport": transport,
        "audio_dialogue_route": _token(
            request.get("audio_dialogue_route")
            or request.get("audio_route")
            or request.get("dialogue_route")
        ),
        "provider_model_key": _token(provider_model_key, default=None),
        "capability_contract_version": str(contract).strip(),
        "provider_tool": _token(provider_tool, default=None),
        "provider_rpc": _token(provider_rpc, default=None),
    }
    return identity


def _known_certification(identity: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    exact_10 = {
        "provider": "google_flow",
        "model": "omni_flash",
        "duration_seconds": 10,
        "prompt_block_count": 1,
        "aspect_ratio": "9:16",
        "output_count": 1,
        "reference_topology": "one_reference",
        "generation_type": "reference_frame_2_video",
        "execution_transport": "flow_creation_agent",
        "audio_dialogue_route": None,
        "provider_model_key": "abra_r2v_10s",
        "capability_contract_version": "flow-agent-reference-omni10-v1",
        "provider_tool": "generate_video_with_references",
        "provider_rpc": "agent_stream_chat",
    }
    exact_16 = {
        "provider": "google_flow",
        "model": "veo_3_1_lite",
        "duration_seconds": 16,
        "prompt_block_count": 2,
        "aspect_ratio": "9:16",
        "output_count": 1,
        "reference_topology": "source_agnostic",
        "generation_type": "native_extend",
        "execution_transport": "google_flow_native_extend",
        "audio_dialogue_route": None,
        "provider_model_key": "veo_3_1_extension_lite",
        "capability_contract_version": "google-flow-native-extend-v1",
        "provider_tool": None,
        "provider_rpc": "batchasyncgeneratevideoextendvideo",
    }
    key = {field: identity[field] for field in _IDENTITY_FIELDS}
    if key == exact_10:
        return (
            PROFILE_CERTIFIED,
            "FLOW_AGENT_REFERENCE_OMNI_10S|artifacts:86e5a494-3c52-42b5-91c4-acfa34960543,676c5f53-fec2-422e-8b45-e55128a5d84d",
            "Existing registered 10s Omni/reference artifacts and captured agent transport.",
        )
    if key == exact_16:
        return (
            PROFILE_CERTIFIED,
            "video_extension_all_modes_golden_path_closure.sanitized.json#live_full_chain_16s",
            "Existing Native Extend lineage plus measured 16s final artifact.",
        )
    if identity["duration_seconds"] == 8 and identity["reference_topology"] != "none":
        return (
            PROFILE_NOT_CERTIFIED,
            None,
            "Exact reference-aware 8s provider tuple lacks complete artifact-backed retrieval proof.",
        )
    if identity["duration_seconds"] == 24:
        return (
            PROFILE_NOT_CERTIFIED,
            None,
            "Native Extend block lineage exists, but no registered/measured final 24s artifact is proven.",
        )
    return (
        PROFILE_NOT_CERTIFIED,
        None,
        "No exact durable provider certification is registered for this tuple.",
    )


def resolve_provider_execution_profile(
    request: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Resolve one provider capability tuple without inspecting a provider.

    ``surface_lane`` may be present in ``request`` for caller convenience, but
    it is intentionally ignored.  The returned ``identity`` is the exact
    provider-certification key and contains no surface or lane-owned fields.
    """
    merged: dict[str, Any] = dict(request or {})
    merged.update(kwargs)
    nested = merged.get("provider_execution_profile")
    if isinstance(nested, Mapping):
        values = dict(nested)
        values.update({k: v for k, v in merged.items() if k != "provider_execution_profile"})
        merged = values
    identity = _normalise_identity(merged)
    digest = hashlib.sha256(_stable_json(identity).encode("utf-8")).hexdigest()
    status, evidence_id, reason = _known_certification(identity)
    duration = identity["duration_seconds"]
    profile = {
        "profile_version": PROVIDER_EXECUTION_PROFILE_VERSION,
        "profile_id": f"pep_{digest[:24]}",
        "provider_profile_digest": digest,
        "profile_digest": digest,
        **identity,
        "block_count": identity["prompt_block_count"],
        "duration_s": duration,
        "certification_status": status,
        "certification_evidence_id": evidence_id,
        "certification_reason": reason,
        "identity": dict(identity),
    }
    return profile


def resolve_lane_execution(
    surface_lane: Any,
    request: Mapping[str, Any] | None = None,
    *,
    lane_validator: Callable[[str, Mapping[str, Any]], Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Bind a lane adapter to a shared provider profile.

    Lane validation remains an explicit callback boundary.  A provider profile
    being certified does not run, skip, or imply Copy V2, custody, package,
    manifest, staff, or scene validation.  When a validator is supplied, any
    false result or exception fails closed before a profile is returned.
    """
    try:
        lane = normalize_surface_lane(surface_lane)
    except ValueError as exc:
        raise ProviderExecutionProfileError(ERR_PROFILE_SURFACE_INVALID, str(exc)) from exc
    if not lane:
        raise ProviderExecutionProfileError(ERR_PROFILE_SURFACE_INVALID, "surface lane is required")
    values: dict[str, Any] = dict(request or {})
    values.update(kwargs)
    if lane_validator is not None:
        try:
            decision = lane_validator(lane, values)
        except Exception as exc:  # noqa: BLE001 - adapter boundaries fail closed
            raise ProviderExecutionProfileError(
                "LANE_VALIDATION_FAILED", str(exc)
            ) from exc
        if decision is False or (
            isinstance(decision, Mapping) and decision.get("ok") is False
        ):
            raise ProviderExecutionProfileError(
                "LANE_VALIDATION_FAILED", "lane-specific validation rejected the request"
            )
    profile = resolve_provider_execution_profile(values)
    return {
        "surface_lane": lane,
        "provider_profile": profile,
        "provider_profile_id": profile["profile_id"],
        "provider_profile_digest": profile["provider_profile_digest"],
        "lane_adapter": {
            "surface_lane": lane,
            "provider_profile_id": profile["profile_id"],
            "provider_profile_digest": profile["provider_profile_digest"],
        },
    }


def canonical_profile_matrix() -> list[dict[str, Any]]:
    """Return the provider-free current profile certification matrix."""
    ten = resolve_provider_execution_profile(
        provider="GOOGLE_FLOW", model="omni_flash", duration_seconds=10,
        prompt_block_count=1, aspect_ratio="9:16", output_count=1,
        reference_topology="ONE_REFERENCE", generation_type="reference_frame_2_video",
        execution_transport="flow_creation_agent", provider_model_key="abra_r2v_10s",
        capability_contract_version="flow-agent-reference-omni10-v1",
    )
    sixteen = resolve_provider_execution_profile(
        provider="GOOGLE_FLOW", model="veo_3_1_lite", duration_seconds=16,
        prompt_block_count=2, aspect_ratio="9:16", output_count=1,
        reference_topology="SOURCE_AGNOSTIC", generation_type="native_extend",
        execution_transport="google_flow_native_extend",
        provider_model_key="veo_3_1_extension_lite",
        capability_contract_version="google-flow-native-extend-v1",
    )
    return [
        {
            "duration_seconds": 8,
            "status": PROFILE_NOT_CERTIFIED,
            "profile_id": None,
            "evidence": None,
            "reason": "Exact intended reference-aware Veo 8s proof is incomplete.",
        },
        {"duration_seconds": 10, "profile": ten, "status": ten["certification_status"]},
        {"duration_seconds": 16, "profile": sixteen, "status": sixteen["certification_status"]},
        {
            "duration_seconds": 24,
            "status": PROFILE_NOT_CERTIFIED,
            "profile_id": None,
            "evidence": None,
            "reason": "No registered/measured final 24s artifact.",
        },
    ]


__all__ = [
    "ERR_PROFILE_BLOCK_COUNT_MISMATCH",
    "ERR_PROFILE_REQUEST_INVALID",
    "PROFILE_CERTIFIED",
    "PROFILE_NOT_CERTIFIED",
    "PROVIDER_EXECUTION_PROFILE_VERSION",
    "ProviderExecutionProfileError",
    "canonical_profile_matrix",
    "resolve_lane_execution",
    "resolve_provider_execution_profile",
]
