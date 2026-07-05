"""IMG Asset Factory v1 — lane / recipe governance authority.

This is the single source of truth for what each IMG lane produces and how the
resulting Creative Library asset is governed. It mirrors the shape of
``i2v_slot_recipe_config.py`` (data + tiny lookups) so the two engine-side
recipe systems stay consistent.

A "lane" answers, for one IMG intent, the load-bearing governance questions:
  - which Creative Library ``semantic_role`` the saved asset gets,
  - which downstream video modes (``allowed_modes``) may reuse it,
  - which engine slots (``engine_slot_eligibility``) it may fill — deliberately
    set to the UNION of slots each role can map to across the I2V recipes
    (``i2v_slot_recipe_config``) plus F2V start/end, so the shared
    ``validate_selectable_asset`` engine-slot gate never false-blocks a
    correctly-lane-produced asset,
  - whether rendered text (poster copy) is allowed, and
  - the default poster / video-support classification.

The governance defaults here are AUTHORITATIVE at save time: an operator cannot
mislabel a poster (rendered text) as a clean video-support frame, because the
save path derives these fields from the lane, not from free operator input.
"""

from __future__ import annotations

from typing import Any


# Semantic roles a lane can assign — must stay a subset of
# ``CreativeAssetSemanticRole`` in agent/models/creative_asset.py.
IMG_ASSET_LANES: dict[str, dict[str, Any]] = {
    "AVATAR_REFERENCE": {
        "lane_id": "AVATAR_REFERENCE",
        "label": "Avatar Reference",
        "family": "AVATAR",
        "purpose": (
            "Generate a reusable AI avatar identity image. Saved as a character "
            "reference that anchors the same person across I2V jobs."
        ),
        "required_inputs": ["Avatar profile (generated from character fields)"],
        "optional_inputs": ["Scene context (text)", "Style context (text)"],
        "requires_product_id": False,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "CHARACTER_REFERENCE",
        "default_asset_subtype": "AVATAR_REFERENCE",
        "default_allowed_modes": ["I2V", "IMG"],
        "default_engine_slot_eligibility": ["subject", "scene"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
    "AVATAR_PRODUCT_COMPOSITE": {
        "lane_id": "AVATAR_PRODUCT_COMPOSITE",
        "label": "Avatar + Product Composite",
        "family": "COMPOSITE",
        "purpose": (
            "Combine an AI avatar with the product into one clean composite "
            "frame usable as an F2V start / end frame."
        ),
        "required_inputs": ["Database product"],
        "optional_inputs": ["Character reference image", "Scene context (text)"],
        "requires_product_id": True,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "COMPOSITE_FRAME_REFERENCE",
        "default_asset_subtype": "CLEAN_COMPOSITE_FRAME",
        "default_allowed_modes": ["F2V"],
        "default_engine_slot_eligibility": ["start_frame", "end_frame"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
    "AVATAR_PRODUCT_SCENE_COMPOSITE": {
        "lane_id": "AVATAR_PRODUCT_SCENE_COMPOSITE",
        "label": "Avatar + Product + Scene Composite",
        "family": "COMPOSITE",
        "purpose": (
            "Combine avatar, product, and scene/environment into one clean "
            "composite frame usable as an F2V start / end frame."
        ),
        "required_inputs": ["Database product"],
        "optional_inputs": [
            "Character reference image",
            "Scene context reference image",
            "Style context (text)",
        ],
        "requires_product_id": True,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "COMPOSITE_FRAME_REFERENCE",
        "default_asset_subtype": "CLEAN_COMPOSITE_FRAME",
        "default_allowed_modes": ["F2V"],
        "default_engine_slot_eligibility": ["start_frame", "end_frame"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
    "PRODUCT_ONLY_HERO": {
        "lane_id": "PRODUCT_ONLY_HERO",
        "label": "Product-Only Hero",
        "family": "PRODUCT",
        "purpose": (
            "Clean product hero image with label/scale truth preserved. Reusable "
            "as an I2V product reference or an F2V start frame."
        ),
        "required_inputs": ["Database product"],
        "optional_inputs": ["Scene context (text)", "Style context (text)"],
        "requires_product_id": True,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "PRODUCT_REFERENCE",
        "default_asset_subtype": "PRODUCT_HERO",
        "default_allowed_modes": ["I2V", "F2V", "IMG"],
        "default_engine_slot_eligibility": ["subject", "scene", "start_frame"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
    "PRODUCT_POSTER": {
        "lane_id": "PRODUCT_POSTER",
        "label": "Product Poster Ad",
        "family": "POSTER",
        "purpose": (
            "Commercial poster ad with rendered headline / copy / CTA. A terminal "
            "marketing asset — NOT a clean video-support frame by default."
        ),
        "required_inputs": ["Database product"],
        "optional_inputs": ["Approved copy set", "Scene context (text)"],
        "requires_product_id": True,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "COMPOSITE_FRAME_REFERENCE",
        "default_asset_subtype": "POSTER_AD",
        "default_allowed_modes": [],
        "default_engine_slot_eligibility": [],
        "allows_rendered_text": True,
        "default_contains_rendered_text": True,
        "default_approved_for_video_support": False,
        "default_approved_for_poster": True,
    },
    "SCENE_REFERENCE": {
        "lane_id": "SCENE_REFERENCE",
        "label": "Scene / Environment Reference",
        "family": "SCENE",
        "purpose": (
            "Generate a scene / environment reference image reusable as an I2V "
            "scene-context reference."
        ),
        "required_inputs": ["Scene context (text or reference image)"],
        "optional_inputs": ["Style context (text)"],
        "requires_product_id": False,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "SCENE_CONTEXT_REFERENCE",
        "default_asset_subtype": "SCENE_REFERENCE",
        "default_allowed_modes": ["I2V", "IMG"],
        "default_engine_slot_eligibility": ["scene", "style"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
    "STYLE_REFERENCE": {
        "lane_id": "STYLE_REFERENCE",
        "label": "Style / Mood Reference",
        "family": "STYLE",
        "purpose": (
            "Generate a style / mood reference image reusable as an I2V style "
            "reference layer."
        ),
        "required_inputs": ["Style context (text or reference image)"],
        "optional_inputs": [],
        "requires_product_id": False,
        "requires_character_reference": False,
        "requires_scene_reference": False,
        "requires_style_reference": False,
        "default_semantic_role": "STYLE_REFERENCE",
        "default_asset_subtype": "STYLE_REFERENCE",
        "default_allowed_modes": ["I2V", "IMG"],
        "default_engine_slot_eligibility": ["style"],
        "allows_rendered_text": False,
        "default_contains_rendered_text": False,
        "default_approved_for_video_support": True,
        "default_approved_for_poster": False,
    },
}


def list_img_asset_lanes() -> list[dict[str, Any]]:
    """Return every IMG lane recipe (dashboard lane picker + API)."""
    return list(IMG_ASSET_LANES.values())


def get_img_asset_lane(lane_id: str) -> dict[str, Any]:
    """Return one lane recipe or fail closed on an unknown lane."""
    lane = IMG_ASSET_LANES.get(lane_id)
    if lane is None:
        raise ValueError("UNSUPPORTED_IMG_LANE")
    return lane


def derive_asset_governance(lane_id: str) -> dict[str, Any]:
    """Lane-authoritative governance applied to a saved Creative Library asset.

    Returns the exact ``semantic_role`` / ``allowed_modes`` /
    ``engine_slot_eligibility`` / rendered-text / poster classification the save
    path must stamp. Callers must NOT let operator input override these.
    """
    lane = get_img_asset_lane(lane_id)
    return {
        "generation_recipe_id": lane["lane_id"],
        "asset_subtype": lane["default_asset_subtype"],
        "semantic_role": lane["default_semantic_role"],
        "allowed_modes": list(lane["default_allowed_modes"]),
        "engine_slot_eligibility": list(lane["default_engine_slot_eligibility"]),
        "contains_rendered_text": bool(lane["default_contains_rendered_text"]),
        "approved_for_video_support": bool(lane["default_approved_for_video_support"]),
        "approved_for_poster": bool(lane["default_approved_for_poster"]),
    }


def validate_img_lane_inputs(
    lane_id: str,
    *,
    product_id: str | None = None,
    character_reference_asset_id: str | None = None,
    scene_reference_asset_id: str | None = None,
    style_reference_asset_id: str | None = None,
) -> list[str]:
    """Return lane input blockers (empty list == inputs satisfy the lane)."""
    lane = get_img_asset_lane(lane_id)
    blockers: list[str] = []
    if lane["requires_product_id"] and not product_id:
        blockers.append("PRODUCT_ID_REQUIRED")
    if lane["requires_character_reference"] and not character_reference_asset_id:
        blockers.append("CHARACTER_REFERENCE_REQUIRED")
    if lane["requires_scene_reference"] and not scene_reference_asset_id:
        blockers.append("SCENE_REFERENCE_REQUIRED")
    if lane["requires_style_reference"] and not style_reference_asset_id:
        blockers.append("STYLE_REFERENCE_REQUIRED")
    return blockers
