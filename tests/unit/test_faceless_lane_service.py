"""Faceless lane fail-closed validation + resolution (no generation engine)."""
from agent.services import faceless_lane_service as fl
from agent.services import flow_mode_reference_contract as refc


def test_missing_product_fails_closed():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id=None,
        start_frame_asset_id="asset-1",
    )
    assert not ok
    assert code == fl.ERR_FACELESS_PRODUCT_REQUIRED
    assert "product" in detail.lower()


def test_missing_start_frame_fails_closed():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id="prod-1",
        start_frame_asset_id="",
    )
    assert not ok
    assert code == fl.ERR_FACELESS_START_FRAME_REQUIRED
    assert "start frame" in detail.lower() or "image" in detail.lower()


def test_valid_minimal_inputs_pass():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id="prod-1",
        start_frame_asset_id="asset-start",
        hook_id="AUTO",
        background_id="AUTO",
    )
    assert ok, detail
    assert code is None


def test_invalid_hook_fails_closed():
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="prod-1",
        start_frame_asset_id="asset-start",
        hook_id="FAKE_HOOK",
    )
    assert not ok
    assert code is not None


def test_reference_count_uses_existing_f2v_contract():
    # 0 refs invalid for FRAMES
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="p",
        start_frame_asset_id="a",
        reference_count=0,
    )
    assert not ok
    assert code == refc.ERR_REFERENCE_COUNT_CONTRACT

    # 3 refs invalid for FRAMES
    ok2, code2, _ = fl.validate_faceless_inputs(
        product_id="p",
        start_frame_asset_id="a",
        reference_count=3,
    )
    assert not ok2
    assert code2 == refc.ERR_REFERENCE_COUNT_CONTRACT


def test_resolution_defaults_faceless_no_avatar():
    res = fl.build_faceless_resolution(hook_id="AUTO", background_id="KITCHEN")
    assert res["lane"] == "FACELESS"
    assert res["transport_mode"] == "F2V"
    assert res["source_mode"] == "FRAMES"
    assert res["character_presence"] == "FACELESS"
    assert res["avatar_id"] is None
    assert res["hook"]["setting_id"] == "GENERAL_USP_PRODUCT"
    assert res["background"]["setting_id"] == "KITCHEN"
    assert res["scene_context_override"]


def test_package_fields_are_one_door_compatible():
    res = fl.build_faceless_resolution(hook_id="GENERAL_USP_PRODUCT", background_id="AUTO")
    fields = fl.build_faceless_package_fields(res)
    assert fields["mode"] == "F2V"
    assert fields["source_mode"] == "FRAMES"
    assert fields["character_presence"] == "FACELESS"
    assert fields["avatar_id"] is None
    assert fields["faceless_lane"]["hook_resolved"] == "GENERAL_USP_PRODUCT"
    assert fields["faceless_lane"]["background_resolved"] == "AESTHETIC_TABLE"
