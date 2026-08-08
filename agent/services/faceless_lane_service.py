"""Faceless Video lane — product-first preset over the shared one-door.

Operator surface = Hybrid product path WITHOUT avatar / visible face.
Internal transport reuses F2V + HYBRID product-anchor lineage (approved package
start_frame from product truth). Operator never selects F2V/FRAMES/startAsset.

Visual law: no face; hands/arms/torso OK with face out of frame; product locked.
"""
from __future__ import annotations

from typing import Any, Optional

from agent.services import creative_lane_settings_service as cls
from agent.services import flow_mode_reference_contract as refc

FACELESS_SURFACE_MODE = "FACELESS"
# Internal one-door only — never operator chrome
FACELESS_TRANSPORT_MODE = "F2V"
# Product-first: approved product package supplies the start_frame anchor
FACELESS_SOURCE_MODE = "HYBRID"
FACELESS_CHARACTER_PRESENCE = "FACELESS"

# Advanced override only
FACELESS_OVERRIDE_SOURCE_MODE = "FRAMES"

ERR_FACELESS_PRODUCT_REQUIRED = "ERR_FACELESS_PRODUCT_REQUIRED"
ERR_FACELESS_START_FRAME_REQUIRED = "ERR_FACELESS_START_FRAME_REQUIRED"
ERR_FACELESS_REFERENCE_CONTRACT = "ERR_FACELESS_REFERENCE_CONTRACT"
ERR_FACELESS_MODEL_REQUIRED = "ERR_FACELESS_MODEL_REQUIRED"
ERR_FACELESS_MODEL_UNSUPPORTED = "ERR_FACELESS_MODEL_UNSUPPORTED"
ERR_FACELESS_MODE_INVALID = "ERR_FACELESS_MODE_INVALID"
ERR_FACELESS_DURATION_INVALID = "ERR_FACELESS_DURATION_INVALID"
ERR_FACELESS_MODEL_DURATION_UNSUPPORTED = "ERR_FACELESS_MODEL_DURATION_UNSUPPORTED"
ERR_FACELESS_EXTEND_TOTAL_REQUIRED = "ERR_FACELESS_EXTEND_TOTAL_REQUIRED"


def resolve_faceless_video_configuration(
    *,
    model: Optional[str],
    generation_mode: Optional[str],
    duration_seconds: Optional[int] = None,
    total_duration_seconds: Optional[int] = None,
) -> tuple[bool, Optional[str], Optional[str], Optional[dict[str, Any]]]:
    """Resolve the selected Faceless tuple through shared video authorities.

    SINGLE uses the operator capability matrix (the same matrix exposed by the
    dashboard). EXTEND uses the shared video-model registry's proven totals and
    the existing native-Extend route authority. No Faceless-local model or
    duration table is permitted here.
    """
    mode = str(generation_mode or "SINGLE").strip().upper()
    try:
        from agent.services import video_models as vm

        if mode == "SINGLE":
            duration = int(duration_seconds) if duration_seconds is not None else 0
            from agent.services import video_capability_matrix as cm

            ok, code = cm.validate_single("GOOGLE_FLOW", model, duration)
            if not ok:
                if code in (cm.ERR_UNSUPPORTED_ENGINE_MODEL,):
                    return False, ERR_FACELESS_MODEL_UNSUPPORTED, code, None
                return False, ERR_FACELESS_MODEL_DURATION_UNSUPPORTED, code, None
            orchestration = vm.resolve_orchestration(model, duration)
            return True, None, None, orchestration

        if mode == "EXTEND":
            total = int(total_duration_seconds) if total_duration_seconds is not None else 0
            orchestration = vm.resolve_orchestration(model, total)
            if orchestration.get("generation_mode") != "EXTEND":
                return (
                    False,
                    ERR_FACELESS_MODEL_DURATION_UNSUPPORTED,
                    "selected model/total is not an authorized EXTEND tuple",
                    None,
                )
            from agent.services import extend_route_planner as routes

            duration_authority = routes.resolve_native_extend_execution(
                parent_operation_id=None,
                project_id=None,
                scene_id=None,
                total_duration_seconds=total,
            )
            if not duration_authority.get("duration_plan_authorized"):
                return (
                    False,
                    ERR_FACELESS_MODEL_DURATION_UNSUPPORTED,
                    "selected total is not authorized by the native-Extend route",
                    None,
                )
            return True, None, None, orchestration
    except (TypeError, ValueError) as exc:
        if "unknown video model" in str(exc).lower():
            return False, ERR_FACELESS_MODEL_UNSUPPORTED, str(exc), None
        return False, ERR_FACELESS_MODEL_DURATION_UNSUPPORTED, str(exc), None

    return False, ERR_FACELESS_MODE_INVALID, f"unsupported generation mode: {mode}", None

FACELESS_VISUAL_LAW = (
    "VISUAL LAW (FACELESS): No visible human face and no AI presenter face. "
    "Hands, arms, and torso may appear with the head and face kept out of frame. "
    "The person may hold, interact with, demonstrate, or gently move the product. "
    "Product identity and packaging remain locked and authoritative. "
    "No invented claims, endorsements, or medical authority."
)


def validate_faceless_inputs(
    *,
    product_id: Optional[str],
    start_frame_asset_id: Optional[str] = None,
    end_frame_asset_id: Optional[str] = None,
    hook_id: Optional[str] = None,
    background_id: Optional[str] = None,
    model: Optional[str] = None,
    generation_mode: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    total_duration_seconds: Optional[int] = None,
    require_model: bool = True,
    reference_override: bool = False,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Fail-closed gate before package prepare / generate.

    Normal path: product only (+ settings). Start frame is NOT required unless
    Advanced reference override is active (FRAMES).
    """
    if not str(product_id or "").strip():
        return False, ERR_FACELESS_PRODUCT_REQUIRED, (
            "Faceless requires a product — select a product before prepare/generate"
        )

    gen_mode = str(generation_mode or "SINGLE").strip().upper()
    if gen_mode not in ("SINGLE", "EXTEND"):
        return False, ERR_FACELESS_MODE_INVALID, (
            f"generation_mode must be SINGLE or EXTEND, got {generation_mode!r}"
        )

    if require_model and not str(model or "").strip():
        return False, ERR_FACELESS_MODEL_REQUIRED, (
            "Select a video model (canonical capability authority)"
        )

    if gen_mode == "SINGLE":
        try:
            d = int(duration_seconds) if duration_seconds is not None else 0
        except (TypeError, ValueError):
            d = 0
        if d <= 0:
            return False, ERR_FACELESS_DURATION_INVALID, (
                "Select a clip duration from the canonical model options"
            )
    else:
        try:
            total = int(total_duration_seconds) if total_duration_seconds is not None else 0
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            return False, ERR_FACELESS_EXTEND_TOTAL_REQUIRED, (
                "EXTEND requires an authorized total duration from capability authority"
            )

    ok_video, code_video, detail_video, _ = resolve_faceless_video_configuration(
        model=model,
        generation_mode=gen_mode,
        duration_seconds=duration_seconds,
        total_duration_seconds=total_duration_seconds,
    )
    if not ok_video:
        return False, code_video, detail_video

    ok_h, code_h, detail_h = cls.validate_hook(hook_id)
    if not ok_h:
        return False, code_h, detail_h
    ok_b, code_b, detail_b = cls.validate_background(background_id)
    if not ok_b:
        return False, code_b, detail_b

    # Reference contract: HYBRID product-anchor = 1 product ref (default).
    # Advanced FRAMES override requires explicit start frame.
    if reference_override or str(start_frame_asset_id or "").strip():
        if not str(start_frame_asset_id or "").strip():
            return False, ERR_FACELESS_START_FRAME_REQUIRED, (
                "Advanced reference override requires a start-frame asset"
            )
        count = 2 if str(end_frame_asset_id or "").strip() else 1
        ok_r, code_r, detail_r = refc.validate_reference_count(
            FACELESS_TRANSPORT_MODE,
            count,
            source_mode=FACELESS_OVERRIDE_SOURCE_MODE,
        )
        if not ok_r:
            return False, code_r or ERR_FACELESS_REFERENCE_CONTRACT, detail_r
    else:
        ok_r, code_r, detail_r = refc.validate_reference_count(
            FACELESS_TRANSPORT_MODE,
            1,
            source_mode=FACELESS_SOURCE_MODE,
        )
        if not ok_r:
            return False, code_r or ERR_FACELESS_REFERENCE_CONTRACT, detail_r

    return True, None, None


def build_faceless_resolution(
    *,
    hook_id: Optional[str] = None,
    background_id: Optional[str] = None,
    product_cluster: Optional[str] = None,
    has_approved_usp: bool = False,
    scene_context_hint: Optional[str] = None,
    start_frame_asset_id: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve Hook/Background and stamp reproducibility metadata."""
    hook = cls.resolve_hook(
        hook_id,
        product_cluster=product_cluster,
        has_approved_usp=has_approved_usp,
    )
    background = cls.resolve_background(
        background_id,
        scene_context_hint=scene_context_hint,
    )
    override = bool(str(start_frame_asset_id or "").strip())
    source_mode = (
        FACELESS_OVERRIDE_SOURCE_MODE if override else FACELESS_SOURCE_MODE
    )
    return {
        "lane": FACELESS_SURFACE_MODE,
        "transport_mode": FACELESS_TRANSPORT_MODE,
        "source_mode": source_mode,
        "character_presence": FACELESS_CHARACTER_PRESENCE,
        "avatar_id": None,
        "hook": hook,
        "background": background,
        "scene_context_override": background.get("environment_intent") or None,
        "reference_override": override,
        "visual_law": FACELESS_VISUAL_LAW,
    }


def build_faceless_scene_context(resolution: dict[str, Any]) -> str:
    """Compiler-facing context: RESOLVED settings + faceless visual law. Never raw AUTO."""
    hook = resolution["hook"]
    bg = resolution["background"]
    env = str(bg.get("environment_intent") or "").strip()
    strategy = str(hook.get("strategy_intent") or hook.get("display_label") or "").strip()
    parts = [
        FACELESS_VISUAL_LAW,
        f"Strategy {hook['setting_id']}: {strategy}." if strategy else "",
        f"Environment {bg['setting_id']}: {env}." if env else (
            f"Environment={bg['setting_id']} ({bg['display_label']})."
        ),
        "Creative strategy and environment intent only — no invented claims, "
        "endorsements, or product-truth overrides.",
    ]
    return " ".join(p for p in parts if p)


def build_faceless_package_fields(resolution: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to pass into create_workspace_execution_package."""
    return {
        "mode": resolution["transport_mode"],
        "source_mode": resolution["source_mode"],
        "character_presence": resolution["character_presence"],
        "avatar_id": None,
        "scene_context_override": resolution.get("scene_context_override"),
        "faceless_lane": {
            "hook_operator": resolution["hook"]["operator_selection"],
            "hook_resolved": resolution["hook"]["setting_id"],
            "hook_resolution": resolution["hook"]["resolution"],
            "background_operator": resolution["background"]["operator_selection"],
            "background_resolved": resolution["background"]["setting_id"],
            "background_resolution": resolution["background"]["resolution"],
            "source_mode": resolution["source_mode"],
            "visual_law": FACELESS_VISUAL_LAW,
        },
    }
