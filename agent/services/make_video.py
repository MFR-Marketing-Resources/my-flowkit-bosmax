"""End-to-end automated video pipeline (flowCreationAgent).

One async job does everything: create project -> AI start frame -> agent session ->
negotiate + approve (1 video, Veo 3.1 Lite) -> wait for the render -> navigate the
Flow tab to the project + harvest the video media_id -> get_media returns the bytes
(base64 encodedVideo) -> save the .mp4 into the system. Poll GET /video-job/{id}.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import unquote

from agent.config import OUTPUT_DIR, DIRECT_VIDEO_MODEL_KEYS
from agent.services.flow_client import FlowClient, get_flow_client, resolve_video_model_key
from agent.services import agent_video
from agent.services import video_models
from agent.services import provider_execution_profile as _pep

_JOBS: dict = {}

# Single-flight video lane: the extension drives ONE Flow tab, so at most one video
# job may be in flight at a time. IMG is exempt. (Locked patch H.)
_VIDEO_LANE_JOB = None
_JOB_TTL = 1800  # seconds — GC finished jobs after this.
_GENERATION_TERMINAL_STATUSES = frozenset({
    "DONE",
    "PRODUCT_FIDELITY_REVIEW_REQUIRED",
    "FAILED",
    "REJECTED",
    "ARTIFACT_PERSISTENCE_FAILED",
    "DURABILITY_SYNC_FAILED",
    "RECOVERY_REQUIRED",
    "RECOVERY_UNRECOVERABLE",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
})

# Profile certification is a two-phase lifecycle.  The durable row is created
# before the async worker starts, but it must not look submitted until the
# editor binding, approval envelope, and provider generation boundary have all
# been crossed.
PROFILE_CERTIFICATION_PRE_PROVIDER_STATUS = "PRE_PROVIDER"

# These states have stopped the process-local task, but the durable row still
# owns a provider handle or a retrieved file that can be reconciled without a
# second generation submit.  Keep them separate from the terminal set used by
# the in-memory lane GC: a backend restart must revisit these rows.
_DURABLE_RECOVERY_STATUSES = frozenset({
    "SUBMITTED",
    "SETUP",
    "GENERATING",
    "RECOVERY_REQUIRED",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
    "ARTIFACT_PERSISTING",
    "ARTIFACT_PERSISTENCE_FAILED",
    "RETRIEVED_NOT_REGISTERED",
    # This state used to be terminal even when the accepted Flow-agent request
    # left exact prompt/model anchors that can resolve one unique project-media
    # identity. Revisit it provider-free; ambiguity still remains terminal.
    "RECOVERY_UNRECOVERABLE",
})

_DURABLE_RECOVERY_LOCKS: dict[str, asyncio.Lock] = {}


class FlowEditorBindingError(RuntimeError):
    """Structured, provider-free failure at the official Flow editor boundary."""

    code = "FLOW_EDITOR_BINDING_REQUIRED"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}

# Owner-authorized, one-shot transport discovery.  This remains a separate
# paid boundary; the normal route below is enabled only from the captured,
# reviewed Flow-agent contract.
HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS = (
    "HYBRID_REFERENCE_OMNI_10S_CONTRACT_CAPTURE"
)
HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID = (
    "243bf466-8a42-40b3-a75b-e3068cc430f6"
)
HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE = "FLOW_AGENT_REFERENCE_OMNI_10S"
HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION = "flow-agent-reference-omni10-v1"
HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL = "generate_video_with_references"
HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY = "abra_r2v_10s"
HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE = "reference_frame_2_video"

# The shared profile chain starts with one exact, reference-aware 8s operation.
# It is intentionally a separate bootstrap route: the profile is resolved and
# bound by the shared provider-profile authority, but remains NOT_CERTIFIED until
# this owner-authorized run produces durable provider/artifact evidence.
SHARED_REFERENCE_VEO_8S_BOOTSTRAP_ROUTE = (
    "GOOGLE_FLOW_REFERENCE_8S_CERTIFICATION_BOOTSTRAP"
)
SHARED_REFERENCE_VEO_8S_BOOTSTRAP_OPERATION_BUDGET = 3
SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY = "veo_3_1_r2v_lite"
SHARED_REFERENCE_VEO_8S_CONTRACT_VERSION = "veo-8s-reference-v1"
SHARED_REFERENCE_VEO_8S_PROVIDER_GENERATION_TYPE = "reference_frame_2_video"


def _resolve_submitted_provider_profile(provider_profile: dict | None) -> dict | None:
    """Re-resolve a submitted shared profile and reject forged id/digest pairs."""

    if not isinstance(provider_profile, dict):
        return None
    try:
        resolved = _pep.resolve_provider_execution_profile(provider_profile)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PROVIDER_PROFILE_INVALID:{exc}") from exc
    supplied_digest = str(
        provider_profile.get("provider_profile_digest")
        or provider_profile.get("profile_digest")
        or ""
    ).strip()
    supplied_id = str(provider_profile.get("profile_id") or "").strip()
    if supplied_digest and supplied_digest != resolved["provider_profile_digest"]:
        raise ValueError("PROVIDER_PROFILE_DIGEST_MISMATCH")
    if supplied_id and supplied_id != resolved["profile_id"]:
        raise ValueError("PROVIDER_PROFILE_ID_MISMATCH")
    if not supplied_digest or not supplied_id:
        raise ValueError("PROVIDER_PROFILE_ID_AND_DIGEST_REQUIRED")
    return resolved


def _resolve_shared_reference_8s_profile(
    *,
    mode: str,
    source_mode: str | None,
    model: str | None,
    duration_s: int | None,
    aspect: str | None,
    ref_count: int,
    num_videos: int,
    provider_profile: dict | None,
) -> dict | None:
    """Return the exact shared 8s profile, or ``None`` for another tuple."""

    try:
        resolved_model = video_models.resolve(model)
    except (TypeError, ValueError):
        return None
    try:
        normalized_duration = int(duration_s)
    except (TypeError, ValueError):
        return None
    if not (
        str(mode or "").strip().upper() == "F2V"
        and str(source_mode or "").strip().upper() == "HYBRID"
        and resolved_model.get("key") == "veo_3_1_lite"
        and normalized_duration == 8
        and str(aspect or "").strip() == "9:16"
        and int(ref_count) == 1
        and int(num_videos) == 1
    ):
        return None
    try:
        expected = _pep.resolve_provider_execution_profile(
            provider="GOOGLE_FLOW",
            model="veo_3_1_lite",
            duration_seconds=8,
            prompt_block_count=1,
            aspect_ratio="9:16",
            output_count=1,
            reference_topology="ONE_REFERENCE",
            generation_type=SHARED_REFERENCE_VEO_8S_PROVIDER_GENERATION_TYPE,
            execution_transport="google_flow_reference",
            provider_model_key=SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY,
            capability_contract_version=SHARED_REFERENCE_VEO_8S_CONTRACT_VERSION,
        )
        submitted = _resolve_submitted_provider_profile(provider_profile)
    except (TypeError, ValueError):
        return None
    if not submitted or submitted["profile_id"] != expected["profile_id"]:
        return None
    if submitted["provider_profile_digest"] != expected["provider_profile_digest"]:
        return None
    return expected


def _owner_authorized_shared_reference_8s_bootstrap(
    *,
    profile: dict | None,
    confirm_live_credit_burn: bool,
    maximum_provider_operations: int | None,
    max_retry_operations: int,
) -> bool:
    """Require an authenticated owner and the exact whole-chain budget."""

    if not profile or profile.get("certification_status") != _pep.PROFILE_NOT_CERTIFIED:
        return False
    if confirm_live_credit_burn is not True:
        return False
    if int(maximum_provider_operations or 0) != SHARED_REFERENCE_VEO_8S_BOOTSTRAP_OPERATION_BUDGET:
        return False
    if int(max_retry_operations or 0) != 0:
        return False
    from agent.security.access_control import get_current_auth_context

    context = get_current_auth_context()
    return bool(
        context
        and "OWNER" in {str(role).upper() for role in context.role_codes}
        and "production.execute" in context.permission_codes
    )


def _server_derived_video_profiles(
    *,
    mode: str,
    source_mode: str | None,
    model: str | None,
    duration_s: int | None,
    aspect: str | None,
    ref_count: int,
    num_videos: int,
) -> tuple[dict, dict]:
    """Derive the exact WEP/PEP tuple from provider-affecting request fields.

    Surface and client-authored profile receipts are intentionally absent. A
    supplied receipt can only be compared with these server-derived profiles;
    it never chooses the tuple certified for paid dispatch.
    """
    from agent.services import video_execution_profile_service as _profiles

    # Durable Extend packages historically persist the captured provider model
    # key for their continuation blocks. Its request-model authority is still
    # Veo 3.1 Lite; keep the provider key below unchanged.
    request_model = (
        "veo_3_1_lite"
        if str(model or "").strip().lower() == "veo_3_1_extension_lite"
        else model
    )
    spec = video_models.resolve(request_model)
    duration = int(duration_s or spec["default_duration_s"])
    normalized_mode = str(mode or "").strip().upper()
    normalized_source = str(source_mode or "").strip().upper() or (
        "T2V" if normalized_mode == "T2V" else None
    )
    normalized_aspect = _profiles.normalize_aspect_ratio(aspect or "9:16")
    exact_omni_10 = hybrid_reference_omni10_route_matches(
        normalized_mode, normalized_source, spec["key"], duration, normalized_aspect,
        ref_count, num_videos,
    )
    profile_kwargs = {
        "model": spec["key"],
        "duration_s": duration,
        "aspect_ratio": normalized_aspect,
        "logical_mode": normalized_mode,
        "source_mode": normalized_source,
        "reference_count": ref_count,
    }
    if exact_omni_10:
        profile_kwargs.update(
            transport_route=HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE,
            provider_transport_key_provenance=(
                "captured_flow_agent_contract[abra_r2v_10s]"
            ),
        )
    duration_profile = _profiles.resolve_duration_model_profile(**profile_kwargs)

    if duration in (16, 24):
        reference_topology = "SOURCE_AGNOSTIC"
        generation_type = "native_extend"
        execution_transport = "google_flow_native_extend"
        provider_model_key = "veo_3_1_extension_lite"
        contract_version = "google-flow-native-extend-v1"
        provider_tool = None
        provider_rpc = "batchAsyncGenerateVideoExtendVideo"
    elif ref_count:
        reference_topology = (
            "ONE_REFERENCE" if ref_count == 1 else f"MULTI_REFERENCE_{ref_count}"
        )
        generation_type = "reference_frame_2_video"
        execution_transport = "flow_creation_agent"
        provider_model_key = None
        contract_version = _pep.PROVIDER_EXECUTION_PROFILE_VERSION
        provider_tool = None
        provider_rpc = None
        if (
            duration == 8
            and normalized_mode == "F2V"
            and normalized_source == "HYBRID"
            and spec["key"] == "veo_3_1_lite"
            and ref_count == 1
            and int(num_videos) == 1
        ):
            execution_transport = "google_flow_reference"
            provider_model_key = SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY
            contract_version = SHARED_REFERENCE_VEO_8S_CONTRACT_VERSION
    else:
        reference_topology = "NONE"
        generation_type = "text_to_video"
        execution_transport = "flow_creation_agent"
        provider_model_key = None
        contract_version = _pep.PROVIDER_EXECUTION_PROFILE_VERSION
        provider_tool = None
        provider_rpc = None
    if exact_omni_10:
        provider_model_key = HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY
        contract_version = HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION
        provider_tool = HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL
        provider_rpc = "agent_stream_chat"
    provider_profile = _pep.resolve_provider_execution_profile(
        provider="GOOGLE_FLOW",
        model=spec["key"],
        duration_seconds=duration,
        prompt_block_count=duration_profile["prompt_block_count"],
        aspect_ratio=normalized_aspect,
        output_count=num_videos,
        reference_topology=reference_topology,
        generation_type=generation_type,
        execution_transport=execution_transport,
        provider_model_key=provider_model_key,
        capability_contract_version=contract_version,
        provider_tool=provider_tool,
        provider_rpc=provider_rpc,
    )
    return duration_profile, provider_profile


def hybrid_reference_omni10_capture_enabled() -> bool:
    return os.environ.get("HYBRID_REFERENCE_OMNI_10S_CAPTURE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def hybrid_reference_omni10_route_matches(
    mode: str | None,
    source_mode: str | None,
    model: str | None,
    duration_s: int | None,
    aspect: str | None,
    ref_count: int,
    num_videos: int,
    surface_lane: str | None = None,
) -> bool:
    """Return whether the request consumes the captured 10s reference profile.

    ``abra_r2v_10s`` is deliberately not resolved here as a direct
    ``videoModelKey``.  The captured identity belongs to the
    ``flowCreationAgent`` reference-aware tool, so this predicate gates the
    exact provider-facing settings. ``surface_lane`` remains a compatibility
    argument but is intentionally not part of provider certification identity;
    lane-specific content gates run separately.
    """
    try:
        resolved_model = video_models.resolve(model)
        if not (
            str(mode or "").strip().upper() == "F2V"
            and str(source_mode or "").strip().upper() == "HYBRID"
            and resolved_model.get("key") == "omni_flash"
            and int(duration_s) == 10
            and str(aspect or "").strip() == "9:16"
            and int(ref_count) == 1
            and int(num_videos) == 1
        ):
            return False
        profile = _pep.resolve_provider_execution_profile(
            provider="GOOGLE_FLOW",
            model=resolved_model["key"],
            duration_seconds=10,
            prompt_block_count=1,
            aspect_ratio=aspect,
            output_count=num_videos,
            reference_topology="ONE_REFERENCE",
            generation_type=HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE,
            execution_transport="flow_creation_agent",
            provider_model_key=HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY,
            capability_contract_version=HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION,
            provider_tool=HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL,
            provider_rpc="agent_stream_chat",
            # surface_lane is intentionally not forwarded into the profile.
        )
        return profile["certification_status"] == _pep.PROFILE_CERTIFIED
    except (TypeError, ValueError):
        return False


def hybrid_reference_omni10_provider_route(
    mode: str | None,
    source_mode: str | None,
    model: str | None,
    duration_s: int | None,
    aspect: str | None,
    ref_count: int,
    num_videos: int,
    surface_lane: str | None = None,
) -> str:
    """Return the custody vocabulary for a requested video transport tuple."""
    if hybrid_reference_omni10_route_matches(
        mode,
        source_mode,
        model,
        duration_s,
        aspect,
        ref_count,
        num_videos,
        surface_lane,
    ):
        return HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
    return "API_FIRST_GENERATIVE_REFERENCE"


def _certified_hybrid_reference_omni10_plan() -> dict:
    """Return the shared certified 10s reference-profile transport contract.

    The historical function name is retained for wire/test compatibility. The
    returned provider proof is keyed by the duration/model/transport profile,
    not by the Hybrid surface, so another lane with the same compiled route may
    consume it after its own content gate passes.
    """
    from agent.services import video_execution_profile_service as _profiles

    duration_profile = _profiles.resolve_duration_model_profile(
        model="omni_flash",
        duration_s=10,
        aspect_ratio="9:16",
        provider_transport_key_provenance=(
            "captured_flow_agent_contract[abra_r2v_10s]"
        ),
        transport_route=HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE,
        logical_mode="F2V",
        source_mode="HYBRID",
    )
    certification = _profiles.provider_certification_status(duration_profile)
    if not certification.get("certified"):
        return {
            "eligible": False,
            "reason": f"DIRECT_PROFILE_UNCERTIFIED:{certification.get('reason')}",
            "duration_model_profile": duration_profile,
        }
    provider_profile = _pep.resolve_provider_execution_profile(
        provider="GOOGLE_FLOW",
        model="omni_flash",
        duration_seconds=10,
        prompt_block_count=1,
        aspect_ratio="9:16",
        output_count=1,
        reference_topology="ONE_REFERENCE",
        generation_type=HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE,
        execution_transport="flow_creation_agent",
        provider_model_key=HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY,
        capability_contract_version=HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION,
        provider_tool=HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL,
        provider_rpc="agent_stream_chat",
    )
    provider_certification = {
        "certified": provider_profile.get("certification_status") == _pep.PROFILE_CERTIFIED,
        "status": provider_profile.get("certification_status"),
        "certification_status": provider_profile.get("certification_status"),
        "reason": provider_profile.get("certification_reason"),
        "profile_id": provider_profile.get("profile_id"),
        "profile_digest": provider_profile.get("provider_profile_digest"),
    }
    if not provider_certification["certified"]:
        return {
            "eligible": False,
            "reason": f"DIRECT_PROFILE_UNCERTIFIED:{provider_certification.get('reason')}",
            "duration_model_profile": duration_profile,
            "provider_profile": provider_profile,
            "provider_profile_certification": provider_certification,
        }
    return {
        "eligible": False,
        "reason": HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE,
        "execution_route": HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE,
        "rpc": "agent_stream_chat",
        "gen_type": HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE,
        "provider_generation_type": HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE,
        "provider_tool": HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL,
        "provider_model_usage_key": HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY,
        "aspect_enum": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "video_model_key": None,
        "model_key_source": (
            "captured_flow_agent_contract[abra_r2v_10s]"
        ),
        "contract_version": HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION,
        "duration_model_profile": duration_profile,
        "provider_profile_certification": certification,
        "duration_profile_certification": certification,
        # Provider certification is shared across active surfaces.  The lane
        # adapter persists its own surface/custody provenance separately.
        "provider_profile": provider_profile,
        "provider_profile_id": provider_profile["profile_id"],
        "provider_profile_digest": provider_profile["provider_profile_digest"],
        "provider_profile_status": provider_certification["certification_status"],
        "provider_profile_evidence_id": provider_profile["certification_evidence_id"],
    }


def _is_certified_hybrid_reference_omni10_plan(plan: dict | None) -> bool:
    return bool(
        isinstance(plan, dict)
        and plan.get("execution_route") == HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
    )


def _capture_contract_reject(reason: str) -> dict:
    return {
        "status": "REJECTED",
        "error": reason,
        "capture_class": HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS,
        "pre_provider": {
            "classification": "BLOCKED",
            "provider_calls": 0,
            "credit_spend": False,
            "blocker_code": reason.split(":", 1)[0],
        },
    }


def _capture_reference_routing_receipt(reference_media_ids: list[str]) -> dict:
    refs = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
    return {
        "logical_mode": "F2V",
        "surface_lane": "HYBRID",
        "source_mode": "HYBRID",
        "reference_requested": True,
        "has_reference": bool(refs),
        "reference_uploaded": bool(refs),
        "reference_count": len(refs),
        "reference_media_ids": refs,
        "reference_contract": "valid",
        "reference_contract_code": None,
        "reference_contract_detail": "owner-authorized capture-only boundary",
        "reference_mode_authorized": True,
        "selected_execution_route": "CAPTURE_AGENT_DISCOVERY",
        "text_only_allowed": False,
        "TEXT_ONLY_TOOL_ALLOWED": False,
        "approval_allowed": True,
        "capture_only": True,
        "pre_provider": {
            "classification": "READY",
            "provider_calls": 0,
            "credit_spend": False,
            "selected_route": "CAPTURE_AGENT_DISCOVERY",
            "blocker_code": None,
        },
    }


def _capture_credit_balance(response: dict | None):
    """Extract only a numeric balance from the credits response."""
    if not isinstance(response, dict):
        return None
    candidates = []
    stack = [response]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                token = str(key).lower().replace("_", "")
                if token in {"credits", "creditbalance", "remainingcredits", "balance"}:
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        candidates.append(value)
                    elif isinstance(value, dict):
                        stack.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return candidates[0] if candidates else None


def _measure_video_duration(local_path: str | None):
    if not local_path:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(local_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        value = float((result.stdout or "").strip())
        return round(value, 3) if value >= 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _classify_reference_contract_capture(job: dict) -> str:
    evidence = job.get("capture_contract_evidence") or {}
    if job.get("approved") is not True:
        return "CAPTURE_FAILED_PRE_PROVIDER"
    if evidence.get("text_only_tool_observed"):
        return "WRONG_TRANSPORT"
    if not evidence.get("reference_aware_tool_observed") or not evidence.get(
        "reference_forwarded_to_generation"
    ):
        return "REFERENCE_DROPPED"
    if job.get("model_ok") is False:
        return "CAPTURE_WRONG_MODEL_AFTER_APPROVAL"
    if job.get("duration_ok") is False:
        return "CAPTURE_WRONG_DURATION_AFTER_APPROVAL"
    if job.get("model_ok") is not True or job.get("duration_ok") is not True:
        return "PROVIDER_OUTCOME_UNCERTAIN"
    if job.get("status") not in {"DONE", "PRODUCT_FIDELITY_REVIEW_REQUIRED"}:
        return "PROVIDER_OUTCOME_UNCERTAIN"
    return "REFERENCE_OMNI_10S_CONTRACT_CAPTURED"


def _job_active(job_id) -> bool:
    j = _JOBS.get(job_id)
    return bool(j) and j.get("status") not in _GENERATION_TERMINAL_STATUSES


def _gc_jobs():
    now = time.time()
    for jid in [k for k, v in _JOBS.items()
                if v.get("status") in _GENERATION_TERMINAL_STATUSES
                and (now - v.get("created", now)) > _JOB_TTL]:
        _JOBS.pop(jid, None)


async def _bind_editor_session(
    client,
    requested_project_id=None,
    bridge_lease: dict | None = None,
) -> dict:
    """Bind a video job to the OPEN Flow editor → {project_id, flow_tab_id, flow_project_url}.
    Fail-closed (locked patch A/G): raise if no editor project is open, or if the open editor
    differs from a requested project_id. Never mint a hidden project; never use the wrong tab."""
    selected_binding = None
    bind_flow_session = getattr(client, "bind_flow_session", None)
    if callable(bind_flow_session):
        selected_binding = await bind_flow_session(project_id=requested_project_id)
        if not isinstance(selected_binding, dict) or selected_binding.get("ok") is not True:
            blocker = (selected_binding or {}).get("primary_blocker") or "NO_ELIGIBLE_EXTENSION_SESSION"
            detail = (selected_binding or {}).get("detail") or blocker
            raise RuntimeError(f"{blocker}: {detail}")
        h = await client.harvest_video_urls(tab_id=selected_binding.get("flow_tab_id"))
    else:
        # Provider-free/frozen unit clients predate the identity-aware bridge;
        # retain their harvest contract while the real FlowClient is strict.
        h = await client.harvest_video_urls()
    inner = h.get("result", h) if isinstance(h, dict) else {}
    if (not isinstance(inner, dict) or inner.get("error") == "NO_FLOW_TAB"
            or inner.get("flow_tab_found") is False):
        raise FlowEditorBindingError(
            "NO_OPEN_EDITOR: open the target Flow project in the controlled tab first",
            details={"flow_path_state": "NO_FLOW_TAB"},
        )
    handled_fields = (
        "handled_flow_tab_id",
        "handled_flow_url",
        "handled_flow_project_id",
    )
    handled_present = [field in inner for field in handled_fields]
    if any(handled_present) and not all(handled_present):
        raise FlowEditorBindingError(
            "FLOW_BRIDGE_HANDLED_IDENTITY_INCOMPLETE: the extension did not return a complete handled tab/project tuple",
            details={"handled_fields_present": dict(zip(handled_fields, handled_present))},
        )
    if bridge_lease is not None and not all(handled_present):
        raise FlowEditorBindingError(
            "FLOW_BRIDGE_HANDLED_IDENTITY_REQUIRED: reload the current extension build before provider work",
            details={"lease_id": bridge_lease.get("lease_id")},
        )

    flow_url = inner.get("flow_url") or ""
    flow_tab_id = inner.get("flow_tab_id")
    diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
    project_id = diag.get("projectId") if isinstance(diag, dict) else None
    if all(handled_present):
        handled_tab_id = inner.get("handled_flow_tab_id")
        handled_url = str(inner.get("handled_flow_url") or "").strip()
        handled_project_id = str(
            inner.get("handled_flow_project_id") or ""
        ).strip()
        envelope_tab_id = inner.get("envelope_flow_tab_id")
        envelope_url = str(inner.get("envelope_flow_url") or "").strip()
        canonical_project_id = str(inner.get("flow_project_id") or "").strip()
        diag_project_id = str(project_id or "").strip()
        tab_values = [
            value for value in (flow_tab_id, handled_tab_id)
            if value is not None
        ]
        if (
            handled_tab_id is None
            or len({str(value) for value in tab_values}) != 1
        ):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_TAB_IDENTITY_MISMATCH: wrapper and handled Flow tabs disagree",
                details={
                    "flow_tab_id": flow_tab_id,
                    "handled_flow_tab_id": handled_tab_id,
                    "envelope_flow_tab_id": envelope_tab_id,
                },
            )
        url_values = [
            value.rstrip("/")
            for value in (str(flow_url).strip(), handled_url)
            if value
        ]
        if not handled_url or len(set(url_values)) != 1:
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_URL_IDENTITY_MISMATCH: wrapper and handled Flow URLs disagree",
                details={
                    "flow_url": flow_url,
                    "handled_flow_url": handled_url,
                    "envelope_flow_url": envelope_url,
                },
            )
        project_values = [
            value for value in (
                handled_project_id,
                canonical_project_id,
                diag_project_id,
            ) if value
        ]
        if not handled_project_id or len(set(project_values)) != 1:
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_PROJECT_IDENTITY_MISMATCH: handled and diagnostic Flow projects disagree",
                details={
                    "handled_flow_project_id": handled_project_id,
                    "flow_project_id": canonical_project_id,
                    "diagnostic_project_id": diag_project_id,
                },
            )
        flow_tab_id = handled_tab_id
        flow_url = handled_url
        project_id = handled_project_id
    if not project_id or "/project/" not in str(flow_url):
        raise FlowEditorBindingError(
            "NO_OPEN_EDITOR: the Flow tab is not on a project editor — open the project first",
            details={"flow_path_state": "ROOT_OR_NON_EDITOR"},
        )
    page_diag_fn = getattr(client, "flow_page_state_diagnostic", None)
    if callable(page_diag_fn):
        page_diag = await page_diag_fn("F2V")
        if isinstance(page_diag, dict) and (
            page_diag.get("content_script_loaded") is False
            or page_diag.get("content_script_alive") is False
            or page_diag.get("same_extension_session") is False
        ):
            raise FlowEditorBindingError(
                "CONTENT_SCRIPT_NOT_READY: the active Flow editor is not bound to the current extension session",
                details={"page_state": page_diag},
            )
        error_markers = [
            str(item).strip()
            for item in (page_diag.get("visible_error_markers") or [])
            if str(item).strip()
        ] if isinstance(page_diag, dict) else []
        if error_markers:
            # A marker on an otherwise-healthy editor is a failed media TILE or a
            # stale toast, not a broken page (live: d80e72fd listed every artifact
            # plus one errored tile, and binding was wrongly refused). Only fail
            # closed when the editor surface itself is not usable.
            editor_usable = bool(
                isinstance(page_diag, dict)
                and (page_diag.get("editor_capability_ready")
                     or (page_diag.get("composer_found") and page_diag.get("composer_editable")))
            )
            if not editor_usable:
                raise FlowEditorBindingError(
                    "BROKEN_EDITOR_PAGE: the bound Flow editor shows error markers — "
                    + ", ".join(error_markers),
                    details={"page_state": page_diag},
                )
        if isinstance(page_diag, dict) and page_diag.get("build_match") is False:
            raise FlowEditorBindingError(
                "CONTENT_BUILD_MISMATCH: reload the Flow tab so the content script matches the background build",
                details={"page_state": page_diag},
            )
    if requested_project_id and requested_project_id != project_id:
        raise FlowEditorBindingError(
            f"PROJECT_TAB_MISMATCH: requested {requested_project_id} but the open editor is {project_id}",
            details={"requested_project_id": requested_project_id, "observed_project_id": project_id},
        )
    binding = {
        "project_id": project_id,
        "flow_tab_id": flow_tab_id,
        "flow_project_url": flow_url,
    }
    if bridge_lease is not None:
        required_lease_identity = {
            "connection_id": bridge_lease.get("connection_id"),
            "installation_id": bridge_lease.get("installation_id"),
            "extension_session_id": bridge_lease.get("extension_session_id"),
        }
        if not all(required_lease_identity.values()):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_LEASE_IDENTITY_INCOMPLETE: connection, installation, and session are required",
                details={"lease_id": bridge_lease.get("lease_id")},
            )
        response_identity = {
            "connection_id": inner.get("connection_id"),
            "installation_id": inner.get("installation_id"),
            "extension_session_id": inner.get("extension_session_id"),
        }
        mismatched_identity = {
            key: {"expected": required_lease_identity[key], "observed": value}
            for key, value in response_identity.items()
            if not value or str(value) != str(required_lease_identity[key])
        }
        if mismatched_identity:
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_CONNECTION_IDENTITY_MISMATCH: handled editor response rotated outside the operation lease",
                details={"mismatches": mismatched_identity},
            )
        if (
            bridge_lease.get("flow_tab_id") is not None
            and str(bridge_lease["flow_tab_id"]) != str(flow_tab_id)
        ):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_TAB_IDENTITY_MISMATCH: handled tab differs from the bound operation lease",
                details={
                    "lease_flow_tab_id": bridge_lease.get("flow_tab_id"),
                    "handled_flow_tab_id": flow_tab_id,
                },
            )
        if (
            bridge_lease.get("flow_project_id")
            and str(bridge_lease["flow_project_id"]) != str(project_id)
        ):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_PROJECT_IDENTITY_MISMATCH: handled project differs from the bound operation lease",
                details={
                    "lease_flow_project_id": bridge_lease.get("flow_project_id"),
                    "handled_flow_project_id": project_id,
                },
            )
        challenge_fn = getattr(client, "verify_provider_session_challenge", None)
        if not callable(challenge_fn):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_SESSION_CHALLENGE_UNAVAILABLE: provider authority cannot be proven"
            )
        challenge = await challenge_fn(flow_tab_id)
        if not isinstance(challenge, dict):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_SESSION_CHALLENGE_FAILED: invalid challenge response"
            )
        challenge_identity = {
            "connection_id": challenge.get("backend_connection_id"),
            "connection_epoch": challenge.get("backend_connection_epoch"),
            "installation_id": challenge.get("backend_installation_id"),
            "extension_session_id": challenge.get("backend_extension_session_id"),
            "flow_tab_id": challenge.get("flow_tab_id"),
            "flow_project_id": challenge.get("flow_project_id"),
        }
        expected_challenge_identity = {
            "connection_id": bridge_lease.get("connection_id"),
            "connection_epoch": bridge_lease.get("connection_epoch"),
            "installation_id": bridge_lease.get("installation_id"),
            "extension_session_id": bridge_lease.get("extension_session_id"),
            "flow_tab_id": flow_tab_id,
            "flow_project_id": project_id,
        }
        challenge_mismatches = {
            key: {
                "expected": expected_challenge_identity[key],
                "observed": value,
            }
            for key, value in challenge_identity.items()
            if expected_challenge_identity[key] is not None
            and str(value) != str(expected_challenge_identity[key])
        }
        extension_build = str(challenge.get("extension_build") or "").strip()
        extension_build_rejected = extension_build.lower() in {
            "legacy",
            "unknown",
            "n/a",
            "none",
        }
        if (
            challenge.get("ok") is not True
            or challenge.get("session_challenge_verified") is not True
            or challenge.get("extension_build_match") is not True
            or not extension_build
            or extension_build_rejected
            or challenge_mismatches
        ):
            raise FlowEditorBindingError(
                "FLOW_BRIDGE_SESSION_CHALLENGE_FAILED: connection/tab/project authority was not proven",
                details={
                    "primary_blocker": challenge.get("primary_blocker"),
                    "identity_mismatches": challenge_mismatches,
                    "extension_build_present": bool(extension_build),
                    "extension_build_rejected": extension_build_rejected,
                },
            )
        try:
            bound_lease = client.bind_operation_lease(
                bridge_lease,
                connection_id=required_lease_identity["connection_id"],
                connection_epoch=bridge_lease.get("connection_epoch"),
                installation_id=required_lease_identity["installation_id"],
                extension_session_id=required_lease_identity["extension_session_id"],
                extension_build=extension_build,
                flow_tab_id=flow_tab_id,
                flow_url=flow_url,
                flow_project_id=project_id,
            )
        except (ConnectionError, RuntimeError, ValueError) as exc:
            raise FlowEditorBindingError(
                f"FLOW_BRIDGE_LEASE_BINDING_MISMATCH: {exc}",
                details={"lease_id": bridge_lease.get("lease_id")},
            ) from exc
        binding["bridge_lease"] = bound_lease
    if isinstance(selected_binding, dict):
        for key in (
            "connection_id", "connection_epoch", "installation_id",
            "extension_session_id", "extension_id", "extension_version",
            "extension_build", "content_build_id", "content_script_protocol_version",
            "challenge_verified", "same_extension_session", "same_flow_tab",
        ):
            if selected_binding.get(key) is not None:
                binding[key] = selected_binding[key]
    return binding


async def _bind_with_recovery(client, requested_project_id=None, job=None) -> dict:
    """Bind to the OPEN Flow editor, self-healing ONCE if Google Flow has drifted the controlled
    tab back to the home shell (NO_OPEN_EDITOR — observed: Flow navigates the editor tab to home
    on its own). Recovery RE-OPENS the project the user was working in — the explicitly requested
    project, else the last stored editor URL — and NEVER mints a new project, then re-binds once.
    A stale/missing content script is re-injected once through the extension's
    official exact-project opener. BROKEN_EDITOR_PAGE / PROJECT_TAB_MISMATCH
    and every other binding error still fail closed."""
    bridge_lease = job.get("bridge_lease") if isinstance(job, dict) else None

    def official_reopen_allowed(exc: Exception) -> bool:
        detail = str(exc)
        return any(marker in detail for marker in (
            "NO_OPEN_EDITOR",
            "CONTENT_SCRIPT_NOT_READY",
            "CONTENT_BUILD_MISMATCH",
            "EXTENSION_BUILD_MISMATCH",
        ))

    async def bind_once() -> dict:
        if bridge_lease is None:
            binding = await _bind_editor_session(client, requested_project_id)
        else:
            binding = await _bind_editor_session(
                client,
                requested_project_id,
                bridge_lease=bridge_lease,
            )
        if job is not None:
            job["binding"] = binding
            if isinstance(binding.get("bridge_lease"), dict):
                job["bridge_lease"] = dict(binding["bridge_lease"])
                job["bridge_lease_state"] = "BOUND"
            sync_ok = await _sync_durable_single_job(job)
            if sync_ok is False:
                raise FlowEditorBindingError(
                    "BRIDGE_LEASE_DURABILITY_FAILED: bound bridge identity was not durably recorded"
                )
        return binding

    try:
        return await bind_once()
    except RuntimeError as e:
        if not official_reopen_allowed(e):
            raise
        target = (f"https://labs.google/fx/tools/flow/project/{requested_project_id}"
                  if requested_project_id else None)
        if not target:
            diag_fn = getattr(client, "flow_page_state_diagnostic", None)
            if callable(diag_fn):
                try:
                    pd = await diag_fn("F2V")
                    target = pd.get("stored_flow_project_url") if isinstance(pd, dict) else None
                except Exception:  # noqa: BLE001
                    target = None
        if target:
            if job is not None:
                job["stage"] = "editor drifted to home — re-opening the project"
            opener = getattr(client, "open_target_flow_project", None)
            if not callable(opener):
                raise FlowEditorBindingError(
                    "FLOW_EDITOR_BINDING_REQUIRED: official project-open route unavailable",
                    details={"target": target, "source_error": str(e)},
                ) from e
            try:
                opened = await opener(target)
            except Exception as open_exc:  # noqa: BLE001 — preserve route evidence
                opened = {"ok": False, "error": str(open_exc)}
            if job is not None:
                job["editor_open_result"] = opened
        else:
            # No stored project exists. Use only the extension's official
            # root -> new project -> editor workflow; never mint a hidden
            # project through a direct API call in this binding path.
            opener = getattr(client, "open_flow_new_project", None)
            if not callable(opener):
                raise FlowEditorBindingError(
                    "FLOW_EDITOR_BINDING_REQUIRED: official Flow project-open route unavailable",
                    details={"source_error": str(e)},
                ) from e
            try:
                opened = await opener("T2V")
            except Exception as open_exc:  # noqa: BLE001
                raise FlowEditorBindingError(
                    "FLOW_EDITOR_BINDING_REQUIRED: official Flow project-open route failed",
                    details={"source_error": str(e), "open_error": str(open_exc)},
                ) from open_exc
            if job is not None:
                job["editor_open_result"] = opened

        last_error = e
        for attempt in range(8):
            try:
                binding = await bind_once()
                binding["recovered_officially"] = True
                binding["binding_poll_attempts"] = attempt + 1
                return binding
            except RuntimeError as bind_exc:
                last_error = bind_exc
                if not official_reopen_allowed(bind_exc) or attempt == 7:
                    break
                await asyncio.sleep(1)
        raise FlowEditorBindingError(
            "FLOW_EDITOR_BINDING_REQUIRED: official Flow editor did not become ready",
            details={"source_error": str(e), "last_error": str(last_error)},
        ) from last_error


async def ensure_editor_binding(
    client=None,
    *,
    requested_project_id: str | None = None,
    mode: str = "T2V",
) -> dict:
    """Perform the official, bounded, provider-free editor binding preflight."""

    client = client or get_flow_client()
    if not getattr(client, "connected", False):
        raise FlowEditorBindingError(
            "FLOW_EDITOR_BINDING_REQUIRED: Flow extension transport is not connected",
            details={"transport_connected": False, "mode": mode},
        )
    lease_methods = (
        "acquire_operation_lease",
        "activate_operation_lease",
        "bind_operation_lease",
        "release_operation_lease",
    )
    if not all(callable(getattr(client, method, None)) for method in lease_methods):
        raise FlowEditorBindingError(
            "FLOW_BRIDGE_LEASE_API_UNAVAILABLE: the connected backend cannot bind provider authority"
        )
    lease = None
    binding = None
    released = False
    try:
        acquire_filters = {}
        if isinstance(client, FlowClient):
            selection = await client.bind_flow_session(
                project_id=requested_project_id,
            )
            if selection.get("ok") is not True or not selection.get(
                "connection_id"
            ):
                blocker = selection.get("primary_blocker") or (
                    "NO_ELIGIBLE_EXTENSION_SESSION"
                )
                raise FlowEditorBindingError(
                    f"{blocker}: project-aware bridge selection failed",
                    details={"selection": selection},
                )
            acquire_filters["connection_id"] = selection["connection_id"]
        lease = client.acquire_operation_lease(**acquire_filters)
        with client.activate_operation_lease(lease):
            binding = await _bind_editor_session(
                client,
                requested_project_id,
                bridge_lease=lease,
            )
            lease = dict(binding["bridge_lease"])
    except (ConnectionError, RuntimeError, ValueError) as exc:
        if isinstance(exc, FlowEditorBindingError):
            raise
        raise FlowEditorBindingError(
            f"FLOW_BRIDGE_LEASE_ACQUISITION_FAILED: {exc}",
            details={"mode": mode},
        ) from exc
    finally:
        if lease is not None:
            try:
                released = bool(client.release_operation_lease(lease))
            except Exception:  # noqa: BLE001 — report a closed-preflight failure
                released = False
    if binding is None or not released:
        raise FlowEditorBindingError(
            "FLOW_BRIDGE_LEASE_RELEASE_FAILED: provider readiness lease did not close cleanly"
        )
    binding["bridge_lease"] = {
        **dict(lease),
        "released": True,
        "released_at": time.time(),
        "receipt_state": "PREFLIGHT_RELEASED",
    }
    return binding


def get_job(job_id: str):
    j = _JOBS.get(job_id)
    if not j:
        return None
    return {k: v for k, v in j.items() if k != "_task"}


def _single_logical_job_key(job_id: str, idempotency_key: str | None = None) -> str:
    """Stable identity for the standard one-door SINGLE lane.

    The existing ``video_production_job`` ledger is also the recovery index for
    short jobs.  A caller-provided idempotency key deduplicates a replay; when a
    caller has no key, the generated job id intentionally makes the request a
    distinct logical intent.
    """
    material = str(idempotency_key or job_id).strip()
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"ljk_single_{digest}"


def _durable_single_snapshot(job: dict) -> dict:
    """JSON-safe state used for restart/readiness/retry recovery."""
    return json.loads(json.dumps(
        {k: v for k, v in job.items() if k != "_task"},
        ensure_ascii=False,
        default=str,
    ))


async def _prepare_durable_single_job(
    job: dict,
    *,
    idempotency_key: str | None = None,
    strict: bool = False,
) -> tuple[dict | None, bool]:
    """Create the standard SINGLE lifecycle row before its task can run.

    ``strict`` is used by the HTTP generation boundary.  Unit/programmatic
    callers that intentionally exercise the isolated in-memory lane may omit a
    request key; those callers retain their existing fixture behaviour, while a
    real API request fails closed before provider work if the ledger is down.
    """
    from agent.db import crud

    key = _single_logical_job_key(job["job_id"], idempotency_key)
    try:
        existing = await crud.get_video_production_job_by_logical_key(key)
        if existing:
            return existing, existing.get("job_id") == job.get("job_id")
        snapshot = _durable_single_snapshot(job)
        await crud.create_video_production_job_full(
            job["job_id"],
            logical_job_key=key,
            status=job.get("status") or "SUBMITTED",
            project_id=job.get("project_id"),
            requested_duration_seconds=int(job.get("duration_s") or 8),
            product_id=job.get("product_id"),
            staff_id=job.get("staff_id"),
            staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
            execution_package_id=job.get("workspace_execution_package_id"),
            engine="GOOGLE_FLOW_API_FIRST",
            model=job.get("model"),
            aspect_ratio=job.get("aspect"),
            plan_fingerprint=hashlib.sha256(
                json.dumps(
                    {
                        "mode": job.get("mode"),
                        "prompt": job.get("prompt"),
                        "source_mode": job.get("source_mode"),
                        "production_recipe": job.get("production_recipe"),
                        "references": job.get("reference_media_ids")
                        or job.get("image_media_ids")
                        or [],
                        "model": job.get("model"),
                        "duration_s": job.get("duration_s"),
                        "requested_profile_duration_s": job.get(
                            "requested_profile_duration_s"
                        ),
                        "workspace_execution_package_id": job.get(
                            "workspace_execution_package_id"
                        ),
                        "execution_profile_context": job.get(
                            "execution_profile_context"
                        ),
                        "provider_profile": job.get("provider_profile"),
                        "product_visual_custody": job.get(
                            "product_visual_custody"
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            whole_plan_json=json.dumps(
                {
                    "execution_mode": "SINGLE",
                    "lane": "MAKE_VIDEO_ONE_DOOR",
                    "request_id": job.get("request_id") or idempotency_key,
                    "stable_request_identity": (
                        job.get("request_id") or idempotency_key
                    ),
                    "workspace_execution_package_id": job.get(
                        "workspace_execution_package_id"
                    ),
                    "mode": job.get("mode"),
                    "source_mode": job.get("source_mode"),
                    "production_recipe": job.get("production_recipe"),
                    "surface_lane": job.get("surface_lane"),
                    "product_id": job.get("product_id"),
                    "project_id": job.get("project_id"),
                    "staff_id": job.get("staff_id"),
                    "staff_display_name": job.get("staff_display_name_snapshot"),
                    "requested_profile_duration_s": job.get(
                        "requested_profile_duration_s"
                    ),
                    "execution_identity": job.get("execution_identity"),
                    "execution_profile_context": job.get(
                        "execution_profile_context"
                    ),
                    "provider_profile": job.get("provider_profile"),
                    "product_visual_custody": job.get(
                        "product_visual_custody"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            initial_mode=job.get("mode"),
            initial_prompt_text=job.get("prompt") or "",
            initial_asset_media_id=(job.get("image_media_ids") or [None])[0],
            initial_reference_media_ids_json=json.dumps(
                job.get("image_media_ids") or [],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            initial_source_mode=job.get("source_mode"),
            surface_lane=job.get("surface_lane"),
            transport_mode=job.get("transport_mode") or job.get("mode"),
            source_mode=job.get("source_mode"),
            provider_generation_type=job.get("provider_generation_type"),
            initial_lane_job_id=job.get("job_id"),
            initial_lane_project_id=job.get("project_id"),
            stage_state_json=json.dumps(snapshot, ensure_ascii=False),
        )
        row = await crud.get_video_production_job(job["job_id"])
        if not row:
            raise RuntimeError("DURABLE_SINGLE_LEDGER_ROW_MISSING")
        return row, True
    except Exception as exc:  # noqa: BLE001 — caller decides strictness
        job["durable_ledger_error"] = str(exc)
        if strict:
            raise RuntimeError(
                "DURABLE_SINGLE_LEDGER_UNAVAILABLE:" + str(exc)[:240]
            ) from exc
        return None, True


async def _sync_durable_single_job(job: dict | None) -> bool:
    """Mirror terminal/in-flight state into the existing lifecycle ledger."""
    if not job or not str(job.get("job_id") or "").startswith("g_"):
        return True
    from agent.db import crud

    try:
        row = await crud.get_video_production_job(job["job_id"])
        if not row:
            return False if (
                job.get("durable") is True
                or job.get("bridge_lease_required") is True
            ) else True
        media_id = job.get("media_id") or job.get("video_media_id")
        local_path = job.get("local_path")
        file_sha256 = None
        file_size_bytes = None
        evidence = job.get("artifact_file_evidence") or {}
        if media_id and isinstance(evidence, dict):
            media_evidence = evidence.get(str(media_id)) or evidence.get("default")
            if isinstance(media_evidence, dict):
                file_sha256 = media_evidence.get("sha256")
                file_size_bytes = media_evidence.get("size_bytes")
        if media_id and not file_sha256 and local_path:
            try:
                from agent.services.video_artifact_delivery_service import (
                    file_delivery_evidence,
                )

                media_evidence = file_delivery_evidence(str(local_path))
                file_sha256 = media_evidence["sha256"]
                file_size_bytes = media_evidence["size_bytes"]
                job.setdefault("artifact_file_evidence", {})[str(media_id)] = media_evidence
            except Exception:
                # The persisted lifecycle still records the output identity; the
                # artifact delivery state remains retryable and non-green.
                pass
        provider_operation_ids = job.get("provider_operation_ids") or []
        first_operation_id = None
        for value in provider_operation_ids:
            if isinstance(value, dict):
                value = (
                    value.get("operation_id")
                    or value.get("operation_name")
                    or value.get("name")
                    or value.get("provider_operation_id")
                )
            if value:
                first_operation_id = str(value)
                break
        if not first_operation_id:
            identity = job.get("generation_identity") or {}
            if isinstance(identity, dict):
                names = identity.get("operation_names") or []
                if names:
                    first_operation_id = str(names[0])
        targets = job.get("direct_media_targets") or []
        first_workflow_id = None
        if targets and isinstance(targets[0], dict):
            first_workflow_id = (
                targets[0].get("workflow_id")
                or targets[0].get("workflowId")
            )
        state = _durable_single_snapshot(job)
        if first_operation_id or targets:
            state.setdefault("provider_generation_submit_count", 1)
            state["provider_resubmission"] = False
            state["resubmission_allowed"] = False
        terminal_with_output = {
            "DONE",
            "PRODUCT_FIDELITY_REVIEW_REQUIRED",
            "ARTIFACT_PERSISTENCE_FAILED",
        }
        await crud.update_video_production_job_full(
            job["job_id"],
            status=job.get("status") or "UNKNOWN",
            error_code=(
                (job.get("error") or job.get("artifact_record_error"))
                if job.get("status") != "DONE"
                else None
            ),
            project_id=job.get("project_id") or row.get("project_id"),
            initial_media_id=media_id,
            initial_operation_id=first_operation_id,
            initial_workflow_id=str(first_workflow_id) if first_workflow_id else None,
            final_media_id=media_id if media_id and job.get("status") in terminal_with_output else None,
            final_local_path=(str(local_path) if local_path and job.get("status") in terminal_with_output else None),
            final_sha256=file_sha256 if job.get("status") in terminal_with_output else None,
            final_duration_s=job.get("duration_used") or job.get("duration_s"),
            initial_lane_job_id=job.get("job_id"),
            initial_lane_project_id=job.get("project_id") or row.get("project_id"),
            surface_lane=job.get("surface_lane") or row.get("surface_lane"),
            transport_mode=job.get("transport_mode") or row.get("transport_mode") or job.get("mode"),
            source_mode=job.get("source_mode") or row.get("source_mode") or row.get("initial_source_mode"),
            provider_generation_type=(
                job.get("provider_generation_type")
                or row.get("provider_generation_type")
            ),
            stage_state_json=json.dumps(state, ensure_ascii=False),
            initial_correlation_json=json.dumps(
                job.get("output_correlation")
                or job.get("generation_identity")
                or None,
                ensure_ascii=False,
            ),
        )
        return True
    except Exception as exc:  # noqa: BLE001 — a terminal success needs honest state
        job["status"] = "DURABILITY_SYNC_FAILED"
        job["durability_sync_error"] = str(exc)
        job["error"] = str(exc)
        return False


def _pre_provider_evidence(row: dict, state: dict) -> dict:
    """Return the immutable evidence needed before a failure may be reconciled."""

    provider_ids = state.get("provider_operation_ids") or []
    handles = state.get("direct_media_targets") or []
    accounting = state.get("credit_accounting") or {}
    delta = accounting.get("delta")
    try:
        positive_delta = float(delta) > 0
    except (TypeError, ValueError):
        positive_delta = False
    credit_state = str(state.get("credit_state") or "").upper()
    return {
        "provider_generation_submit_count": int(
            state.get("provider_generation_submit_count") or 0
        ),
        "provider_operation_ids": list(provider_ids) if isinstance(provider_ids, list) else provider_ids,
        "direct_media_targets": list(handles) if isinstance(handles, list) else handles,
        "initial_operation_id": row.get("initial_operation_id"),
        "initial_media_id": row.get("initial_media_id"),
        "final_media_id": row.get("final_media_id"),
        "artifacts": state.get("artifacts") or [],
        "credit_delta": delta,
        "credit_state": credit_state,
        "credit_spent": bool(
            state.get("credit_spent") is True
            or credit_state in {"SPENT", "MAY_HAVE_SPENT"}
            or positive_delta
        ),
    }


async def reconcile_pre_provider_failure(
    job_id: str,
    *,
    classification_code: str,
    detail: str,
    request_id: str | None = None,
) -> dict:
    """Reconcile one provider-free failure through the lifecycle CRUD boundary.

    This is intentionally idempotent and refuses any row carrying a provider
    handle, artifact, submit count, or positive credit evidence.  It preserves
    the original error/lineage in ``stage_state_json`` while making the durable
    ``FAILED`` state explicitly terminal and pre-provider.
    """

    from agent.db import crud

    row = await crud.get_video_production_job(job_id)
    if not row:
        raise RuntimeError("PRE_PROVIDER_JOB_NOT_FOUND")
    state = _durable_state_from_row(row)
    existing = state.get("pre_provider_failure")
    if row.get("status") == "FAILED" and isinstance(existing, dict):
        return {
            "job_id": job_id,
            "status": row.get("status"),
            "pre_provider_failure": existing,
            "provider_evidence": _pre_provider_evidence(row, state),
            "idempotent": True,
        }
    evidence = _pre_provider_evidence(row, state)
    if (
        evidence["provider_generation_submit_count"]
        or evidence["provider_operation_ids"]
        or evidence["direct_media_targets"]
        or evidence["initial_operation_id"]
        or evidence["initial_media_id"]
        or evidence["final_media_id"]
        or evidence["artifacts"]
        or evidence["credit_spent"]
    ):
        raise RuntimeError(
            "PRE_PROVIDER_RECONCILIATION_PROVIDER_EVIDENCE_PRESENT: "
            + json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
        )
    if evidence["credit_state"] and evidence["credit_state"] not in {
        "NOT_SPENT", "NOT_SPENT_CONFIRMED", "UNKNOWN",
    }:
        raise RuntimeError(
            f"PRE_PROVIDER_RECONCILIATION_CREDIT_STATE_UNSAFE:{evidence['credit_state']}"
        )

    failure = {
        "classification": "PRE_PROVIDER",
        "error_code": str(classification_code or "PRE_PROVIDER_FAILURE")[:160],
        "detail": str(detail or "")[:1000],
        "request_id": request_id or state.get("request_id") or row.get("logical_job_key"),
        "provider_dispatch_reached": False,
        "provider_calls": 0,
        "credit_spend": False,
        "original_status": row.get("status"),
        "original_error_code": row.get("error_code"),
        "original_stage": state.get("stage"),
        "reconciled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    state["pre_provider_failure"] = failure
    state["provider_generation_submit_count"] = 0
    state["provider_resubmission"] = False
    state["resubmission_allowed"] = False
    await crud.update_video_production_job_full(
        job_id,
        status="FAILED",
        # Preserve the exact persisted source failure; the structured
        # classification and source detail remain in the audit state above.
        error_code=row.get("error_code") or str(detail or classification_code)[:1000],
        stage_state_json=json.dumps(state, ensure_ascii=False, default=str),
    )
    try:
        await crud.release_video_generation_lane_lease(job_id)
    except Exception:
        pass
    memory_job = _JOBS.get(job_id)
    if memory_job is not None:
        memory_job.update(
            status="FAILED",
            stage="pre_provider_failed",
            error=row.get("error_code") or str(detail or classification_code),
            pre_provider_failure=failure,
            provider_generation_submit_count=0,
            provider_resubmission=False,
            resubmission_allowed=False,
        )
    return {
        "job_id": job_id,
        "status": "FAILED",
        "pre_provider_failure": failure,
        "provider_evidence": evidence,
        "idempotent": False,
    }


def _durable_state_from_row(row: dict) -> dict:
    try:
        state = json.loads(row.get("stage_state_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    return state if isinstance(state, dict) else {}


def _durable_public_state(row: dict, state: dict, *, status: str | None = None) -> dict:
    """Merge the DB lifecycle row and its JSON snapshot for API/status readers."""
    merged = dict(state or {})
    effective_status = str(status or row.get("status") or "UNKNOWN")
    merged.update({
        "job_id": row.get("job_id"),
        "status": effective_status,
        "error": row.get("error_code") or merged.get("error"),
        "media_id": row.get("final_media_id")
        or row.get("initial_media_id")
        or merged.get("media_id"),
        "local_path": row.get("final_local_path") or merged.get("local_path"),
        "project_id": row.get("project_id") or merged.get("project_id"),
        "recovery_required": bool(
            merged.get("recovery_required")
            or effective_status in _DURABLE_RECOVERY_STATUSES
        ),
        "durable": True,
        "provider_generation_submit_count": int(
            merged.get("provider_generation_submit_count")
            or (1 if (
                merged.get("provider_operation_ids")
                or merged.get("direct_media_targets")
                or row.get("initial_operation_id")
                or row.get("initial_media_id")
            ) else 0)
        ),
        "provider_generation_submits": 0,
        "provider_resubmission": False,
        "resubmission_allowed": False,
    })
    # Historical Phase-B rows used PROVIDER_REJECTED for a generation that was
    # approved and then proved to use the wrong settings. Do not rewrite the
    # stored artifact: expose a deterministic derived primary classification with
    # the legacy value and source fields retained for provenance.
    if merged.get("capture_contract_verdict") == "PROVIDER_REJECTED":
        derived = _classify_reference_contract_capture(merged)
        if derived != "PROVIDER_REJECTED":
            merged["capture_contract_verdict_legacy"] = "PROVIDER_REJECTED"
            merged["capture_contract_verdict"] = derived
            merged["capture_contract_verdict_provenance"] = {
                "kind": "DERIVED_VIEW_NO_HISTORICAL_REWRITE",
                "reason": "approved generation has explicit post-approval model/duration mismatch",
                "source_fields": {
                    "approved": merged.get("approved"),
                    "model_ok": merged.get("model_ok"),
                    "duration_ok": merged.get("duration_ok"),
                    "error": merged.get("error"),
                },
            }
    return merged


def _provider_operation_name(value) -> str | None:
    if isinstance(value, dict):
        operation = value.get("operation")
        if isinstance(operation, dict):
            value = operation.get("name") or operation.get("operation_id")
        else:
            value = (
                value.get("operation_id")
                or value.get("operation_name")
                or value.get("provider_operation_id")
                or value.get("name")
            )
    value = str(value or "").strip()
    return value or None


def _durable_provider_handles(row: dict, state: dict) -> tuple[str | None, list, str | None]:
    """Resolve only identities persisted before/at provider acceptance.

    Direct media targets are preferred because they are the current Flow status
    contract. Legacy operation handles remain supported for older rows.  No
    value is manufactured from a prompt, project URL, or process-local map.
    """
    project_id = str(
        row.get("project_id") or state.get("project_id") or ""
    ).strip()
    raw_targets = state.get("direct_media_targets")
    if isinstance(raw_targets, list):
        targets = []
        for raw in raw_targets:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("media_id") or "").strip()
            target_project = str(
                raw.get("projectId")
                or raw.get("project_id")
                or project_id
                or ""
            ).strip()
            if name and target_project:
                targets.append({"name": name, "projectId": target_project})
        if targets:
            return "media", targets, None

    # A synced row carries initial_media_id even when an older snapshot did not
    # retain the list-shaped direct target.  This is still safe only with the
    # exact provider project id.
    media_id = str(
        state.get("media_id")
        or row.get("initial_media_id")
        or ""
    ).strip()
    if media_id and project_id:
        return "media", [{"name": media_id, "projectId": project_id}], None

    raw_operations = state.get("provider_operation_ids")
    if not isinstance(raw_operations, list):
        identity = state.get("generation_identity")
        raw_operations = identity.get("operation_names") if isinstance(identity, dict) else []
    if not isinstance(raw_operations, list):
        raw_operations = []
    if row.get("initial_operation_id"):
        raw_operations = [row["initial_operation_id"], *raw_operations]
    operations = []
    seen = set()
    for raw in raw_operations:
        name = _provider_operation_name(raw)
        if name and name not in seen:
            seen.add(name)
            operations.append({"operation": {"name": name}})
    if operations:
        return "operation", operations, None

    if (state.get("direct_media_targets") or media_id) and not project_id:
        return None, [], "DURABLE_PROVIDER_PROJECT_ID_MISSING"
    return None, [], "DURABLE_PROVIDER_IDENTITY_INSUFFICIENT"


def _provider_history_created_at(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _provider_history_aspect_matches(requested: str | None, observed: str | None) -> bool:
    if not requested or not observed:
        return True
    aliases = {
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "1:1": "VIDEO_ASPECT_RATIO_SQUARE",
    }
    expected = aliases.get(str(requested).strip(), str(requested).strip())
    return expected == str(observed).strip()


async def _recover_provider_media_from_project_history(
    row: dict,
    state: dict,
    client,
) -> dict:
    """Resolve one missing paid-operation identity from authenticated Flow state.

    The Flow creation-agent acknowledgement does not always expose an operation
    handle. Recovery is safe only when the durable provider-accepted envelope
    and one project-media row form an exact, unique composite. Freshness/order
    alone is never accepted.
    """
    lister = getattr(client, "list_project_media", None)
    project_id = str(row.get("project_id") or state.get("project_id") or "").strip()
    identity = state.get("generation_identity")
    identity = identity if isinstance(identity, dict) else {}
    anchors = {
        str(value).strip()
        for value in (
            identity.get("sse_prompt"),
            state.get("prompt"),
            row.get("initial_prompt_text"),
        )
        if str(value or "").strip()
    }
    expected_model = str(identity.get("expected_model") or "").strip()
    submitted_count = int(state.get("provider_generation_submit_count") or 0)
    if not callable(lister) or not project_id or not anchors or submitted_count != 1:
        return {
            "matched": False,
            "error": "PROJECT_HISTORY_RECOVERY_PRECONDITIONS_UNMET",
            "provider_calls": 0,
        }

    try:
        snapshot = await lister(project_id)
    except Exception as exc:  # noqa: BLE001 — preserve the accepted attempt
        return {
            "matched": False,
            "error": "PROJECT_HISTORY_LOOKUP_FAILED",
            "detail": str(exc)[:400],
            "provider_calls": 1,
        }
    if not isinstance(snapshot, dict) or snapshot.get("error"):
        detail = (
            snapshot.get("error")
            if isinstance(snapshot, dict)
            else "invalid project history response"
        )
        return {
            "matched": False,
            "error": "PROJECT_HISTORY_LOOKUP_FAILED",
            "detail": str(detail or "invalid response")[:400],
            "provider_calls": 1,
        }
    observed_project_id = str(snapshot.get("project_id") or "").strip()
    if observed_project_id != project_id:
        return {
            "matched": False,
            "error": "PROJECT_HISTORY_PROJECT_MISMATCH",
            "observed_project_id": observed_project_id,
            "provider_calls": 1,
        }

    job_created = _provider_history_created_at(row.get("created_at"))
    window_start = (job_created.timestamp() - 5) if job_created else None
    window_end = (job_created.timestamp() + 45 * 60) if job_created else None
    matches = []
    rejected = {
        "missing_identity": 0,
        "outside_window": 0,
        "prompt_mismatch": 0,
        "model_mismatch": 0,
        "aspect_mismatch": 0,
        "provider_failed": 0,
    }
    for item in snapshot.get("media") or []:
        if not isinstance(item, dict):
            continue
        media_id = str(item.get("name") or "").strip()
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        generated = (
            video.get("generatedVideo")
            if isinstance(video.get("generatedVideo"), dict)
            else video
        )
        metadata = (
            item.get("mediaMetadata")
            if isinstance(item.get("mediaMetadata"), dict)
            else {}
        )
        created_at = _provider_history_created_at(metadata.get("createTime"))
        if not media_id or created_at is None:
            rejected["missing_identity"] += 1
            continue
        created_ts = created_at.timestamp()
        if (
            window_start is not None
            and window_end is not None
            and not (window_start <= created_ts <= window_end)
        ):
            rejected["outside_window"] += 1
            continue
        _normalization, provider_prompt = _extract_provider_prompt(generated.get("prompt"))
        if provider_prompt not in anchors:
            rejected["prompt_mismatch"] += 1
            continue
        provider_model = str(generated.get("model") or "").strip()
        if expected_model and provider_model and provider_model != expected_model:
            rejected["model_mismatch"] += 1
            continue
        if not _provider_history_aspect_matches(
            row.get("aspect_ratio") or state.get("aspect"),
            generated.get("aspectRatio"),
        ):
            rejected["aspect_mismatch"] += 1
            continue
        media_status = (
            metadata.get("mediaStatus")
            if isinstance(metadata.get("mediaStatus"), dict)
            else {}
        )
        status = str(media_status.get("mediaGenerationStatus") or "").strip()
        if status == "MEDIA_GENERATION_STATUS_FAILED":
            rejected["provider_failed"] += 1
            continue
        matches.append({
            "name": media_id,
            "projectId": project_id,
            "workflow_id": str(item.get("workflowId") or "").strip() or None,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "provider_status": status or None,
            "provider_model": provider_model or None,
            "media_seed": generated.get("seed"),
        })

    if len(matches) != 1:
        return {
            "matched": False,
            "error": (
                "PROJECT_HISTORY_IDENTITY_NOT_FOUND"
                if not matches
                else "PROJECT_HISTORY_IDENTITY_AMBIGUOUS"
            ),
            "candidate_count": len(matches),
            "rejected": rejected,
            "provider_calls": 1,
        }
    return {
        "matched": True,
        "target": matches[0],
        "candidate_count": 1,
        "rejected": rejected,
        "provider_calls": 1,
        "correlation": "EXACT_PROMPT_MODEL_ASPECT_PROJECT_TIME_UNIQUE",
    }


def _durable_recovery_job(row: dict, state: dict) -> dict:
    """Rebuild the poll/retrieve job envelope without inventing a submit."""
    job = dict(state)
    job.update({
        "job_id": row.get("job_id"),
        "durable": True,
        "mode": state.get("mode") or row.get("initial_mode") or "F2V",
        "source_mode": state.get("source_mode") or row.get("initial_source_mode"),
        "surface_lane": state.get("surface_lane") or row.get("surface_lane"),
        "transport_mode": state.get("transport_mode") or row.get("transport_mode") or state.get("mode") or row.get("initial_mode"),
        "provider_generation_type": state.get("provider_generation_type") or row.get("provider_generation_type"),
        "prompt": state.get("prompt") or row.get("initial_prompt_text") or "",
        "model": state.get("model") or row.get("model"),
        "aspect": state.get("aspect") or row.get("aspect_ratio") or "9:16",
        "duration_s": state.get("duration_s") or row.get("requested_duration_seconds") or 8,
        "project_id": state.get("project_id") or row.get("project_id"),
        "product_id": state.get("product_id") or row.get("product_id"),
        "request_id": state.get("request_id"),
        "num_videos": int(state.get("num_videos") or 1),
        "strict_artifact_delivery": True,
        "resubmission_allowed": False,
        "provider_resubmission": False,
        "provider_generation_submit_count": int(
            state.get("provider_generation_submit_count") or 1
        ),
    })
    return job


async def _check_direct_media_targets_once(client, targets: list[dict]) -> dict:
    """Make one provider status call; a scheduler tick must never hold 15 min."""
    try:
        result = await client.check_video_status_by_media(targets)
    except Exception as exc:  # noqa: BLE001 — retain the handle for a later tick
        return {"state": "POLL_ERROR", "error": str(exc)[:400]}
    if not isinstance(result, dict) or result.get("error"):
        return {"state": "POLL_ERROR", "error": str((result or {}).get("error") or "empty status response")[:400]}
    entries = _direct_media_entries(result)
    by_name = {str(m.get("name")): m for m in entries if m.get("name")}
    names = {str(t.get("name")) for t in targets if t.get("name")}
    failed = [
        (name, _direct_media_status(by_name[name]))
        for name in names
        if name in by_name
        and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_FAILED"
    ]
    if failed:
        return {"state": "FAILED", "error": f"Media generation failed: {failed[0][0]}", "data": result}
    if names and all(
        name in by_name
        and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        for name in names
    ):
        return {"state": "SUCCESS", "data": result}
    return {"state": "PENDING", "data": result}


async def _check_direct_operations_once(client, operations: list[dict]) -> dict:
    """Make one legacy operation status call for restart reconciliation."""
    try:
        result = await client.check_video_status(operations)
    except Exception as exc:  # noqa: BLE001 — retain the handle for a later tick
        return {"state": "POLL_ERROR", "error": str(exc)[:400]}
    if not isinstance(result, dict) or result.get("error"):
        return {"state": "POLL_ERROR", "error": str((result or {}).get("error") or "empty status response")[:400]}
    data = _direct_response_data(result)
    ops = data.get("operations") if isinstance(data, dict) else []
    if not ops:
        return {"state": "PENDING", "data": result}
    statuses = [str(op.get("status") or "") for op in ops if isinstance(op, dict)]
    if any(status == "MEDIA_GENERATION_STATUS_FAILED" for status in statuses):
        return {"state": "FAILED", "error": "Provider operation failed", "data": result}
    if statuses and all(status == "MEDIA_GENERATION_STATUS_SUCCESSFUL" for status in statuses):
        return {"state": "SUCCESS", "data": result}
    return {"state": "PENDING", "data": result}


async def _reconcile_artifacts_only(job: dict) -> bool:
    """Retry a retrieved file/library registration without touching the provider."""
    artifacts = job.get("artifacts") or []
    if not artifacts and job.get("media_id") and job.get("local_path"):
        artifacts = [{
            "media_id": job.get("media_id"),
            "local_path": job.get("local_path"),
            "size_mb": job.get("size_mb"),
        }]
        job["artifacts"] = artifacts
    if not artifacts:
        return False
    job["status"] = "ARTIFACT_PERSISTING"
    await _record_artifacts(job, job.get("mode") or "F2V", artifacts)
    return True


async def reconcile_durable_single_job(
    job_id: str,
    *,
    provider_client=None,
) -> dict | None:
    """Resume one persisted SINGLE job using its exact provider identity.

    This function is deliberately submit-free.  It performs at most one status
    call per invocation, retrieves only a provider-terminal target, and then
    registers the local artifact.  A pending/error response leaves the exact
    handle in the ledger for the next scheduler/startup tick.
    """
    from agent.db import crud

    row = await crud.get_video_production_job(job_id)
    if not row or not str(row.get("job_id") or "").startswith("g_"):
        return None
    lock = _DURABLE_RECOVERY_LOCKS.setdefault(job_id, asyncio.Lock())
    async with lock:
        row = await crud.get_video_production_job(job_id)
        if not row:
            return None
        state = _durable_state_from_row(row)
        status = str(row.get("status") or "UNKNOWN")
        if status not in _DURABLE_RECOVERY_STATUSES:
            return _durable_public_state(row, state)

        job = _durable_recovery_job(row, state)
        job["recovery_required"] = True
        job["recovery_attempts"] = int(state.get("recovery_attempts") or 0) + 1
        job["provider_generation_submit_count"] = max(
            1,
            int(state.get("provider_generation_submit_count") or 0),
        )
        job["provider_reconciliation"] = {
            **(
                state.get("provider_reconciliation")
                if isinstance(state.get("provider_reconciliation"), dict)
                else {}
            ),
            "provider_generation_submits": 0,
            "provider_resubmission": False,
            "last_attempt": time.time(),
        }

        # A process can die after retrieval and before the two library writes.
        # The artifact list is enough to repair locally; no provider poll is
        # needed and no provider identity is required for this branch.
        if status in {"ARTIFACT_PERSISTING", "ARTIFACT_PERSISTENCE_FAILED", "RETRIEVED_NOT_REGISTERED"} or (
            state.get("provider_terminal") is True and state.get("artifacts")
        ):
            try:
                if await _reconcile_artifacts_only(job):
                    await _sync_durable_single_job(job)
                    fresh = await crud.get_video_production_job(job_id)
                    return _durable_public_state(
                        fresh or row,
                        _durable_state_from_row(fresh or row),
                    )
            except Exception as exc:  # noqa: BLE001 — preserve retryable evidence
                job["status"] = "ARTIFACT_PERSISTENCE_FAILED"
                job["artifact_record_error"] = str(exc)
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        client = provider_client
        if client is None:
            client = get_flow_client()

        handle_kind, handles, identity_error = _durable_provider_handles(row, state)
        if not handle_kind and identity_error == "DURABLE_PROVIDER_IDENTITY_INSUFFICIENT":
            history_lookup_lease = None
            try:
                if isinstance(client, FlowClient):
                    persisted_history_lease = (
                        state.get("bridge_lease")
                        if isinstance(state.get("bridge_lease"), dict)
                        else {}
                    )
                    persisted_installation_id = str(
                        persisted_history_lease.get("installation_id") or ""
                    ).strip()
                    if not persisted_installation_id:
                        raise ConnectionError(
                            "DURABLE_BRIDGE_LEASE_IDENTITY_REQUIRED:installation_id"
                        )
                    history_lookup_lease = client.acquire_operation_lease(
                        installation_id=persisted_installation_id
                    )
                    with client.activate_operation_lease(history_lookup_lease):
                        history_recovery = await (
                            _recover_provider_media_from_project_history(
                                row,
                                state,
                                client,
                            )
                        )
                else:
                    history_recovery = await (
                        _recover_provider_media_from_project_history(
                            row,
                            state,
                            client,
                        )
                    )
            except Exception as exc:  # noqa: BLE001 — preserve exact lookup blocker
                history_recovery = {
                    "matched": False,
                    "error": "PROJECT_HISTORY_LOOKUP_FAILED",
                    "detail": str(exc)[:400],
                    "provider_calls": 0,
                }
            finally:
                if history_lookup_lease is not None:
                    try:
                        client.release_operation_lease(history_lookup_lease)
                    except Exception:  # noqa: BLE001 — lookup remains fail-closed
                        pass
            job["provider_identity_recovery"] = history_recovery
            job["provider_reconciliation"]["identity_lookup_provider_calls"] = int(
                history_recovery.get("provider_calls") or 0
            )
            if history_recovery.get("matched") is True:
                recovered_target = dict(history_recovery["target"])
                job["direct_media_targets"] = [{
                    "name": recovered_target["name"],
                    "projectId": recovered_target["projectId"],
                    **(
                        {"workflow_id": recovered_target["workflow_id"]}
                        if recovered_target.get("workflow_id")
                        else {}
                    ),
                }]
                job["provider_operation_ids"] = [recovered_target["name"]]
                job["generation_identity"] = {
                    **(
                        state.get("generation_identity")
                        if isinstance(state.get("generation_identity"), dict)
                        else {}
                    ),
                    "operation_names": [recovered_target["name"]],
                    "provider_generation_submit_count": 1,
                }
                job.update(
                    status="RECOVERY_REQUIRED",
                    stage="provider_identity_recovered",
                    error=None,
                    recovery_unrecoverable=False,
                )
                sync_ok = await _sync_durable_single_job(job)
                if sync_ok is False:
                    raise RuntimeError(
                        "RECOVERED_PROVIDER_IDENTITY_DURABILITY_FAILED"
                    )
                row = await crud.get_video_production_job(job_id) or row
                state = _durable_state_from_row(row)
                handle_kind, handles, identity_error = _durable_provider_handles(
                    row,
                    state,
                )
        if not handle_kind:
            job.update(
                status="RECOVERY_UNRECOVERABLE",
                stage="recovery_unrecoverable",
                recovery_unrecoverable=True,
                error=identity_error,
                recovery_hint=(
                    "The durable row has no complete provider operation/media identity "
                    "and cannot be resumed safely. No provider resubmission is allowed."
                ),
            )
            job["provider_reconciliation"].update({
                "state": "UNRECOVERABLE",
                "error_code": identity_error,
            })
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        if handle_kind == "media":
            job["direct_media_targets"] = handles
            job["provider_operation_ids"] = [str(t["name"]) for t in handles]
        else:
            job["provider_operation_ids"] = handles
            job["generation_identity"] = {
                **(
                    state.get("generation_identity")
                    if isinstance(state.get("generation_identity"), dict)
                    else {}
                ),
                "operation_names": [
                    str((op.get("operation") or {}).get("name"))
                    for op in handles
                    if (op.get("operation") or {}).get("name")
                ],
                "provider_generation_submit_count": 1,
            }

        production_lease_required = client is None or isinstance(client, FlowClient)
        recovery_lease = None
        persisted_lease = (
            state.get("bridge_lease")
            if isinstance(state.get("bridge_lease"), dict)
            else {}
        )

        if production_lease_required:
            project_identity = {
                "row_project_id": str(row.get("project_id") or "").strip(),
                "state_project_id": str(state.get("project_id") or "").strip(),
                "lease_flow_project_id": str(
                    persisted_lease.get("flow_project_id") or ""
                ).strip(),
            }
            media_target_projects = (
                [
                    str(target.get("projectId") or "").strip()
                    for target in handles
                    if isinstance(target, dict)
                ]
                if handle_kind == "media"
                else []
            )
            project_values = [
                *project_identity.values(),
                *media_target_projects,
            ]
            if (
                any(not value for value in project_values)
                or len(set(project_values)) != 1
            ):
                job.update(
                    status="RECOVERY_REQUIRED",
                    stage="bridge_lease_recovery_blocked",
                    error="DURABLE_PROVIDER_PROJECT_CUSTODY_MISMATCH",
                    recovery_hint=(
                        "The provider handle is preserved, but its row/state/lease/"
                        "media project custody is incomplete or inconsistent. Never "
                        "poll or resubmit until the durable identity is repaired."
                    ),
                )
                job["provider_reconciliation"].update({
                    "state": "BRIDGE_LEASE_BLOCKED",
                    "error_code": "DURABLE_PROVIDER_PROJECT_CUSTODY_MISMATCH",
                    "project_identity": project_identity,
                    "media_target_projects": media_target_projects,
                    "provider_calls": 0,
                })
                await _sync_durable_single_job(job)
                fresh = await crud.get_video_production_job(job_id)
                return _durable_public_state(
                    fresh or row,
                    _durable_state_from_row(fresh or row),
                )

        def release_recovery_lease() -> None:
            nonlocal recovery_lease
            if recovery_lease is None:
                return
            try:
                released = bool(client.release_operation_lease(recovery_lease))
            except Exception as exc:  # noqa: BLE001 — persist exact cleanup state
                released = False
                job["bridge_lease_release_error"] = str(exc)
            job["bridge_lease"] = {
                **dict(job.get("bridge_lease") or recovery_lease),
                "released": released,
                "released_at": time.time(),
            }
            job["bridge_lease_state"] = (
                "RELEASED" if released else "RELEASE_FAILED"
            )
            recovery_lease = None

        if production_lease_required:
            installation_id = str(
                persisted_lease.get("installation_id") or ""
            ).strip()
            extension_build = str(
                persisted_lease.get("extension_build") or ""
            ).strip()
            durable_project_id = str(
                persisted_lease.get("flow_project_id")
                or job.get("project_id")
                or ""
            ).strip()
            missing_lease_fields = [
                field for field, value in {
                    "installation_id": installation_id,
                    "extension_build": extension_build,
                    "flow_project_id": durable_project_id,
                }.items() if not value
            ]
            if missing_lease_fields:
                job.update(
                    status="RECOVERY_REQUIRED",
                    stage="bridge_lease_recovery_blocked",
                    error="DURABLE_BRIDGE_LEASE_IDENTITY_REQUIRED",
                    recovery_hint=(
                        "The provider handle remains durable, but restart polling is "
                        "blocked until its exact installation/build/project lease can "
                        "be proven. Never resubmit the generation."
                    ),
                )
                job["provider_reconciliation"].update({
                    "state": "BRIDGE_LEASE_BLOCKED",
                    "error_code": "DURABLE_BRIDGE_LEASE_IDENTITY_REQUIRED",
                    "missing_lease_fields": missing_lease_fields,
                    "provider_calls": 0,
                })
                await _sync_durable_single_job(job)
                fresh = await crud.get_video_production_job(job_id)
                return _durable_public_state(
                    fresh or row,
                    _durable_state_from_row(fresh or row),
                )
            lease_methods = (
                "acquire_operation_lease",
                "activate_operation_lease",
                "bind_operation_lease",
                "release_operation_lease",
            )
            if not all(
                callable(getattr(client, method, None)) for method in lease_methods
            ):
                job.update(
                    status="RECOVERY_REQUIRED",
                    stage="bridge_lease_recovery_blocked",
                    error="FLOW_BRIDGE_LEASE_API_UNAVAILABLE",
                )
                job["provider_reconciliation"].update({
                    "state": "BRIDGE_LEASE_BLOCKED",
                    "error_code": "FLOW_BRIDGE_LEASE_API_UNAVAILABLE",
                    "provider_calls": 0,
                })
                await _sync_durable_single_job(job)
                fresh = await crud.get_video_production_job(job_id)
                return _durable_public_state(
                    fresh or row,
                    _durable_state_from_row(fresh or row),
                )
            try:
                recovery_lease = client.acquire_operation_lease(
                    installation_id=installation_id
                )
                with client.activate_operation_lease(recovery_lease):
                    recovery_lease = client.bind_operation_lease(
                        recovery_lease,
                        extension_build=extension_build,
                        flow_project_id=durable_project_id,
                    )
                    job["bridge_lease_previous"] = dict(persisted_lease)
                    job["bridge_lease"] = dict(recovery_lease)
                    job["bridge_lease_state"] = "REACQUIRED"
                    sync_ok = await _sync_durable_single_job(job)
                    if sync_ok is False:
                        raise RuntimeError(
                            "BRIDGE_LEASE_DURABILITY_FAILED: reacquired bridge identity was not persisted"
                        )
                    binding = await _bind_with_recovery(
                        client,
                        durable_project_id,
                        job,
                    )
                    recovery_lease = dict(binding["bridge_lease"])
                    if handle_kind == "media":
                        poll = await _check_direct_media_targets_once(client, handles)
                    else:
                        poll = await _check_direct_operations_once(client, handles)
            except asyncio.CancelledError:
                # Cancellation must not strand a process-local lease or mutate the
                # durable provider handle/status into a retry classification.
                release_recovery_lease()
                raise
            except Exception as exc:  # noqa: BLE001 — never poll through another profile
                release_recovery_lease()
                job.update(
                    status="RECOVERY_REQUIRED",
                    stage="bridge_lease_recovery_blocked",
                    error=f"FLOW_BRIDGE_REBIND_FAILED:{exc}",
                    recovery_hint=(
                        "Reconnect the same extension installation and its exact Flow "
                        "project. The provider handle is preserved and must not be resubmitted."
                    ),
                )
                job["provider_reconciliation"].update({
                    "state": "BRIDGE_LEASE_BLOCKED",
                    "error_code": "FLOW_BRIDGE_REBIND_FAILED",
                    "provider_calls": 0,
                })
                await _sync_durable_single_job(job)
                fresh = await crud.get_video_production_job(job_id)
                return _durable_public_state(
                    fresh or row,
                    _durable_state_from_row(fresh or row),
                )
        else:
            # Explicit provider injection is a provider-free unit-test seam.  All
            # production callers use the singleton path above.
            job["bridge_lease_test_seam"] = "INJECTED_PROVIDER_CLIENT"
            if handle_kind == "media":
                poll = await _check_direct_media_targets_once(client, handles)
            else:
                poll = await _check_direct_operations_once(client, handles)
        job["provider_reconciliation"].update({
            "state": poll.get("state"),
            "error": poll.get("error"),
            "handle_kind": handle_kind,
            "provider_handle_count": len(handles),
            "provider_calls": 1,
        })
        if poll.get("state") == "PENDING":
            release_recovery_lease()
            job.update(
                status="RECOVERY_REQUIRED",
                stage="provider_poll_pending",
                error="DURABLE_PROVIDER_POLL_PENDING",
                recovery_hint=(
                    "Provider operation is still rendering. The persisted handle will "
                    "be polled again; no provider resubmission is allowed."
                ),
            )
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )
        if poll.get("state") != "SUCCESS":
            release_recovery_lease()
            job.update(
                status="GENERATED_BUT_UNRETRIEVED",
                stage="provider_reconciliation_error",
                error=poll.get("error") or "DURABLE_PROVIDER_POLL_FAILED",
                recovery_hint=(
                    "The provider handle remains durable and can be polled again. "
                    "Do not resubmit the generation."
                ),
            )
            await _sync_durable_single_job(job)
            fresh = await crud.get_video_production_job(job_id)
            return _durable_public_state(
                fresh or row,
                _durable_state_from_row(fresh or row),
            )

        job["provider_terminal"] = True
        job["provider_status"] = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        plan = state.get("direct_plan") if isinstance(state.get("direct_plan"), dict) else {
            "gen_type": (state.get("generation_identity") or {}).get("gen_type")
            if isinstance(state.get("generation_identity"), dict)
            else "reference_frame_2_video",
            "aspect_enum": "VIDEO_ASPECT_RATIO_PORTRAIT",
        }
        seed = (state.get("generation_identity") or {}).get("seed", 0)
        try:
            if recovery_lease is not None:
                lease_context = client.activate_operation_lease(recovery_lease)
            else:
                from contextlib import nullcontext

                lease_context = nullcontext()
            with lease_context:
                if handle_kind == "media":
                    await _direct_media_retrieve_from_poll(
                        job,
                        client,
                        job.get("mode") or "F2V",
                        handles,
                        plan,
                        seed,
                        int(job.get("num_videos") or 1),
                        poll.get("data") or {},
                    )
                else:
                    await _direct_operation_retrieve_from_poll(
                        job,
                        client,
                        job.get("mode") or "F2V",
                        poll.get("data") or {},
                        plan,
                        seed,
                        int(job.get("num_videos") or 1),
                    )
        except Exception as exc:  # noqa: BLE001 — retain provider terminal identity
            job.update(
                status="GENERATED_BUT_UNRETRIEVED",
                stage="provider_terminal_retrieval_failed",
                error=str(exc),
                recovery_hint=(
                    "Provider is terminal but retrieval failed. Keep polling/retrieving "
                    "the persisted identity; never resubmit."
                ),
            )
        finally:
            release_recovery_lease()
        await _sync_durable_single_job(job)
        fresh = await crud.get_video_production_job(job_id)
        return _durable_public_state(
            fresh or row,
            _durable_state_from_row(fresh or row),
        )


async def get_durable_job(
    job_id: str,
    *,
    reconcile: bool = True,
    provider_client=None,
) -> dict | None:
    """Read/resume a standard job after the process-local map is gone."""
    from agent.db import crud

    row = await crud.get_video_production_job(job_id)
    if not row or not str(row.get("job_id") or "").startswith("g_"):
        return None
    state = _durable_state_from_row(row)
    status = str(row.get("status") or "UNKNOWN")
    if reconcile and status in _DURABLE_RECOVERY_STATUSES:
        return await reconcile_durable_single_job(
            job_id,
            provider_client=provider_client,
        )
    return _durable_public_state(row, state)


async def recover_durable_single_jobs(*, provider_client=None) -> dict:
    """Startup sweep: poll/retrieve/register persisted SINGLE identities once."""
    from agent.db import crud

    candidates = 0
    recovered = 0
    unrecoverable = 0
    provider_calls = 0
    for row in await crud.list_video_production_jobs(limit=1000):
        job_id = str(row.get("job_id") or "")
        if not job_id.startswith("g_"):
            continue
        status = str(row.get("status") or "")
        if status not in _DURABLE_RECOVERY_STATUSES:
            continue
        candidates += 1
        try:
            result = await reconcile_durable_single_job(
                job_id,
                provider_client=provider_client,
            )
            if isinstance(result, dict):
                reconciliation = result.get("provider_reconciliation") or {}
                provider_calls += int(reconciliation.get("provider_calls") or 0)
                if result.get("status") == "DONE":
                    recovered += 1
                if result.get("status") == "RECOVERY_UNRECOVERABLE":
                    unrecoverable += 1
        except Exception as exc:  # noqa: BLE001 — preserve a retryable row
            state = _durable_state_from_row(row)
            state.update({
                "recovery_required": True,
                "recovery_hint": (
                    "Provider reconciliation raised a transient error. The persisted "
                    "identity remains the only allowed retry target; no resubmission."
                ),
                "provider_reconciliation": {
                    "state": "POLL_ERROR",
                    "error": str(exc)[:400],
                    "provider_generation_submits": 0,
                },
            })
            await crud.update_video_production_job_full(
                job_id,
                status="RECOVERY_REQUIRED",
                error_code="DURABLE_RECOVERY_ATTEMPT_FAILED",
                stage_state_json=json.dumps(state, ensure_ascii=False),
            )
    return {
        "candidates": candidates,
        "recovered": recovered,
        "unrecoverable": unrecoverable,
        "provider_calls": provider_calls,
        "provider_generation_submits": 0,
        "marked_recovery_required": 0,
    }


async def _reconcile_profile_certification_task(job: dict | None) -> None:
    """Reconcile a profile capture that failed before provider acceptance."""

    if not job or not job.get("profile_certification_capture"):
        return
    if int(job.get("provider_generation_submit_count") or 0) != 0:
        return
    if job.get("artifacts") or job.get("provider_operation_ids"):
        return
    message = str(job.get("error") or "PROFILE_CERTIFICATION_PRE_PROVIDER_FAILURE")
    code = (
        "FLOW_EDITOR_BINDING_REQUIRED"
        if any(token in message for token in ("NO_OPEN_EDITOR", "EDITOR_TAB_LOST", "PROJECT_TAB_MISMATCH"))
        else "PROFILE_CERTIFICATION_PRE_PROVIDER_FAILED"
    )
    try:
        await reconcile_pre_provider_failure(
            str(job.get("job_id")),
            classification_code=code,
            detail=message,
            request_id=job.get("request_id"),
        )
    except Exception as exc:  # noqa: BLE001 — keep original failure and expose reconciliation error
        job["pre_provider_reconciliation_error"] = str(exc)
        return

    certification_id = job.get("profile_certification_id")
    snapshot_id = job.get("execution_snapshot_id")
    if certification_id:
        try:
            from agent.services import provider_certification_service as _certifications

            await _certifications.reconcile_pre_provider_failure(
                str(certification_id),
                job_id=str(job.get("job_id")),
                code=code,
                detail=message,
                snapshot_id=str(snapshot_id or "") or None,
            )
        except Exception as exc:  # noqa: BLE001
            job["pre_provider_certification_reconciliation_error"] = str(exc)
    if snapshot_id:
        try:
            from agent.services import execution_approval_service as _eas

            await _eas.reconcile_pre_provider_failure(
                str(snapshot_id),
                reason=f"{code}:{message}"[:1000],
            )
        except Exception as exc:  # noqa: BLE001
            job["pre_provider_snapshot_reconciliation_error"] = str(exc)


async def _run_generate_task(job_id: str, runner, *args) -> None:
    """Run a task while preserving the pre-provider certification state machine."""
    job = _JOBS.get(job_id)
    client = get_flow_client()
    # Detach any operation-lease id inherited via asyncio context copy from the
    # dispatching request (whose lease may already be released, e.g. faceless
    # profile certification). This task always acquires+activates its OWN lease
    # below, so it must never rely on an inherited one. Guarded so injected test
    # doubles without the method are unaffected.
    _detach = getattr(client, "detach_inherited_operation_lease", None)
    if callable(_detach):
        _detach()
    lease = None
    runner_started = False
    lease_methods = (
        "acquire_operation_lease",
        "activate_operation_lease",
        "bind_operation_lease",
        "release_operation_lease",
    )
    lease_capable = all(
        callable(getattr(client, method, None)) for method in lease_methods
    )
    try:
        if not job:
            raise RuntimeError("VIDEO_JOB_STATE_MISSING")
        injected_runner_fixture = bool(
            getattr(runner, "__module__", "")
            and getattr(runner, "__module__", "") != __name__
        )
        if injected_runner_fixture and not isinstance(client, FlowClient):
            job["bridge_lease_test_seam"] = "INJECTED_RUNNER_FIXTURE"
            runner_started = True
            await runner(job_id, *args)
            return
        if not lease_capable:
            # Existing isolated unit fixtures inject small provider doubles.  The
            # production singleton is never allowed through this compatibility seam.
            if isinstance(client, FlowClient):
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_LEASE_API_UNAVAILABLE: production FlowClient cannot acquire an operation lease"
                )
            job["bridge_lease_test_seam"] = "INJECTED_NON_FLOWCLIENT_FIXTURE"
            runner_started = True
            await runner(job_id, *args)
            return

        required_installation_id = str(
            job.get("required_extension_installation_id") or ""
        ).strip() or None
        acquire_filters = (
            {"installation_id": required_installation_id}
            if required_installation_id
            else {}
        )
        if not acquire_filters and isinstance(client, FlowClient):
            selection = await client.bind_flow_session(
                project_id=job.get("project_id"),
            )
            if selection.get("ok") is not True or not selection.get(
                "connection_id"
            ):
                blocker = selection.get("primary_blocker") or (
                    "NO_ELIGIBLE_EXTENSION_SESSION"
                )
                raise FlowEditorBindingError(
                    f"{blocker}: project-aware bridge selection failed",
                    details={"selection": selection},
                )
            acquire_filters = {"connection_id": selection["connection_id"]}
        lease = client.acquire_operation_lease(**acquire_filters)
        job["bridge_lease"] = dict(lease)
        job["bridge_lease_state"] = "ACQUIRED"
        sync_ok = await _sync_durable_single_job(job)
        if sync_ok is False:
            raise FlowEditorBindingError(
                "BRIDGE_LEASE_DURABILITY_FAILED: acquired bridge identity was not durably recorded"
            )
        with client.activate_operation_lease(lease):
            status_fn = getattr(client, "get_status", None)
            if not callable(status_fn):
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_STATUS_UNAVAILABLE: connection identity cannot be proven"
                )
            status = await status_fn(timeout=5)
            status_identity = {
                "connection_id": status.get("connection_id"),
                "connection_epoch": status.get("connection_epoch"),
                "installation_id": status.get("installation_id"),
                "extension_session_id": status.get("extension_session_id"),
            }
            required_status_fields = (
                "connection_id",
                "installation_id",
                "extension_session_id",
            )
            if status.get("error") or not all(
                status_identity.get(field) for field in required_status_fields
            ):
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_LEASE_IDENTITY_INCOMPLETE: live connection identity is incomplete",
                    details={"status_error": status.get("error")},
                )
            lease_mismatches = {
                field: {
                    "expected": lease.get(field),
                    "observed": status_identity.get(field),
                }
                for field in required_status_fields
                if lease.get(field) is not None
                and str(lease.get(field)) != str(status_identity.get(field))
            }
            if lease_mismatches:
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_CONNECTION_IDENTITY_MISMATCH: status rotated outside the acquired lease",
                    details={"mismatches": lease_mismatches},
                )
            extension_build = str(
                status.get("extension_build")
                or status.get("background_build_id")
                or ""
            ).strip()
            if not extension_build or extension_build.lower() in {
                "legacy",
                "unknown",
                "n/a",
                "none",
            }:
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_BUILD_IDENTITY_INVALID: a current non-legacy extension build is required"
                )
            required_build = str(
                job.get("required_extension_build") or ""
            ).strip()
            if required_build and required_build != extension_build:
                raise FlowEditorBindingError(
                    "FLOW_BRIDGE_BUILD_IDENTITY_MISMATCH: preflight and dispatch extension builds differ",
                    details={
                        "expected_extension_build": required_build,
                        "observed_extension_build": extension_build,
                    },
                )
            lease = client.bind_operation_lease(
                lease,
                **status_identity,
                extension_build=extension_build,
            )
            job["bridge_lease"] = dict(lease)
            job["bridge_lease_state"] = "CONNECTION_BOUND"
            sync_ok = await _sync_durable_single_job(job)
            if sync_ok is False:
                raise FlowEditorBindingError(
                    "BRIDGE_LEASE_DURABILITY_FAILED: acquired bridge identity was not durably recorded"
                )

            if job.get("mode") in _VIDEO_MODES:
                binding = await _bind_with_recovery(
                    client,
                    job.get("project_id"),
                    job,
                )
                job["binding"] = binding
                job["project_id"] = binding["project_id"]
                lease = dict(binding["bridge_lease"])

            runner_started = True
            await runner(job_id, *args)
    except Exception as exc:  # noqa: BLE001 — pre-provider lease failures are terminal
        if runner_started:
            raise
        if job is not None:
            if job.get("status") != "DURABILITY_SYNC_FAILED":
                job["status"] = "FAILED"
            job["stage"] = "bridge_lease_failed_pre_provider"
            job["error"] = str(exc)
            job["bridge_lease_error"] = {
                "classification": "PRE_PROVIDER",
                "provider_calls": 0,
                "credit_spend": False,
                "detail": str(exc),
            }
            _stamp_credit(job, CREDIT_NOT_SPENT)
    finally:
        job = _JOBS.get(job_id)
        # Release the process-local bridge lease before any cancellable cleanup
        # await. Durable/profile cleanup must never strand connection ownership.
        if lease is not None and lease_capable:
            try:
                released = bool(client.release_operation_lease(lease))
            except Exception as exc:  # noqa: BLE001 — retain exact cleanup evidence
                released = False
                if job is not None:
                    job["bridge_lease_release_error"] = str(exc)
            if job is not None:
                job["bridge_lease"] = {
                    **dict(job.get("bridge_lease") or lease),
                    "released": released,
                    "released_at": time.time(),
                }
                job["bridge_lease_state"] = (
                    "RELEASED" if released else "RELEASE_FAILED"
                )
        try:
            await _reconcile_profile_certification_task(job)
        finally:
            try:
                await _sync_durable_single_job(job)
            finally:
                try:
                    from agent.db import crud as _single_crud

                    await _single_crud.release_video_generation_lane_lease(job_id)
                except Exception:  # noqa: BLE001 - cleanup must not mask lifecycle evidence
                    pass


async def _run_reference_contract_capture(
    job_id, mode, prompt, project_id, image_media_ids,
    image_prompt, aspect, tier, model=None, duration_s=None,
    num_videos=1, image_model=None, max_image_attempts=8,
    collect_image_variants=False, product_id=None, copy_execution_binding=None,
):
    """Run the existing API-first agent lane behind the temporary capture gate."""
    await _run_generate(
        job_id, mode, prompt, project_id, image_media_ids, image_prompt,
        aspect, tier, model, duration_s, num_videos, image_model,
        max_image_attempts, collect_image_variants, product_id,
        copy_execution_binding,
    )
    job = _JOBS.get(job_id)
    if not job:
        return
    client = get_flow_client()
    after = None
    try:
        after = _capture_credit_balance(await client.get_credits())
    except Exception as exc:  # noqa: BLE001 - accounting stays explicit/unknown
        job["credit_balance_after_error"] = str(exc)[:240]
    job["credit_balance_after"] = after
    before = (job.get("capture_subject") or {}).get("credit_balance_before")
    delta = None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        delta = before - after
    job["credit_accounting"] = {
        "balance_before": before,
        "balance_after": after,
        "delta": delta,
        "generation_submit_count": int(job.get("provider_generation_submit_count") or 0),
        "actual_cost_observed": delta is not None,
    }
    media_evidence = {}
    for artifact in job.get("artifacts") or []:
        media_id = str(artifact.get("media_id") or "")
        path = artifact.get("local_path")
        if not media_id or not path:
            continue
        try:
            from agent.services.video_artifact_delivery_service import file_delivery_evidence

            evidence = file_delivery_evidence(str(path))
        except Exception as exc:  # noqa: BLE001 - keep capture evidence honest
            media_evidence[media_id] = {"error": str(exc)[:240]}
            continue
        measured = _measure_video_duration(str(path))
        evidence["measured_duration_s"] = measured
        evidence["provider_duration_s"] = job.get("duration_used")
        media_evidence[media_id] = evidence
        artifact["measured_duration_s"] = measured
    job["capture_media_evidence"] = media_evidence
    job["capture_contract_verdict"] = _classify_reference_contract_capture(job)
    await _sync_durable_single_job(job)


async def _run_profile_certification_capture(
    job_id, mode, prompt, project_id, image_media_ids,
    image_prompt, aspect, tier, model=None, duration_s=None,
    num_videos=1, image_model=None, max_image_attempts=8,
    collect_image_variants=False, product_id=None, copy_execution_binding=None,
):
    """Run the active Faceless T2V/compositor route with one credit boundary.

    This wrapper adds only before/after credit accounting and never changes the
    provider route.  Retrieval and deterministic finalization remain owned by
    the normal active ``_run_generate`` path.
    """

    job = _JOBS.get(job_id)
    if not job:
        return
    client = get_flow_client()
    try:
        before = _capture_credit_balance(await client.get_credits())
    except Exception as exc:  # noqa: BLE001 — no provider call without a quote
        job.update(
            status="FAILED",
            stage="certification_credit_precheck",
            error=f"CERTIFICATION_CREDITS_PRECHECK_FAILED:{exc}",
        )
        job["credit_accounting"] = {
            "balance_before": None,
            "balance_after": None,
            "delta": None,
            "actual_cost_observed": False,
        }
        return
    if before is None:
        job.update(
            status="FAILED",
            stage="certification_credit_precheck",
            error="CERTIFICATION_CREDITS_QUOTE_UNPROVEN",
        )
        job["credit_accounting"] = {
            "balance_before": None,
            "balance_after": None,
            "delta": None,
            "actual_cost_observed": False,
        }
        return
    job["credit_balance_before"] = before
    await _run_generate(
        job_id, mode, prompt, project_id, image_media_ids, image_prompt,
        aspect, tier, model, duration_s, num_videos, image_model,
        max_image_attempts, collect_image_variants, product_id,
        copy_execution_binding,
    )
    # The active conversational Flow route exposes the provider generation
    # identity through the authenticated extension's mediaGenerationIds map.
    # Carry that observed identity across the deterministic compositor boundary
    # so certification can report the real provider operation, never a local
    # job/media id guessed after the fact.
    observed_operations = []
    for artifact in job.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        correlation = artifact.get("correlation") or {}
        operation_id = (
            correlation.get("provider_operation_id")
            or correlation.get("media_generation_id")
        )
        if operation_id:
            observed_operations.append({
                "provider_operation_id": str(operation_id),
                "operation_id_source": (
                    correlation.get("provider_operation_id_source")
                    or "GOOGLE_FLOW_MEDIA_GENERATION_ID"
                ),
            })
    if observed_operations:
        job["provider_operation_ids"] = observed_operations
        job["provider_operation_id_source"] = observed_operations[0].get(
            "operation_id_source"
        )
    try:
        after = _capture_credit_balance(await client.get_credits())
    except Exception as exc:  # noqa: BLE001 — accounting stays explicit/unknown
        after = None
        job["credit_balance_after_error"] = str(exc)[:240]
    delta = before - after if isinstance(after, (int, float)) else None
    job["credit_balance_after"] = after
    job["credit_accounting"] = {
        "balance_before": before,
        "balance_after": after,
        "delta": delta,
        "generation_submit_count": int(job.get("provider_generation_submit_count") or 0),
        "actual_cost_observed": delta is not None,
    }
    if delta is None:
        job["credit_accounting"]["error"] = "CREDIT_DELTA_UNPROVEN"
    await _sync_durable_single_job(job)


async def retry_artifact_delivery(job_id: str) -> dict:
    """Retry only local artifact registration; never re-submit a provider job."""
    job = _JOBS.get(job_id)
    if job is None:
        from agent.db import crud

        row = await crud.get_video_production_job(job_id)
        if not row:
            raise KeyError(job_id)
        try:
            job = json.loads(row.get("stage_state_json") or "{}")
        except (TypeError, ValueError):
            job = {}
        if not isinstance(job, dict):
            job = {}
        job["job_id"] = job_id
    artifacts = job.get("artifacts") or []
    if not artifacts:
        raise RuntimeError("ARTIFACT_DELIVERY_RETRY_DATA_MISSING")
    await _record_artifacts(job, job.get("mode") or "F2V", artifacts)
    if job_id in _JOBS:
        _JOBS[job_id].update(job)
    await _sync_durable_single_job(job)
    return _durable_single_snapshot(job)


def _reretrieve_media_targets(job: dict) -> list[dict]:
    """Collect the ALREADY-CAPTURED provider media targets to re-fetch.

    Each target carries the rendered ``media_id`` plus optional
    ``media_generation_id``/``fife_url`` retrieval hints.  This reads only
    provider identity the job already recorded (artifacts -> output_correlation
    -> direct_media_targets); it never derives a NEW media id and never submits a
    generation.  Ordered de-dupe keeps the first occurrence.
    """
    targets: list[dict] = []
    seen: set[str] = set()

    def _add(media_id, media_generation_id=None, fife_url=None):
        mid = str(media_id or "").strip()
        if not mid or mid in seen:
            return
        seen.add(mid)
        targets.append({
            "media_id": mid,
            "media_generation_id": (
                str(media_generation_id).strip() if media_generation_id else None
            ),
            "fife_url": str(fife_url).strip() if fife_url else None,
        })

    for art in job.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        corr = art.get("correlation") if isinstance(art.get("correlation"), dict) else {}
        _add(
            art.get("media_id") or corr.get("media_id"),
            art.get("media_generation_id") or corr.get("media_generation_id"),
            art.get("fife_url") or corr.get("fife_url") or art.get("url"),
        )
    if not targets:
        corr = job.get("output_correlation")
        if isinstance(corr, dict):
            _add(
                corr.get("media_id"),
                corr.get("media_generation_id"),
                corr.get("fife_url"),
            )
    if not targets:
        for tgt in job.get("direct_media_targets") or []:
            if isinstance(tgt, dict):
                _add(
                    tgt.get("name") or tgt.get("media_id"),
                    tgt.get("media_generation_id"),
                    tgt.get("fife_url"),
                )
    return targets


async def reretrieve_provider_media_delivery(job_id: str) -> dict:
    """Session-pinned RE-RETRIEVAL recovery for a job whose provider media was
    RENDERED but whose ORIGINAL local delivery never persisted the bytes.

    Unlike ``retry_artifact_delivery`` (which only re-registers bytes already on
    disk), this RE-FETCHES the existing provider media for a KNOWN media id from
    the pinned Flow project and writes it to the CURRENT ``config.OUTPUT_DIR``
    retrieved path, ignoring any stale stored ``local_path``.  It NEVER submits
    or retries a generation -- recovery is bytes-only.

    Invariants (mirroring the normal generation lane):
      * acquire the durable SINGLE video lane before any provider-affecting call;
      * pin exactly ONE Flow session to the job's project via
        ``ensure_editor_binding`` (bind_flow_session -> acquire/activate/release
        operation lease); fail closed, provider-free, if it cannot be pinned;
      * reuse the SAME atomic delivery seam (``_record_artifacts`` ->
        ``generated_artifact`` + readback + ``generation_result``).

    Idempotent: if every media already has current-path bytes on disk AND a
    ``generation_result`` row, it returns COMPLETE without re-fetching.
    """
    from agent.db import crud

    job = _JOBS.get(job_id)
    if job is None:
        row = await crud.get_video_production_job(job_id)
        if not row:
            raise KeyError(job_id)
        try:
            job = json.loads(row.get("stage_state_json") or "{}")
        except (TypeError, ValueError):
            job = {}
        if not isinstance(job, dict):
            job = {}
        job["job_id"] = job_id

    mode = str(job.get("mode") or "F2V").upper()
    project_id = str(job.get("project_id") or "").strip()
    if not project_id:
        raise RuntimeError("RERETRIEVE_PROJECT_MISSING")
    targets = _reretrieve_media_targets(job)
    if not targets:
        raise RuntimeError("RERETRIEVE_MEDIA_TARGET_MISSING")

    outdir = OUTPUT_DIR / "retrieved"

    # Idempotency: already-persisted bytes + recorded result -> COMPLETE, no
    # re-fetch and no session/provider touch.
    already_complete = True
    for target in targets:
        path = outdir / f"{target['media_id']}.mp4"
        result_row = await crud.get_generation_result(target["media_id"])
        if not (path.exists() and path.stat().st_size > 0 and result_row):
            already_complete = False
            break
    if already_complete:
        job["reretrieve_recovery"] = {
            "state": "ALREADY_COMPLETE",
            "provider_generation_submits": 0,
            "media_ids": [t["media_id"] for t in targets],
        }
        if job.get("status") not in {"DONE", "PRODUCT_FIDELITY_REVIEW_REQUIRED"}:
            job.update(status="DONE", stage="done")
        if job_id in _JOBS:
            _JOBS[job_id].update(job)
        await _sync_durable_single_job(job)
        return _durable_single_snapshot(job)

    client = get_flow_client()

    # Durable single-flight guard -- the same cross-process lease the normal
    # generation lane holds, so re-retrieval never races a live generation.
    lane_lease = await crud.acquire_video_generation_lane_lease(job_id)
    if not lane_lease.get("acquired"):
        owner = (lane_lease.get("row") or {}).get("job_id")
        raise RuntimeError(
            f"VIDEO_JOB_IN_FLIGHT:{owner}" if owner else "VIDEO_JOB_IN_FLIGHT"
        )
    try:
        # Pin exactly ONE Flow session to the job's project.  A failed bind is a
        # structured, provider-free ``FlowEditorBindingError`` (a RuntimeError):
        # no bytes are fetched and no generation is submitted.
        binding = await ensure_editor_binding(
            client, requested_project_id=project_id, mode=mode
        )
        job["binding"] = binding

        outdir.mkdir(parents=True, exist_ok=True)
        collected: list[dict] = []
        for target in targets:
            media_id = target["media_id"]
            data_bytes, source = await _download_video_bytes(
                client,
                media_id,
                target.get("fife_url"),
                media_generation_id=target.get("media_generation_id"),
            )
            path = outdir / f"{media_id}.mp4"
            path.write_bytes(data_bytes)
            if not path.exists() or path.stat().st_size <= 0:
                raise RuntimeError(f"RERETRIEVE_WRITE_VERIFY_FAILED:{media_id}")
            collected.append({
                "media_id": media_id,
                "local_path": str(path),
                "size_mb": round(len(data_bytes) / 1024 / 1024, 2),
                "measured_duration_s": _measure_video_duration(str(path)),
                "correlation": {
                    "media_id": media_id,
                    "matched_on": "reretrieve_known_media_id",
                    "retrieval_source": source,
                    "media_generation_id": target.get("media_generation_id"),
                },
            })

        first = collected[0]
        # Set DONE BEFORE registration so the shared delivery seam runs its
        # ARTIFACT_PERSISTING -> DONE (or ARTIFACT_PERSISTENCE_FAILED) transition,
        # exactly as the normal retrieval path does.
        job.update(
            status="DONE", stage="done",
            media_id=first["media_id"], local_path=first["local_path"],
            size_mb=first["size_mb"], artifact="video",
            artifacts=list(collected),
            strict_artifact_delivery=True,
        )
        job["reretrieve_recovery"] = {
            "state": "RERETRIEVED",
            "provider_generation_submits": 0,
            "media_ids": [t["media_id"] for t in targets],
        }
        await _record_artifacts(job, mode, collected)
        if job.get("artifact_delivery_failed"):
            raise RuntimeError(
                "RERETRIEVE_DELIVERY_REGISTRATION_FAILED:"
                + str(job.get("artifact_record_error") or "")
            )
    finally:
        try:
            await crud.release_video_generation_lane_lease(job_id)
        except Exception:  # noqa: BLE001 -- cleanup must not mask recovery evidence
            pass

    if job_id in _JOBS:
        _JOBS[job_id].update(job)
    await _sync_durable_single_job(job)
    return _durable_single_snapshot(job)


def _pid(obj) -> str:
    m = re.search(r'"projectId"\s*:\s*"([^"]+)"', json.dumps(obj))
    return m.group(1) if m else ""


def _deep(obj, *keys):
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and v:
                    return v
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return None


async def start(prompt: str, image_prompt: str, product_id: str | None = None) -> dict:
    """Retired paid compatibility entrypoint; use the durable video job."""
    raise RuntimeError("LEGACY_PAID_VIDEO_ENTRYPOINT_RETIRED_USE_DURABLE_VIDEO_JOB")
    job_id = "v_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": None, "product_id": product_id,
                     "local_path": None, "video_media_id": None,
                     "size_mb": None, "error": None}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run(job_id, prompt, image_prompt, product_id)
    )
    return {"job_id": job_id, "status": "SUBMITTED"}


async def start_negotiate(prompt: str, image_prompt: str = None, dry: bool = True,
                          model: str = None, duration_s: int = None,
                          project_id: str = None,
                          reference_media_ids: list[str] | None = None) -> dict:
    """Async negotiation job — captures the FULL transcript (so a client timeout never
    loses it). dry=True stops before approving (0 video credits). model/duration steer the
    agent (patch I4a); project_id reuses an existing project (minimise junk); image_prompt=None
    skips the start frame (pure T2V dry capture). Existing reference_media_ids are passed
    through unchanged so a dry negotiation can audit the real reference contract without
    creating or uploading a new media target."""
    if dry is not True:
        raise RuntimeError("LEGACY_PAID_VIDEO_ENTRYPOINT_RETIRED_USE_DURABLE_VIDEO_JOB")
    job_id = "n_" + uuid4().hex[:12]
    refs = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                      "project_id": project_id, "dry": dry, "model": model,
                      "duration_s": duration_s, "reference_media_ids": refs,
                      "result": None, "transcript": None, "error": None,
                      "created": time.time()}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_negotiate(job_id, prompt, image_prompt, dry, model, duration_s,
                       project_id, refs))
    return {"job_id": job_id, "status": "SUBMITTED"}


# Known stale video id from an earlier project — must never be accepted as "the new video".
_STALE_VIDEO_IDS = {"b267d480-a516-4d00-a7a4-ac39bdae479d"}


async def start_on_existing(project_id: str, image_media_id: str, prompt: str) -> dict:
    """DEPRECATED — superseded by start_generate("I2V", ...). The /make-video-existing
    endpoint now routes through the guarded one door; this legacy path has NO single-flight
    lane, bound-session, or drift invariants. Do not call it for new work.

    The historical implementation is retained below for forensic context, but
    invocation is retired; /make-video-existing already uses start_generate."""
    raise RuntimeError("LEGACY_PAID_VIDEO_ENTRYPOINT_RETIRED_USE_DURABLE_VIDEO_JOB")
    job_id = "x_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "stage": "queued",
                     "project_id": project_id, "image_media_id": image_media_id,
                     "local_path": None, "video_media_id": None, "size_mb": None,
                     "approved": None, "generation_started": None, "error": None}
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_on_existing(job_id, project_id, image_media_id, prompt))
    return {"job_id": job_id, "status": "SUBMITTED"}


async def _run_on_existing(job_id: str, project_id: str, image_media_id: str, prompt: str):
    import base64
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        job["status"], job["stage"] = "NEGOTIATING", "agent session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["stage"] = "negotiating (approve 1 video, Veo Lite)"
        res = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, [image_media_id])
        job["approved"] = res.get("approved")
        job["generation_started"] = res.get("generation_started")
        if not res.get("approved"):
            if res.get("error_class") == agent_video.RATE_LIMITED:
                raise RuntimeError(str(res.get("error")))  # honest 0-credit rate-limit label
            raise RuntimeError("agent did not approve a video: " + str(res.get("error") or res))

        # Retrieve the NEW video. Harvest the (user's) tab — already on this project, no drift.
        # Accept only a media_id whose get_media returns video.encodedVideo (a real video),
        # excluding the start image and any known stale id.
        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        exclude = set(_STALE_VIDEO_IDS) | {image_media_id}
        await asyncio.sleep(120)
        for i in range(36):
            job["stage"] = f"checking for finished video (try {i + 1})"
            h = await client.harvest_video_urls()
            inner = h.get("result", h) if isinstance(h, dict) else {}
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            cands = []
            for k in ("videoIds", "imageIds", "mediaIds"):
                cands += (diag.get(k) or []) if isinstance(diag, dict) else []
            for mid in dict.fromkeys(cands):  # de-dupe, keep order
                if mid in exclude:
                    continue
                media = await client.get_media(mid)
                mdata = media.get("data", media) if isinstance(media, dict) else media
                enc = _deep(mdata, "encodedVideo")
                if enc:
                    vbytes = base64.b64decode(enc)
                    outdir = OUTPUT_DIR / "retrieved"
                    outdir.mkdir(parents=True, exist_ok=True)
                    path = outdir / f"{mid}.mp4"
                    path.write_bytes(vbytes)
                    job["status"], job["stage"] = "DONE", "done"
                    job["local_path"] = str(path)
                    job["video_media_id"] = mid
                    job["size_mb"] = round(len(vbytes) / 1024 / 1024, 2)
                    return
            await asyncio.sleep(18)
        job["status"], job["error"] = "FAILED", "video not found/retrieved in time"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"


_VIDEO_MODES = ("T2V", "I2V", "F2V")
_ALL_MODES = ("IMG",) + _VIDEO_MODES
ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL = (
    "ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL"
)
DIRECT_10S_CONTRACT_NOT_CERTIFIED = "DIRECT_10S_CONTRACT_NOT_CERTIFIED"
DIRECT_VIDEO_READINESS_CONTRACT_VERSION = "direct-video-readiness-v2"


def _pre_dispatch_generation_type(
    product_visual_custody: dict | None,
    direct_plan: dict | None,
) -> str:
    """Resolve the generation type used by the product-custody route guard.

    Exact-product T2V deliberately declines the direct reference plan and uses
    the agent scene-scaffold lane. That declined plan has no ``gen_type``;
    custody remains the authority for the required scaffold/composite contract.
    """
    if (
        isinstance(product_visual_custody, dict)
        and product_visual_custody.get("provider_route")
        == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    ):
        return str(
            product_visual_custody.get("generation_type")
            or "scene_video_scaffold_then_deterministic_composite"
        )
    return str((direct_plan or {}).get("gen_type") or "reference_frame_2_video")


def _build_reference_routing_receipt(
    mode: str,
    source_mode: str | None,
    image_media_ids: list | None,
    plan: dict | None,
) -> dict:
    """Build the provider-free routing proof for the one-door video service.

    A reference-bearing request is safe only when the selected route is either
    the captured direct reference-aware lane, the separately certified Flow-agent
    Omni 10s contract, or the explicitly owner-authorized shared 8s bootstrap.
    Unsupported reference tuples remain blocked before approval; pure T2V remains
    on its text-only agent lane.
    """
    mode = (mode or "").upper()
    normalized_source_mode = str(source_mode or "").strip().upper() or None
    reference_media_ids = [str(media_id) for media_id in (image_media_ids or []) if media_id]
    has_reference = bool(reference_media_ids)
    reference_requested = mode in ("F2V", "I2V") or has_reference

    from agent.services import flow_mode_reference_contract as _refc

    contract_ok, contract_code, contract_detail = _refc.validate_reference_count(
        mode, len(reference_media_ids), source_mode=normalized_source_mode
    )
    reference_contract = "valid" if contract_ok else "invalid"
    direct_eligible = bool(plan and plan.get("eligible"))
    certified_agent_route = _is_certified_hybrid_reference_omni10_plan(plan)
    shared_8s_bootstrap_route = bool(
        plan
        and plan.get("execution_route") == SHARED_REFERENCE_VEO_8S_BOOTSTRAP_ROUTE
    )
    text_only_allowed = not reference_requested
    reference_mode_authorized = (
        not reference_requested
        or (
            contract_ok
            and (direct_eligible or certified_agent_route or shared_8s_bootstrap_route)
        )
    )
    if reference_requested:
        if certified_agent_route and contract_ok:
            selected_route = HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
        elif shared_8s_bootstrap_route and contract_ok:
            selected_route = SHARED_REFERENCE_VEO_8S_BOOTSTRAP_ROUTE
        elif direct_eligible and contract_ok:
            selected_route = "DIRECT_API"
        else:
            selected_route = "BLOCKED_REFERENCE_ROUTE"
    elif mode == "T2V":
        selected_route = "AGENT_T2V"
    else:
        selected_route = "NON_VIDEO"

    reference_fingerprint = None
    if reference_media_ids:
        reference_fingerprint = hashlib.sha256(
            json.dumps(
                reference_media_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    return {
        "logical_mode": mode,
        "source_mode": normalized_source_mode,
        "reference_requested": reference_requested,
        "has_reference": has_reference,
        "reference_uploaded": has_reference,
        "reference_count": len(reference_media_ids),
        "reference_media_ids": reference_media_ids,
        "reference_fingerprint": reference_fingerprint,
        "reference_contract": reference_contract,
        "reference_contract_code": contract_code,
        "reference_contract_detail": contract_detail,
        "reference_mode_authorized": reference_mode_authorized,
        "selected_execution_route": selected_route,
        "text_only_allowed": text_only_allowed,
        "TEXT_ONLY_TOOL_ALLOWED": text_only_allowed,
        "approval_allowed": reference_mode_authorized,
        "route_reason": (plan or {}).get("reason"),
        "provider_generation_type": (plan or {}).get("provider_generation_type")
        or (plan or {}).get("gen_type"),
        "provider_tool": (plan or {}).get("provider_tool"),
        "provider_model_usage_key": (plan or {}).get("provider_model_usage_key"),
        "transport_contract_version": (plan or {}).get("contract_version"),
        # Shared provider certification is a separate axis from this lane's
        # surface/copy/custody envelope.  Keep only the provider proof here;
        # surface provenance is persisted by video_surface_provenance.
        "provider_profile_id": (plan or {}).get("provider_profile_id"),
        "provider_profile_digest": (plan or {}).get("provider_profile_digest"),
        "provider_profile_status": (plan or {}).get("provider_profile_status"),
        "provider_profile_evidence_id": (plan or {}).get(
            "provider_profile_evidence_id"
        ),
        "provider_certification_bootstrap": (
            "OWNER_AUTHORIZED_SHARED_8_TO_24_CHAIN"
            if shared_8s_bootstrap_route
            else None
        ),
        "pre_provider": {
            "classification": "READY" if reference_mode_authorized else "BLOCKED",
            "provider_calls": 0,
            "credit_spend": False,
            "selected_route": selected_route,
            "blocker_code": (
                None
                if reference_mode_authorized
                else (
                    contract_code
                    or (plan or {}).get("reason")
                    or ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
                )
            ),
        },
    }


async def _record_artifacts(job, mode, artifacts):
    """Persist every finished artifact into the system library (generated_artifact
    table) and durable Results Hub so completed videos/images survive restarts and
    are listable/downloadable from the dashboard. A delivery failure is terminal
    and retryable locally; it must never be reported as a provider-complete DONE."""
    job["artifact_persist_attempted"] = True
    job["artifact_persisted_count"] = 0
    from agent.services.video_surface_provenance import (
        build_video_surface_provenance,
    )
    provenance = build_video_surface_provenance(
        surface_lane=job.get("surface_lane"),
        transport_mode=job.get("transport_mode") or mode,
        source_mode=job.get("source_mode"),
        provider_type=job.get("provider_generation_type"),
        mode=mode,
        copy_lane=(job.get("copy_execution_binding") or {}).get("lane"),
        execution_identity=job.get("execution_identity"),
        routing_receipt=job.get("routing_receipt"),
        direct_plan=job.get("direct_plan"),
    )
    job.update(provenance)
    prior_status = job.get("status")
    delivery_retry = prior_status in {
        "DONE",
        "ARTIFACT_PERSISTING",
        "ARTIFACT_PERSISTENCE_FAILED",
        "RETRIEVED_NOT_REGISTERED",
    }
    if delivery_retry:
        job["status"] = "ARTIFACT_PERSISTING"
    custody = job.get("product_visual_custody")
    exact_route = bool(
        isinstance(custody, dict)
        and custody.get("exact_product_required")
        and custody.get("provider_route") == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    )
    if exact_route and mode in _VIDEO_MODES:
        # The retrieved provider scene is an internal scaffold.  Register only
        # deterministic final videos whose product pixels came from the
        # approved Product Truth cutout.
        try:
            from agent.services import exact_product_video_compositor_service as _exact_video
            from agent.db import crud

            product = await crud.get_product(str(custody.get("product_id") or job.get("product_id") or ""))
            if not product:
                raise _exact_video.ExactProductVideoCompositeError(
                    "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                    "Exact video compositor could not resolve the server product row.",
                )
            plan = custody.get("exact_product_video")
            if not isinstance(plan, dict):
                raise _exact_video.ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_PLAN_MISSING",
                    "Exact video custody has no compositor plan.",
                )
            final_artifacts = []
            for raw_artifact in artifacts:
                final_artifacts.append(
                    _exact_video.compose_exact_product_video_artifact(
                        product=product,
                        plan=plan,
                        scene_artifact=raw_artifact,
                        product_visual_custody=custody,
                        job_id=job.get("job_id"),
                        foreground_masks=(
                            raw_artifact.get("foreground_masks")
                            or plan.get("foreground_masks")
                            or []
                        ),
                        transform_track=(
                            raw_artifact.get("transform_track")
                            or raw_artifact.get("frame_transform_track")
                            or plan.get("transform_track")
                        ),
                    )
                )
            if not final_artifacts:
                raise _exact_video.ExactProductVideoCompositeError(
                    "EXACT_COMPOSITE_FINAL_MISSING",
                    "The provider returned no scene artifact for exact compositing.",
                )
            artifacts = final_artifacts
            job["artifacts"] = list(final_artifacts)
            job["media_id"] = final_artifacts[0].get("media_id")
            job["local_path"] = final_artifacts[0].get("local_path")
            job["size_mb"] = final_artifacts[0].get("size_mb")
            job["product_fidelity_qc_evidence"] = final_artifacts[0].get(
                "product_fidelity_qc_evidence"
            )
            custody = {
                **custody,
                "exact_video_composite": final_artifacts[0].get(
                    "exact_product_lineage"
                ),
            }
            job["product_visual_custody"] = custody
        except Exception as exc:  # noqa: BLE001 — exact output must fail closed
            job["status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["product_fidelity_qc_status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["generated_output_review_state"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"
            job["error"] = str(exc)
            job["exact_composite_error"] = getattr(exc, "code", "EXACT_COMPOSITE_FAILED")
            return
    try:
        from agent.db import crud
        from agent.services.video_artifact_delivery_service import file_delivery_evidence

        artifact_evidence: dict[str, dict] = {}
        strict_delivery = bool(
            job.get("strict_artifact_delivery")
            or job.get("request_id")
            or job.get("durable")
        )
        for art in artifacts:
            media_id = str(art.get("media_id") or "").strip()
            if not media_id:
                raise RuntimeError("ARTIFACT_MEDIA_ID_MISSING")
            local_path = str(art.get("local_path") or "").strip()
            try:
                evidence = file_delivery_evidence(local_path)
            except Exception:
                if strict_delivery:
                    raise
                # Legacy unit/programmatic callers may use a synthetic path;
                # real API jobs always carry strict_artifact_delivery/request_id.
                evidence = {
                    "local_path": local_path,
                    "size_bytes": None,
                    "sha256": None,
                    "unverified": True,
                }
            artifact_evidence[media_id] = evidence
        job["artifact_file_evidence"] = artifact_evidence
        for art in artifacts:
            evidence = artifact_evidence[str(art["media_id"])]
            readback = await crud.insert_generated_artifact(
                media_id=art["media_id"],
                job_id=job.get("job_id"),
                mode=mode,
                surface_lane=provenance["surface_lane"],
                transport_mode=provenance["transport_mode"],
                source_mode=provenance["source_mode"],
                provider_generation_type=provenance["provider_generation_type"],
                artifact_kind=("image" if mode == "IMG" else "video"),
                local_path=art.get("local_path"),
                size_mb=art.get("size_mb"),
                project_id=job.get("project_id"),
                model_used=job.get("model_used") or job.get("model"),
                duration_used=job.get("duration_used") or job.get("duration_s"),
                file_size_bytes=evidence["size_bytes"],
                file_sha256=evidence["sha256"],
                delivery_status="REGISTERED",
                readback_verified=True,
                staff_id=job.get("staff_id"),
                staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
            )
            if readback is not None and str(readback.get("local_path") or "") != str(art.get("local_path") or ""):
                raise RuntimeError(
                    f"ARTIFACT_READBACK_PATH_MISMATCH:{art['media_id']}"
                )
            job["artifact_persisted_count"] += 1
        # The generated_artifact row is the file/library index; generation_result
        # is the durable operator recovery record. Both are idempotent on media_id.
        for art in artifacts:
            await crud.insert_generation_result(
                art["media_id"],
                job_id=job.get("job_id"),
                request_id=job.get("request_id"),
                staff_id=job.get("staff_id"),
                staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
                mode=mode,
                artifact_kind=("image" if mode == "IMG" else "video"),
                 surface_lane=provenance["surface_lane"],
                 transport_mode=provenance["transport_mode"],
                 source_mode=provenance["source_mode"],
                 provider_generation_type=provenance["provider_generation_type"],
                product_id=job.get("product_id"),
                final_prompt_text=job.get("prompt") or "",
                aspect_ratio=job.get("aspect"),
                model_label=job.get("model_used") or job.get("model"),
                duration_s=job.get("duration_used") or job.get("duration_s"),
                count_setting=job.get("num_videos"),
                reference_media_ids=(job.get("routing_receipt") or {}).get(
                    "reference_media_ids"
                ) or [],
                project_id=job.get("project_id"),
                product_visual_custody=job.get("product_visual_custody") or {},
            )
    except Exception as e:  # noqa: BLE001 — delivery must be honest and retryable
        job["artifact_record_error"] = str(e)
        job["artifact_delivery_failed"] = True
        job["recovery_required"] = True
        job["recovery_hint"] = (
            "Provider output was retrieved but local artifact delivery failed. "
            "Retry artifact registration only; do not resubmit the provider job."
        )
        job["status"] = "ARTIFACT_PERSISTENCE_FAILED"
        return
    if delivery_retry:
        job["status"] = "DONE"
    custody = job.get("product_visual_custody") or custody
    if custody and mode in _VIDEO_MODES:
        from agent.services.product_visual_custody_service import (
            evaluate_product_fidelity_qc,
            exact_output_ready,
        )

        evidence = job.get("product_fidelity_qc_evidence")
        if evidence is None and artifacts:
            # Reuse the existing Product Reference Pack machine check as an
            # explicit review signal. It intentionally reports WARN/UNVERIFIED
            # for generated pixels; it must never be promoted to PASS here.
            evidence = {
                "status": "REVIEW_REQUIRED",
                "verified": False,
                "dimensions": {},
                "source": "product_reference_pack_machine_check",
            }
            try:
                from agent.services.product_reference_pack_service import (
                    get_reference_pack,
                    machine_check_generated_output,
                )

                pack = await get_reference_pack(str(custody.get("product_id") or ""))
                if pack is not None:
                    evidence["machine_qa"] = [
                        machine_check_generated_output(
                            str(artifact.get("media_id") or ""), pack
                        ).model_dump(mode="json")
                        for artifact in artifacts
                    ]
            except Exception as exc:  # noqa: BLE001 - QC remains review-required
                evidence["machine_qa_error"] = str(exc)

        qc = evaluate_product_fidelity_qc(
            custody,
            evidence=evidence,
            artifact_available=bool(artifacts),
        )
        job["product_fidelity_qc"] = qc
        job["product_fidelity_qc_status"] = qc.get("status")
        job["generated_output_review_state"] = qc.get("status")
        custody_result = {
            **custody,
            "product_fidelity_qc": qc,
            "product_fidelity_qc_status": qc.get("status"),
        }
        try:
            from agent.db import crud

            routing_receipt = job.get("routing_receipt") or {}
            for artifact in artifacts:
                artifact_custody_result = custody_result
                if artifact.get("exact_product_lineage"):
                    artifact_custody_result = {
                        **custody_result,
                        "exact_video_composite": artifact.get("exact_product_lineage"),
                    }
                await crud.insert_generation_result(
                    artifact["media_id"],
                    job_id=job.get("job_id"),
                    request_id=job.get("request_id"),
                    staff_id=job.get("staff_id"),
                    staff_display_name_snapshot=job.get("staff_display_name_snapshot"),
                    mode=mode,
                    surface_lane=provenance["surface_lane"],
                    transport_mode=provenance["transport_mode"],
                    source_mode=provenance["source_mode"],
                    provider_generation_type=provenance["provider_generation_type"],
                    artifact_kind="video",
                    product_id=job.get("product_id") or custody.get("product_id"),
                    product_name=custody.get("product_name"),
                    final_prompt_text=job.get("prompt") or "",
                    aspect_ratio=job.get("aspect"),
                    model_label=job.get("model"),
                    duration_s=job.get("duration_s"),
                    count_setting=job.get("num_videos"),
                    reference_media_ids=routing_receipt.get("reference_media_ids") or [],
                    project_id=job.get("project_id"),
                    product_visual_custody=artifact_custody_result,
                )
        except Exception as exc:  # noqa: BLE001 - lineage must not fail retrieval
            job["product_visual_custody_record_error"] = str(exc)
        if not exact_output_ready(custody, qc) and job.get("status") == "DONE":
            # Keep a returned artifact auditable, but never expose an exact
            # product as READY without explicit fidelity evidence.
            job["status"] = "PRODUCT_FIDELITY_REVIEW_REQUIRED"

    # Round 3 shared BEHAVIORAL acceptance: an MP4 existing is NOT success. For the
    # HYBRID / FACELESS / MONTAGE surfaces, inspect the RENDERED media against the
    # lane behavioral contract (presenter/hands/mascot visible, spoken dialogue,
    # lip-sync, non-static, not BGM-only). Provider-free here: vision/speech provers
    # are absent, so those properties are UNPROVEN and the job routes to behavioral
    # review rather than a silent success — UNPROVEN never becomes PASS. (Round 4
    # injects vision/speech provers to prove a live PASS.)
    if mode in _VIDEO_MODES and artifacts:
        import asyncio as _asyncio

        try:
            from agent.services import rendered_output_acceptance_service as _roa

            _surface = _roa.normalize_surface(
                (provenance or {}).get("surface_lane")
                or job.get("surface_lane")
                or (job.get("product_visual_custody") or {}).get("source_mode")
            )
            if _surface in ("HYBRID", "FACELESS", "MONTAGE"):
                _pf = (job.get("product_fidelity_qc") or {}).get("status")
                _accepts: list[dict] = []
                for artifact in artifacts:
                    _mp = artifact.get("local_path") or artifact.get("path") or ""
                    _acc = await _asyncio.to_thread(
                        _roa.evaluate_surface_acceptance, _surface, str(_mp),
                        product_fidelity_status=_pf,
                    )
                    _accepts.append(_acc.to_dict())
                job["behavioral_acceptance"] = _accepts
                if all(a["status"] == _roa.ACCEPT_PASS for a in _accepts):
                    _bstatus = _roa.ACCEPT_PASS
                elif any(a["status"] == _roa.ACCEPT_FAIL for a in _accepts):
                    _bstatus = _roa.ACCEPT_FAIL
                else:
                    _bstatus = _roa.ACCEPT_REVIEW
                job["behavioral_acceptance_status"] = _bstatus
                job["behavioral_acceptance_surface"] = _surface
                # Never let an unproven/failed behavioral clip stand as a plain DONE.
                if _bstatus != _roa.ACCEPT_PASS and job.get("status") == "DONE":
                    job["status"] = "BEHAVIORAL_REVIEW_REQUIRED"
        except Exception as exc:  # noqa: BLE001 - acceptance must never crash delivery; fail to review
            job["behavioral_acceptance_error"] = str(exc)
            if job.get("status") == "DONE":
                job["status"] = "BEHAVIORAL_REVIEW_REQUIRED"


def _image_provider_operation_reference(response: dict) -> dict[str, str | None]:
    """Extract provider correlation evidence without inventing an operation id.

    The current Flow image response is known to expose media names, while an
    operation id is not yet part of the proven response contract. Keep both
    facts explicit so a live benchmark can promote the status only when the
    provider actually returns an operation identifier.
    """
    data = response.get("data", response) if isinstance(response, dict) else response
    provider_operation_id = _deep(
        data, "operationId", "operation_id", "requestId", "request_id"
    )
    transport_batch_id = _deep(data, "batchId", "batch_id")
    return {
        "provider_operation_id": str(provider_operation_id)
        if provider_operation_id
        else None,
        "transport_batch_id": str(transport_batch_id) if transport_batch_id else None,
        "operation_id_status": "OBSERVED"
        if provider_operation_id
        else "UNPROVEN_PROVIDER_OPERATION_ID",
    }


async def _verify_generation_approval(
    *, mode, prompt, source_mode, model, aspect, duration_s, num_videos,
    image_model, asset_fingerprints, image_media_ids, product_id,
    manifest_id, execution_identity, execution_profile_context=None,
    provider_profile=None, allow_uncertified_profile_capture=False,
    snapshot_id: str | None = None,
):
    """Run the normal WYSIWYG approval gate for non-capture dispatches."""
    from agent.services import execution_approval_service as _eas
    from agent.services import video_execution_profile_service as _profiles
    from agent.services import provider_certification_service as _certifications

    if execution_profile_context is not None:
        try:
            _canonical_context = _profiles.normalize_approval_context(
                execution_profile_context
            )
            _certification = await _certifications.provider_certification_status(
                _canonical_context["duration_model_profile"]
            )
        except _profiles.ExecutionProfileError as exc:
            raise _eas.ExecutionApprovalError(
                "EXECUTION_PROFILE_CONTEXT_INVALID",
                str(exc),
                details={"code": exc.code, "details": exc.details},
            ) from exc
        if not _certification.get("certified") and not allow_uncertified_profile_capture:
            raise _eas.ExecutionApprovalError(
                "DURATION_PROFILE_NOT_CERTIFIED",
                "Provider proof is missing for this exact duration/model profile.",
                details=_certification,
            )
        execution_profile_context = _canonical_context

    _assets = [] if manifest_id else list(image_media_ids or [])
    _pinned_snapshot_id = snapshot_id
    if manifest_id:
        _resolved = await _eas.resolve_manifest_approved_snapshot(
            manifest_id=manifest_id, mode=mode, final_prompt_text=prompt,
            source_mode=source_mode, model=model, aspect=aspect,
            duration_s=duration_s, count=num_videos, image_model=image_model,
            asset_fingerprints=asset_fingerprints, asset_media_ids=_assets,
            product_id=product_id, execution_identity=execution_identity,
            execution_profile_context=execution_profile_context,
            provider_profile=provider_profile,
        )
        _pinned_snapshot_id = (_resolved or {}).get("snapshot_id")
    await _eas.verify_and_bind_dispatch(
        mode=mode, final_prompt_text=prompt, source_mode=source_mode,
        model=model, aspect=aspect, duration_s=duration_s,
        count=num_videos, image_model=image_model,
        asset_fingerprints=asset_fingerprints, asset_media_ids=_assets,
        product_id=product_id, snapshot_id=_pinned_snapshot_id,
        execution_identity=execution_identity,
        execution_profile_context=execution_profile_context,
        provider_profile=provider_profile,
    )


async def start_generate(mode: str, prompt: str, project_id: str = None,
                         image_media_ids: list = None, image_prompt: str = None,
                         aspect: str = "9:16", tier: str = "PAYGATE_TIER_ONE",
                         model: str = None, duration_s: int = None,
                         num_videos: int = 1, image_model: str = None,
                         max_image_attempts: int = 8,
                         collect_image_variants: bool = False,
                         product_id: str = None, source_mode: str = None,
                         staff_id: str | None = None,
                         staff_display_name_snapshot: str | None = None,
                         copy_execution_binding: dict | None = None,
                         manifest_id: str | None = None,
                         asset_fingerprints: list[str] | None = None,
                         workspace_execution_package_id: str | None = None,
                         execution_identity: dict | None = None,
                         execution_profile_context: dict | None = None,
                         requested_profile_duration_s: int | None = None,
                         provider_profile: dict | None = None,
                         product_visual_custody: dict | None = None,
                         request_id: str | None = None,
                         idempotency_key: str | None = None,
                         production_recipe: str | None = None,
                         surface_lane: str | None = None,
                         confirm_live_credit_burn: bool = False,
                         maximum_provider_operations: int | None = None,
                         max_retry_operations: int = 0,
                         capture_class: str | None = None,
                         capture_subject: dict | None = None,
                         capture_confirmed: bool = False,
                         profile_certification_capture: bool = False,
                         execution_snapshot_id: str | None = None,
                         profile_certification_id: str | None = None,
                         editor_binding: dict | None = None,
                         provider_target_authorization: dict | None = None) -> dict:
    """THE one door. mode = IMG | T2V | I2V | F2V. Returns a job_id; poll get_job.
    num_videos is the USER's count setting (1–4) — honoured end-to-end: the
    negotiation demands exactly that many and retrieval collects them all.
    source_mode (HYBRID | FRAMES | INGREDIENTS, optional) is the logical lane —
    it selects the direct-lane RPC (HYBRID composes references; FRAMES anchors
    start/end frames) and is recorded on the job. Under
    DIRECT_VIDEO_LANE_ENABLED, eligible reference-bearing video jobs run the
    DOM-free direct batchAsync lane. The certified Hybrid Omni Flash 10s tuple
    uses the separately proven Flow-agent reference-aware lane. Every other
    reference-bearing tuple is rejected before provider approval; pure T2V
    remains on the conversational agent lane."""
    global _VIDEO_LANE_JOB
    _gc_jobs()
    mode = (mode or "").upper()
    capture_requested = bool(capture_class)
    profile_certification_capture_requested = bool(profile_certification_capture)
    if capture_requested:
        if capture_class != HYBRID_REFERENCE_OMNI_10S_CAPTURE_CLASS:
            return _capture_contract_reject("CAPTURE_CLASS_UNSUPPORTED")
        if not hybrid_reference_omni10_capture_enabled():
            return _capture_contract_reject("CAPTURE_FEATURE_DISABLED")
        if capture_confirmed is not True:
            return _capture_contract_reject("CAPTURE_LIVE_CREDIT_CONFIRMATION_REQUIRED")
        if mode != "F2V":
            return _capture_contract_reject("CAPTURE_MODE_MUST_BE_F2V")
        if str(surface_lane or "").strip().upper() != "HYBRID":
            return _capture_contract_reject("CAPTURE_SURFACE_LANE_MUST_BE_HYBRID")
        if str(source_mode or "").strip().upper() != "HYBRID":
            return _capture_contract_reject("CAPTURE_SOURCE_MODE_MUST_BE_HYBRID")
        try:
            resolved_model = video_models.resolve(model)
        except (TypeError, ValueError):
            return _capture_contract_reject("CAPTURE_MODEL_MUST_BE_OMNI_FLASH")
        if resolved_model.get("key") != "omni_flash":
            return _capture_contract_reject("CAPTURE_MODEL_MUST_BE_OMNI_FLASH")
        if duration_s != 10:
            return _capture_contract_reject("CAPTURE_DURATION_MUST_BE_10")
        if str(aspect or "").strip() != "9:16":
            return _capture_contract_reject("CAPTURE_ASPECT_MUST_BE_9_16")
        if int(num_videos or 0) != 1:
            return _capture_contract_reject("CAPTURE_COUNT_MUST_BE_1")
        if len([media_id for media_id in (image_media_ids or []) if media_id]) != 1:
            return _capture_contract_reject("CAPTURE_REFERENCE_COUNT_MUST_BE_1")
        if str(product_id or "") != HYBRID_REFERENCE_OMNI_10S_CAPTURE_PRODUCT_ID:
            return _capture_contract_reject("CAPTURE_PRODUCT_NOT_AUTHORIZED")
    production_recipe = str(production_recipe or "").strip().upper() or None
    from agent.security.access_control import get_current_auth_context, resolve_request_staff
    if profile_certification_capture_requested:
        from agent.services import provider_certification_service as _certifications

        try:
            execution_profile_context = _certifications.validate_capture_contract(
                profile_context=execution_profile_context,
                mode=mode,
                source_mode=source_mode,
                model=model,
                duration_s=duration_s,
                aspect=aspect,
                num_videos=num_videos,
                image_media_ids=image_media_ids,
                product_id=product_id,
                production_recipe=production_recipe,
                surface_lane=surface_lane,
                product_visual_custody=product_visual_custody,
                confirm_live_credit_burn=confirm_live_credit_burn,
                maximum_provider_operations=maximum_provider_operations,
                max_retry_operations=max_retry_operations,
                auth_context=get_current_auth_context(),
            )
        except _certifications.ProviderCertificationError as exc:
            return {
                "status": "REJECTED",
                "error": exc.code,
                "detail": str(exc),
                "details": exc.details,
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                    "blocker_code": exc.code,
                },
            }
    if production_recipe or get_current_auth_context() is not None:
        if production_recipe not in {"HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"}:
            if production_recipe:
                return {
                    "status": "REJECTED",
                    "error": "PRODUCTION_RECIPE_UNSUPPORTED",
                    "pre_provider": {"provider_calls": 0, "credit_spend": False},
                }
        from agent.services.staff_identity_service import StaffIdentityError

        try:
            profile = await resolve_request_staff(staff_id)
        except StaffIdentityError as exc:
            return {
                "status": "REJECTED",
                "error": exc.code,
                "detail": exc.message,
                "pre_provider": {"provider_calls": 0, "credit_spend": False},
            }
        staff_id = profile["staff_id"]
        staff_display_name_snapshot = profile["display_name"]
    idempotency_key = idempotency_key or request_id
    strict_durable = bool(request_id or idempotency_key or mode in _ALL_MODES)
    required_extension_installation_id = None
    required_extension_build = None
    if editor_binding is not None:
        editor_binding_dict = (
            editor_binding if isinstance(editor_binding, dict) else {}
        )
        preflight_lease = (
            editor_binding_dict.get("bridge_lease")
        )
        preflight_project_id = str(
            editor_binding_dict.get("project_id")
            or (preflight_lease or {}).get("flow_project_id")
            or ""
        ).strip()
        required_preflight_fields = (
            "connection_id",
            "installation_id",
            "extension_session_id",
            "extension_build",
            "flow_tab_id",
            "flow_project_id",
        )
        missing_preflight_fields = [
            field for field in required_preflight_fields
            if not (preflight_lease or {}).get(field)
        ]
        preflight_extension_build = str(
            (preflight_lease or {}).get("extension_build") or ""
        ).strip()
        rejected_preflight_build = preflight_extension_build.lower() in {
            "legacy",
            "unknown",
            "n/a",
            "none",
        }
        if (
            not isinstance(preflight_lease, dict)
            or missing_preflight_fields
            or rejected_preflight_build
            or preflight_lease.get("released") is not True
            or not preflight_project_id
        ):
            return {
                "status": "REJECTED",
                "error": "FLOW_BRIDGE_PREFLIGHT_LEASE_REQUIRED",
                "detail": (
                    "Editor preflight must include a released installation/connection/"
                    "session/tab/project lease receipt."
                ),
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                    "missing_fields": missing_preflight_fields,
                    "extension_build_rejected": rejected_preflight_build,
                },
            }
        if project_id and str(project_id) != preflight_project_id:
            return {
                "status": "REJECTED",
                "error": "FLOW_BRIDGE_PREFLIGHT_PROJECT_MISMATCH",
                "detail": (
                    f"requested {project_id} but preflight proved "
                    f"{preflight_project_id}"
                ),
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                },
            }
        project_id = preflight_project_id
        required_extension_installation_id = str(
            preflight_lease["installation_id"]
        )
        required_extension_build = str(preflight_lease["extension_build"])
    num_videos = max(1, min(4, int(num_videos or 1)))
    max_image_attempts = max(1, min(8, int(max_image_attempts or 1)))
    # ONE-DOOR reference contract (transport hard caps): T2V is text-only —
    # attached references are NEVER inherited/forwarded; F2V carries at most 2
    # frames, I2V at most 3 ingredient refs. Rejected synchronously, before the
    # lane is claimed or any credit-adjacent work starts. Lower bounds live at
    # the operator layers (see flow_mode_reference_contract).
    from agent.services import flow_mode_reference_contract as _refc
    _ref_count = len([m for m in (image_media_ids or []) if m])
    _violation = _refc.service_hard_violation(mode, _ref_count)
    if _violation:
        return {
            "status": "REJECTED",
            "error": _violation,
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": _violation.split(":", 1)[0],
            },
        }
    _duration_model_profile = None
    _provider_profile_certification = None
    _submitted_provider_profile = None
    if mode in _VIDEO_MODES:
        try:
            _duration_model_profile, _derived_provider_profile = (
                _server_derived_video_profiles(
                    mode=mode,
                    source_mode=source_mode,
                    model=model,
                    duration_s=(requested_profile_duration_s or duration_s),
                    aspect=aspect,
                    ref_count=_ref_count,
                    num_videos=num_videos,
                )
            )
            if provider_profile is not None:
                _submitted_provider_profile = _resolve_submitted_provider_profile(
                    provider_profile
                )
                if (
                    _submitted_provider_profile["provider_profile_digest"]
                    != _derived_provider_profile["provider_profile_digest"]
                ):
                    raise ValueError("PROVIDER_PROFILE_CONTEXT_MISMATCH")
            if execution_profile_context is not None:
                from agent.services import video_execution_profile_service as _profiles

                _expected_context = dict(execution_profile_context)
                _expected_profile = (
                    execution_profile_context.get("duration_model_profile")
                    if isinstance(execution_profile_context, dict)
                    else None
                )
                _expected_profile = _profiles.canonicalize_profile(
                    _expected_profile or {}
                )
                if (
                    _expected_profile["profile_digest"]
                    != _duration_model_profile["profile_digest"]
                ):
                    raise ValueError("EXECUTION_PROFILE_CONTEXT_MISMATCH")
                _approval_digest_fields = (
                    "lane_adapter_digest",
                    "product_digest",
                    "copy_digest",
                    "sweetwps_digest",
                    "compositor_digest",
                    "compiler_digest",
                )
                if any(_expected_context.get(key) for key in _approval_digest_fields):
                    execution_profile_context = _profiles.normalize_approval_context(
                        _expected_context
                    )
                else:
                    execution_profile_context = {
                        "duration_model_profile": _expected_profile,
                        "lane": str(_expected_context.get("lane") or "")
                        .strip()
                        .upper()
                        .replace("-", "_"),
                    }
            provider_profile = _derived_provider_profile
        except (TypeError, ValueError) as exc:
            _code = getattr(exc, "code", None) or str(exc).split(":", 1)[0]
            return {
                "status": "REJECTED",
                "error": _code,
                "detail": str(exc),
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                    "blocker_code": _code,
                },
            }
    _shared_8s_profile = _resolve_shared_reference_8s_profile(
        mode=mode,
        source_mode=source_mode,
        model=model,
        duration_s=duration_s,
        aspect=aspect,
        ref_count=_ref_count,
        num_videos=num_videos,
        provider_profile=provider_profile,
    )
    _shared_8s_capture_authorized = _owner_authorized_shared_reference_8s_bootstrap(
        profile=_shared_8s_profile,
        confirm_live_credit_burn=confirm_live_credit_burn,
        maximum_provider_operations=maximum_provider_operations,
        max_retry_operations=max_retry_operations,
    )
    _exact_profile_certified = bool(
        isinstance(provider_profile, dict)
        and provider_profile.get("certification_status") == _pep.PROFILE_CERTIFIED
    )
    if mode in _VIDEO_MODES and not _exact_profile_certified:
        try:
            from agent.services import provider_certification_service as _certifications

            _provider_profile_certification = (
                await _certifications.provider_certification_status(
                    _duration_model_profile
                )
            )
            _exact_profile_certified = bool(
                _provider_profile_certification.get("certified")
            )
        except Exception as exc:  # noqa: BLE001 - fail closed before provider
            _provider_profile_certification = {
                "certified": False,
                "status": "NOT_CERTIFIED",
                "reason": "PROFILE_CERTIFICATION_LOOKUP_FAILED",
                "detail": str(exc),
            }
    _shared_8s_route_authorized = bool(
        _exact_profile_certified or _shared_8s_capture_authorized
    )
    if _shared_8s_profile and not _shared_8s_route_authorized:
        return {
            "status": "REJECTED",
            "error": "SHARED_8S_BOOTSTRAP_AUTHORIZATION_REQUIRED",
            "detail": (
                "Exact shared 8s provider profile requires authenticated OWNER "
                "authorization, confirm_live_credit_burn=true, a whole-chain "
                "budget of 3 provider operations, and retry count 0."
            ),
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": "SHARED_8S_BOOTSTRAP_AUTHORIZATION_REQUIRED",
            },
        }
    if _shared_8s_capture_authorized and not str(manifest_id or "").strip():
        return {
            "status": "REJECTED",
            "error": "SHARED_8S_EXECUTION_MANIFEST_REQUIRED",
            "detail": "The shared 8s certification bootstrap must dispatch from an approved execution manifest.",
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": "SHARED_8S_EXECUTION_MANIFEST_REQUIRED",
            },
        }
    if (
        mode in _VIDEO_MODES
        and not _exact_profile_certified
        and not capture_requested
        and not profile_certification_capture_requested
        and not _shared_8s_capture_authorized
    ):
        return {
            "status": "REJECTED",
            "error": "DURATION_PROFILE_NOT_CERTIFIED",
            "detail": (
                "Provider proof is missing for the exact server-derived "
                "duration/model/transport profile."
            ),
            "provider_profile": provider_profile,
            "provider_certification": _provider_profile_certification,
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": "DURATION_PROFILE_NOT_CERTIFIED",
            },
        }
    # A replay must resolve to the existing logical job before the process-local
    # single-flight check.  This is a read-only DB lookup and never resubmits a
    # provider operation, even when the old process-local map has been cleared.
    if idempotency_key:
        from agent.db import crud as _single_crud

        try:
            _existing = await _single_crud.get_video_production_job_by_logical_key(
                _single_logical_job_key("pending", idempotency_key)
            )
        except Exception as _exc:  # noqa: BLE001 — API callers fail closed
            if strict_durable:
                return {
                    "status": "REJECTED",
                    "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
                    "detail": str(_exc),
                    "pre_provider": {
                        "classification": "BLOCKED",
                        "provider_calls": 0,
                        "credit_spend": False,
                        "blocker_code": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
                    },
                }
            _existing = None
        if _existing:
            _memory_existing = get_job(_existing.get("job_id"))
            if _memory_existing:
                return {**_memory_existing, "request_id": request_id, "durable": True}
            _recovered_existing = await get_durable_job(_existing["job_id"])
            if _recovered_existing:
                return {**_recovered_existing, "request_id": request_id, "durable": True}
    # Single-flight (patch H): one video job at a time on the shared Flow tab. IMG exempt.
    if mode in _VIDEO_MODES and _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"status": "REJECTED", "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    _direct_plan = None
    _routing_receipt = None
    if mode in _VIDEO_MODES:
        if capture_requested:
            _direct_plan = {
                "eligible": False,
                "reason": "CAPTURE_ONLY_AGENT_DISCOVERY",
                "rpc": "agent_stream_chat",
                "gen_type": None,
                "aspect_enum": "VIDEO_ASPECT_RATIO_PORTRAIT",
                "video_model_key": None,
                "model_key_source": "provider_capture_only",
            }
            _routing_receipt = _capture_reference_routing_receipt(
                image_media_ids or []
            )
        else:
            _direct_plan = _direct_lane_plan(
                mode, source_mode, model, duration_s, aspect,
                ref_count=_ref_count, num_videos=num_videos,
                surface_lane=surface_lane,
                provider_profile=provider_profile,
                shared_8s_bootstrap_authorized=_shared_8s_route_authorized,
            )
            _routing_receipt = _build_reference_routing_receipt(
                mode, source_mode, image_media_ids, _direct_plan,
            )
        _exact_video_route = bool(
            isinstance(product_visual_custody, dict)
            and product_visual_custody.get("exact_product_required")
            and product_visual_custody.get("provider_route")
            == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
        )
        if _exact_video_route:
            # Exact finalization consumes a text-only scene scaffold.  Keep it
            # on the agent T2V scaffold lane until a separate captured direct
            # scaffold contract exists; never reinterpret the route as a
            # reference-bearing direct operation.
            _direct_plan = {
                **(_direct_plan or {}),
                "eligible": False,
                "reason": "EXACT_PRODUCT_SCENE_SCAFFOLD_AGENT_T2V",
            }
        if product_visual_custody and not capture_requested:
            from agent.services.product_visual_custody_service import (
                ProductVisualCustodyError,
                validate_pre_dispatch_route,
            )

            exact_route = _exact_video_route
            selected_route = (
                "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
                if exact_route
                else (_routing_receipt or {}).get("selected_execution_route")
                or (
                    "DIRECT_API"
                    if _direct_plan.get("eligible")
                    else "API_FIRST_GENERATIVE_REFERENCE"
                )
            )
            if exact_route:
                _routing_receipt.update(
                    {
                        "selected_execution_route": selected_route,
                        "provider_product_reference_forbidden": True,
                        "scene_scaffold_route": "AGENT_T2V",
                    }
                )
            try:
                validate_pre_dispatch_route(
                    product_visual_custody,
                    provider_route=selected_route,
                    generation_type=_pre_dispatch_generation_type(
                        product_visual_custody, _direct_plan
                    ),
                )
            except ProductVisualCustodyError as exc:
                return {
                    "status": "REJECTED",
                    "error": exc.code,
                    "detail": exc.message,
                    "routing_receipt": _routing_receipt,
                    "product_visual_custody": product_visual_custody,
                }
        if (
            not capture_requested
            and
            _routing_receipt["reference_requested"]
            and not _routing_receipt["reference_mode_authorized"]
        ):
            reason = (
                _routing_receipt.get("reference_contract_detail")
                or _routing_receipt.get("route_reason")
                or "reference-aware execution route is not proven"
            )
            return {
                "status": "REJECTED",
                "error": ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL,
                "detail": f"Reference-bearing video blocked before provider approval: {reason}",
                "routing_receipt": _routing_receipt,
                "pre_provider": (_routing_receipt or {}).get("pre_provider"),
            }
    from agent.services.video_surface_provenance import build_video_surface_provenance
    _surface_provenance = build_video_surface_provenance(
        surface_lane=surface_lane,
        transport_mode=mode,
        source_mode=source_mode,
        mode=mode,
        copy_lane=(copy_execution_binding or {}).get("lane"),
        execution_identity=execution_identity,
        routing_receipt=_routing_receipt,
        direct_plan=_direct_plan,
    )
    # Provider-bound jobs must carry a current released/readiness-approved product.
    # Legacy direct service tests without an HTTP AuthContext remain provider-free
    # compatibility calls; every real route and worker supplies the identity.
    from agent.security.access_control import get_current_auth_context
    if product_id or get_current_auth_context() is not None:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="MAKE_VIDEO_PROVIDER"
            )
        except ProductOperationalVisibilityError as exc:
            return {
                "status": "REJECTED",
                "error": exc.code,
                "detail": str(exc),
                "pre_provider": {"provider_calls": 0, "credit_spend": False},
            }
    # Final Prompt Approval Gate (WYSIWYG dispatch verification) is intentionally
    # skipped only for the owner-authorized capture boundary above.  That boundary
    # has its own exact class/flag/confirmation checks and is not reachable through
    # the normal /generate request model.
    if not capture_requested and not profile_certification_capture_requested:
        from agent.services import execution_approval_service as _eas
        try:
            await _verify_generation_approval(
                mode=mode, prompt=prompt, source_mode=source_mode,
                model=model, aspect=aspect, duration_s=duration_s,
                num_videos=num_videos, image_model=image_model,
                asset_fingerprints=asset_fingerprints,
                image_media_ids=image_media_ids, product_id=product_id,
                manifest_id=manifest_id, execution_identity=execution_identity,
                execution_profile_context=execution_profile_context,
                provider_profile=(
                    provider_profile
                    or (
                        (_direct_plan or {}).get("provider_profile")
                        if isinstance(_direct_plan, dict)
                        else None
                    )
                ),
                allow_uncertified_profile_capture=profile_certification_capture_requested,
            )
        except _eas.ExecutionApprovalError as _gate_err:
            return {"status": "REJECTED", "error": _gate_err.code,
                    "detail": _gate_err.message, "approval": _gate_err.details}
    job_id = "g_" + uuid4().hex[:12]
    _JOBS[job_id] = {"job_id": job_id, "status": (
                         PROFILE_CERTIFICATION_PRE_PROVIDER_STATUS
                         if profile_certification_capture_requested
                         else "SUBMITTED"
                     ), "mode": mode,
                     "stage": "queued", "project_id": project_id, "local_path": None,
                     "media_id": None, "size_mb": None, "artifact": None,
                     "approved": None, "binding": None, "model": model,
                     "num_videos": num_videos, "artifacts": [],
                     "provider_operation_ids": [],
                     "max_image_attempts": max_image_attempts,
                     "collect_image_variants": bool(collect_image_variants),
                     "product_id": product_id, "source_mode": source_mode,
                     "production_recipe": production_recipe,
                     "staff_id": staff_id,
                     "staff_display_name_snapshot": staff_display_name_snapshot,
                     "prompt": prompt, "aspect": aspect, "duration_s": duration_s,
                     "image_media_ids": [media_id for media_id in (image_media_ids or []) if media_id],
                     "reference_media_ids": [media_id for media_id in (image_media_ids or []) if media_id],
                      **_surface_provenance,
                      "transport_mode": _surface_provenance["transport_mode"] or mode,
                      "direct_plan": _direct_plan,
                      "workspace_execution_package_id": workspace_execution_package_id,
                      "execution_identity": execution_identity,
                      "execution_profile_context": execution_profile_context,
                      "requested_profile_duration_s": requested_profile_duration_s,
                      "duration_model_profile": _duration_model_profile,
                      "provider_profile_certification": _provider_profile_certification,
                      "provider_profile": provider_profile,
                      "provider_profile_id": (
                          provider_profile.get("profile_id")
                          if isinstance(provider_profile, dict)
                          else None
                      ),
                      "provider_profile_digest": (
                          provider_profile.get("provider_profile_digest")
                          if isinstance(provider_profile, dict)
                          else None
                      ),
                      "provider_profile_status": (
                          "CERTIFIED" if _exact_profile_certified else "NOT_CERTIFIED"
                      ),
                      "provider_certification_bootstrap": (
                          "OWNER_AUTHORIZED_SHARED_8_TO_24_CHAIN"
                          if _shared_8s_capture_authorized
                          else None
                      ),
                      "provider_operation_budget": maximum_provider_operations,
                      "max_retry_operations": int(max_retry_operations or 0),
                      "confirm_live_credit_burn": bool(confirm_live_credit_burn),
                      "product_visual_custody": product_visual_custody,
                     "capture_only": capture_requested,
                     "capture_class": capture_class,
                     "capture_subject": capture_subject,
                      "profile_certification_capture": profile_certification_capture_requested,
                      "profile_certification_id": profile_certification_id,
                      "execution_snapshot_id": execution_snapshot_id,
                      "provider_target_authorization": provider_target_authorization,
                      "editor_binding_preflight": editor_binding,
                      "bridge_lease_required": True,
                      "required_extension_installation_id": required_extension_installation_id,
                      "required_extension_build": required_extension_build,
                     "profile_certification_profile_digest": (
                         (execution_profile_context or {})
                         .get("duration_model_profile", {})
                         .get("profile_digest")
                         if profile_certification_capture_requested
                         else None
                     ),
                     "profile_certification_context": (
                         execution_profile_context
                         if profile_certification_capture_requested
                         else None
                     ),
                     "provider_generation_submit_count": 0,
                     "provider_resubmission": False,
                     "resubmission_allowed": False,
                     "error": None, "created": time.time(),
                     "request_id": request_id, "idempotency_key": idempotency_key,
                     "durable": False}
    if _routing_receipt is not None:
        _JOBS[job_id]["routing_receipt"] = _routing_receipt
    if capture_requested:
        _JOBS[job_id]["surface_lane"] = "HYBRID"
        _JOBS[job_id]["transport_mode"] = "F2V"
        _JOBS[job_id]["provider_generation_type"] = None
    if copy_execution_binding is not None:
        _JOBS[job_id]["copy_execution_binding"] = copy_execution_binding
    try:
        _durable_row, _durable_owner = await _prepare_durable_single_job(
            _JOBS[job_id], idempotency_key=idempotency_key, strict=strict_durable
        )
    except RuntimeError as _exc:
        _JOBS.pop(job_id, None)
        return {
            "status": "REJECTED",
            "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            "detail": str(_exc),
            "pre_provider": {
                "classification": "BLOCKED",
                "provider_calls": 0,
                "credit_spend": False,
                "blocker_code": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            },
        }
    if _durable_row and not _durable_owner:
        _JOBS.pop(job_id, None)
        _recovered = await get_durable_job(_durable_row["job_id"])
        return {
            **(_recovered or {"job_id": _durable_row["job_id"], "status": "RECOVERY_REQUIRED"}),
            "request_id": request_id,
            "durable": True,
        }
    if _durable_row:
        _JOBS[job_id]["durable"] = True
        _JOBS[job_id]["logical_job_key"] = _durable_row.get("logical_job_key")
    if mode in _VIDEO_MODES:
        from agent.db import crud as _lane_crud

        try:
            _lane_lease = await _lane_crud.acquire_video_generation_lane_lease(job_id)
        except Exception as _exc:  # noqa: BLE001 - real API requests fail closed
            if strict_durable:
                _JOBS.pop(job_id, None)
                return {
                    "status": "REJECTED",
                    "error": "DURABLE_SINGLE_LANE_UNAVAILABLE",
                    "detail": str(_exc),
                    "pre_provider": {
                        "classification": "BLOCKED",
                        "provider_calls": 0,
                        "credit_spend": False,
                        "blocker_code": "DURABLE_SINGLE_LANE_UNAVAILABLE",
                    },
                }
            _lane_lease = None
        if _lane_lease is not None and not _lane_lease.get("acquired"):
            _owner_row = _lane_lease.get("row") or {}
            _JOBS.pop(job_id, None)
            return {
                "status": "REJECTED",
                "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _owner_row.get("job_id"),
                "pre_provider": {
                    "classification": "BLOCKED",
                    "provider_calls": 0,
                    "credit_spend": False,
                    "blocker_code": "VIDEO_JOB_IN_FLIGHT",
                },
            }
        if _lane_lease is not None:
            _JOBS[job_id]["lane_lease"] = _lane_lease.get("row")
        _VIDEO_LANE_JOB = job_id  # cache; the DB lease is the source of truth
    lane = None
    if mode in _VIDEO_MODES:
        plan = _direct_plan
        if capture_requested:
            lane = "CAPTURE_AGENT_DISCOVERY"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["capture_only"] = True
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_reference_contract_capture, mode, prompt,
                    project_id, image_media_ids, image_prompt, aspect, tier,
                    model, duration_s, num_videos, image_model,
                    max_image_attempts, collect_image_variants, product_id,
                    copy_execution_binding,
                )
            )
            return {
                "job_id": job_id, "status": "SUBMITTED", "mode": mode,
                "lane": lane, "capture_class": capture_class,
                "routing_receipt": _routing_receipt,
                "request_id": request_id, "durable": bool(_durable_row),
            }
        if profile_certification_capture_requested:
            lane = "PROFILE_CERTIFICATION_AGENT"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["provider_route"] = "GOOGLE_FLOW_CREATION_AGENT"
            _JOBS[job_id]["provider_generation_type"] = "scene_video_scaffold_then_deterministic_composite"
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_profile_certification_capture, mode, prompt,
                    project_id, image_media_ids, image_prompt, aspect, tier,
                    model, duration_s, num_videos, image_model,
                    max_image_attempts, collect_image_variants, product_id,
                    copy_execution_binding,
                )
            )
            return {
                "job_id": job_id,
                "status": PROFILE_CERTIFICATION_PRE_PROVIDER_STATUS,
                "mode": mode,
                "lane": lane,
                "provider_route": _JOBS[job_id]["provider_route"],
                "profile_digest": _JOBS[job_id].get(
                    "profile_certification_profile_digest"
                ),
                "request_id": request_id,
                "durable": bool(_durable_row),
            }
        if plan["eligible"]:
            lane = "DIRECT_API"
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_generate_direct, mode, prompt, project_id,
                    image_media_ids, aspect, tier, model, duration_s, num_videos,
                    product_id, plan,
                )
            )
            return {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                    "lane": lane, "routing_receipt": _routing_receipt,
                    "product_visual_custody": product_visual_custody,
                    "request_id": request_id, "durable": bool(_durable_row)}
        if _is_certified_hybrid_reference_omni10_plan(plan):
            lane = HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
            _JOBS[job_id]["lane"] = lane
            _JOBS[job_id]["provider_route"] = lane
            _JOBS[job_id]["transport_contract_version"] = (
                HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION
            )
            _JOBS[job_id]["_task"] = asyncio.create_task(
                _run_generate_task(
                    job_id, _run_generate, mode, prompt, project_id,
                    image_media_ids, image_prompt, aspect, tier, model,
                    duration_s, num_videos, image_model, max_image_attempts,
                    collect_image_variants, product_id, copy_execution_binding,
                )
            )
            return {
                "job_id": job_id, "status": "SUBMITTED", "mode": mode,
                "lane": lane, "routing_receipt": _routing_receipt,
                "product_visual_custody": product_visual_custody,
                "request_id": request_id, "durable": bool(_durable_row),
                "surface_lane": _JOBS[job_id].get("surface_lane"),
                "transport_mode": _JOBS[job_id].get("transport_mode"),
                "source_mode": _JOBS[job_id].get("source_mode"),
                "provider_generation_type": _JOBS[job_id].get(
                    "provider_generation_type"
                ),
            }
        lane = "AGENT"
        _JOBS[job_id]["lane"] = lane
        if direct_video_lane_enabled():
            # The flag is on but THIS job could not provably run direct — record
            # why, so the T2V routing decision is auditable per job. Reference
            # jobs are rejected above instead of reaching this fallback.
            _JOBS[job_id]["direct_decline_reason"] = plan["reason"]
    _JOBS[job_id]["_task"] = asyncio.create_task(
        _run_generate_task(
            job_id, _run_generate, mode, prompt, project_id, image_media_ids,
            image_prompt, aspect, tier, model, duration_s, num_videos, image_model,
            max_image_attempts, collect_image_variants, product_id,
            copy_execution_binding,
        )
    )
    return {
        "job_id": job_id,
        "status": "SUBMITTED",
        "mode": mode,
        "lane": lane,
        "routing_receipt": _routing_receipt,
        "product_visual_custody": product_visual_custody,
        "request_id": request_id,
        "durable": bool(_durable_row),
    }


def _reference_run_dropped_reference(refs, model_used):
    """True when a REFERENCE run verifiably fired a TEXT-ONLY generation tool
    (the attached image was dropped) — NOT merely a different image-based engine.

    Captured contract:
      - g_09ced57d5d4b: an attached start image on a T2V-style run fires the r2v
        variant (model_used veo_3_1_r2v_lite); a text-only run fires the plain
        veo_3_1_* key.
      - g_7b29b837c259 (first live F2V, 2026-07-18): a genuine first-frame F2V run
        fires the i2v variant (model_used veo_3_1_i2v_lite).
    BOTH r2v (reference-to-video) and i2v (image-to-video) CONSUME the attached
    image — neither dropped it — so only a plain/t2v veo_3_1 key is a text-only
    fallback. Flagging i2v as "dropped" was a false positive that fail-closed a
    valid F2V generation. Only the veo_3_1 family is captured — other engines
    return None (unverified, flagged upstream) rather than guessed. No refs → None.
    """
    if not refs or not isinstance(model_used, str) or not model_used:
        return None
    mu = model_used.lower()
    if not mu.startswith("veo_3_1"):
        return None  # contract not captured for this engine — never guess
    return not ("r2v" in mu or "i2v" in mu)


async def _durable_media_exclusion() -> set:
    """Every media id BOSMAX has ever recorded (artifacts / results / extend lineage).

    A freshly generated clip can never be in this set, so it is the DOM-independent
    freshness authority for retrieval (SEV-0 fix). Fail-soft: a DB error returns an
    empty set — the DOM snapshot + stale/ref excludes still apply."""
    from agent.db import crud
    try:
        return await crud.list_known_media_ids()
    except Exception:  # noqa: BLE001
        return set()


def _is_flow_media_redirect_url(url: str) -> bool:
    """True for the authenticated Flow tRPC delivery URL, not a signed asset URL."""
    value = str(url or "").strip()
    return value.startswith("/fx/api/trpc/media.getMediaUrlRedirect") or value.startswith(
        "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect"
    )


async def _resolve_media_download_url(client, media_id: str, url: str) -> str:
    """Resolve a Flow-relative image URL through the authenticated extension relay."""
    if url and not _is_flow_media_redirect_url(url):
        return str(url or "")
    resolver = getattr(client, "get_media_download_url", None)
    if not callable(resolver):
        raise RuntimeError("MEDIA_REDIRECT_UNAVAILABLE: extension relay lacks MEDIA_URL_REDIRECT")
    redirect_media_id = str(media_id or "")
    match = re.search(r"[?&]name=([^&#]+)", str(url or ""))
    if match:
        redirect_media_id = unquote(match.group(1))
    resolved = await resolver(redirect_media_id)
    if not isinstance(resolved, dict) or not resolved.get("ok") or not resolved.get("url"):
        status = resolved.get("status") if isinstance(resolved, dict) else None
        raise RuntimeError(
            f"MEDIA_REDIRECT_FAILED: media {media_id} status={status or 'unknown'}"
        )
    return str(resolved["url"])


def _extract_provider_prompt(raw) -> tuple:
    """Normalize the provider-stored media prompt to its EFFECTIVE prompt text.

    Captured live contract (incident manual_faf40cf6 output f0f865d6 + extend
    child 12b526c5 — two independent captures, one consistent envelope): Google
    Flow stores `media.video.prompt` as an XML envelope

        <root><context>…</context><instruction><prompt>{INPUT PROMPT}</prompt>…

    whose inner <prompt> equals the submitted/tool prompt VERBATIM (proven
    lossless). This helper extracts that inner value with REAL XML parsing
    (entity escaping handled by the parser — never string surgery):

      * plain text (no XML envelope)      → ("PLAIN", stripped text)
      * proven envelope, ONE <prompt>     → ("XML_INNER_PROMPT", inner text)
      * malformed XML                     → ("MALFORMED_XML", None)  fail-safe
      * zero or >1 CONFLICTING <prompt>s  → ("AMBIGUOUS_PROMPT_NODES", None)
        (never silently choose between different values)

    No fuzzy matching, no content rewriting — exact text in, exact text out.
    """
    if raw is None:
        return "ABSENT", None
    text = str(raw)
    if "<prompt" not in text or "<instruction" not in text:
        return "PLAIN", text.strip()
    import xml.etree.ElementTree as _ET
    try:
        root = _ET.fromstring(text)
    except _ET.ParseError:
        return "MALFORMED_XML", None
    nodes = root.findall(".//prompt")
    values = {("".join(n.itertext())).strip() for n in nodes}
    values.discard("")
    if len(values) != 1:
        return "AMBIGUOUS_PROMPT_NODES", None
    return "XML_INNER_PROMPT", next(iter(values))


async def _accept_correlated_output(client, candidates, exclude, correlation,
                                    stats) -> tuple:
    """DETERMINISTIC current-run output binding (PR321/322/323 + Owner Phase-1).

    A candidate media id becomes this run's output ONLY when its OWN media
    resource structurally proves it belongs to THIS submission. Two captured
    live contracts carry the same identity fields: legacy
    ``GET /v1/media/{generation-key}``, and current
    ``flow.projectInitialData`` when ``/v1/media/{delivery UUID}`` returns 400.
    Both expose the generation prompt (XML envelope, inner <prompt> == the exact
    input prompt), model and seed. The current contract then delivers bytes via
    the authenticated ``media.getMediaUrlRedirect`` endpoint.

    Acceptance = the proven composite (Owner-approved contract):
      * current bound project + PROJECT_DRIFT guard (enforced by the caller);
      * candidate absent from the pre-submit snapshot and every stale/reference/
        DB-known exclusion (defensive prefilter — never the sole authority);
      * NORMALIZED provider prompt (see _extract_provider_prompt) equals the
        exact prompt THIS run fired — the SSE tool prompt when captured, else
        the submitted block-1 prompt. Raw XML markup is NEVER compared;
      * a CONFIRMED model mismatch (both sides known) rejects the candidate;
      * seed must match ONLY when BOTH sides expose a usable seed (live SSE may
        omit it — the media seed is then recorded as evidence, never used to
        manufacture a link the submit never exposed, and never a reason to
        reject the otherwise-proven composite).

    A finished video with NO prompt metadata, malformed XML or ambiguous
    prompt nodes is counted `unverifiable` with the precise normalization path
    recorded — never accepted, never guessed.

    Returns (media_id, mp4_path, size_mb, evidence) or (None, None, None, None).
    """
    import base64
    anchors = [str(a).strip() for a in (correlation.get("sse_prompt"),
                                        correlation.get("submitted_prompt")) if a]
    gen_seed = _seed_value(correlation.get("seed"))
    project_id = (
        correlation.get("_project_id") if isinstance(correlation, dict) else None
    )
    stats.setdefault("media_fetch_errors", 0)
    stats.setdefault("media_fetch_error_ids", [])
    stats.setdefault("media_fetch_error_statuses", {})
    stats.setdefault("media_not_ready", 0)
    stats.setdefault("media_not_ready_ids", [])
    stats.setdefault("project_metadata_fallbacks", 0)
    stats.setdefault("project_metadata_fallback_ids", [])
    stats.setdefault("media_download_errors", 0)
    stats.setdefault("media_download_error_ids", [])
    stats["round_rejected_ids"] = []  # per-call: completed-but-identity-rejected
    project_media_by_id = None
    for mid in dict.fromkeys(candidates):  # de-dupe, keep order
        if mid in exclude:
            continue
        media_error_status = None
        try:
            media = await client.get_media(mid)
        except Exception:
            media = None
            media_error_status = "exception"
        media_status = media.get("status") if isinstance(media, dict) else None
        if ((isinstance(media, dict) and media.get("error"))
                or (isinstance(media_status, int) and media_status >= 400)):
            media_error_status = (
                media_status if isinstance(media_status, int) else "error")
        from_project_metadata = False
        if media_error_status is not None:
            # Preserve a compact retrieval trace without storing response bodies
            # or signed URLs in job telemetry.
            stats["media_fetch_errors"] += 1
            if mid not in stats["media_fetch_error_ids"]:
                stats["media_fetch_error_ids"].append(mid)
            stats["media_fetch_error_statuses"][mid] = media_error_status

            # Current Flow agent clips are delivery UUIDs. Their exact identity
            # lives in the authenticated project payload even though the legacy
            # /v1/media lookup rejects that UUID. Read the project once per poll,
            # keep the same prompt/model/seed guard, and never accept freshness
            # alone as correlation.
            lister = getattr(client, "list_project_media", None)
            if project_id and callable(lister):
                if project_media_by_id is None:
                    try:
                        snapshot = await lister(project_id)
                    except Exception:  # noqa: BLE001 — keep polling with telemetry
                        snapshot = {"media": [], "error": "exception"}
                    observed_project_id = str(snapshot.get("project_id") or "").strip()
                    if observed_project_id and observed_project_id != str(project_id):
                        stats["project_metadata_error"] = "PROJECT_DRIFT"
                        project_media_by_id = {}
                    else:
                        project_media_by_id = {
                            str(item.get("name")): item
                            for item in (snapshot.get("media") or [])
                            if isinstance(item, dict) and item.get("name")
                        }
                        if snapshot.get("error"):
                            stats["project_metadata_error"] = str(snapshot["error"])
                fallback = project_media_by_id.get(str(mid))
                if fallback:
                    media = {"status": 200, "data": fallback}
                    from_project_metadata = True
                    stats["project_metadata_fallbacks"] += 1
                    if mid not in stats["project_metadata_fallback_ids"]:
                        stats["project_metadata_fallback_ids"].append(mid)
            if not from_project_metadata:
                continue
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        generation_status = _deep(mdata, "mediaGenerationStatus")
        if from_project_metadata and generation_status != "MEDIA_GENERATION_STATUS_SUCCESSFUL":
            stats["media_not_ready"] += 1
            if mid not in stats["media_not_ready_ids"]:
                stats["media_not_ready_ids"].append(mid)
            continue
        video_meta = mdata.get("video") if isinstance(mdata, dict) else None
        video_meta = video_meta if isinstance(video_meta, dict) else {}
        if isinstance(video_meta.get("generatedVideo"), dict):
            video_meta = video_meta["generatedVideo"]
        if not enc and not from_project_metadata:
            stats["media_not_ready"] += 1
            if mid not in stats["media_not_ready_ids"]:
                stats["media_not_ready_ids"].append(mid)
            continue  # not a finished video (or not a video resource at all)
        norm_path, vprompt = _extract_provider_prompt(video_meta.get("prompt"))
        vmodel = video_meta.get("model")
        if vprompt is None:
            # No usable prompt metadata (absent / malformed XML / ambiguous
            # nodes) — it can NEVER be bound to this run; record the precise
            # normalization evidence so the job fails closed with proof.
            stats["unverifiable"] += 1
            if mid not in stats["unverifiable_ids"]:
                stats["unverifiable_ids"].append(mid)
            stats.setdefault("normalization_failures", {})[mid] = norm_path
            stats["round_rejected_ids"].append(mid)
            continue
        if vprompt not in anchors:
            stats["prompt_mismatched"] += 1  # another run's output — never ours
            stats["round_rejected_ids"].append(mid)
            continue
        expected_model = correlation.get("expected_model")
        if expected_model and vmodel and str(vmodel) != str(expected_model):
            stats["model_mismatched"] += 1
            stats["round_rejected_ids"].append(mid)
            continue
        media_seed = _seed_value(video_meta.get("seed"))
        if gen_seed is not None:
            # Both sides must agree when the approved SSE exposed a seed.
            if media_seed is None or media_seed != gen_seed:
                stats["seed_mismatched"] += 1
                stats["round_rejected_ids"].append(mid)
                continue
        retrieval_source = "get_media"
        if enc:
            vbytes = base64.b64decode(enc)
        else:
            try:
                vbytes, retrieval_source = await _download_video_bytes(
                    client, mid, None)
            except Exception:  # noqa: BLE001 — keep the bounded retrieval trace
                stats["media_download_errors"] += 1
                if mid not in stats["media_download_error_ids"]:
                    stats["media_download_error_ids"].append(mid)
                continue
        outdir = OUTPUT_DIR / "retrieved"
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(vbytes)
        sse_anchor = str(correlation.get("sse_prompt") or "").strip()
        evidence = {
            "media_id": mid,
            "matched_on": ("sse_tool_prompt" if sse_anchor and vprompt == sse_anchor
                           else "submitted_prompt"),
            "prompt_normalization": norm_path,
            "media_model": vmodel,
            "media_seed": video_meta.get("seed"),
            "gen_seed": correlation.get("seed"),
            "seed_matched": (True if gen_seed is not None
                             else "EVIDENCE_ONLY_SSE_SEED_ABSENT"),
            "tool_call_id": correlation.get("tool_call_id"),
            "response_id": correlation.get("response_id"),
            "metadata_source": ("project_initial_data" if from_project_metadata
                                else "get_media"),
            "retrieval_source": retrieval_source,
        }
        # The extension's authenticated harvest is the source of truth for the
        # provider generation resource. Do not substitute the delivery tile
        # UUID when the provider identity is absent.
        provider_operation_id = (
            getattr(client, "_media_generation_ids", {}) or {}
        ).get(str(mid))
        if provider_operation_id:
            evidence["provider_operation_id"] = str(provider_operation_id)
            evidence["media_generation_id"] = str(provider_operation_id)
            evidence["provider_operation_id_source"] = (
                "GOOGLE_FLOW_MEDIA_GENERATION_ID"
            )
        return mid, str(path), round(len(vbytes) / 1024 / 1024, 2), evidence
    return None, None, None, None


def _seed_value(raw):
    """Normalize a generation seed for exact comparison (int when possible;
    None for absent/unusable values — never a coincidental string match)."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        s = str(raw).strip()
        return s or None


# Retrieval-phase failure markers (false-negative fix). A failure carrying one of these AFTER the
# agent approved a video and rendering started is a RETRIEVAL/harvest failure: the video was
# likely generated (credits likely spent) but could not be fetched locally. Such a job must be
# reported as GENERATED_BUT_UNRETRIEVED, never as a plain generation FAILED.
_RETRIEVAL_PHASE_MARKERS = (
    "EDITOR_TAB_LOST", "TAB_DRIFT", "PROJECT_DRIFT", "OUTPUT_CORRELATION_UNAVAILABLE",
    "CURRENT_OUTPUT_IDENTITY_MISMATCH", "OUTPUT_IDENTITY_NOT_CAPTURED",
    "video not found/retrieved in time")

# Fast-failure bound (Owner Phase-1): once the SAME non-empty set of COMPLETED
# candidates has been rejected for deterministic identity reasons this many polls
# in a row (their stored metadata can never change), stop early with precise
# evidence instead of blind-polling to the 12-minute ceiling. Rendering-in-
# progress never trips this: a still-rendering output is not a completed
# candidate, and any NEW completed candidate changes the set and resets the run.
_IDENTITY_MISMATCH_FASTFAIL_ROUNDS = 3
_IDENTITY_MISMATCH_MIN_TRIES = 6  # never before ~4.5 min total (120s + 6 polls)


def _is_retrieval_phase_error(msg) -> bool:
    return any(m in (msg or "") for m in _RETRIEVAL_PHASE_MARKERS)


def _terminal_agent_failure_error(classification: str | None) -> str | None:
    """Map a terminal Flow-agent reply to one stable operator-facing error."""
    if classification == "REFERENCE_IMAGE_MISSING":
        return (
            "FAILED_REFERENCE_IMAGE_MISSING: the Flow agent cannot access the start "
            "image — re-upload the product image and resubmit (do NOT just regenerate)"
        )
    if classification == agent_video.SAFETY_FILTERED:
        return (
            "FAILED_PROVIDER_SAFETY_FILTER: Google Flow rejected the prompt under its "
            "prominent-people safety policy. Recompile with the creator attribution "
            "removed; do not auto-retry the same prompt"
        )
    if classification == "RENDER_FAILED":
        return (
            "FAILED_RENDER_REPORTED_BY_AGENT: the Flow agent reports the generation "
            "failed server-side — safe to resubmit only after the prompt/cause is fixed"
        )
    return None


def _zero_completed_candidates(stats) -> bool:
    """True only when the poll window PROVABLY evaluated no completed candidate.

    Every completed candidate the retrieval loop examines leaves a trace in
    corr_stats (a deterministic-mismatch counter, an unverifiable entry, or a
    round_rejected id). All traces empty ⇒ nothing finished ever appeared.
    Unknown/absent stats ⇒ False — the conservative caller keeps the
    credits-likely-spent classification.
    """
    if not isinstance(stats, dict):
        return False
    if (stats.get("round_rejected_ids") or stats.get("unverifiable_ids")
            or stats.get("media_fetch_errors")):
        return False
    return not any(stats.get(k) for k in (
        "prompt_mismatched", "model_mismatched", "seed_mismatched", "unverifiable"))


# C-4: ONE structured credit vocabulary, shared verbatim with
# video_production_orchestrator (NOT_SPENT / MAY_HAVE_SPENT / SPENT / UNKNOWN) so
# the two lanes can never disagree about what a word means. Mirrored rather than
# imported to keep make_video free of orchestrator imports.
CREDIT_NOT_SPENT, CREDIT_MAY_HAVE_SPENT, CREDIT_SPENT, CREDIT_UNKNOWN = (
    "NOT_SPENT", "MAY_HAVE_SPENT", "SPENT", "UNKNOWN")


def _stamp_credit(job: dict, state: str) -> None:
    """Record the credit verdict on a TERMINAL job, truthfully.

    C-4: `credit_spent_likely` used to be written in exactly ONE place — the
    GENERATED_BUT_UNRETRIEVED recovery path — so every other terminal state
    (including a DONE job that delivered a real paid video) reported the field
    as False. Read as a ledger that produced a flat lie: live job
    g_edf503991e7c bound an 8s 720x1280 mp4 and still reported
    credit_spent_likely=False.

    Every terminal outcome now carries an explicit `credit_state`, and
    `credit_spent_likely` is DERIVED from it so existing readers (the queue's
    binding outcome, OperatorPage) stay correct instead of silently wrong.
    `SPENT` is still reserved for authoritative debit evidence (a real balance
    decrease), exactly as the orchestrator defines it — a delivered artifact
    proves the provider did the work, not what the account was charged.
    """
    job["credit_state"] = state
    job["credit_spent_likely"] = state in (CREDIT_SPENT, CREDIT_MAY_HAVE_SPENT)


def _apply_post_approval_failure(job: dict, msg: str) -> None:
    """Terminal classification of a post-approval, retrieval-phase failure.

    B-15: GENERATED_BUT_UNRETRIEVED exists so a paid, completed video is never
    presented as "no video" — but it also fired when the render never
    materialized at all (live g_99daae472362: zero completed candidates in the
    whole window, no media with this run's dialogue 15+ min later), claiming
    credit_spent_likely=True and promising a harvest of a video that does not
    exist. The plain not-found timeout with a provably-empty candidate record
    is now RENDER_NOT_MATERIALIZED with credit UNCERTAIN. Any evidence a
    completed candidate existed — or no stats at all (e.g. tab lost mid-poll)
    — keeps the existing conservative classification.
    """
    if "CURRENT_OUTPUT_IDENTITY_MISMATCH" in (msg or ""):
        # The candidates were deterministically rejected as stale/foreign. They
        # are not evidence that THIS run rendered, so they cannot use the
        # GENERATED_BUT_UNRETRIEVED success-like accounting contract.
        job.update(status="STALE_OR_FOREIGN_CANDIDATES_ONLY",
                   stage="stale_or_foreign_candidates_only",
                   artifact=None, media_id=None, local_path=None,
                   recovery_required=True,
                   recovery_hint=("verify the Flow project media list — only stale or "
                                  "foreign completed candidates were observed; do not "
                                  "assume this run produced a video"),
                   original_error=msg, error=msg)
        _stamp_credit(job, CREDIT_UNKNOWN)
        return
    if ("video not found/retrieved in time" in (msg or "")
            and _zero_completed_candidates(job.get("correlation_stats"))):
        job.update(status="RENDER_NOT_MATERIALIZED", stage="render_not_materialized",
                   artifact=None, media_id=None, local_path=None,
                   recovery_required=True,
                   recovery_hint=("verify the Flow project media list — no completed "
                                  "candidate for this run ever appeared; do not assume "
                                  "a video exists"),
                   original_error=msg, error=msg)
        _stamp_credit(job, CREDIT_UNKNOWN)
        return
    job.update(status="GENERATED_BUT_UNRETRIEVED", stage="generated_but_unretrieved",
               artifact=None, media_id=None, local_path=None,
               recovery_required=True,
               recovery_hint="open Flow project and harvest/download existing video",
               original_error=msg, error=msg)
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)


# The anchors _accept_correlated_output can actually bind an output with. Any ONE
# of them is enough to make a candidate decidable; NONE of them means the run is
# unverifiable no matter what is retrieved.
_IDENTITY_ANCHORS = ("sse_prompt", "seed", "expected_model", "tool_call_id")


_IDENTITY_GAP_SSE_LIMIT = 20000


def _last_approve_sse(nres) -> str | None:
    """The raw SSE of the LAST negotiation turn (the approve stream).

    negotiate_and_generate returns a transcript carrying raw_sse per turn, but the
    generate lane discarded it — so when identity capture failed there was nothing
    left to diagnose from and the only way forward was another paid run. Truncated:
    this is a breadcrumb, not an archive.
    """
    transcript = nres.get("transcript") if isinstance(nres, dict) else None
    if not isinstance(transcript, list) or not transcript:
        return None
    last = transcript[-1]
    raw = last.get("raw_sse") if isinstance(last, dict) else None
    return str(raw)[:_IDENTITY_GAP_SSE_LIMIT] if raw else None


def _identity_captured(identity) -> bool:
    """True when the submission exposed at least one correlation anchor.

    False is not a failure of retrieval — it means binding was impossible from the
    moment the generation fired, so the run must fail closed with
    OUTPUT_IDENTITY_NOT_CAPTURED rather than blame the polling window.
    """
    if not isinstance(identity, dict):
        return False
    return any(identity.get(k) not in (None, "") for k in _IDENTITY_ANCHORS)


# ─── Direct API-first video lane (ADR-007 recommit, flag-gated) ─────────────
#
# The agent lane's retrieval is DOM-blind: it detects a finished video ONLY via
# the extension's DOM harvest, so a labs.google React crash (error boundary,
# tiles unmounted) makes a finished, PAID video unretrievable and the job times
# out with empty results. This lane re-commits to the direct batchAsync RPCs the
# SDK/worker already runs: submit -> operation handles -> poll
# batchCheckAsyncVideoGenerationStatus -> mediaId/fifeUrl from the poll's OWN
# metadata -> bytes -> generated_artifact. Zero DOM after submit; the operation
# handle deterministically binds the output to THIS run (no prompt-matching
# heuristics needed). Kill-switch defaults OFF; anything the direct lane cannot
# PROVABLY honor (explicit model without a captured key, unproven count/duration)
# rejects a reference-bearing request before provider approval; pure T2V alone may
# continue on the conversational lane (USER SETTINGS ARE LAW).

def direct_video_lane_enabled() -> bool:
    """Kill-switch for routing canonical video jobs onto the direct lane
    (default OFF), mirroring the NATIVE_EXTEND_ENABLED pattern."""
    return os.environ.get("DIRECT_VIDEO_LANE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


def direct_capture_enabled() -> bool:
    """Kill-switch for the one-shot live-capture branch (default OFF). Separate
    from the routing flag so the contract capture can run while general routing
    stays off."""
    return os.environ.get("DIRECT_VIDEO_CAPTURE_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


def _direct_poll_timeout() -> int:
    """Seconds to poll batchCheckAsyncVideoGenerationStatus before declaring the
    render unretrieved (operations stay re-pollable for recovery)."""
    try:
        return max(60, int(os.environ.get("DIRECT_VIDEO_POLL_TIMEOUT", "900")))
    except (TypeError, ValueError):
        return 900


_DIRECT_VIDEO_ASPECT = {
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
}

# fifeUrl delivery hosts proven for Flow media (mirrors FlowClient._SAFE_URL_RE);
# anything else falls back to the authenticated zero-credit get_media fetch.
_DIRECT_FIFE_URL_RE = re.compile(
    r"^https://(?:storage\.googleapis\.com|lh3\.googleusercontent\.com|"
    r"(?:[a-z0-9-]+\.)?flow-content\.google)/", re.I)


def _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                      ref_count, num_videos, require_flag=True,
                      surface_lane: str | None = None,
                      provider_profile: dict | None = None,
                      shared_8s_bootstrap_authorized: bool = False) -> dict:
    """Decide whether a job may run on the direct batchAsync lane.

    Fail-closed: any setting the direct lane cannot PROVABLY honor returns an
    explicit reason. The one captured Hybrid Omni 10s tuple is represented as
    a certified *agent* route here, never as a direct-plan eligibility result.
    ``start_generate`` rejects every other reference-bearing decline before
    provider approval. Returns
    {"eligible": bool, "reason": str|None, "rpc": "r2v"|"start_frame",
     "gen_type": str, "aspect_enum": str, "video_model_key": str|None,
     "model_key_source": str}.
    """
    def _decline(reason):
        return {"eligible": False, "reason": reason}

    if mode not in _VIDEO_MODES:
        return _decline("NOT_A_VIDEO_MODE")
    shared_8s_profile = _resolve_shared_reference_8s_profile(
        mode=mode,
        source_mode=source_mode,
        model=model,
        duration_s=duration_s,
        aspect=aspect,
        ref_count=ref_count,
        num_videos=num_videos,
        provider_profile=provider_profile,
    )
    if shared_8s_profile and shared_8s_bootstrap_authorized:
        return {
            "eligible": False,
            "reason": SHARED_REFERENCE_VEO_8S_BOOTSTRAP_ROUTE,
            "execution_route": SHARED_REFERENCE_VEO_8S_BOOTSTRAP_ROUTE,
            "rpc": "agent_stream_chat",
            "gen_type": SHARED_REFERENCE_VEO_8S_PROVIDER_GENERATION_TYPE,
            "provider_generation_type": SHARED_REFERENCE_VEO_8S_PROVIDER_GENERATION_TYPE,
            "provider_tool": "generate_video_with_references",
            "provider_model_usage_key": SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY,
            "contract_version": SHARED_REFERENCE_VEO_8S_CONTRACT_VERSION,
            "provider_profile": shared_8s_profile,
            "provider_profile_id": shared_8s_profile["profile_id"],
            "provider_profile_digest": shared_8s_profile["provider_profile_digest"],
            "provider_profile_status": shared_8s_profile["certification_status"],
            "provider_profile_evidence_id": shared_8s_profile.get(
                "certification_evidence_id"
            ),
        }
    if hybrid_reference_omni10_route_matches(
        mode,
        source_mode,
        model,
        duration_s,
        aspect,
        ref_count,
        num_videos,
        surface_lane,
    ):
        return _certified_hybrid_reference_omni10_plan()
    if mode in ("F2V", "I2V") and ref_count >= 1:
        try:
            if int(duration_s) == 10:
                # Certification truth must win over the feature flag: a 10s
                # reference request is never allowed to degrade to an 8s
                # agent/default route when direct transport is disabled.
                return _decline(DIRECT_10S_CONTRACT_NOT_CERTIFIED)
        except (TypeError, ValueError):
            pass
    if require_flag and not direct_video_lane_enabled():
        return _decline("DIRECT_LANE_DISABLED")
    if mode == "T2V":
        # No direct text-only RPC has been captured (no batchAsync T2V endpoint
        # exists in config); T2V stays on the conversational agent lane.
        return _decline("NO_DIRECT_T2V_RPC")
    aspect_enum = _DIRECT_VIDEO_ASPECT.get(str(aspect or "").strip())
    if not aspect_enum:
        return _decline(f"DIRECT_ASPECT_UNSUPPORTED:{aspect}")
    if int(num_videos or 1) != 1:
        # requests[] batch replication is not yet live-captured; a multi-count
        # job must keep its full count on the agent lane, never be clamped.
        return _decline("DIRECT_COUNT_UNPROVEN")
    if ref_count < 1:
        return _decline("DIRECT_NEEDS_REFERENCE")
    sm = str(source_mode or "").strip().upper()
    if mode == "F2V" and sm == "HYBRID":
        # HYBRID = one product reference composed into a new scene (r2v) — NOT a
        # start frame; there is no separate "Hybrid" RPC.
        rpc, gen_type = "r2v", "reference_frame_2_video"
    elif mode == "F2V" and sm == "FRAMES":
        rpc = "start_frame"
        gen_type = "start_end_frame_2_video" if ref_count >= 2 else "frame_2_video"
    elif mode == "F2V":
        # F2V without a declared source_mode is ambiguous: a logical-HYBRID job
        # routed to the start-frame RPC would CHANGE semantics (the product
        # photo becomes frame 1 instead of a composed reference). Callers that
        # do not thread source_mode (bulk/queue lanes) are rejected before
        # provider approval.
        return _decline("DIRECT_F2V_SOURCE_MODE_UNKNOWN")
    else:  # I2V — ingredient references compose the video (r2v)
        rpc, gen_type = "r2v", "reference_frame_2_video"
    video_model_key = None
    model_key_source = "models.json default (tier, gen_type, aspect)"
    if model:
        try:
            spec = video_models.resolve(model)
        except ValueError:
            # Unknown model must surface through the canonical fail-closed path;
            # never fire an unproven direct request.
            return _decline(f"DIRECT_MODEL_UNKNOWN:{model}")
        table = DIRECT_VIDEO_MODEL_KEYS.get(spec["key"]) or {}
        video_model_key = (table.get(gen_type) or {}).get(aspect_enum)
        if not video_model_key:
            return _decline(f"DIRECT_MODEL_KEY_UNPROVEN:{spec['key']}")
        model_key_source = f"direct_video_model_keys[{spec['key']}]"
    if duration_s is not None:
        try:
            normalized_duration = int(duration_s)
        except (TypeError, ValueError):
            return _decline(f"DIRECT_DURATION_UNPROVEN:{duration_s}")
        if normalized_duration == 10:
            # The direct submit contract has never captured a 10s request.  Keep
            # this as a stable machine-readable readiness blocker instead of
            # treating the provider's 8s default as a silent 10s success.
            return _decline(DIRECT_10S_CONTRACT_NOT_CERTIFIED)
        if normalized_duration != 8:
            # The captured submit contract carries no duration field; only the
            # Veo 8s default is provably delivered. Anything else is rejected
            # for a reference-bearing request before provider approval.
            return _decline(f"DIRECT_DURATION_UNPROVEN:{duration_s}")
    direct_profile = None
    if model:
        # A captured videoModelKey is transport evidence, not a lane-specific
        # provider certification. The exact direct route must also have one
        # shared duration/model profile proof; that proof is reusable by every
        # eligible lane with the same profile digest.
        from agent.services import video_execution_profile_service as _profiles

        try:
            direct_profile = _profiles.resolve_duration_model_profile(
                model=spec["key"],
                duration_s=normalized_duration if duration_s is not None else 8,
                aspect_ratio=aspect,
                audio_dialogue_route=_profiles.DEFAULT_AUDIO_DIALOGUE_ROUTE,
                provider_transport_key_provenance=model_key_source,
                transport_route=f"GOOGLE_FLOW_DIRECT:{gen_type}:{aspect_enum}",
                logical_mode=mode,
                source_mode=sm,
            )
            profile_status = _profiles.provider_certification_status(direct_profile)
        except _profiles.ExecutionProfileError as exc:
            return _decline(f"DIRECT_PROFILE_UNPROVEN:{exc.code}")
        if not profile_status.get("certified"):
            return _decline(
                f"DIRECT_PROFILE_UNCERTIFIED:{profile_status.get('reason')}"
            )
    return {"eligible": True, "reason": None, "rpc": rpc, "gen_type": gen_type,
            "aspect_enum": aspect_enum, "video_model_key": video_model_key,
            "model_key_source": model_key_source,
            "duration_model_profile": direct_profile}


def direct_video_readiness(
    mode: str | None = None,
    *,
    source_mode: str | None = None,
    model: str | None = None,
    duration_s: int | None = None,
    aspect: str = "9:16",
    ref_count: int = 1,
    num_videos: int = 1,
) -> dict:
    """Return provider-free video-route readiness and certification state.

    This is deliberately a pure readiness surface: it does not bind Flow,
    inspect the extension, resolve a project, or call a provider.  A readiness
    response may therefore be safely shown before approval.  The certified
    conversational Hybrid Omni 10s tuple is ready independently of the direct
    batchAsync feature flag; all other unproven combinations remain explicit
    blockers.
    """
    normalized_mode = (mode or "F2V").strip().upper()
    normalized_duration = duration_s
    plan = _direct_lane_plan(
        normalized_mode,
        source_mode,
        model,
        normalized_duration,
        aspect,
        ref_count=max(0, int(ref_count or 0)),
        num_videos=max(1, int(num_videos or 1)),
        require_flag=False,
    )
    certified_agent_route = _is_certified_hybrid_reference_omni10_plan(plan)
    blockers: list[dict[str, str]] = []
    reason = str(plan.get("reason") or "")
    if reason and not certified_agent_route:
        blockers.append({
            "code": reason.split(":", 1)[0],
            "detail": reason,
            "stage": "PRE_PROVIDER",
        })
    if not direct_video_lane_enabled() and not certified_agent_route:
        blockers.append({
            "code": "DIRECT_LANE_DISABLED",
            "detail": "DIRECT_VIDEO_LANE_ENABLED is not enabled",
            "stage": "PRE_PROVIDER",
        })
    # Always publish the independent 10s certification state.  A caller asking
    # for another duration must not make the 10s contract appear certified.
    ten_second_plan = _direct_lane_plan(
        normalized_mode,
        source_mode,
        model,
        10,
        aspect,
        ref_count=max(0, int(ref_count or 0)),
        num_videos=max(1, int(num_videos or 1)),
        require_flag=False,
    )
    ten_second_certified = _is_certified_hybrid_reference_omni10_plan(ten_second_plan)
    ten_second_blocker = (
        None if ten_second_certified else DIRECT_10S_CONTRACT_NOT_CERTIFIED
    )
    route_ready = bool(
        certified_agent_route
        or (plan.get("eligible") and direct_video_lane_enabled())
    )
    selected_route = (
        HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
        if certified_agent_route
        else "DIRECT_API"
        if plan.get("eligible") and direct_video_lane_enabled()
        else "BLOCKED"
    )
    return {
        "contract_version": DIRECT_VIDEO_READINESS_CONTRACT_VERSION,
        "provider_calls": 0,
        "credit_spend": False,
        "live_capture_required": not certified_agent_route,
        "mode": normalized_mode,
        "source_mode": str(source_mode or "").strip().upper() or None,
        "model": model,
        "duration_s": normalized_duration,
        "aspect": aspect,
        "reference_count": max(0, int(ref_count or 0)),
        "num_videos": max(1, int(num_videos or 1)),
        "eligible": route_ready,
        "selected_route": selected_route,
        "plan": plan,
        "provider_profile_id": plan.get("provider_profile_id"),
        "provider_profile_digest": plan.get("provider_profile_digest"),
        "provider_profile_status": plan.get("provider_profile_status"),
        "provider_profile_evidence_id": plan.get("provider_profile_evidence_id"),
        "blockers": blockers,
        "certified_agent_route": {
            "status": "READY" if certified_agent_route else "NOT_APPLICABLE",
            "selected_route": (
                HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
                if certified_agent_route
                else None
            ),
            "contract_version": (
                HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION
                if certified_agent_route
                else None
            ),
            "provider_tool": (
                HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL
                if certified_agent_route
                else None
            ),
            "provider_model_usage_key": (
                HYBRID_REFERENCE_OMNI_10S_PROVIDER_MODEL_KEY
                if certified_agent_route
                else None
            ),
            "provider_generation_type": (
                HYBRID_REFERENCE_OMNI_10S_PROVIDER_GENERATION_TYPE
                if certified_agent_route
                else None
            ),
            "provider_profile_id": (
                plan.get("provider_profile_id") if certified_agent_route else None
            ),
            "provider_profile_digest": (
                plan.get("provider_profile_digest") if certified_agent_route else None
            ),
            "provider_profile_status": (
                plan.get("provider_profile_status") if certified_agent_route else None
            ),
            "provider_calls": 0,
            "credit_spend": False,
        },
        "ten_second": {
            "duration_s": 10,
            "status": "READY" if ten_second_certified else "NOT_CERTIFIED",
            "blocker_code": ten_second_blocker,
            "provider_calls": 0,
            "selected_route": (
                HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
                if ten_second_certified
                else "BLOCKED"
            ),
            "contract_version": (
                HYBRID_REFERENCE_OMNI_10S_CONTRACT_VERSION
                if ten_second_certified
                else None
            ),
            "provider_profile_id": (
                ten_second_plan.get("provider_profile_id")
                if ten_second_certified else None
            ),
            "provider_profile_digest": (
                ten_second_plan.get("provider_profile_digest")
                if ten_second_certified else None
            ),
            "provider_profile_status": (
                ten_second_plan.get("provider_profile_status")
                if ten_second_certified else None
            ),
        },
    }


async def _direct_submit(client, plan, refs, prompt, project_id, tier, seed,
                         scene_id) -> dict:
    """Fire the ONE direct submit the plan selected. Returns the raw response."""
    if plan["rpc"] == "r2v":
        return await client.generate_video_from_references(
            refs, prompt, project_id, scene_id,
            aspect_ratio=plan["aspect_enum"], user_paygate_tier=tier,
            video_model_key=plan.get("video_model_key"), seed=seed)
    return await client.generate_video(
        refs[0], prompt, project_id, scene_id,
        aspect_ratio=plan["aspect_enum"],
        end_image_media_id=(refs[1] if len(refs) > 1 else None),
        user_paygate_tier=tier,
        video_model_key=plan.get("video_model_key"), seed=seed)


def _direct_response_data(response: dict) -> dict:
    """Unwrap relay/provider data envelopes without assuming one fixed depth."""
    data = response if isinstance(response, dict) else {}
    # The extension relay may return ``{id,status,data:<provider>}``, while
    # provider responses can themselves carry ``data:{media/workflows}``.
    # Unwrap only bounded dictionaries; never walk arbitrary response values.
    for _ in range(3):
        nested = data.get("data") if isinstance(data, dict) else None
        if not isinstance(nested, dict):
            break
        data = nested
    return data


def _direct_media_status(media: dict) -> str:
    """Read the current media-generation status from either known nesting."""
    if not isinstance(media, dict):
        return ""
    status = media.get("mediaStatus")
    if not isinstance(status, dict):
        status = (media.get("mediaMetadata") or {}).get("mediaStatus")
    return str((status or {}).get("mediaGenerationStatus") or "")


def _direct_media_entries(response: dict) -> list[dict]:
    data = _direct_response_data(response)
    return [m for m in (data.get("media") or []) if isinstance(m, dict)]


def _extract_direct_media_targets(response: dict, project_id: str) -> list[dict]:
    """Extract the current Flow media-status poll targets from a submit.

    Current ``batchAsyncGenerateVideoReferenceImages`` responses expose
    ``data.media[].name`` and ``data.workflows[].metadata.primaryMediaId``;
    they do not expose the legacy ``data.operations`` list.  The status RPC
    accepts only the media name and project id, so keep this target deliberately
    small and free of provider response payloads.
    """
    data = _direct_response_data(response)
    media = data.get("media") if isinstance(data.get("media"), list) else []
    workflows = data.get("workflows") if isinstance(data.get("workflows"), list) else []

    targets = []
    seen = set()
    for item in media:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            workflow_id = item.get("workflowId")
            name = next(
                (
                    (w.get("metadata") or {}).get("primaryMediaId")
                    for w in workflows
                    if isinstance(w, dict) and w.get("name") == workflow_id
                ),
                None,
            )
        name = str(name or "").strip()
        pid = str(item.get("projectId") or project_id or "").strip()
        if not name or not pid or name in seen:
            continue
        seen.add(name)
        targets.append({"name": name, "projectId": pid})

    # A future response may expose only workflows.  The primary media id is
    # still a valid status target, so preserve it when there is no media list.
    if not targets:
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            name = str((workflow.get("metadata") or {}).get("primaryMediaId") or "").strip()
            pid = str(project_id or "").strip()
            if name and pid and name not in seen:
                seen.add(name)
                targets.append({"name": name, "projectId": pid})
    return targets


def _extract_direct_submission(response: dict, project_id: str) -> tuple[list[dict], list[dict]]:
    """Return legacy operation handles and/or current media poll targets."""
    from agent.sdk.services.operations import _extract_operations
    operations = _extract_operations(response)
    return operations, _extract_direct_media_targets(response, project_id)


async def _poll_direct_media_targets(client, targets: list[dict], timeout: int) -> dict:
    """Poll the current Flow ``{"media": [...]}`` status contract.

    This path is intentionally separate from ``_poll_operations``: sending a
    media target through the legacy ``{"operations": [...]}`` body returns an
    empty/non-terminal response from the provider and loses the accepted render.
    """
    if not targets:
        return {"error": "No media targets to poll"}
    from agent.sdk.services import operations as sdk_operations

    try:
        interval = max(0.0, float(sdk_operations.VIDEO_POLL_INTERVAL))
    except (TypeError, ValueError):
        interval = 15.0
    elapsed = 0.0
    target_names = {str(t.get("name")) for t in targets if t.get("name")}
    while elapsed < timeout:
        if interval:
            await asyncio.sleep(interval)
            elapsed += interval
        else:
            # Test/failsafe configurations may set a zero interval.  Advance a
            # logical second so a permanently pending provider cannot spin.
            elapsed += 1.0
        try:
            status_result = await client.check_video_status_by_media(targets)
        except Exception:  # noqa: BLE001 — transient relay failures stay pollable
            continue
        if not isinstance(status_result, dict) or status_result.get("error"):
            continue
        entries = _direct_media_entries(status_result)
        by_name = {str(m.get("name")): m for m in entries if m.get("name")}
        failed = [
            (name, _direct_media_status(by_name[name]))
            for name in target_names
            if name in by_name
            and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_FAILED"
        ]
        if failed:
            return {"error": f"Media generation failed: {failed[0][0]}"}
        if target_names and all(
                name in by_name
                and _direct_media_status(by_name[name]) == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
                for name in target_names):
            return {"data": _direct_response_data(status_result)}
    return {"error": f"Polling timeout after {timeout}s"}


def _direct_media_url(media: dict) -> str | None:
    """Find a provider delivery URL without trusting it until host validation."""
    if not isinstance(media, dict):
        return None
    for key in ("fifeUrl", "servingUri", "downloadUrl", "url", "servingUrl"):
        value = _deep(media, key)
        if value:
            return str(value).strip()
    return None


def _direct_media_generation_id(media: dict) -> str | None:
    """Extract the v1 media resource key when the status payload exposes it."""
    if not isinstance(media, dict):
        return None
    for key in ("mediaGenerationId", "media_generation_id", "generationId", "clipId"):
        value = _deep(media, key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("id")
        if value:
            return str(value).strip()
    return None


async def _download_from_direct_url(url: str, source: str) -> tuple | None:
    if not url or not _DIRECT_FIFE_URL_RE.match(url):
        return None
    try:
        import aiohttp
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    if data and len(data) > 1024:
                        return data, source
    except Exception:  # noqa: BLE001 — authenticated fallbacks remain available
        pass
    return None


async def _download_video_bytes(client, media_id, fife_url,
                                media_generation_id=None) -> tuple:
    """DOM-free byte retrieval with current Flow tile fallbacks.

    Prefer a trusted signed URL from the status response, then the authenticated
    generation-resource ``get_media`` endpoint, and finally the authenticated
    tile redirect used by the current Flow Library.  None of these paths submits
    or retries a generation.
    """
    direct = await _download_from_direct_url(str(fife_url or "").strip(), "fifeUrl")
    if direct:
        return direct

    media = None
    media_error = None
    try:
        media = await client.get_media(media_id, media_generation_id=media_generation_id)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        enc = _deep(mdata, "encodedVideo")
        if enc:
            return base64.b64decode(enc), "get_media"
    except Exception as exc:  # noqa: BLE001 — try the tile redirect next
        media_error = str(exc)

    redirect_fn = getattr(client, "get_media_download_url", None)
    if callable(redirect_fn):
        try:
            redirect = await redirect_fn(media_id)
            redirect_url = _deep(redirect, "downloadUrl", "url", "servingUri", "servingUrl")
            direct = await _download_from_direct_url(str(redirect_url or "").strip(),
                                                     "media_redirect")
            if direct:
                return direct
        except Exception:  # noqa: BLE001 — report one bounded retrieval error
            pass

    status = media.get("status") if isinstance(media, dict) else None
    detail = f"status={status}"
    if media_error:
        detail += f" get_media_error={media_error[:160]}"
    raise RuntimeError(
        f"DIRECT_MEDIA_BYTES_UNAVAILABLE: media {media_id} returned no "
        f"encodedVideo ({detail}) and signed delivery failed")


async def _direct_operation_retrieve_from_poll(
        job, client, mode, polled, plan, seed, num_videos) -> None:
    """Retrieve/register a successful legacy-operation poll response."""
    from agent.worker._parsing import _extract_uuid_from_url

    data = _direct_response_data(polled)
    final_ops = data.get("operations", []) if isinstance(data, dict) else []
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for op in final_ops:
        if not isinstance(op, dict):
            continue
        op_name = (op.get("operation") or {}).get("name")
        video_meta = ((op.get("operation") or {}).get("metadata") or {}).get("video") or {}
        mid = str(video_meta.get("mediaId") or "").strip()
        fife = video_meta.get("fifeUrl")
        if not mid and fife:
            mid = _extract_uuid_from_url(str(fife))
        if not mid:
            skipped.append({"operation": op_name, "reason": "NO_MEDIA_ID_IN_METADATA"})
            continue
        data_bytes, source = await _download_video_bytes(client, mid, fife)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data_bytes)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data_bytes) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "operation_handle",
                "operation_name": op_name,
                "retrieval_source": source,
                "gen_seed": seed,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: provider terminal operation exposed no retrievable media"
        )
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(
        status="DONE",
        stage="done",
        media_id=first["media_id"],
        local_path=first["local_path"],
        size_mb=first["size_mb"],
        artifact="video",
        artifacts=list(collected),
    )
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = f"retrieved {len(collected)}/{num_videos} requested videos"
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


async def _direct_media_retrieve_from_poll(
        job, client, mode, targets, plan, seed, num_videos, polled) -> None:
    """Retrieve/register a successful current media-target poll response."""
    entries = _direct_media_entries(polled)
    by_name = {str(m.get("name")): m for m in entries if m.get("name")}
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for target in targets:
        mid = str(target.get("name") or "").strip()
        media = by_name.get(mid)
        if not mid or not media:
            skipped.append({"media_id": mid, "reason": "NO_MEDIA_IN_SUCCESS_POLL"})
            continue
        generation_id = _direct_media_generation_id(media)
        if generation_id and hasattr(client, "_media_generation_ids"):
            client._media_generation_ids[mid] = generation_id
        data_bytes, source = await _download_video_bytes(
            client,
            mid,
            _direct_media_url(media),
            media_generation_id=generation_id,
        )
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data_bytes)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data_bytes) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "media_status",
                "operation_name": mid,
                "retrieval_source": source,
                "gen_seed": seed,
                "media_generation_id": generation_id,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: provider terminal media status exposed no retrievable media"
        )
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(
        status="DONE",
        stage="done",
        media_id=first["media_id"],
        local_path=first["local_path"],
        size_mb=first["size_mb"],
        artifact="video",
        artifacts=list(collected),
    )
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = f"retrieved {len(collected)}/{num_videos} requested videos"
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


async def _direct_poll_retrieve_finish(job, client, mode, operations, plan,
                                       seed, num_videos) -> None:
    """Poll the operation handles to terminal, download every finished video,
    persist generated_artifact rows and mark the job DONE. DOM-free end to end;
    raises on failure (caller classifies)."""
    from agent.sdk.services.operations import _poll_operations
    from agent.worker._parsing import _extract_uuid_from_url
    job["stage"] = f"polling render status ({len(operations)} operation(s))"
    polled = await _poll_operations(client, operations,
                                    timeout=_direct_poll_timeout())
    if not isinstance(polled, dict) or polled.get("error"):
        emsg = str((polled or {}).get("error") or "empty poll result")
        if "timeout" in emsg.lower():
            # Exact marker string: classifies as a retrieval-phase failure
            # (GENERATED_BUT_UNRETRIEVED) — the operations stay re-pollable.
            raise RuntimeError(
                "video not found/retrieved in time (direct poll timeout; "
                f"operations {job.get('provider_operation_ids')} remain re-pollable)")
        raise RuntimeError(f"DIRECT_RENDER_FAILED: {emsg}")
    final_ops = (polled.get("data") or {}).get("operations", [])
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for op in final_ops:
        op_name = (op.get("operation") or {}).get("name")
        video_meta = ((op.get("operation") or {}).get("metadata") or {}).get("video") or {}
        mid = str(video_meta.get("mediaId") or "").strip()
        fife = video_meta.get("fifeUrl")
        if not mid and fife:
            mid = _extract_uuid_from_url(str(fife))
        if not mid:
            skipped.append({"operation": op_name, "reason": "NO_MEDIA_ID_IN_METADATA"})
            continue
        job["stage"] = f"downloading finished video {mid[:12]}"
        data, source = await _download_video_bytes(client, mid, fife)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "operation_handle",
                "operation_name": op_name,
                "retrieval_source": source,
                "gen_seed": seed,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: the poll reported success but exposed no "
            f"retrievable mediaId (skipped={skipped}) — do not assume no video "
            "exists; re-poll the recorded operations")
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(status="DONE", stage="done", media_id=first["media_id"],
               local_path=first["local_path"], size_mb=first["size_mb"],
               artifact="video", artifacts=list(collected))
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = (
            f"retrieved {len(collected)}/{num_videos} requested videos")
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


async def _direct_media_poll_retrieve_finish(job, client, mode, targets,
                                             plan, seed, num_videos) -> None:
    """Poll current Flow media targets, retrieve bytes, and persist artifacts."""
    job["stage"] = f"polling media render status ({len(targets)} target(s))"
    polled = await _poll_direct_media_targets(
        client, targets, timeout=_direct_poll_timeout())
    if not isinstance(polled, dict) or polled.get("error"):
        emsg = str((polled or {}).get("error") or "empty media poll result")
        if "timeout" in emsg.lower():
            raise RuntimeError(
                "video not found/retrieved in time (direct media poll timeout; "
                f"media targets {job.get('provider_operation_ids')} remain re-pollable)")
        raise RuntimeError(f"DIRECT_RENDER_FAILED: {emsg}")

    entries = _direct_media_entries(polled)
    by_name = {str(m.get("name")): m for m in entries if m.get("name")}
    outdir = OUTPUT_DIR / "retrieved"
    outdir.mkdir(parents=True, exist_ok=True)
    collected = []
    skipped = []
    for target in targets:
        mid = str(target.get("name") or "").strip()
        media = by_name.get(mid)
        if not mid or not media:
            skipped.append({"media_id": mid, "reason": "NO_MEDIA_IN_SUCCESS_POLL"})
            continue
        generation_id = _direct_media_generation_id(media)
        if generation_id and hasattr(client, "_media_generation_ids"):
            client._media_generation_ids[mid] = generation_id
        job["stage"] = f"downloading finished video {mid[:12]}"
        data, source = await _download_video_bytes(
            client, mid, _direct_media_url(media),
            media_generation_id=generation_id)
        path = outdir / f"{mid}.mp4"
        path.write_bytes(data)
        collected.append({
            "media_id": mid,
            "local_path": str(path),
            "size_mb": round(len(data) / 1024 / 1024, 2),
            "correlation": {
                "media_id": mid,
                "matched_on": "media_status",
                "operation_name": mid,
                "retrieval_source": source,
                "gen_seed": seed,
                "media_generation_id": generation_id,
            },
        })
    job["direct_retrieval_skipped"] = skipped
    if not collected:
        raise RuntimeError(
            "DIRECT_RETRIEVAL_EMPTY: the media poll reported success but exposed "
            f"no retrievable media (skipped={skipped}) — re-poll the recorded targets")
    first = collected[0]
    job["output_correlation"] = first["correlation"]
    job.update(status="DONE", stage="done", media_id=first["media_id"],
               local_path=first["local_path"], size_mb=first["size_mb"],
               artifact="video", artifacts=list(collected))
    if len(collected) < int(num_videos or 1):
        job["partial"] = True
        job["partial_detail"] = (
            f"retrieved {len(collected)}/{num_videos} requested videos")
        job["stage"] = "done_partial"
    _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
    await _record_artifacts(job, mode, collected)


def _direct_submit_handles(submit: dict, project_id: str) -> tuple[list[dict], list[dict], list[str]]:
    """Choose the poll contract without treating an accepted media response as empty."""
    operations, media_targets = _extract_direct_submission(submit, project_id)
    operation_names = [
        str(name)
        for name in ((o.get("operation") or {}).get("name") for o in operations)
        if name
    ]
    media_names = [str(target["name"]) for target in media_targets if target.get("name")]
    # Current Flow returns media targets; legacy captures return operation
    # handles. Prefer media targets when present because their status endpoint
    # is the contract paired with the current response.
    handles = media_names or operation_names
    return operations, media_targets, handles


async def _run_generate_direct(job_id, mode, prompt, project_id, image_media_ids,
                               aspect, tier, model, duration_s, num_videos,
                               product_id, plan):
    """API-first direct video lane: submit -> poll -> retrieve -> persist.

    The Flow tab's DOM is never consulted after submit, so a labs.google React
    crash cannot lose a finished, paid video (the root cause of the empty
    results/library incidents). The only DOM touch is the optional pre-submit
    editor binding when no project_id was provided."""
    global _VIDEO_LANE_JOB
    job = _JOBS[job_id]
    client = get_flow_client()
    if product_id:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="MAKE_VIDEO_DIRECT_PROVIDER"
            )
        except ProductOperationalVisibilityError as exc:
            job["status"] = "REJECTED"
            job["error"] = f"{exc.code}:{exc}"
            return
    generating = False
    try:
        refs = [m for m in (image_media_ids or []) if m]
        job["direct_plan"] = {k: plan.get(k) for k in
                              ("rpc", "gen_type", "aspect_enum", "model_key_source")}
        # 1) project context: explicit id wins; else bind to the OPEN editor
        # (read-only DOM touch, pre-submit and pre-credits — fail-closed).
        if not project_id:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_with_recovery(client, None, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id

        seed = int(time.time()) % 100000
        fired_model_key = resolve_video_model_key(
            tier, plan["gen_type"], plan["aspect_enum"],
            override=plan.get("video_model_key"))
        if not fired_model_key:
            raise RuntimeError(
                f"DIRECT_MODEL_KEY_MISSING: no captured videoModelKey for "
                f"tier={tier} gen_type={plan['gen_type']} aspect={plan['aspect_enum']}")
        job["status"] = "GENERATING"
        job["stage"] = f"submitting direct render ({plan['gen_type']})"
        submit = await _direct_submit(client, plan, refs, prompt, project_id,
                                      tier, seed, str(uuid4()))
        if (not isinstance(submit, dict) or submit.get("error")
                or (isinstance(submit.get("status"), int) and submit["status"] >= 400)):
            detail = (submit or {}).get("error") or submit
            raise RuntimeError(f"DIRECT_SUBMIT_REJECTED: {str(detail)[:300]}")
        operations, media_targets, op_names = _direct_submit_handles(
            submit, project_id)
        if not op_names:
            raise RuntimeError(
                f"DIRECT_SUBMIT_NO_OPERATIONS: {str(submit)[:300]}")
        job["provider_operation_ids"] = op_names
        job["direct_media_targets"] = media_targets
        # The submit acceptance IS this lane's approval: the provider accepted
        # the render request (credits may be charged from here on).
        job["approved"] = True
        generating = True
        job["model_used"] = fired_model_key
        job["model_ok"] = True if model else None
        job["model_key_source"] = plan.get("model_key_source")
        # Duration is not expressible in the captured submit contract; the Veo
        # default (8s) is expected but not asserted — flagged, never invented.
        job["duration_unverified"] = True
        job["generation_identity"] = {
            "seed": seed,
            "expected_model": fired_model_key,
            "operation_names": op_names,
            "provider_generation_submit_count": 1,
        }
        job["provider_generation_submit_count"] = 1
        job["provider_resubmission"] = False
        job["identity_captured"] = True  # the operation handle IS the binding
        # Provider identity is durable before the long poll/retrieval window.
        await _sync_durable_single_job(job)
        if media_targets:
            await _direct_media_poll_retrieve_finish(
                job, client, mode, media_targets, plan, seed, num_videos)
        else:
            await _direct_poll_retrieve_finish(
                job, client, mode, operations, plan, seed, num_videos)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if job.get("approved") is True and generating and _is_retrieval_phase_error(msg):
            _apply_post_approval_failure(job, msg)
        else:
            job.update(status="FAILED", error=msg, stage="failed")
            _stamp_credit(
                job,
                CREDIT_MAY_HAVE_SPENT
                if (job.get("approved") is True and generating)
                else CREDIT_NOT_SPENT,
            )
    finally:
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None


async def start_direct_capture(mode: str, prompt: str, project_id: str,
                               refs: list, aspect: str = "9:16",
                               tier: str = "PAYGATE_TIER_ONE",
                               source_mode: str = None, model: str = None,
                               duration_s: int = None,
                               confirm_live_credit_burn: bool = False,
                               product_visual_custody: dict | None = None,
                               execution_identity: dict | None = None,
                               request_id: str | None = None,
                               staff_id: str | None = None,
                               staff_display_name_snapshot: str | None = None,
                               production_recipe: str | None = None) -> dict:
    """Retired compatibility capture; canonical certification uses start_generate.

    The historical implementation remains below as contract archaeology."""
    raise RuntimeError("LEGACY_PAID_VIDEO_ENTRYPOINT_RETIRED_USE_DURABLE_VIDEO_JOB")
    global _VIDEO_LANE_JOB
    production_recipe = str(production_recipe or "").strip().upper() or None
    from agent.security.access_control import get_current_auth_context, resolve_request_staff
    if production_recipe or get_current_auth_context() is not None:
        if production_recipe not in {"HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"}:
            if production_recipe:
                return {"ok": False, "error": "PRODUCTION_RECIPE_UNSUPPORTED", "provider_submit": False}
        from agent.services.staff_identity_service import StaffIdentityError

        try:
            profile = await resolve_request_staff(staff_id)
        except StaffIdentityError as exc:
            return {"ok": False, "error": exc.code, "detail": exc.message, "provider_submit": False}
        staff_id = profile["staff_id"]
        staff_display_name_snapshot = profile["display_name"]
    if not direct_capture_enabled():
        return {"ok": False, "error": "DIRECT_CAPTURE_DISABLED: set "
                                      "DIRECT_VIDEO_CAPTURE_ENABLED=1"}
    if confirm_live_credit_burn is not True:
        return {"ok": False, "error":
                "DIRECT_CAPTURE_CONFIRMATION_REQUIRED: explicit credit "
                "authorization is required before the live submit"}
    refs = [m for m in (refs or []) if m]
    plan = _direct_lane_plan(mode, source_mode, model, duration_s, aspect,
                             ref_count=len(refs), num_videos=1,
                             require_flag=False)
    if not plan["eligible"]:
        return {"ok": False, "error": f"DIRECT_CAPTURE_INELIGIBLE: {plan['reason']}"}
    if product_visual_custody:
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            validate_pre_dispatch_route,
        )

        try:
            validate_pre_dispatch_route(
                product_visual_custody,
                provider_route="DIRECT_API",
                generation_type=str(plan.get("gen_type") or "reference_frame_2_video"),
            )
        except ProductVisualCustodyError as exc:
            return {"ok": False, "error": exc.code, "detail": exc.message}
    _gc_jobs()
    if _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"ok": False, "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "g_" + uuid4().hex[:12]
    from agent.db import crud as _capture_crud

    try:
        _capture_lease = await _capture_crud.acquire_video_generation_lane_lease(job_id)
    except Exception as exc:  # noqa: BLE001 - capture must fail closed
        return {
            "ok": False,
            "error": "DURABLE_SINGLE_LANE_UNAVAILABLE",
            "detail": str(exc),
            "provider_submit": False,
        }
    if not _capture_lease.get("acquired"):
        return {
            "ok": False,
            "error": "VIDEO_JOB_IN_FLIGHT",
            "active_job": (_capture_lease.get("row") or {}).get("job_id"),
            "provider_submit": False,
        }
    _JOBS[job_id] = {"job_id": job_id, "status": "SUBMITTED", "mode": mode,
                     "stage": "direct capture submit", "project_id": project_id,
                     "local_path": None, "media_id": None, "size_mb": None,
                     "artifact": None, "approved": None, "binding": None,
                     "model": model, "duration_s": duration_s,
                     "prompt": prompt, "aspect": aspect,
                     "num_videos": 1, "artifacts": [],
                     "provider_operation_ids": [], "product_id": (
                         product_visual_custody or {}
                     ).get("product_id"),
                     "lane": "DIRECT_CAPTURE", "source_mode": source_mode,
                     "staff_id": staff_id,
                     "staff_display_name_snapshot": staff_display_name_snapshot,
                     "production_recipe": production_recipe,
                     "product_visual_custody": product_visual_custody,
                     "execution_identity": execution_identity,
                     "request_id": request_id,
                     "idempotency_key": request_id or job_id,
                     "strict_artifact_delivery": True,
                     "error": None, "created": time.time()}
    try:
        _durable_row, _durable_owner = await _prepare_durable_single_job(
            _JOBS[job_id],
            idempotency_key=request_id or job_id,
            strict=True,
        )
    except RuntimeError as exc:
        _JOBS.pop(job_id, None)
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {
            "ok": False,
            "error": "DURABLE_SINGLE_LEDGER_UNAVAILABLE",
            "detail": str(exc),
            "provider_submit": False,
        }
    if _durable_row and not _durable_owner:
        _JOBS.pop(job_id, None)
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {
            **(await get_durable_job(_durable_row["job_id"]) or {}),
            "ok": True,
            "provider_submit": False,
            "request_id": request_id,
            "replayed": True,
        }
    _JOBS[job_id]["durable"] = bool(_durable_row)
    _VIDEO_LANE_JOB = job_id
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        if not project_id:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_with_recovery(client, None, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id
        seed = int(time.time()) % 100000
        fired_model_key = resolve_video_model_key(
            tier, plan["gen_type"], plan["aspect_enum"],
            override=plan.get("video_model_key"))
        job["status"], job["stage"] = "GENERATING", "direct capture submit"
        submit = await _direct_submit(client, plan, refs, prompt, project_id,
                                      tier, seed, str(uuid4()))
    except Exception as e:  # noqa: BLE001
        job.update(status="FAILED", error=str(e), stage="failed")
        _stamp_credit(job, CREDIT_NOT_SPENT)
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {"ok": False, "job_id": job_id, "error": str(e)}
    fired = {"rpc": plan["rpc"], "gen_type": plan["gen_type"],
             "aspect_enum": plan["aspect_enum"], "video_model_key": fired_model_key,
             "seed": seed, "refs": refs, "project_id": project_id, "tier": tier,
             "model": model, "duration_s": duration_s}
    job["direct_capture_fired"] = fired
    if (not isinstance(submit, dict) or submit.get("error")
            or (isinstance(submit.get("status"), int) and submit["status"] >= 400)):
        job.update(status="FAILED", stage="failed",
                   error=f"DIRECT_SUBMIT_REJECTED: {str((submit or {}).get('error') or submit)[:300]}")
        _stamp_credit(job, CREDIT_NOT_SPENT)
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None
        await _capture_crud.release_video_generation_lane_lease(job_id)
        return {"ok": False, "job_id": job_id, "fired": fired,
                "submit_response": submit, "error": job["error"]}
    operations, media_targets, op_names = _direct_submit_handles(
        submit, project_id)
    job["provider_operation_ids"] = op_names
    job["approved"] = bool(op_names)
    job["direct_media_targets"] = media_targets
    job["model_used"] = fired_model_key
    job["generation_identity"] = {"seed": seed, "expected_model": fired_model_key,
                                  "operation_names": op_names,
                                  "provider_generation_submit_count": 1}
    job["provider_generation_submit_count"] = 1
    job["provider_resubmission"] = False
    job["identity_captured"] = bool(op_names)
    await _sync_durable_single_job(job)

    async def _finish():
        global _VIDEO_LANE_JOB
        try:
            if not op_names:
                raise RuntimeError(
                    f"DIRECT_SUBMIT_NO_OPERATIONS: {str(submit)[:300]}")
            if media_targets:
                await _direct_media_poll_retrieve_finish(
                    job, client, mode, media_targets, plan, seed, 1)
            else:
                await _direct_poll_retrieve_finish(
                    job, client, mode, operations, plan, seed, 1)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if job.get("approved") is True and _is_retrieval_phase_error(msg):
                _apply_post_approval_failure(job, msg)
            else:
                job.update(status="FAILED", error=msg, stage="failed")
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT if job.get("approved")
                              else CREDIT_NOT_SPENT)
        finally:
            if _VIDEO_LANE_JOB == job_id:
                _VIDEO_LANE_JOB = None
            await _capture_crud.release_video_generation_lane_lease(job_id)

    job["_task"] = asyncio.create_task(_finish())
    return {"ok": True, "job_id": job_id, "fired": fired,
            "operations": op_names, "submit_response": submit}


async def start_direct_media_recovery(
        media_id: str, project_id: str, mode: str = "F2V",
        source_mode: str = "HYBRID", model_key: str | None = None,
        duration_s: int | None = 8, seed: int | None = None,
        recovery_of: str | None = None,
        confirm_recovery: bool = False) -> dict:
    """Recover one already-accepted media target without a provider submit.

    This is deliberately a separate entrypoint from ``start_direct_capture``:
    it has no generation flag and no submit call.  The explicit recovery
    confirmation prevents an operator from confusing a status/retrieval repair
    with a new credit-bearing capture.
    """
    global _VIDEO_LANE_JOB
    if confirm_recovery is not True:
        return {"ok": False,
                "error": "DIRECT_RECOVERY_CONFIRMATION_REQUIRED"}
    media_id = str(media_id or "").strip()
    project_id = str(project_id or "").strip()
    if not media_id or not project_id:
        return {"ok": False, "error": "DIRECT_RECOVERY_TARGET_REQUIRED"}
    _gc_jobs()
    if _VIDEO_LANE_JOB and _job_active(_VIDEO_LANE_JOB):
        return {"ok": False, "error": "VIDEO_JOB_IN_FLIGHT",
                "active_job": _VIDEO_LANE_JOB}
    job_id = "r_" + uuid4().hex[:12]
    target = {"name": media_id, "projectId": project_id}
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "SUBMITTED",
        "mode": str(mode or "F2V").upper(),
        "source_mode": source_mode,
        "stage": "direct media recovery",
        "project_id": project_id,
        "local_path": None,
        "media_id": None,
        "size_mb": None,
        "artifact": None,
        "approved": True,
        "binding": None,
        "model": model_key,
        "model_used": model_key,
        "duration_s": duration_s,
        "num_videos": 1,
        "artifacts": [],
        "provider_operation_ids": [media_id],
        "direct_media_targets": [target],
        "product_id": None,
        "lane": "DIRECT_CAPTURE_RECOVERY",
        "direct_recovery": True,
        "strict_artifact_delivery": True,
        "recovery_of": recovery_of,
        "generation_identity": {
            "seed": seed,
            "expected_model": model_key,
            "operation_names": [media_id],
        },
        "identity_captured": True,
        "error": None,
        "created": time.time(),
    }
    _VIDEO_LANE_JOB = job_id
    job = _JOBS[job_id]
    client = get_flow_client()
    plan = {"gen_type": "reference_frame_2_video"}

    async def _finish():
        global _VIDEO_LANE_JOB
        try:
            await _direct_media_poll_retrieve_finish(
                job, client, job["mode"], [target], plan, seed, 1)
        except Exception as exc:  # noqa: BLE001 — preserve accepted-credit truth
            msg = str(exc)
            if _is_retrieval_phase_error(msg):
                _apply_post_approval_failure(job, msg)
            else:
                job.update(status="FAILED", error=msg, stage="failed")
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
        finally:
            if _VIDEO_LANE_JOB == job_id:
                _VIDEO_LANE_JOB = None

    job["_task"] = asyncio.create_task(_finish())
    return {
        "ok": True,
        "job_id": job_id,
        "media_id": media_id,
        "operations": [media_id],
        "provider_submit": False,
        "credit_action": "NO_PROVIDER_SUBMIT",
        "recovery_of": recovery_of,
    }


async def _run_generate(job_id, mode, prompt, project_id, image_media_ids,
                        image_prompt, aspect, tier, model=None, duration_s=None,
                        num_videos=1, image_model=None, max_image_attempts=8,
                        collect_image_variants=False, product_id=None,
                        copy_execution_binding=None):
    from agent.api.flow import (_generate_image_with_recovery, _extract_images,
                                 _extract_project_id, _IMG_ASPECT_MAP)
    import aiohttp
    global _VIDEO_LANE_JOB
    job = _JOBS[job_id]
    client = get_flow_client()
    generating = False  # set True once we pass approval into the render/retrieve phase
    try:
        if product_id:
            from agent.services.product_release_service import (
                ProductOperationalVisibilityError,
                require_product_operational_visibility,
            )
            try:
                await require_product_operational_visibility(
                    product_id, lane="MAKE_VIDEO_AGENT_PROVIDER"
                )
            except ProductOperationalVisibilityError as exc:
                raise RuntimeError(f"{exc.code}:{exc}") from exc
        if mode not in _ALL_MODES:
            raise RuntimeError(f"unknown mode '{mode}' (use IMG/T2V/I2V/F2V)")
        aspect_key = _IMG_ASPECT_MAP.get(aspect, "IMAGE_ASPECT_RATIO_PORTRAIT")

        # 1) project: IMG may mint a fresh project; video modes BIND to the OPEN editor
        #    (patch A/G — never mint a hidden project; fail-closed if no editor is open).
        if mode == "IMG":
            if not project_id:
                job["status"], job["stage"] = "SETUP", "creating project"
                proj = await client.create_project(f"{mode.lower()} auto")
                project_id = _extract_project_id(proj)
                if not project_id:
                    raise RuntimeError("create_project returned no projectId")
        else:
            job["status"], job["stage"] = "SETUP", "binding to open Flow editor"
            binding = await _bind_with_recovery(client, project_id, job)
            project_id = binding["project_id"]
            job["binding"] = binding
        job["project_id"] = project_id

        # 2) IMG — direct image API, no agent, no video credits
        if mode == "IMG":
            job["status"], job["stage"] = "GENERATING", "generating image"
            outdir = OUTPUT_DIR / "retrieved"
            outdir.mkdir(parents=True, exist_ok=True)
            variant_count = num_videos if collect_image_variants else 1
            collected: list[dict] = []
            provider_operation_ids: list[dict] = []
            for variant_index in range(variant_count):
                job["stage"] = (
                    f"generating image variant {variant_index + 1}/{variant_count}"
                    if collect_image_variants
                    else "generating image"
                )
                res = await _generate_image_with_recovery(
                    client,
                    prompt,
                    project_id,
                    aspect_key,
                    tier,
                    image_media_ids or [],
                    max_tries=max_image_attempts,
                    image_model=image_model or "NANO_BANANA_PRO",
                )
                evidence = _image_provider_operation_reference(res or {})
                imgs = _extract_images(
                    (res or {}).get("data", res or {})
                    if isinstance(res or {}, dict)
                    else {}
                )
                provider_media_id = imgs[0].get("media_id") if imgs else None
                response_status = (
                    "ERROR"
                    if not res or res.get("error")
                    else "MEDIA_RETURNED"
                    if provider_media_id
                    else "NO_MEDIA_RETURNED"
                )
                if collect_image_variants:
                    from agent.db import crud as _crud

                    try:
                        operation = await _crud.record_image_generation_operation(
                            job_id=job_id,
                            product_id=product_id,
                            model=image_model or "NANO_BANANA_PRO",
                            variant_index=variant_index,
                            provider_operation_id=evidence.get("provider_operation_id"),
                            transport_batch_id=evidence.get("transport_batch_id"),
                            operation_id_status=str(
                                evidence.get("operation_id_status")
                                or "UNPROVEN_PROVIDER_OPERATION_ID"
                            ),
                            provider_media_id=provider_media_id,
                            response_status=response_status,
                        )
                    except Exception as exc:  # noqa: BLE001 - provenance is mandatory
                        job["operation_provenance_error"] = str(exc)
                        raise RuntimeError(
                            "IMAGE_OPERATION_PROVENANCE_PERSIST_FAILED: "
                            f"{exc}"
                        ) from exc
                    evidence.update(operation)
                evidence["variant_index"] = str(variant_index)
                provider_operation_ids.append(evidence)
                if not res or res.get("error"):
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("image gen failed: " + str((res or {}).get("error")))
                if not imgs:
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("no image returned")
                mid, url = imgs[0]["media_id"], imgs[0].get("url")
                download_media_id = imgs[0].get("delivery_media_id") or mid
                download_url = await _resolve_media_download_url(
                    client, download_media_id, url
                )
                if not download_url:
                    job["provider_operation_ids"] = provider_operation_ids
                    raise RuntimeError("no image/url returned")
                path = outdir / f"{mid}.jpg"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                    async with s.get(download_url) as r:
                        if r.status != 200:
                            job["provider_operation_ids"] = provider_operation_ids
                            raise RuntimeError(f"image download HTTP {r.status}")
                        data = await r.read()
                path.write_bytes(data)
                collected.append({
                    "media_id": mid,
                    "local_path": str(path),
                    "size_mb": round(len(data) / 1024 / 1024, 2),
                    "url": url,
                    "variant_index": variant_index,
                    "provider_operation_id": evidence.get("provider_operation_id"),
                    "transport_batch_id": evidence.get("transport_batch_id"),
                })
                await _record_artifacts(job, mode, [collected[-1]])
            if not collected:
                raise RuntimeError("no image artifact returned")
            first = collected[0]
            job["provider_operation_ids"] = provider_operation_ids
            job["artifacts"] = collected
            if collect_image_variants and product_id:
                try:
                    from agent.services.product_reference_pack_service import (
                        get_reference_pack,
                        machine_check_generated_output,
                    )

                    pack = await get_reference_pack(product_id)
                    if pack is not None:
                        job["generated_output_machine_qa"] = [
                            machine_check_generated_output(
                                artifact["media_id"], pack
                            ).model_dump(mode="json")
                            for artifact in collected
                        ]
                        job["generated_output_review_state"] = (
                            "GENERATED_OUTPUT_MACHINE_CHECKED"
                        )
                    else:
                        job["generated_output_machine_qa"] = []
                        job["generated_output_review_state"] = "UNPROVEN"
                except Exception as exc:  # noqa: BLE001 - QA cannot corrupt retrieval
                    job["generated_output_machine_qa_error"] = str(exc)
            job.update(status="DONE", stage="done", media_id=first["media_id"],
                       local_path=first["local_path"], size_mb=first["size_mb"],
                       artifact="image", url=first["url"])
            # The direct image API does not consume Google Flow video credits.
            # Keep the explicit IMG verdict separate from the paid video lane.
            _stamp_credit(job, CREDIT_NOT_SPENT)
            await _record_artifacts(job, mode, collected)
            return

        # 3) T2V / I2V / F2V — agent video
        refs = [m for m in (image_media_ids or []) if m]
        if mode in ("I2V", "F2V") and not refs:
            if image_prompt:
                job["status"], job["stage"] = "SETUP", "generating start frame"
                ires = await _generate_image_with_recovery(
                    client, image_prompt, project_id, aspect_key, tier, [])
                imgs = _extract_images((ires or {}).get("data", ires or {}))
                if imgs:
                    refs = [imgs[0]["media_id"]]
            if not refs:
                raise RuntimeError(f"{mode} needs a reference image (image_media_ids or image_prompt)")

        # False-DONE guard: take the project media snapshot after any required
        # start-frame resolution but BEFORE agent negotiation can mint this run's
        # output.  A snapshot taken after approval can classify a freshly created
        # tile as pre-existing and exclude the only valid result.
        preexisting = set()
        try:
            h0 = await client.harvest_video_urls(
                tab_id=(job.get("binding") or {}).get("flow_tab_id"))
            inner0 = h0.get("result", h0) if isinstance(h0, dict) else {}
            diag0 = inner0.get("diag", inner0) if isinstance(inner0, dict) else {}
            for k in ("videoIds", "imageIds", "mediaIds"):
                preexisting |= set((diag0.get(k) or []) if isinstance(diag0, dict) else [])
        except Exception:  # noqa: BLE001 — stale/ref excludes still apply
            pass
        job["preexisting_media_excluded"] = len(preexisting)
        # SEV-0 durable exclusion: the DOM snapshot can under-report history-laden
        # projects, while every DB-known id is guaranteed not to be freshly minted.
        known = await _durable_media_exclusion()
        job["db_known_media_excluded"] = len(known)
        exclude = set(_STALE_VIDEO_IDS) | set(refs) | preexisting | known

        # Profile certification snapshots are deliberately bound only after the
        # editor is verified.  This is the exact pre-provider dispatch choke
        # point: the WYSIWYG envelope is revalidated immediately before the
        # authenticated generation negotiation begins.
        if job.get("profile_certification_capture"):
            await _verify_generation_approval(
                mode=mode,
                prompt=prompt,
                source_mode=job.get("source_mode") or "T2V",
                model=model,
                aspect=aspect,
                duration_s=duration_s,
                num_videos=num_videos,
                image_model=image_model,
                asset_fingerprints=None,
                image_media_ids=refs,
                product_id=product_id,
                manifest_id=None,
                execution_identity=job.get("execution_identity"),
                execution_profile_context=job.get("profile_certification_context"),
                provider_profile=job.get("provider_profile"),
                allow_uncertified_profile_capture=True,
                snapshot_id=job.get("execution_snapshot_id"),
            )
            job["approval_boundary_reached"] = True

        job["status"], job["stage"] = "NEGOTIATING", "agent session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["stage"] = (f"negotiating (approve {num_videos} video"
                        f"{'s' if num_videos > 1 else ''}, "
                        f"{video_models.resolve(model)['ui_label']})")

        target_authorization = job.get("provider_target_authorization")

        async def _persist_target_acknowledgement(acknowledgement):
            if not target_authorization:
                raise RuntimeError("PROVIDER_TARGET_AUTHORIZATION_REQUIRED")
            snapshot_id = str(job.get("execution_snapshot_id") or "")
            if not snapshot_id:
                raise RuntimeError("PROVIDER_TARGET_ACK_SNAPSHOT_REQUIRED")
            from agent.services import execution_approval_service as _eas
            from agent.services import provider_certification_service as _certifications

            snapshot = await _eas.record_provider_target_acknowledgement(
                snapshot_id,
                target_authorization=target_authorization,
                acknowledgement=acknowledgement,
            )
            certification_id = job.get("profile_certification_id")
            if certification_id:
                await _certifications.record_target_acknowledgement(
                    str(certification_id),
                    snapshot_id=snapshot_id,
                    acknowledgement=acknowledgement,
                )
            job["provider_target_acknowledgement"] = dict(acknowledgement)
            job["provider_target_acknowledgement_snapshot_id"] = snapshot_id
            return snapshot

        nres = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, refs,
            target_model=model, target_duration_s=duration_s,
            desired_num=num_videos,
            target_authorization=target_authorization,
            on_target_acknowledged=_persist_target_acknowledgement
            if target_authorization
            else None,
        )
        job["approved"] = nres.get("approved")
        job["negotiation_state"] = nres.get("negotiation_state") or {}
        if job.get("capture_only"):
            job["capture_contract_evidence"] = agent_video.build_reference_contract_capture_evidence(
                nres, refs, project_id=project_id
            )
            observed_types = [
                item.get("value")
                for item in (job["capture_contract_evidence"].get("generation_type_fields") or [])
                if isinstance(item, dict) and item.get("value") not in (None, "")
            ]
            if observed_types:
                job["provider_generation_type"] = str(observed_types[0])
        # Approval may already have triggered provider work.  Every subsequent failure
        # is therefore credit-uncertain, including a safety rejection inside the approve
        # stream; never stamp it as NOT_SPENT merely because retrieval did not begin.
        if job["approved"] is True:
            generating = True
            # This is the single logical provider submit.  Persist the count before
            # any long render/retrieval wait; recovery must never infer a second
            # submit from a lost process-local task.
            job["provider_generation_submit_count"] = 1
            job["provider_resubmission"] = False
            job["resubmission_allowed"] = False
            if job.get("profile_certification_capture"):
                # The route remains PRE_PROVIDER until this observed provider
                # acceptance.  No certification row is SUBMITTED merely because
                # a background task was created.
                job["status"] = "SUBMITTED"
                certification_id = job.get("profile_certification_id")
                if certification_id:
                    try:
                        from agent.services import provider_certification_service as _certifications

                        job["profile_certification"] = await _certifications.mark_submitted(
                            str(certification_id),
                            job_id=job_id,
                            snapshot_id=str(job.get("execution_snapshot_id") or ""),
                        )
                    except Exception as exc:  # noqa: BLE001 — preserve paid/provider truth
                        job["profile_certification_persistence_error"] = str(exc)
        # Expose the FULL post-approve verification status on the job (the API returns the job
        # dict verbatim), so an unverified generation is NEVER presented as fully verified.
        job["model_used"] = nres.get("model_used")
        job["model_ok"] = nres.get("model_ok")
        job["duration_used"] = nres.get("duration_used")
        job["duration_ok"] = nres.get("duration_ok")
        # DIAGNOSABILITY: persist the captured identity (toolNames seen, anchors, and
        # the raw approve SSE on a gap) HERE — before any post-approve guard below can
        # raise — so a REJECTED run still reveals what tool/model it fired instead of
        # forcing another paid capture. (F2V live g_7b29b837c259: the agent fired
        # veo_3_1_i2v_lite, the reference-dropped guard rejected it, and every
        # persisted anchor came back empty ONLY because this capture used to run after
        # the guard.) Idempotent: the success path re-confirms the same values below.
        job["generation_identity"] = {
            "sse_prompt": nres.get("gen_prompt"),
            "expected_model": nres.get("model_used"),
            "tool_call_id": nres.get("tool_call_id"),
            "response_id": nres.get("response_id"),
            "seed": nres.get("gen_seed"),
        }
        job["identity_captured"] = _identity_captured(job["generation_identity"])
        job["tools_seen"] = list(nres.get("tools_seen") or [])
        job["gen_tool_matched"] = bool(nres.get("gen_tool_matched"))
        if job.get("provider_certification_bootstrap"):
            observed_model = str(nres.get("model_used") or "").strip().lower()
            observed_tools = {str(tool).strip() for tool in (nres.get("tools_seen") or [])}
            if observed_model != SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY:
                raise RuntimeError(
                    "SHARED_8S_PROVIDER_MODEL_PROVENANCE_UNPROVEN: expected "
                    f"{SHARED_REFERENCE_VEO_8S_PROVIDER_MODEL_KEY}, got "
                    f"{nres.get('model_used')}"
                )
            if "generate_video_with_references" not in observed_tools:
                raise RuntimeError(
                    "SHARED_8S_REFERENCE_TRANSPORT_UNPROVEN: "
                    "generate_video_with_references was not observed"
                )
            if nres.get("duration_used") != 8:
                raise RuntimeError(
                    "SHARED_8S_DURATION_PROVENANCE_UNPROVEN: expected 8s, got "
                    f"{nres.get('duration_used')}"
                )
            job["provider_profile_observed"] = {
                "provider_model_key": observed_model,
                "provider_generation_type": SHARED_REFERENCE_VEO_8S_PROVIDER_GENERATION_TYPE,
                "provider_tool": "generate_video_with_references",
                "duration_seconds": 8,
                "reference_media_ids": list(refs),
            }
        certified_route = (
            (job.get("routing_receipt") or {}).get("selected_execution_route")
            == HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
        )
        if certified_route and job.get("approved") is True:
            # This helper stores only sanitized tool/model/duration/reference
            # fields.  It gives the normal certified route the same typed
            # reference-forwarding proof that authorized discovery captured,
            # without persisting raw SSE or provider session material.
            transport_evidence = agent_video.build_reference_contract_capture_evidence(
                nres, refs, project_id=project_id
            )
            job["reference_transport_evidence"] = transport_evidence
            job["certified_transport_verdict"] = (
                "REFERENCE_OMNI_10S_TRANSPORT_VERIFIED"
                if (
                    HYBRID_REFERENCE_OMNI_10S_PROVIDER_TOOL
                    in (transport_evidence.get("provider_generation_tools") or [])
                    and transport_evidence.get("reference_forwarded_to_generation")
                    and transport_evidence.get("reference_aware_tool_observed")
                )
                else "REFERENCE_OMNI_10S_TRANSPORT_UNPROVEN"
            )
            if job["certified_transport_verdict"] != (
                "REFERENCE_OMNI_10S_TRANSPORT_VERIFIED"
            ):
                raise RuntimeError(
                    "FLOW_AGENT_REFERENCE_OMNI_10S_TRANSPORT_UNPROVEN: the approved "
                    "stream did not prove generate_video_with_references with the "
                    "persisted reference media id"
                )
        if not job["identity_captured"]:
            if job.get("capture_only"):
                # The capture evidence is sanitized; never persist raw SSE as a
                # fallback because it can contain provider/session material.
                job["identity_gap_sse"] = None
            else:
                job["identity_gap_sse"] = _last_approve_sse(nres)
        # Persist the approved provider/correlation envelope before any long
        # render wait. A restart can therefore reconcile this same attempt.
        await _sync_durable_single_job(job)
        # Post-approve verification (Layer A): a CONFIRMED model OR duration mismatch hard-fails.
        if nres.get("model_ok") is False:
            raise RuntimeError(
                f"FAILED_WRONG_MODEL: expected {model or 'default'}, got {nres.get('model_used')}")
        if nres.get("duration_ok") is False:
            raise RuntimeError(
                f"FAILED_WRONG_DURATION: expected {duration_s or 'default'}s, got {nres.get('duration_used')}s")
        # SEV-0 Mission 11: a reference run must fire a REFERENCE generation tool.
        # The proposal carries no tool/model (fixture-proven), so this is the earliest
        # honest boundary — fail LOUD instead of reporting a text-only fallback (image
        # silently dropped) as a successful reference generation.
        if _reference_run_dropped_reference(refs, nres.get("model_used")) is True:
            raise RuntimeError(
                "INITIAL_T2V_FALLBACK_REJECTED: references were attached but the agent "
                f"fired a text-only generation tool ({nres.get('model_used')}) — the "
                "product image was dropped; do not treat this output as reference-anchored")
        # Evidence ABSENT from the approved SSE (e.g. an unrecognized generation tool) → unknown,
        # NOT a hard fail, but FLAGGED so it is never reported as verified. A None model_used means
        # the fired tool was unrecognized, in which case duration is absent too (both flags set).
        if nres.get("approved"):
            if nres.get("model_ok") is None:
                job["model_unverified"] = True
            if nres.get("duration_ok") is None:
                job["duration_unverified"] = True
        if not nres.get("approved"):
            if nres.get("error_class") == agent_video.RATE_LIMITED:
                raise RuntimeError(str(nres.get("error")))  # honest 0-credit rate-limit label
            raise RuntimeError("agent did not approve a video: " + str(nres.get("error") or nres))
        # The render can die inside the approve stream itself.  Treat every known
        # terminal reply as terminal now so the shared video lock is released in the
        # finally block instead of holding every lane until the retrieval timeout.
        terminal_error = _terminal_agent_failure_error(
            nres.get("failure_classification")
        )
        if terminal_error:
            raise RuntimeError(terminal_error)

        job["status"], job["stage"] = "GENERATING", "rendering + retrieving"
        generating = True  # also true for legacy responses that omitted approved=True
        # DETERMINISTIC current-run binding (PR321 closure): the exact identities of
        # THIS submission — the acceptance authority for every retrieved artifact.
        correlation = {
            "submitted_prompt": prompt,
            "sse_prompt": nres.get("gen_prompt"),
            "expected_model": nres.get("model_used"),
            "tool_call_id": nres.get("tool_call_id"),
            "response_id": nres.get("response_id"),
            "seed": nres.get("gen_seed"),
        }
        job["generation_identity"] = {
            k: v for k, v in correlation.items() if k != "submitted_prompt"}
        # Retrieval-only context, deliberately added after the durable identity
        # snapshot so the existing five-argument correlation helper contract stays
        # compatible with harnesses and downstream overrides.
        correlation["_project_id"] = project_id
        # Identity-capture status (PR392 follow-up). Anchors are only captured for
        # toolNames in agent_video._GEN_TOOLS; a generation firing under any other
        # name leaves EVERY anchor None, and retrieval can then never bind an
        # output — the run is unverifiable before a single poll runs. Record that
        # as a first-class fact (with the toolNames actually seen) instead of
        # letting it surface later as a generic "not found in time".
        job["identity_captured"] = _identity_captured(job["generation_identity"])
        job["tools_seen"] = list(nres.get("tools_seen") or [])
        job["gen_tool_matched"] = bool(nres.get("gen_tool_matched"))
        if not job["identity_captured"]:
            # IDENTITY-GAP CAPTURE. tools_seen only names a tool if the stream
            # actually carried a toolInvocation. T2V's post-approve stream reports
            # "started" via soft TEXT (_STARTED_PHRASES), not started_tool, so it
            # may carry no invocation at all — in which case tools_seen is empty
            # and the paid run reveals nothing. Keep the raw approve stream so the
            # real identity source can be found from THIS run instead of buying
            # another. Diagnostic only: never parsed, never an anchor.
            if job.get("capture_only"):
                job["identity_gap_sse"] = None
            else:
                job["identity_gap_sse"] = _last_approve_sse(nres)
        corr_stats = {"unverifiable": 0, "prompt_mismatched": 0,
                      "model_mismatched": 0, "seed_mismatched": 0,
                      "unverifiable_ids": [], "normalization_failures": {},
                      "round_rejected_ids": [], "media_fetch_errors": 0,
                      "media_fetch_error_ids": [], "media_fetch_error_statuses": {},
                      "media_not_ready": 0, "media_not_ready_ids": []}
        # Fast-failure trackers (Owner Phase-1): consecutive polls in which the
        # SAME completed candidates were rejected for deterministic identity reasons.
        identity_reject_sig, identity_reject_rounds = None, 0
        identity_reject_epoch = None
        reload_epoch = 0
        probe_turn = int(nres.get("turns_used") or 0) + 1  # next agent turn for status probes
        collected = []  # user's count setting: retrieval collects num_videos artifacts
        await asyncio.sleep(120)
        for i in range(36):
            job["stage"] = f"checking for finished video (try {i + 1})"
            bound_tab = (job.get("binding") or {}).get("flow_tab_id")
            # Omni/V2 editor DOM does NOT live-update: a finished video never becomes
            # harvestable until the tab reloads (live proof g_01b041b563dc — the mp4 only
            # appeared, filed under imageIds, after a manual reload). Refresh the bound
            # tab every 6 polls so harvest can see newly finished media.
            if i and i % 6 == 0:
                try:
                    await client.reload_flow_tab(tab_id=bound_tab)
                    await asyncio.sleep(8)
                    reload_epoch += 1
                except Exception:  # noqa: BLE001 — refresh is best-effort, harvest re-checks
                    pass
            h = await client.harvest_video_urls(tab_id=bound_tab)
            inner = h.get("result", h) if isinstance(h, dict) else {}
            # Fail-closed harvest (patch A/G): abort on a lost/bound-gone tab or a drifted
            # project instead of polling into a generic late timeout.
            if (not isinstance(inner, dict)
                    or inner.get("error") in ("NO_FLOW_TAB", "BOUND_TAB_GONE")
                    or inner.get("flow_tab_found") is False):
                raise RuntimeError("EDITOR_TAB_LOST: the bound Flow tab/editor is gone")
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            seen_pid = diag.get("projectId") if isinstance(diag, dict) else None
            bridge_lease = job.get("bridge_lease")
            if isinstance(bridge_lease, dict):
                handled_tab_id = inner.get("handled_flow_tab_id")
                handled_project_id = inner.get("handled_flow_project_id")
                handled_url = str(inner.get("handled_flow_url") or "").strip()
                expected_tab_id = (
                    bridge_lease.get("flow_tab_id")
                    if bridge_lease.get("flow_tab_id") is not None
                    else bound_tab
                )
                expected_project_id = (
                    bridge_lease.get("flow_project_id") or project_id
                )
                expected_url = str(
                    bridge_lease.get("flow_url")
                    or (job.get("binding") or {}).get("flow_project_url")
                    or ""
                ).strip()
                identity_checks = {
                    "connection_id": (
                        bridge_lease.get("connection_id"),
                        inner.get("connection_id"),
                    ),
                    "installation_id": (
                        bridge_lease.get("installation_id"),
                        inner.get("installation_id"),
                    ),
                    "extension_session_id": (
                        bridge_lease.get("extension_session_id"),
                        inner.get("extension_session_id"),
                    ),
                    "handled_flow_tab_id": (expected_tab_id, handled_tab_id),
                    "canonical_flow_tab_id": (handled_tab_id, inner.get("flow_tab_id")),
                    "binding_flow_tab_id": (expected_tab_id, bound_tab),
                    "handled_flow_project_id": (
                        expected_project_id,
                        handled_project_id,
                    ),
                    "canonical_flow_project_id": (
                        handled_project_id,
                        inner.get("flow_project_id"),
                    ),
                    "diagnostic_project_id": (expected_project_id, seen_pid),
                }
                if expected_url:
                    identity_checks["handled_flow_url"] = (
                        expected_url.rstrip("/"),
                        handled_url.rstrip("/"),
                    )
                identity_mismatches = {
                    key: {"expected": expected, "observed": observed}
                    for key, (expected, observed) in identity_checks.items()
                    if expected is None
                    or observed is None
                    or str(expected) != str(observed)
                }
                if identity_mismatches:
                    raise RuntimeError(
                        "TAB_DRIFT: BOUND_RETRIEVAL_IDENTITY_MISMATCH: "
                        + json.dumps(
                            identity_mismatches,
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        )
                    )
            if seen_pid and seen_pid != project_id:
                raise RuntimeError(
                    f"PROJECT_DRIFT: tab moved to {seen_pid}, expected {project_id}")
            # Commit 2 canonicalizes flow_tab_id to handled_flow_tab_id.  The global
            # envelope_* snapshot may legitimately identify another Flow tab during a
            # targeted harvest, so retrieval validates only handled/canonical identity.
            cands = []
            for k in ("videoIds", "imageIds", "mediaIds"):
                cands += (diag.get(k) or []) if isinstance(diag, dict) else []
            # Collect up to num_videos fresh artifacts (user count setting = x2 means
            # TWO videos must come home, not just the first one found).
            while True:
                mid, path, size, evidence = await _accept_correlated_output(
                    client, cands, exclude, correlation, corr_stats)
                if not mid:
                    break
                exclude.add(mid)
                collected.append({"media_id": mid, "local_path": path,
                                  "size_mb": size, "correlation": evidence})
                job["output_correlation"] = evidence
                job["artifacts"] = list(collected)
                job["stage"] = (f"retrieved {len(collected)}/{num_videos} video(s)"
                                f" (try {i + 1})")
                if len(collected) >= num_videos:
                    break
            job["correlation_stats"] = dict(corr_stats)
            job["retrieval_telemetry"] = {
                "try": i + 1,
                "candidate_count": len(cands),
                "collected_count": len(collected),
                "media_fetch_errors": corr_stats.get("media_fetch_errors", 0),
                "media_not_ready": corr_stats.get("media_not_ready", 0),
                "artifact_persist_attempted": bool(job.get("artifact_persist_attempted")),
                "artifact_persisted_count": job.get("artifact_persisted_count", 0),
            }
            if len(collected) >= num_videos:
                first = collected[0]
                job.update(status="DONE", stage="done", media_id=first["media_id"],
                           local_path=first["local_path"], size_mb=first["size_mb"],
                           artifact="video", artifacts=list(collected))
                _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
                await _record_artifacts(job, mode, collected)
                return
            # FAST FAILURE (Owner Phase-1): completed candidates rejected for
            # deterministic identity reasons have IMMUTABLE stored metadata — no
            # future poll changes them. When the SAME non-empty rejected set
            # repeats _IDENTITY_MISMATCH_FASTFAIL_ROUNDS polls in a row (and the
            # run is past the minimum window so an in-flight render still gets
            # its chance), stop with precise evidence instead of the blind
            # 12-minute loop the incident suffered (31 identical rejections).
            round_sig = tuple(sorted(corr_stats.get("round_rejected_ids") or []))
            if round_sig and round_sig == identity_reject_sig and not collected:
                identity_reject_rounds += 1
            else:
                identity_reject_sig = round_sig or None
                identity_reject_rounds = 1 if round_sig else 0
                identity_reject_epoch = reload_epoch if round_sig else None
            if (identity_reject_rounds >= _IDENTITY_MISMATCH_FASTFAIL_ROUNDS
                    and i >= _IDENTITY_MISMATCH_MIN_TRIES and not collected
                    and reload_epoch > (identity_reject_epoch or 0)):
                job["correlation_stats"] = dict(corr_stats)
                raise RuntimeError(
                    "CURRENT_OUTPUT_IDENTITY_MISMATCH: completed candidate(s) "
                    f"{list(round_sig)[:4]} were rejected {identity_reject_rounds} "
                    "consecutive polls for deterministic identity reasons "
                    f"(prompt_mismatched={corr_stats['prompt_mismatched']}, "
                    f"model_mismatched={corr_stats['model_mismatched']}, "
                    f"seed_mismatched={corr_stats['seed_mismatched']}, "
                    f"unverifiable={corr_stats['unverifiable']}, "
                    f"normalization={corr_stats.get('normalization_failures') or {} }, "
                    f"sse_seed={'present' if _seed_value(correlation.get('seed')) is not None else 'absent'}) "
                    "— their stored metadata cannot change; refusing to blind-poll")
            # Empty project after minutes of polling can mean the render died
            # server-side (agent posts "Failed / missing reference image" in chat,
            # invisible to harvest). Ask the agent directly — a zero-credit turn —
            # instead of blind-polling to a 12-minute timeout.
            if i in (0, 8, 20) and not collected:
                probe = await agent_video.probe_render_failure(
                    client, project_id, sid, probe_turn)
                probe_turn = probe.get("turn_number", probe_turn + 1)
                job["render_probe"] = probe
                terminal_error = _terminal_agent_failure_error(
                    probe.get("classification")
                )
                if terminal_error:
                    raise RuntimeError(terminal_error)
            await asyncio.sleep(18)
        # Timeout with SOME videos home but fewer than requested → honest partial DONE
        # (the user gets what exists; the shortfall is flagged, never hidden).
        if collected:
            first = collected[0]
            job.update(status="DONE", stage="done_partial", media_id=first["media_id"],
                       local_path=first["local_path"], size_mb=first["size_mb"],
                       artifact="video", artifacts=list(collected),
                       partial=True,
                       partial_detail=f"retrieved {len(collected)}/{num_videos} requested videos")
            _stamp_credit(job, CREDIT_MAY_HAVE_SPENT)
            await _record_artifacts(job, mode, collected)
            return
        # Finished video(s) exist but expose no generation prompt to bind them to
        # THIS run — refuse the uncorrelated candidate(s) instead of guessing
        # (never a false success; credits may have been spent).
        if corr_stats["unverifiable"] and not collected:
            job["correlation_stats"] = dict(corr_stats)
            raise RuntimeError(
                "OUTPUT_CORRELATION_UNAVAILABLE: finished media "
                f"{corr_stats['unverifiable_ids'][:4]} cannot be deterministically "
                "bound (no usable prompt metadata; normalization="
                f"{corr_stats.get('normalization_failures') or {} }) — refusing an "
                "uncorrelated candidate as this run's output")
        # Render started but no mp4 harvested in the polling window.
        job["correlation_stats"] = dict(corr_stats)
        # Distinguish "we could not find it" from "we could never have bound it".
        # With no anchors, no amount of polling could have produced a bindable
        # output — reporting a timeout there sends the operator hunting a
        # retrieval bug that does not exist (live g_e71cd329b524).
        if not job.get("identity_captured"):
            raise RuntimeError(
                "OUTPUT_IDENTITY_NOT_CAPTURED: the generation fired but exposed no "
                "correlation anchor (seed/sse_prompt/model/tool_call_id all absent), "
                "so no retrieved media can be deterministically bound to this run. "
                f"toolNames seen={job.get('tools_seen') or []}; "
                "add the generation toolName to agent_video._GEN_TOOLS")
        raise RuntimeError("video not found/retrieved in time")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        # False-negative fix: a retrieval-phase failure AFTER approval + render start means the
        # video was likely generated (credits likely spent) but could not be harvested locally.
        # Report GENERATED_BUT_UNRETRIEVED (never plain FAILED) so a paid, completed video is not
        # presented as "no video". Pre-approval / pre-render errors stay FAILED.
        if job.get("approved") is True and generating and _is_retrieval_phase_error(msg):
            # B-15: split "video exists but could not be bound/retrieved" from
            # "no completed candidate ever materialized" — see the helper.
            _apply_post_approval_failure(job, msg)
        else:
            job.update(status="FAILED", error=msg, stage="failed")
            # C-4: a failure BEFORE approval never reached generation (the lane
            # refuses locally, or Google's anti-abuse layer rejects pre-approval —
            # e.g. RATE_LIMITED). After approval the provider may already have
            # charged, so it must never be reported as free.
            _stamp_credit(
                job,
                CREDIT_MAY_HAVE_SPENT
                if (job.get("approved") is True and generating)
                else CREDIT_NOT_SPENT,
            )
    finally:
        # Release the single-flight video lane (patch H).
        if _VIDEO_LANE_JOB == job_id:
            _VIDEO_LANE_JOB = None


async def _run_negotiate(job_id, prompt, image_prompt=None, dry=True,
                         model=None, duration_s=None, project_id=None,
                         reference_media_ids=None):
    from agent.api.flow import _generate_image_with_recovery  # lazy
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        if not project_id:
            job["status"], job["stage"] = "SETUP", "creating project"
            proj = await client.create_project("nego-test")
            project_id = _pid(proj)
            if not project_id:
                raise RuntimeError("no project")
        job["project_id"] = project_id
        media_ids = [str(media_id) for media_id in (reference_media_ids or []) if media_id]
        # Preserve the established pure-T2V adapter contract (`None` means no
        # media field) while carrying an existing reference list unchanged.
        media = media_ids or None
        if image_prompt and media:
            raise RuntimeError(
                "NEGOTIATION_REFERENCE_INPUT_AMBIGUOUS: use reference_media_ids "
                "or image_prompt, not both"
            )
        if image_prompt:  # optional start frame (skip for a pure T2V dry capture)
            job["stage"] = "start frame"
            img = await _generate_image_with_recovery(
                client, image_prompt, project_id, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
            mid = _deep(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
            if mid:
                media = [mid]
        job["reference_media_ids"] = list(media or [])
        job["stage"] = "session"
        sess = await client.create_agent_session(project_id)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        job["status"], job["stage"] = "NEGOTIATING", "negotiating"
        res = await agent_video.negotiate_and_generate(
            client, project_id, sid, prompt, media,
            target_model=model, target_duration_s=duration_s, approve=not dry)
        job["transcript"] = res.get("transcript")
        job["result"] = {k: v for k, v in res.items() if k != "transcript"}
        # Defense-in-depth: a dry capture MUST end on a would_approve proposal. If it instead
        # short-circuited to generation_started (no would_approve), fail loud rather than report
        # a clean DONE — that result is the wrong shape for I4a.
        if dry and "would_approve" not in res and res.get("generation_started"):
            job["status"], job["error"], job["stage"] = (
                "FAILED", "DRY_SHORT_CIRCUIT: generation_started without would_approve", "failed")
        else:
            job["status"], job["stage"] = "DONE", "done"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"


async def _run(job_id: str, prompt: str, image_prompt: str, product_id: str | None = None):
    from agent.api.flow import _generate_image_with_recovery  # lazy (avoid circular)
    job = _JOBS[job_id]
    client = get_flow_client()
    try:
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                product_id, lane="FLOW_MAKE_VIDEO_WORKER"
            )
        except ProductOperationalVisibilityError as exc:
            raise RuntimeError(f"{exc.code}:{exc}") from exc
        # 1) project
        job["status"], job["stage"] = "SETUP", "creating project"
        proj = await client.create_project("auto-video")
        pid = _pid(proj)
        if not pid:
            raise RuntimeError("no project")
        job["project_id"] = pid

        # 2) AI start frame
        job["stage"] = "generating start frame"
        img = await _generate_image_with_recovery(
            client, image_prompt, pid, "IMAGE_ASPECT_RATIO_PORTRAIT", "PAYGATE_TIER_ONE", [])
        media_id = _deep(img.get("data", img) if isinstance(img, dict) else {}, "name", "mediaId")
        if not media_id:
            raise RuntimeError("no start frame")

        # 3) agent session + negotiate + approve
        job["status"], job["stage"] = "NEGOTIATING", "agent negotiation"
        sess = await client.create_agent_session(pid)
        sid = _deep(sess.get("data", sess) if isinstance(sess, dict) else {}, "agentSessionId")
        if not sid:
            raise RuntimeError("no agent session")
        res = await agent_video.negotiate_and_generate(client, pid, sid, prompt, [media_id])
        if not res.get("ok"):
            raise RuntimeError("negotiation: " + str(res.get("error")))
        job["approved"] = True

        # 4) wait for the render, then navigate + harvest until the bytes are ready
        job["status"], job["stage"] = "GENERATING", "rendering (~5-8 min)"
        project_url = f"https://labs.google/fx/tools/flow/project/{pid}"
        await asyncio.sleep(150)  # the video takes minutes; don't poll too early
        for i in range(30):
            job["stage"] = f"checking for finished video (try {i + 1})"
            try:
                await client.open_target_flow_project(project_url)
            except Exception:
                pass
            await asyncio.sleep(12)
            h = await client.harvest_video_urls()
            inner = h.get("result", h) if isinstance(h, dict) else {}
            diag = inner.get("diag", inner) if isinstance(inner, dict) else {}
            mids = (diag.get("mediaIds") if isinstance(diag, dict) else None) or []
            for mid in mids:
                media = await client.get_media(mid)
                enc = _deep(media.get("data", media) if isinstance(media, dict) else {}, "encodedVideo")
                if enc:
                    vbytes = base64.b64decode(enc)
                    outdir = OUTPUT_DIR / "retrieved"
                    outdir.mkdir(parents=True, exist_ok=True)
                    path = outdir / f"{mid}.mp4"
                    path.write_bytes(vbytes)
                    job["status"], job["stage"] = "DONE", "done"
                    job["local_path"] = str(path)
                    job["video_media_id"] = mid
                    job["size_mb"] = round(len(vbytes) / 1024 / 1024, 2)
                    return
            await asyncio.sleep(18)
        job["status"], job["error"] = "FAILED", "video not ready/found in time"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"], job["stage"] = "FAILED", str(e), "failed"
