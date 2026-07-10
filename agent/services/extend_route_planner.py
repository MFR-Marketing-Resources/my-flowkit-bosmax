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
