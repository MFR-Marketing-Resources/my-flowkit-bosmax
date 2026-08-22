"""Active video-surface identity separated from internal transport details.

The operator-facing production lanes are intentionally smaller than the logical
video modes used by the Flow transport.  This module is the single normalizer
used at durable artifact/result boundaries so a Hybrid job may retain F2V as
transport metadata without being presented as an F2V production lane.
"""
from __future__ import annotations

from typing import Any, Mapping


ACTIVE_SURFACE_LANES = frozenset(
    {"HYBRID", "FACELESS", "MONTAGE", "PRODUCTION_STUDIO_P6"}
)

SURFACE_LABELS = {
    "HYBRID": "Hybrid",
    "FACELESS": "Faceless Video",
    "MONTAGE": "Montage",
    "PRODUCTION_STUDIO_P6": "Production Studio / P6",
}

_SURFACE_ALIASES = {
    "P6": "PRODUCTION_STUDIO_P6",
    "PRODUCTION_STUDIO": "PRODUCTION_STUDIO_P6",
    "PRODUCTION_STUDIO_P6": "PRODUCTION_STUDIO_P6",
    "FACELESS_VIDEO": "FACELESS",
}


class VideoSurfaceProvenanceError(ValueError):
    """Raised when a caller tries to use an internal mode as a surface lane."""

    code = "ACTIVE_SURFACE_LANE_REQUIRED"


def normalize_surface_lane(value: Any) -> str | None:
    """Return a canonical active surface or ``None`` for an untyped legacy row."""

    token = str(value or "").strip().upper().replace("-", "_")
    if not token:
        return None
    token = _SURFACE_ALIASES.get(token, token)
    if token in ACTIVE_SURFACE_LANES:
        return token
    raise VideoSurfaceProvenanceError(
        f"{VideoSurfaceProvenanceError.code}:{value} is an internal or unknown video mode"
    )


def _candidate_lane(value: Any) -> str | None:
    """Read an active lane candidate without promoting internal mode names."""

    token = str(value or "").strip().upper().replace("-", "_")
    if not token:
        return None
    token = _SURFACE_ALIASES.get(token, token)
    return token if token in ACTIVE_SURFACE_LANES else None


def resolve_surface_lane(
    *,
    explicit: Any = None,
    mode: Any = None,
    source_mode: Any = None,
    copy_lane: Any = None,
    execution_identity: Mapping[str, Any] | None = None,
    package: Mapping[str, Any] | None = None,
    existing: Mapping[str, Any] | None = None,
    execution_mode: Any = None,
) -> str | None:
    """Resolve active-surface identity without confusing it with transport mode.

    Explicit ``surface_lane`` is strict.  Untyped historical/programmatic rows
    remain ``None`` and are displayed as Legacy/Internal or Unknown Surface.
    """

    if str(explicit or "").strip():
        return normalize_surface_lane(explicit)
    identity = execution_identity if isinstance(execution_identity, Mapping) else {}
    package_map = package if isinstance(package, Mapping) else {}
    existing_map = existing if isinstance(existing, Mapping) else {}
    for candidate in (
        identity.get("surface_lane"),
        package_map.get("surface_lane"),
        existing_map.get("surface_lane"),
        copy_lane,
    ):
        resolved = _candidate_lane(candidate)
        if resolved:
            return resolved

    mode_token = str(mode or "").strip().upper().replace("-", "_")
    source_token = str(source_mode or "").strip().upper().replace("-", "_")
    execution_token = str(execution_mode or "").strip().upper().replace("-", "_")
    identity_lane = str(identity.get("lane") or "").strip().upper().replace("-", "_")
    if mode_token == "FACELESS" or identity_lane == "FACELESS":
        return "FACELESS"
    if mode_token == "MONTAGE":
        return "MONTAGE"
    if mode_token in {"P6", "PRODUCTION_STUDIO", "PRODUCTION_STUDIO_P6"}:
        return "PRODUCTION_STUDIO_P6"
    if source_token == "HYBRID":
        return "HYBRID"
    if "HYBRID" in execution_token:
        return "HYBRID"
    return None


def provider_generation_type(
    *,
    mode: Any = None,
    source_mode: Any = None,
    routing_receipt: Mapping[str, Any] | None = None,
    direct_plan: Mapping[str, Any] | None = None,
    existing: Any = None,
) -> str | None:
    """Return observed/declared provider generation type, never a surface label."""

    for mapping in (routing_receipt, direct_plan):
        if isinstance(mapping, Mapping):
            value = mapping.get("provider_generation_type") or mapping.get("gen_type")
            if value:
                return str(value)
    if isinstance(existing, Mapping):
        value = existing.get("provider_generation_type")
        if value:
            return str(value)
    mode_token = str(mode or "").strip().upper()
    source_token = str(source_mode or "").strip().upper()
    if mode_token in {"T2V"} and not source_token:
        return "text_to_video"
    if source_token in {"HYBRID", "FRAMES", "INGREDIENTS"}:
        return "reference_frame_2_video"
    return None


def build_video_surface_provenance(
    *,
    surface_lane: Any = None,
    transport_mode: Any = None,
    source_mode: Any = None,
    provider_type: Any = None,
    mode: Any = None,
    copy_lane: Any = None,
    execution_identity: Mapping[str, Any] | None = None,
    package: Mapping[str, Any] | None = None,
    execution_mode: Any = None,
    routing_receipt: Mapping[str, Any] | None = None,
    direct_plan: Mapping[str, Any] | None = None,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """Build the four-field provenance tuple persisted with a video result."""

    effective_mode = transport_mode or mode
    effective_source = source_mode
    if not effective_source and isinstance(existing, Mapping):
        effective_source = existing.get("source_mode") or existing.get("initial_source_mode")
    existing_mode = None
    if isinstance(existing, Mapping):
        existing_mode = existing.get("initial_mode") or existing.get("mode")
    surface = resolve_surface_lane(
        explicit=surface_lane,
        mode=mode or existing_mode,
        source_mode=effective_source,
        copy_lane=copy_lane,
        execution_identity=execution_identity,
        package=package,
        existing=existing,
        execution_mode=execution_mode,
    )
    provider = provider_type or provider_generation_type(
        mode=effective_mode,
        source_mode=effective_source,
        routing_receipt=routing_receipt,
        direct_plan=direct_plan,
        existing=existing,
    )
    return {
        "surface_lane": surface,
        "transport_mode": str(effective_mode).upper() if effective_mode else None,
        "source_mode": str(effective_source).upper() if effective_source else None,
        "provider_generation_type": provider,
    }


def surface_display_label(surface_lane: Any, *, mode: Any = None) -> str:
    """Safe user-facing label; internal mode is never used as an active lane."""

    resolved = _candidate_lane(surface_lane)
    if resolved:
        return SURFACE_LABELS[resolved]
    return "Legacy/Internal" if mode else "Unknown Surface"
