"""Faceless Video lane — product-first preset over the shared one-door.

Operator surface = Hybrid product path WITHOUT avatar / visible face.
Internal transport reuses F2V + HYBRID product-anchor lineage (approved package
start_frame from product truth). Operator never selects F2V/FRAMES/startAsset.

Visual law: no face; hands/arms/torso OK with face out of frame; product locked.
"""
from __future__ import annotations

from typing import Any, Optional

from agent.db import crud
from agent.services import creative_lane_settings_service as cls
from agent.services import flow_mode_reference_contract as refc
from agent.services.scene_choreography_catalog import select_variant_for_strategy
from agent.services.scene_strategy_library import (
    resolve_scene_strategy,
    select_scene_strategy_variant,
)

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
ERR_FACELESS_PRODUCT_NOT_FOUND = "ERR_FACELESS_PRODUCT_NOT_FOUND"
ERR_FACELESS_SCENE_STRATEGY_REQUIRED = "ERR_FACELESS_SCENE_STRATEGY_REQUIRED"


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

    ok_h, code_h, detail_h = cls.validate_opening_strategy(hook_id)
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
    scene_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve opening/background and stamp authority metadata.

    ``hook`` remains a response/wire alias for existing callers. Production
    Faceless requests pass ``scene_authority`` from the async product resolver;
    the authority receipt is kept separate from Copy Register V2 text.
    """
    opening_strategy = cls.resolve_opening_strategy(
        hook_id,
        product_cluster=product_cluster,
        has_approved_usp=has_approved_usp,
    )
    if scene_authority:
        opening_strategy = scene_authority.get("opening_strategy") or opening_strategy
        background = scene_authority.get("background") or cls.resolve_background(
            background_id,
            scene_context_hint=scene_context_hint,
            compatible_contexts=scene_authority.get("compatible_contexts"),
        )
    else:
        background = cls.resolve_background(
            background_id,
            scene_context_hint=scene_context_hint,
        )
    override = bool(str(start_frame_asset_id or "").strip())
    source_mode = (
        FACELESS_OVERRIDE_SOURCE_MODE if override else FACELESS_SOURCE_MODE
    )
    scene_strategy = (scene_authority or {}).get("scene_strategy")
    choreography = (scene_authority or {}).get("choreography")
    receipt = _faceless_resolution_receipt(
        opening_strategy=opening_strategy,
        background=background,
        scene_strategy=scene_strategy,
        choreography=choreography,
    )
    resolution = {
        "lane": FACELESS_SURFACE_MODE,
        "transport_mode": FACELESS_TRANSPORT_MODE,
        "source_mode": source_mode,
        "character_presence": FACELESS_CHARACTER_PRESENCE,
        "avatar_id": None,
        "opening_strategy": opening_strategy,
        # Backward-compatible response/wire alias. This is never Copy V2 text.
        "hook": opening_strategy,
        "background": background,
        "scene_strategy": scene_strategy,
        "choreography": choreography,
        "compatible_background_options": (scene_authority or {}).get(
            "background_options", []
        ),
        "compatible_contexts": (scene_authority or {}).get(
            "compatible_contexts", []
        ),
        "scene_context_override": background.get("environment_intent") or None,
        "reference_override": override,
        "visual_law": FACELESS_VISUAL_LAW,
    }
    if receipt is not None:
        resolution["faceless_resolution"] = receipt
    return resolution


def _faceless_resolution_receipt(
    *,
    opening_strategy: dict[str, Any],
    background: dict[str, Any],
    scene_strategy: dict[str, Any] | None,
    choreography: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not scene_strategy or not choreography:
        return None
    return {
        "opening_strategy_operator": opening_strategy["operator_selection"],
        "opening_strategy_resolved": opening_strategy["setting_id"],
        "background_operator": background["operator_selection"],
        "background_resolved": background["setting_id"],
        "scene_strategy_id": scene_strategy["scene_strategy_id"],
        "choreography_id": choreography["choreography_id"],
        "choreography_schema_version": choreography[
            "choreography_schema_version"
        ],
        "choreography_sha256": choreography["choreography_sha256"],
        "character_presence": FACELESS_CHARACTER_PRESENCE,
        "compatibility_status": "COMPATIBLE",
    }


async def resolve_faceless_scene_authority(
    *,
    product_id: str,
    hook_id: Optional[str] = None,
    background_id: Optional[str] = None,
    product_cluster: Optional[str] = None,
    has_approved_usp: bool = False,
    scene_context_hint: Optional[str] = None,
    variation_index: int = 0,
) -> dict[str, Any]:
    """Resolve Product → Scene Strategy → compatible Choreography → Background."""

    product = await crud.get_product(str(product_id).strip())
    if not product:
        raise ValueError(
            f"{ERR_FACELESS_PRODUCT_NOT_FOUND}: product_id={product_id}"
        )
    strategy = resolve_scene_strategy(product)
    if (
        strategy["fallback_used"]
        or strategy["strategy_id"] == "GENERIC_FALLBACK"
    ):
        raise ValueError(
            f"{ERR_FACELESS_SCENE_STRATEGY_REQUIRED}: "
            "Product Truth did not resolve a production Scene Strategy"
        )

    # Select through the existing Scene Choreography V2 catalog. The explicit
    # character gate is also enforced again by the canonical compiler.
    variant = select_variant_for_strategy(
        strategy["strategy_id"],
        variation_index,
        character_presence=FACELESS_CHARACTER_PRESENCE,
    )
    selected = select_scene_strategy_variant(
        strategy,
        variation_index,
        character_presence=FACELESS_CHARACTER_PRESENCE,
    )
    scene_receipt = {
        "scene_strategy_id": selected["scene_strategy_id"],
        "resolution_source": strategy["resolution_source"],
        "fallback_used": bool(strategy["fallback_used"]),
    }
    compatible_contexts = list(variant.compatible_contexts)
    background = cls.resolve_background(
        background_id,
        scene_context_hint=scene_context_hint,
        compatible_contexts=compatible_contexts,
    )
    return {
        "product": product,
        "opening_strategy": cls.resolve_opening_strategy(
            hook_id,
            product_cluster=product_cluster,
            has_approved_usp=has_approved_usp,
        ),
        "background": background,
        "background_options": cls.background_options_for_contexts(
            compatible_contexts
        ),
        "compatible_contexts": compatible_contexts,
        "scene_strategy": scene_receipt,
        "choreography": selected,
    }


def build_faceless_scene_context(resolution: dict[str, Any]) -> str:
    """Compiler-facing context: RESOLVED settings + faceless visual law. Never raw AUTO."""
    opening_strategy = resolution.get("opening_strategy") or resolution["hook"]
    bg = resolution["background"]
    env = str(bg.get("environment_intent") or "").strip()
    strategy = str(
        opening_strategy.get("strategy_intent")
        or opening_strategy.get("display_label")
        or ""
    ).strip()
    scene = resolution.get("scene_strategy") or {}
    choreography = resolution.get("choreography") or {}
    parts = [
        FACELESS_VISUAL_LAW,
        (
            f"Opening strategy {opening_strategy['setting_id']}: {strategy}."
            if strategy
            else ""
        ),
        f"Environment {bg['setting_id']}: {env}." if env else (
            f"Environment={bg['setting_id']} ({bg['display_label']})."
        ),
        (
            f"Scene Strategy {scene['scene_strategy_id']}; choreography "
            f"{choreography['choreography_id']} ({choreography['choreography_schema_version']}) "
            f"sha256={choreography['choreography_sha256']}; "
            "character presence compatibility=COMPATIBLE."
            if scene and choreography
            else ""
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
            "opening_strategy_operator": resolution["opening_strategy"][
                "operator_selection"
            ],
            "opening_strategy_resolved": resolution["opening_strategy"]["setting_id"],
            # Compatibility aliases for older package consumers.
            "hook_operator": resolution["hook"]["operator_selection"],
            "hook_resolved": resolution["hook"]["setting_id"],
            "hook_resolution": resolution["hook"]["resolution"],
            "background_operator": resolution["background"]["operator_selection"],
            "background_resolved": resolution["background"]["setting_id"],
            "background_resolution": resolution["background"]["resolution"],
            "source_mode": resolution["source_mode"],
            "visual_law": FACELESS_VISUAL_LAW,
        },
        "faceless_resolution": resolution.get("faceless_resolution"),
    }
