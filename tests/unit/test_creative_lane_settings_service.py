"""SSOT Hook/Background settings — controlled vocab + deterministic AUTO."""
from agent.services import creative_lane_settings_service as cls


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
