"""SSOT Hook/Background settings — controlled vocab + deterministic AUTO."""
import pytest

from agent.services import creative_lane_settings_service as cls
from agent.services.scene_choreography_catalog import all_choreography_variants


def test_hook_options_match_owner_vocabulary():
    labels = {o["label"] for o in cls.hook_options()}
    assert "Auto (AI decided)" in labels
    assert "Penat Kejar Promo" in labels
    assert "Finally Dapat Less" in labels
    assert "Nangis Mak-Mak" in labels
    assert "Baru Launch Discount" in labels
    assert "Diskaun Disbelief" in labels
    assert "General (USP Product)" in labels
    assert cls.hook_default() == "AUTO"


def test_background_options_match_owner_vocabulary():
    labels = {o["label"] for o in cls.background_options()}
    assert "Auto (AI decided)" in labels
    assert "Dalam kereta" in labels
    assert "Laman rumah" in labels
    assert "Aesthetic Table" in labels
    assert "Pharmacy" in labels
    assert "Kitchen" in labels
    assert "Rumah aesthetic" in labels
    assert cls.background_default() == "AUTO"


def test_unknown_hook_fails_closed():
    ok, code, detail = cls.validate_hook("NOT_A_REAL_HOOK")
    assert not ok
    assert code == cls.ERR_UNKNOWN_HOOK
    assert "controlled vocabulary" in detail


def test_unknown_background_fails_closed():
    ok, code, detail = cls.validate_background("MARS_BASE")
    assert not ok
    assert code == cls.ERR_UNKNOWN_BACKGROUND


def test_auto_hook_resolves_deterministically_without_llm():
    resolved = cls.resolve_hook("AUTO")
    assert resolved["operator_selection"] == "AUTO"
    assert resolved["setting_id"] == "GENERAL_USP_PRODUCT"
    assert resolved["resolution"] == "AUTO_DETERMINISTIC"
    assert resolved["claim_authority"] == "PRODUCT_TRUTH_ONLY"
    assert resolved["display_label"] == "General (USP Product)"


def test_explicit_hook_preserved():
    resolved = cls.resolve_hook("NANGIS_MAK_MAK")
    assert resolved["setting_id"] == "NANGIS_MAK_MAK"
    assert resolved["resolution"] == "EXPLICIT"
    assert "empathy" in resolved["strategy_intent"].lower() or resolved["strategy_intent"]


def test_auto_background_hint_mapping():
    car = cls.resolve_background("AUTO", scene_context_hint="inside kereta cabin")
    assert car["setting_id"] == "DALAM_KERETA"
    assert car["resolution"] == "AUTO_DETERMINISTIC"
    assert car["product_truth_override"] is False

    neutral = cls.resolve_background("AUTO", scene_context_hint=None)
    assert neutral["setting_id"] == "AESTHETIC_TABLE"


def test_background_resolution_is_constrained_by_existing_scene_contexts():
    contexts = [
        "warm heritage tabletop with the bottle label visible",
        "bedside shelf during a quiet nightly routine",
    ]
    eligible = cls.compatible_background_ids(contexts)
    assert eligible
    assert "AESTHETIC_TABLE" in eligible
    assert "KITCHEN" not in eligible

    auto = cls.resolve_background("AUTO", compatible_contexts=contexts)
    assert auto["operator_selection"] == "AUTO"
    assert auto["setting_id"] != "AUTO"
    assert auto["setting_id"] in eligible

    explicit = cls.resolve_background(
        "AESTHETIC_TABLE",
        compatible_contexts=contexts,
    )
    assert explicit["setting_id"] == "AESTHETIC_TABLE"
    with pytest.raises(ValueError, match=cls.ERR_FACELESS_BACKGROUND_INCOMPATIBLE):
        cls.resolve_background("KITCHEN", compatible_contexts=contexts)


def test_public_payload_exposes_opening_strategy_without_removing_wire_alias():
    payload = cls.public_settings_payload()
    assert payload["opening_strategy"]["default"] == "AUTO"
    assert payload["opening_strategy"]["options"] == payload["hook"]["options"]


def test_every_production_choreography_has_a_controlled_background_match():
    for strategy_id, variants in all_choreography_variants().items():
        for variant in variants:
            assert cls.compatible_background_ids(variant.compatible_contexts), (
                strategy_id,
                variant.choreography_id,
            )


def test_pharmacy_is_environment_only():
    bg = cls.resolve_background("PHARMACY")
    assert bg["setting_id"] == "PHARMACY"
    assert "endorsement" in bg["environment_intent"].lower() or "visual" in bg["environment_intent"].lower()
    assert bg["product_truth_override"] is False


def test_public_payload_shape():
    payload = cls.public_settings_payload()
    assert payload["hook"]["default"] == "AUTO"
    assert payload["background"]["default"] == "AUTO"
    assert payload["source"].endswith("creative_lane_settings.json")
    assert len(payload["hook"]["options"]) == 7
    assert len(payload["background"]["options"]) == 7
