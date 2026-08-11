"""Faceless lane — product-first Hybrid parity validation."""
from agent.services import faceless_lane_service as fl


def test_missing_product_fails_closed():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id=None,
        model="Veo 3.1 - Lite",
        generation_mode="SINGLE",
        duration_seconds=8,
    )
    assert not ok
    assert code == fl.ERR_FACELESS_PRODUCT_REQUIRED
    assert "product" in detail.lower()


def test_product_only_path_does_not_require_start_frame():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="Veo 3.1 - Lite",
        generation_mode="SINGLE",
        duration_seconds=8,
        hook_id="AUTO",
        background_id="AUTO",
    )
    assert ok, detail
    assert code is None


def test_missing_model_fails_closed():
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="",
        generation_mode="SINGLE",
        duration_seconds=8,
    )
    assert not ok
    assert code == fl.ERR_FACELESS_MODEL_REQUIRED


def test_missing_duration_fails_closed():
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="Omni Flash",
        generation_mode="SINGLE",
        duration_seconds=None,
    )
    assert not ok
    assert code == fl.ERR_FACELESS_DURATION_INVALID


def test_extend_requires_total():
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="Veo 3.1 - Lite",
        generation_mode="EXTEND",
        total_duration_seconds=None,
    )
    assert not ok
    assert code == fl.ERR_FACELESS_EXTEND_TOTAL_REQUIRED


def test_advanced_override_requires_start_frame():
    ok, code, detail = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="Veo 3.1 - Lite",
        generation_mode="SINGLE",
        duration_seconds=8,
        reference_override=True,
        start_frame_asset_id="",
    )
    assert not ok
    assert code == fl.ERR_FACELESS_START_FRAME_REQUIRED


def test_invalid_hook_fails_closed():
    ok, code, _ = fl.validate_faceless_inputs(
        product_id="prod-1",
        model="Veo 3.1 - Lite",
        generation_mode="SINGLE",
        duration_seconds=8,
        hook_id="FAKE_HOOK",
    )
    assert not ok
    assert code is not None


def test_resolution_defaults_hybrid_product_anchor_no_avatar():
    res = fl.build_faceless_resolution(hook_id="AUTO", background_id="KITCHEN")
    assert res["lane"] == "FACELESS"
    assert res["transport_mode"] == "F2V"
    assert res["source_mode"] == "HYBRID"
    assert res["character_presence"] == "FACELESS"
    assert res["avatar_id"] is None
    assert res["hook"]["setting_id"] == "GENERAL_USP_PRODUCT"
    assert res["background"]["setting_id"] == "KITCHEN"
    assert "no visible human face" in res["visual_law"].lower()


def test_override_resolution_uses_frames():
    res = fl.build_faceless_resolution(
        hook_id="AUTO",
        background_id="AUTO",
        start_frame_asset_id="ca_frame_1",
    )
    assert res["source_mode"] == "FRAMES"
    assert res["reference_override"] is True


def test_scene_context_never_raw_auto_and_has_visual_law():
    res = fl.build_faceless_resolution(hook_id="AUTO", background_id="AUTO")
    ctx = fl.build_faceless_scene_context(res)
    assert "AUTO (AI decided)" not in ctx
    assert "Auto (AI decided)" not in ctx
    assert "VISUAL LAW" in ctx
    assert "face" in ctx.lower()
    assert res["hook"]["setting_id"] != "AUTO"


def test_package_fields_are_one_door_compatible():
    res = fl.build_faceless_resolution(hook_id="GENERAL_USP_PRODUCT", background_id="AUTO")
    fields = fl.build_faceless_package_fields(res)
    assert fields["mode"] == "F2V"
    assert fields["source_mode"] == "HYBRID"
    assert fields["character_presence"] == "FACELESS"
    assert fields["avatar_id"] is None
    assert fields["faceless_lane"]["hook_resolved"] == "GENERAL_USP_PRODUCT"
