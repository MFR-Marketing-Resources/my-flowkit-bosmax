from types import SimpleNamespace

from agent.services.copy_signal_generator_service import (
    build_copy_signal_response_for_product,
)


def _product(**overrides):
    payload = {
        "id": "prod-001",
        "product_display_name": "Atlas Lip Balm",
        "raw_product_title": "Atlas Lip Balm Original",
        "product_short_name": "Atlas Lip Balm",
        "category": "Beauty Personal Care",
        "subcategory": "Skincare",
        "type": "Lip Balm",
        "product_type": "Lip Balm",
        "claim_risk_level": "LOW",
        "scene_context": "Bedroom vanity close-up.",
        "camera_style": "Close-up handheld demo.",
        "camera_behavior": "Short handheld push-in.",
        "product_scale": "SMALL_OBJECT",
        "recommended_grip": "Light fingertip pinch with label visible.",
        "hand_object_interaction": "Fit naturally between fingers without covering the cap seam.",
        "section_5_product_physics_prompt": "Small balm tube with natural fingertip handling.",
        "copywriting_angle": "Everyday confidence framing",
        "silo": "beauty_mass_01",
        "trigger_id": "TRUST_01",
    }
    payload.update(overrides)
    return payload


def _operator_pack():
    product = SimpleNamespace(
        product_id="prod-001",
        product_name="Atlas Lip Balm Original",
        raw_product_title="Atlas Lip Balm Original",
        product_display_name="Atlas Lip Balm",
        product_short_name="Atlas Lip Balm",
        hook="Swipe once, lips stay comfortable.",
        usp_1="Slim balm size that fits natural finger handling.",
        usp_2="Everyday carry format with easy close-up demo.",
        usp_3="Label-forward product demo stays clean and readable.",
        cta="Build the prompt package before any execution.",
    )
    return SimpleNamespace(products=[product])


def test_direct_product_has_product_scale_prompt_and_copy_signals():
    result = build_copy_signal_response_for_product(
        _product(),
        content_style_mode="UGC_IPHONE",
        operator_pack=_operator_pack(),
    )

    assert result.route == "DIRECT"
    assert result.product_context["product_scale_prompt"]
    assert result.product_context["scale_truth_status"] == "DERIVED_RELATIVE_SCALE"
    assert result.copy_signals["hook"] == "Swipe once, lips stay comfortable."


def test_small_product_gets_exact_relative_scale_wording_and_warning_without_verified_dimensions():
    result = build_copy_signal_response_for_product(
        _product(product_scale="SMALL_OBJECT"),
        content_style_mode="UGC_IPHONE",
        operator_pack=_operator_pack(),
    )

    assert "EXACTLY lip balm size" in result.product_context["product_scale_prompt"]
    assert result.product_context["scale_warning"] == "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"
    assert "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED" in result.warnings


def test_ugc_iphone_includes_raw_handheld_jitter_and_micro_shake_language():
    result = build_copy_signal_response_for_product(
        _product(),
        content_style_mode="UGC_IPHONE",
        operator_pack=_operator_pack(),
    )

    prompt = result.product_context["ugc_camera_lock_prompt"]
    assert result.product_context["camera_capture_mode"] == "UGC_IPHONE_RAW"
    assert "Raw iPhone handheld footage" in prompt
    assert "subtle hand jitter" in prompt
    assert "natural micro-shake" in prompt
    assert "imperfect creator framing" in prompt
    assert "autofocus breathing" in prompt


def test_cinematic_pro_excludes_raw_iphone_jitter_language():
    result = build_copy_signal_response_for_product(
        _product(),
        content_style_mode="CINEMATIC_PRO",
        operator_pack=_operator_pack(),
    )

    prompt = result.product_context["cinematic_camera_prompt"]
    assert result.product_context["camera_capture_mode"] == "CINEMATIC_PRO_CONTROLLED"
    assert "controlled cinematic camera" in prompt.lower()
    assert "raw iphone" not in prompt.lower()
    assert "micro-shake" not in prompt.lower()
    assert "hand jitter" not in prompt.lower()


def test_stealth_metaphor_does_not_leak_into_scale_or_camera_fields():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="Atlas Relief Capsules",
            raw_product_title="Atlas Relief Capsules",
            type="Supplement Bottle",
            product_type="Supplement",
            category="Health",
            silo="health_supp_stealth_01",
            claim_risk_level="HIGH",
        ),
        content_style_mode="UGC_IPHONE",
        dialogue_metaphor_hint="quiet shield for the day",
        operator_pack=None,
    )

    assert result.route == "STEALTH"
    assert result.review_status == "REVIEW_REQUIRED"
    assert result.visual_dialogue_isolation["visual_metaphor_allowed"] is False
    assert result.visual_dialogue_isolation["dialogue_metaphor_allowed"] is True
    assert "quiet shield for the day" in result.copy_signals["hook"]
    assert "quiet shield for the day" not in result.product_context["product_scale_prompt"]
    assert "quiet shield for the day" not in result.product_context["ugc_camera_lock_prompt"]