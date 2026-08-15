"""Faceless lane — product-first Hybrid parity validation."""
import pytest

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


def test_opening_strategy_never_mutates_actual_copy_authority():
    approved_copy = {"hook": "Mak selalu cari yang senang guna setiap hari..."}
    first = fl.build_faceless_resolution(
        hook_id="AUTO",
        background_id="AUTO",
    )
    second = fl.build_faceless_resolution(
        hook_id="PENAT_KEJAR_PROMO",
        background_id="AUTO",
    )
    assert first["opening_strategy"]["setting_id"] != second["opening_strategy"][
        "setting_id"
    ]
    assert approved_copy == {"hook": "Mak selalu cari yang senang guna setiap hari..."}
    assert "hook" not in (first.get("faceless_resolution") or {})
    assert "hook" not in (second.get("faceless_resolution") or {})


@pytest.mark.asyncio
async def test_scene_authority_resolves_faceless_receipt_and_concrete_auto_background(
    monkeypatch: pytest.MonkeyPatch,
):
    product = {
        "id": "prod-oil",
        "name": "Minyak Warisan Cap Burung 25ml",
        "raw_product_title": "Minyak Warisan Cap Burung 25ml",
        "product_type": "TRADITIONAL_HERBAL_OIL",
        "product_physics": "TRADITIONAL_HERBAL_OIL_BOTTLE",
    }

    async def _get_product(_: str):
        return product

    monkeypatch.setattr(fl.crud, "get_product", _get_product)
    authority = await fl.resolve_faceless_scene_authority(
        product_id="prod-oil",
        hook_id="AUTO",
        background_id="AUTO",
    )
    resolution = fl.build_faceless_resolution(
        hook_id="AUTO",
        background_id="AUTO",
        scene_authority=authority,
    )
    receipt = resolution["faceless_resolution"]
    assert receipt["opening_strategy_operator"] == "AUTO"
    assert receipt["opening_strategy_resolved"] == "GENERAL_USP_PRODUCT"
    assert receipt["background_resolved"] != "AUTO"
    assert receipt["scene_strategy_id"] == "TRADITIONAL_HERBAL_OIL"
    assert receipt["choreography_id"] == "traditional_herbal_oil.v0"
    assert receipt["choreography_schema_version"] == "scene_choreography_v2"
    assert len(receipt["choreography_sha256"]) == 64
    assert receipt["character_presence"] == "FACELESS"
    assert receipt["compatibility_status"] == "COMPATIBLE"


@pytest.mark.asyncio
async def test_incompatible_background_fails_before_any_provider_boundary(
    monkeypatch: pytest.MonkeyPatch,
):
    product = {
        "id": "prod-oil",
        "name": "Minyak Warisan Cap Burung 25ml",
        "raw_product_title": "Minyak Warisan Cap Burung 25ml",
        "product_type": "TRADITIONAL_HERBAL_OIL",
        "product_physics": "TRADITIONAL_HERBAL_OIL_BOTTLE",
    }

    async def _get_product(_: str):
        return product

    monkeypatch.setattr(fl.crud, "get_product", _get_product)
    with pytest.raises(ValueError, match=fl.cls.ERR_FACELESS_BACKGROUND_INCOMPATIBLE):
        await fl.resolve_faceless_scene_authority(
            product_id="prod-oil",
            background_id="KITCHEN",
        )
