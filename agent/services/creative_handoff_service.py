"""Creative Intelligence — Round 5: gated generation handoff PREVIEW.

The single APPROVED-ONLY boundary between the Round 4 planning artifact
(``creative_product_selection``) and any future generation. This service:
  * reads ONLY an ``APPROVED`` creative selection (DRAFT/REJECTED/missing/invalid
    are fail-closed);
  * resolves ``[AVATAR]`` (via the sanctioned ``avatar_registry.presenter_prose``)
    and ``[PRODUCT]`` (product display name) at THIS boundary only;
  * returns a read-only PREVIEW payload (chosen avatar + scene template + camera
    preset + product identity + provenance) explicitly labelled
    ``auto_generated=False`` / ``requires_confirmation=True``.

Hard safety: it NEVER calls a generation provider, DeepSeek, ``make_video.start_generate``,
the canonical compiler, a production queue, or credit-burn; it creates no generated
assets; and it WRITES NOTHING to any table. It only READS the Round 4 selection plus
the existing avatar/scene/camera libraries. Placeholders are resolved solely inside
the returned ``resolved_prompt_preview`` string — the raw template is preserved
unresolved alongside it.
"""
from __future__ import annotations

from typing import Any

from agent.services import avatar_registry
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera

HANDOFF_SOURCE = "CREATIVE_HANDOFF_v1"

_HANDOFF_NOTE = (
    "Generation handoff PREVIEW only. No image/video generation, credits, "
    "production-queue insertion, or generated assets are produced here. Explicit "
    "user confirmation and the existing credit-burn gate are required before any "
    "generation. Placeholders are resolved only in this preview."
)


def _scene_index() -> dict[str, dict[str, Any]]:
    return {t["template_id"]: t for t in _scene.library_templates()}


def _camera_index() -> dict[str, dict[str, Any]]:
    return {p["preset_code"]: p for p in _camera.named_presets()}


async def prepare_generation_handoff(product_id: str) -> dict[str, Any]:
    """Prepare a read-only generation handoff preview from an APPROVED selection.

    Fail-closed error codes (mapped to HTTP by the API):
      PRODUCT_NOT_FOUND / SELECTION_NOT_FOUND -> 404
      SELECTION_NOT_APPROVED (DRAFT or REJECTED) -> 409
      INVALID_AVATAR_CODE / INVALID_SCENE_TEMPLATE_ID / INVALID_CAMERA_PRESET_CODE -> 422
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    selection = await crud.get_creative_product_selection(product_id)
    if not selection:
        raise ValueError("SELECTION_NOT_FOUND")
    if selection.get("status") != "APPROVED":
        # blocks DRAFT and REJECTED — only user-approved plans may hand off
        raise ValueError("SELECTION_NOT_APPROVED")

    avatar_code = selection.get("selected_avatar_code")
    scene_id = selection.get("selected_scene_template_id")
    camera_code = selection.get("selected_camera_preset_code")

    # Re-validate the chosen ids at the boundary (fail-closed).
    try:
        avatar_profile = avatar_registry.resolve_presenter(avatar_id=avatar_code) if avatar_code else None
    except ValueError as exc:
        raise ValueError("INVALID_AVATAR_CODE") from exc
    scene = _scene_index().get(scene_id) if scene_id else None
    if scene_id and not scene:
        raise ValueError("INVALID_SCENE_TEMPLATE_ID")
    camera = _camera_index().get(camera_code) if camera_code else None
    if camera_code and not camera:
        raise ValueError("INVALID_CAMERA_PRESET_CODE")

    # Resolve placeholders ONLY at this handoff boundary.
    product_name = product.get("product_display_name") or product.get("raw_product_title") or ""
    avatar_prose = avatar_registry.presenter_prose(avatar_profile) if avatar_profile else ""
    raw_template = (scene or {}).get("full_prompt_template") or ""
    resolved_prompt_preview = raw_template
    if avatar_prose:
        resolved_prompt_preview = resolved_prompt_preview.replace("[AVATAR]", avatar_prose)
    if product_name:
        resolved_prompt_preview = resolved_prompt_preview.replace("[PRODUCT]", product_name)

    return {
        "product_id": product_id,
        "product_name": product_name,
        "selection_id": selection.get("selection_id"),
        "selection_status": selection.get("status"),
        "cluster": selection.get("cluster"),
        "cluster_source": selection.get("cluster_source"),
        "avatar": {
            "avatar_code": avatar_code,
            "character_name": (avatar_profile or {}).get("character_name"),
            "resolved_descriptor": avatar_prose or None,
        },
        "scene_template": {
            "template_id": scene_id,
            "variant": (scene or {}).get("variant"),
            "main_action": (scene or {}).get("main_action"),
            "setting": (scene or {}).get("setting"),
            "raw_prompt_template": raw_template or None,  # preserved unresolved
        },
        "camera_preset": {
            "preset_code": camera_code,
            "preset_name": (camera or {}).get("preset_name"),
            "shot_type": (camera or {}).get("shot_type"),
            "distance_angle": (camera or {}).get("distance_angle"),
            "movement": (camera or {}).get("movement"),
        },
        "resolved_prompt_preview": resolved_prompt_preview or None,
        "placeholders_resolved": {
            "[AVATAR]": bool(avatar_prose),
            "[PRODUCT]": bool(product_name),
        },
        "provenance": {
            "source": HANDOFF_SOURCE,
            "selection_id": selection.get("selection_id"),
            "from_service": "creative_setup_service (Round 4 APPROVED selection)",
        },
        "auto_generated": False,
        "requires_confirmation": True,
        "handoff_status": "PREVIEW_ONLY_REQUIRES_CONFIRMATION",
        "note": _HANDOFF_NOTE,
    }
