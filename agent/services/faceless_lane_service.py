"""Faceless Video lane — preset + fail-closed validation over the shared one-door.

No new generation engine. Surface uses F2V transport with a product/scene start
frame (image → single clip). Avatar default = NONE (true faceless).
"""
from __future__ import annotations

from typing import Any, Optional

from agent.services import creative_lane_settings_service as cls
from agent.services import flow_mode_reference_contract as refc

FACELESS_SURFACE_MODE = "FACELESS"
FACELESS_TRANSPORT_MODE = "F2V"
FACELESS_SOURCE_MODE = "FRAMES"
FACELESS_CHARACTER_PRESENCE = "FACELESS"

ERR_FACELESS_PRODUCT_REQUIRED = "ERR_FACELESS_PRODUCT_REQUIRED"
ERR_FACELESS_START_FRAME_REQUIRED = "ERR_FACELESS_START_FRAME_REQUIRED"
ERR_FACELESS_REFERENCE_CONTRACT = "ERR_FACELESS_REFERENCE_CONTRACT"


def validate_faceless_inputs(
    *,
    product_id: Optional[str],
    start_frame_asset_id: Optional[str],
    hook_id: Optional[str] = None,
    background_id: Optional[str] = None,
    reference_count: Optional[int] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Fail-closed gate before package prepare / generate.

    Returns (ok, error_code, human_detail).
    """
    if not str(product_id or "").strip():
        return False, ERR_FACELESS_PRODUCT_REQUIRED, (
            "Faceless requires a product — select a product before prepare/generate"
        )
    if not str(start_frame_asset_id or "").strip():
        return False, ERR_FACELESS_START_FRAME_REQUIRED, (
            "Faceless requires a product or scene image as the start frame "
            "(image-first → single clip). Bind an approved image reference first."
        )

    ok_h, code_h, detail_h = cls.validate_hook(hook_id)
    if not ok_h:
        return False, code_h, detail_h
    ok_b, code_b, detail_b = cls.validate_background(background_id)
    if not ok_b:
        return False, code_b, detail_b

    # Faceless is F2V/FRAMES: 1–2 refs. Default path uses exactly the start frame.
    count = 1 if reference_count is None else int(reference_count)
    ok_r, code_r, detail_r = refc.validate_reference_count(
        FACELESS_TRANSPORT_MODE, count, source_mode=FACELESS_SOURCE_MODE,
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
    return {
        "lane": FACELESS_SURFACE_MODE,
        "transport_mode": FACELESS_TRANSPORT_MODE,
        "source_mode": FACELESS_SOURCE_MODE,
        "character_presence": FACELESS_CHARACTER_PRESENCE,
        "avatar_id": None,
        "hook": hook,
        "background": background,
        # Environment intent for package scene_context_override (visual only).
        "scene_context_override": background.get("environment_intent") or None,
    }


def build_faceless_package_fields(resolution: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to pass into create_workspace_execution_package."""
    return {
        "mode": resolution["transport_mode"],
        "source_mode": resolution["source_mode"],
        "character_presence": resolution["character_presence"],
        "avatar_id": None,
        "scene_context_override": resolution.get("scene_context_override"),
        # Reproducibility stamp (metadata only; not a parallel schema).
        "faceless_lane": {
            "hook_operator": resolution["hook"]["operator_selection"],
            "hook_resolved": resolution["hook"]["setting_id"],
            "hook_resolution": resolution["hook"]["resolution"],
            "background_operator": resolution["background"]["operator_selection"],
            "background_resolved": resolution["background"]["setting_id"],
            "background_resolution": resolution["background"]["resolution"],
        },
    }
