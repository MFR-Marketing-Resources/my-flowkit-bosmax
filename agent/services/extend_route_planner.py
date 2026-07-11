"""Route-aware EXTEND block-plan authority (storyboard-first planner contract).

Layers a ROUTE CAPABILITY model on top of the workbook block-plan authority
(`canonical_prompt_compiler.resolve_block_plan`). Production EXTEND block plans MUST
come from an AUTHORIZED route; routes without captured runtime evidence FAIL CLOSED
with ``ROUTE_DURATION_AUTHORITY_MISSING`` — the planner never silently invents a plan.

Owner decision (2026-07-10): public Veo API docs are DESIGN REFERENCE ONLY. Production
authority must come from internal route evidence / captured Flow behaviour / explicit
workbook authority. ``GOOGLE_FLOW_VEO_EXTEND`` (the public-API 8+7n model) has NO captured
aisandbox/Flow runtime evidence in this checkout, so it is DECLARED but AUTHORITY_MISSING
(fail closed, pending evidence). The only currently-authorized multi-block route is the
workbook-backed independent-block plan (Google Flow uniform 8s/10s blocks).
"""
from __future__ import annotations

from typing import Any

from agent.services import canonical_prompt_compiler as _canonical

ROUTE_DURATION_AUTHORITY_MISSING = "ROUTE_DURATION_AUTHORITY_MISSING"

AUTHORIZED = "AUTHORIZED"
AUTHORITY_MISSING = "AUTHORITY_MISSING"

# route_id -> capability.
#   authority     : AUTHORIZED (workbook-backed) | AUTHORITY_MISSING (fail closed)
#   plan_engine   : workbook engine whose block-plan table backs an authorized route
#   preferred_lane: lane hint forwarded to resolve_block_plan (disambiguates Flow 40s)
#   multi_block   : True => drives EXTEND; False => single-generation surface (declared
#                   for explicit messaging, not a multi-block extend route)
ROUTE_REGISTRY: dict[str, dict[str, Any]] = {
    "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS": {
        "authority": AUTHORIZED,
        "plan_engine": "GOOGLE_FLOW",
        "preferred_lane": "8s",
        "multi_block": True,
    },
    "GOOGLE_FLOW_VEO_EXTEND": {
        "authority": AUTHORITY_MISSING,
        "plan_engine": "GOOGLE_FLOW",
        "preferred_lane": None,
        "multi_block": True,
        "pending_reason": (
            "No captured aisandbox/Flow VEO-extend runtime evidence in this checkout; "
            "8+7n is public-Veo-API-only and the public API != Flow UI."
        ),
    },
    "GROK_INDEPENDENT_BLOCKS": {
        "authority": AUTHORIZED,
        "plan_engine": "GROK",
        "preferred_lane": None,
        "multi_block": True,
    },
    # Single-generation surfaces — NOT multi-block extend routes (declared so callers
    # that mis-route an EXTEND request get an explicit, non-silent rejection).
    "GOOGLE_FLOW_FIRST_LAST_FRAME": {
        "authority": AUTHORIZED, "plan_engine": "GOOGLE_FLOW", "multi_block": False,
    },
    "GOOGLE_FLOW_REFERENCE_IMAGE": {
        "authority": AUTHORIZED, "plan_engine": "GOOGLE_FLOW", "multi_block": False,
    },
}

_DEFAULT_ROUTE_BY_ENGINE = {
    "GOOGLE_FLOW": "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
    "GROK": "GROK_INDEPENDENT_BLOCKS",
}


class RouteDurationAuthorityMissing(ValueError):
    """Raised when an EXTEND block plan is requested for a route that has no captured
    runtime/authority evidence. Fail closed — never fall back to a manual plan."""

    def __init__(self, route_id: str, reason: str = "") -> None:
        self.route_id = route_id
        self.reason = reason
        message = f"{ROUTE_DURATION_AUTHORITY_MISSING}:{route_id}"
        if reason:
            message = f"{message}:{reason}"
        super().__init__(message)


def normalize_route(route_id: str | None) -> str | None:
    if not route_id:
        return None
    return str(route_id).strip().upper()


def default_route_for_engine(engine: str | None) -> str:
    """The only currently-authorized multi-block route for the given workbook engine."""
    eng = str(engine or "GOOGLE_FLOW").strip().upper().replace(" ", "_")
    return _DEFAULT_ROUTE_BY_ENGINE.get(eng, "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS")


def resolve_route_block_plan(
    route_id: str,
    total_duration_seconds: int,
    *,
    preferred_lane: str | None = None,
) -> list[int]:
    """Resolve a TOTAL duration to an authority-backed block plan for the route.

    Raises:
        UNKNOWN_EXTEND_ROUTE          — route not declared
        ROUTE_NOT_MULTI_BLOCK         — single-generation surface asked for an extend plan
        RouteDurationAuthorityMissing — route declared but has no runtime authority
        UNSUPPORTED_EXTEND_TOTAL_DURATION_<n> — total not representable in the workbook
    """
    route_id = normalize_route(route_id) or ""
    cap = ROUTE_REGISTRY.get(route_id)
    if cap is None:
        raise ValueError(f"UNKNOWN_EXTEND_ROUTE:{route_id}")
    if not cap.get("multi_block", False):
        raise ValueError(f"ROUTE_NOT_MULTI_BLOCK:{route_id}")
    if cap.get("authority") != AUTHORIZED:
        raise RouteDurationAuthorityMissing(route_id, cap.get("pending_reason", ""))
    lane = preferred_lane or cap.get("preferred_lane")
    try:
        return _canonical.resolve_block_plan(
            cap["plan_engine"], int(total_duration_seconds), preferred_lane=lane,
        )
    except ValueError as exc:
        # Normalize the workbook's engine-level miss to the EXTEND-total vocabulary
        # (parity with the #294 total path); other workbook errors (PREFERRED_LANE_*)
        # surface unchanged.
        if str(exc).startswith("UNSUPPORTED_ENGINE_DURATION"):
            raise ValueError(
                f"UNSUPPORTED_EXTEND_TOTAL_DURATION_{int(total_duration_seconds)}"
            ) from exc
        raise


def segment_timeline(plan: list[int]) -> list[dict[str, Any]]:
    """Storyboard timeline metadata: absolute [start_s, end_s) per block + is_final."""
    segments: list[dict[str, Any]] = []
    cursor = 0
    total = len(plan)
    for index, seconds in enumerate(plan, start=1):
        start = cursor
        end = cursor + int(seconds)
        segments.append(
            {
                "block_index": index,
                "start_s": start,
                "end_s": end,
                "is_final": index == total,
            }
        )
        cursor = end
    return segments


# ─── Native-Extend CAPABILITY authority (a SECOND, orthogonal axis) ──────────
# TWO-AXIS RULE (do not conflate):
#   * ROUTE authority (ROUTE_REGISTRY above) = block-DURATION math. It answers
#     "may this route turn a total duration into a block plan?" The public-API
#     8+7n route `GOOGLE_FLOW_VEO_EXTEND` stays AUTHORITY_MISSING forever here —
#     native extend borrows its durations from the already-AUTHORIZED
#     `GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS` workbook (uniform 8s), NOT from 8+7n.
#   * CAPABILITY authority (below) = which RUNTIME aisandbox operations are proven
#     by CAPTURED wire evidence. AUTHORIZED here means "we have the exact request
#     contract"; it does NOT relax any route/duration gate.
# Flipping a route flag and proving a transport capability are different acts;
# keeping them separate is what lets native extend ship while 8+7n stays closed.
CAPTURE_EVIDENCE_SUBMIT = "CAPTURE_20260711_094742"   # extend request/response/poll
CAPTURE_EVIDENCE_RETRIEVE = "CAPTURE_20260711_100555"  # scene/workflows + media retrieval
CAPTURE_EVIDENCE_DOWNLOAD = "CAPTURE_20260711_102244"  # Download Project ZIP

NATIVE_EXTEND_CAPABILITIES: dict[str, dict[str, Any]] = {
    "GOOGLE_FLOW_NATIVE_EXTEND_REQUEST": {
        "authority": AUTHORIZED,
        "rpc": "POST /v1/video:batchAsyncGenerateVideoExtendVideo",
        "evidence": CAPTURE_EVIDENCE_SUBMIT,
    },
    "GOOGLE_FLOW_EXTEND_CHILD_POLLING": {
        "authority": AUTHORIZED,
        "rpc": "POST /v1/video:batchCheckAsyncVideoGenerationStatus {media:[{name,projectId}]}",
        "evidence": CAPTURE_EVIDENCE_SUBMIT,
    },
    "GOOGLE_FLOW_EXTEND_LINEAGE": {
        "authority": AUTHORIZED,
        "evidence": CAPTURE_EVIDENCE_SUBMIT,
    },
    "GOOGLE_FLOW_PER_BLOCK_MEDIA_RETRIEVAL": {
        "authority": AUTHORIZED,
        "rpc": "GET /v1/media/{id} (get_media); trpc media.getMediaUrlRedirect -> signed flow-content.google",
        "evidence": CAPTURE_EVIDENCE_RETRIEVE,
    },
    "GOOGLE_FLOW_DOWNLOAD_PROJECT_ZIP": {
        "authority": AUTHORIZED,
        "rpc": "client-side ZIP blob of per-workflow media (NO server export/concat)",
        "evidence": CAPTURE_EVIDENCE_DOWNLOAD,
    },
    # CAPTURED end-to-end (concat_completion_smoke_20260711_100555 rid=9924.2526/
    # 2540/2542): submit runVideoFxConcatenation {inputVideos[mediaGenerationId,
    # length(ns), start/endTimeOffset]} -> {operation{operation{name: .../jobs/<id>}}};
    # poll runVideoFxCheckConcatenationStatus (submit response verbatim) ->
    # ACTIVE -> SUCCESSFUL with the ONE combined MP4 delivered INLINE in
    # ``encodedVideo`` (mediaGenerationId/outputUri empty). Execution stays gated
    # behind dry-run-default + explicit live confirmation; the Download Project ZIP
    # is still NEVER a substitute for this deliverable.
    "GOOGLE_FLOW_FINAL_CONCAT_EXPORT": {
        "authority": AUTHORIZED,
        "rpc": ("POST /v1:runVideoFxConcatenation; "
                "POST /v1:runVideoFxCheckConcatenationStatus -> encodedVideo inline"),
        "evidence": "CAPTURE_20260711_100555:rid=9924.2526/2540/2542",
    },
}


class CapabilityAuthorityMissing(ValueError):
    """Raised when a native-extend RUNTIME capability without captured evidence is
    required. Fail closed — never substitute a different capability (e.g. Download
    Project ZIP for final concat export)."""

    def __init__(self, capability_id: str, error_code: str | None = None,
                 reason: str = "") -> None:
        self.capability_id = capability_id
        self.error_code = error_code or "CAPABILITY_AUTHORITY_MISSING"
        self.reason = reason
        message = f"{self.error_code}:{capability_id}"
        if reason:
            message = f"{message}:{reason}"
        super().__init__(message)


def capability_authority(capability_id: str) -> str:
    """AUTHORIZED / AUTHORITY_MISSING for a native-extend capability.

    Raises ``UNKNOWN_NATIVE_EXTEND_CAPABILITY:{id}`` for an undeclared capability.
    """
    cid = normalize_route(capability_id) or ""
    cap = NATIVE_EXTEND_CAPABILITIES.get(cid)
    if cap is None:
        raise ValueError(f"UNKNOWN_NATIVE_EXTEND_CAPABILITY:{capability_id}")
    return cap["authority"]


def require_capability(capability_id: str) -> dict[str, Any]:
    """Return the capability record iff AUTHORIZED, else fail closed.

    Raises:
        UNKNOWN_NATIVE_EXTEND_CAPABILITY:{id} — undeclared capability
        CapabilityAuthorityMissing            — declared but not AUTHORIZED
    """
    cid = normalize_route(capability_id) or ""
    cap = NATIVE_EXTEND_CAPABILITIES.get(cid)
    if cap is None:
        raise ValueError(f"UNKNOWN_NATIVE_EXTEND_CAPABILITY:{capability_id}")
    if cap.get("authority") != AUTHORIZED:
        raise CapabilityAuthorityMissing(
            cid, cap.get("error_code"), cap.get("pending_reason", ""))
    return cap


# Route id the operator surface uses for a native-extend continuation. Native extend
# BORROWS its uniform-8s durations from the AUTHORIZED independent-block workbook —
# it is NOT the 8+7n route `GOOGLE_FLOW_VEO_EXTEND` (which stays AUTHORITY_MISSING).
NATIVE_EXTEND_ROUTE_ID = "GOOGLE_FLOW_NATIVE_EXTEND"
_NATIVE_EXTEND_DURATION_ROUTE = "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS"


def resolve_native_extend_execution(
    *,
    parent_operation_id: str | None,
    project_id: str | None,
    scene_id: str | None,
    planned_block_count: int = 0,
    planned_operation_count: int | None = None,
    total_duration_seconds: int | None = None,
) -> dict[str, Any]:
    """THE single deterministic resolver for "can native extend run, and what blocks
    apply?". One truth for the UI, the API and the planner — so they can never
    disagree (UI enabled / planner blocked / API silently runs / route unsupported).

    Returns a consolidated, machine-readable decision with the EXACT blockers. Never
    authorizes the unverified final concat export.
    """
    blockers: list[str] = []

    transport_proven = capability_authority("GOOGLE_FLOW_NATIVE_EXTEND_REQUEST") == AUTHORIZED
    if not transport_proven:
        blockers.append("EXTEND_RUNTIME_CONTRACT_MISSING")

    parent_ready = bool(parent_operation_id)
    if not parent_ready:
        blockers.append("EXTEND_PARENT_MEDIA_ID_MISSING")
    project_ready = bool(project_id)
    if not project_ready:
        blockers.append("EXTEND_PROJECT_CONTEXT_MISSING")
    scene_ready = bool(scene_id)
    if not scene_ready:
        blockers.append("EXTEND_SCENE_CONTEXT_MISSING")

    duration_plan_authorized = True
    block_plan: list[int] | None = None
    if total_duration_seconds:
        try:
            block_plan = resolve_route_block_plan(
                _NATIVE_EXTEND_DURATION_ROUTE, int(total_duration_seconds))
        except (ValueError, RouteDurationAuthorityMissing) as exc:
            duration_plan_authorized = False
            blockers.append(str(exc).split(":")[0])

    final_concat_available = (
        capability_authority("GOOGLE_FLOW_FINAL_CONCAT_EXPORT") == AUTHORIZED)

    route_executable = not blockers
    return {
        "route_id": NATIVE_EXTEND_ROUTE_ID,
        "transport_proven": transport_proven,
        "duration_plan_authorized": duration_plan_authorized,
        "block_plan": block_plan,
        "parent_ready": parent_ready,
        "project_ready": project_ready,
        "scene_ready": scene_ready,
        "project_scene_ready": project_ready and scene_ready,
        "route_executable": route_executable,
        "final_concat_export_available": final_concat_available,
        "model_key": "veo_3_1_extension_lite",
        "block_duration_seconds": 8,
        "planned_block_count": planned_block_count,
        "planned_operation_count": (
            planned_operation_count if planned_operation_count is not None
            else planned_block_count),
        "blockers": blockers,
    }
