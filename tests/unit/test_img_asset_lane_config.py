"""IMG Asset Factory v1 — lane recipe governance invariants."""

import pytest

from agent.services.img_asset_lane_config import (
    IMG_ASSET_LANES,
    derive_asset_governance,
    get_img_asset_lane,
    list_img_asset_lanes,
    validate_img_lane_inputs,
)

VALID_ROLES = {
    "PRODUCT_REFERENCE",
    "CHARACTER_REFERENCE",
    "SCENE_CONTEXT_REFERENCE",
    "STYLE_REFERENCE",
    "COMPOSITE_FRAME_REFERENCE",
}
VALID_MODES = {"T2V", "F2V", "I2V", "IMG"}
VALID_SLOTS = {"subject", "scene", "style", "start_frame", "end_frame"}

EXPECTED_LANES = {
    "AVATAR_REFERENCE",
    "AVATAR_PRODUCT_COMPOSITE",
    "AVATAR_PRODUCT_SCENE_COMPOSITE",
    "PRODUCT_ONLY_HERO",
    "PRODUCT_POSTER",
    "SCENE_REFERENCE",
    "STYLE_REFERENCE",
}


def test_seven_lanes_present():
    assert set(IMG_ASSET_LANES) == EXPECTED_LANES
    assert len(list_img_asset_lanes()) == 7


def test_every_lane_uses_valid_roles_modes_slots():
    for lane in list_img_asset_lanes():
        assert lane["default_semantic_role"] in VALID_ROLES, lane["lane_id"]
        assert set(lane["default_allowed_modes"]) <= VALID_MODES, lane["lane_id"]
        assert set(lane["default_engine_slot_eligibility"]) <= VALID_SLOTS, lane["lane_id"]
        # lane_id key must match its dict key
        assert lane["lane_id"] in EXPECTED_LANES


def test_poster_lane_is_governed_terminal_asset():
    lane = get_img_asset_lane("PRODUCT_POSTER")
    assert lane["allows_rendered_text"] is True
    assert lane["default_contains_rendered_text"] is True
    assert lane["default_approved_for_poster"] is True
    assert lane["default_approved_for_video_support"] is False
    # allowed_modes MUST be a non-empty IMG-only list (NOT []) so the poster fails
    # the mode gate for F2V/I2V — empty lists are wildcard/permissive downstream.
    assert lane["default_allowed_modes"] == ["IMG"]
    assert "F2V" not in lane["default_allowed_modes"]
    assert "I2V" not in lane["default_allowed_modes"]
    assert lane["default_engine_slot_eligibility"] == []


def test_product_only_hero_is_not_an_f2v_frame():
    # A saved PRODUCT_REFERENCE asset is not a valid F2V start/end frame (the F2V
    # resolver accepts only COMPOSITE_FRAME_REFERENCE), so the lane must not
    # advertise F2V / start_frame eligibility.
    lane = get_img_asset_lane("PRODUCT_ONLY_HERO")
    assert lane["default_semantic_role"] == "PRODUCT_REFERENCE"
    assert "F2V" not in lane["default_allowed_modes"]
    assert "start_frame" not in lane["default_engine_slot_eligibility"]
    assert "end_frame" not in lane["default_engine_slot_eligibility"]


def test_composite_lanes_are_clean_f2v_frames():
    for lane_id in ("AVATAR_PRODUCT_COMPOSITE", "AVATAR_PRODUCT_SCENE_COMPOSITE"):
        lane = get_img_asset_lane(lane_id)
        assert lane["default_semantic_role"] == "COMPOSITE_FRAME_REFERENCE"
        assert lane["default_allowed_modes"] == ["F2V"]
        assert set(lane["default_engine_slot_eligibility"]) == {"start_frame", "end_frame"}
        assert lane["default_contains_rendered_text"] is False
        assert lane["default_approved_for_video_support"] is True
        assert lane["default_approved_for_poster"] is False


def test_reference_lanes_are_clean_and_role_correct():
    expected = {
        "AVATAR_REFERENCE": "CHARACTER_REFERENCE",
        "SCENE_REFERENCE": "SCENE_CONTEXT_REFERENCE",
        "STYLE_REFERENCE": "STYLE_REFERENCE",
        "PRODUCT_ONLY_HERO": "PRODUCT_REFERENCE",
    }
    for lane_id, role in expected.items():
        lane = get_img_asset_lane(lane_id)
        assert lane["default_semantic_role"] == role
        assert lane["default_contains_rendered_text"] is False
        assert lane["default_approved_for_poster"] is False


def test_unknown_lane_fails_closed():
    with pytest.raises(ValueError, match="UNSUPPORTED_IMG_LANE"):
        get_img_asset_lane("NOT_A_LANE")


def test_derive_governance_mirrors_lane():
    gov = derive_asset_governance("AVATAR_REFERENCE")
    assert gov["semantic_role"] == "CHARACTER_REFERENCE"
    assert gov["generation_recipe_id"] == "AVATAR_REFERENCE"
    assert gov["asset_subtype"] == "AVATAR_REFERENCE"
    assert "I2V" in gov["allowed_modes"]
    assert gov["contains_rendered_text"] is False


def test_derive_governance_poster_cannot_be_video_support():
    gov = derive_asset_governance("PRODUCT_POSTER")
    assert gov["contains_rendered_text"] is True
    assert gov["approved_for_poster"] is True
    assert gov["approved_for_video_support"] is False


def test_validate_lane_inputs_enforces_product_requirement():
    assert "PRODUCT_ID_REQUIRED" in validate_img_lane_inputs("PRODUCT_ONLY_HERO")
    assert validate_img_lane_inputs("PRODUCT_ONLY_HERO", product_id="prod-1") == []
    # generated-avatar lane never forces a product/character/scene reference.
    assert validate_img_lane_inputs("AVATAR_REFERENCE") == []
