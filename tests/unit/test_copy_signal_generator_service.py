from types import SimpleNamespace

from agent.services.copy_signal_generator_service import (
    _detect_bad_copy_fields,
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
        "language": "English",
    }
    payload.update(overrides)
    return payload


def _operator_pack(**copy_overrides):
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
        cta="Choose the one that fits your routine.",
    )
    for key, value in copy_overrides.items():
        setattr(product, key, value)
    return SimpleNamespace(products=[product])


def test_direct_womenswear_sleepwear_generates_malay_commercial_copy():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="A14 - Alyanaa Baju Kelawar Moden / Baju Tidur",
            raw_product_title="A14 - Alyanaa Baju Kelawar Moden / Baju Tidur",
            category="Womenswear & Underwear",
            subcategory="Women's Sleepwear & Loungewear",
            type="Nightdresses",
            product_type="Nightdresses",
            language="Malay",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=None,
    )

    assert result.route == "DIRECT"
    assert result.review_status == "AUTO_APPROVED"
    assert result.copy_quality_status == "COMMERCIAL_COPY_READY"
    assert result.copy_signals["hook"] == "Baju tidur nak selesa tapi tetap nampak kemas?"
    assert result.copy_signals["usp_1"] == "Potongan longgar senang dipakai untuk rehat harian."
    assert result.copy_signals["usp_2"] == "Kain nampak ringan dan mudah digayakan di rumah."
    assert result.copy_signals["usp_3"] == "Sesuai untuk video demo sebab bentuk dan jatuhan kain jelas nampak."
    assert result.copy_signals["cta"] == "Pilih warna dan size yang sesuai sebelum checkout."
    assert result.text_to_video_readiness_status == "READY"


def test_commercial_direct_copy_does_not_use_internal_execution_language():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="A14 - Alyanaa Baju Kelawar Moden / Baju Tidur",
            raw_product_title="A14 - Alyanaa Baju Kelawar Moden / Baju Tidur",
            category="Womenswear & Underwear",
            subcategory="Women's Sleepwear & Loungewear",
            type="Nightdresses",
            product_type="Nightdresses",
            language="Malay",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=None,
    )

    combined = " ".join(
        str(result.copy_signals[key])
        for key in [
            "hook",
            "usp_1",
            "usp_2",
            "usp_3",
            "cta",
            "dialogue_opening",
            "dialogue_body",
            "dialogue_cta",
        ]
    ).lower()
    assert "review the prompt package" not in combined
    assert "before any execution" not in combined
    assert "use product with use" not in combined


def test_unknown_category_direct_copy_stays_fallback_draft():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="Mystery Gadget",
            raw_product_title="Mystery Gadget",
            product_short_name="Mystery Gadget",
            category="General Goods",
            subcategory="Unknown",
            type="Unknown",
            product_type="Unknown",
            language="English",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=None,
    )

    assert result.route == "DIRECT"
    assert result.copy_quality_status == "FALLBACK_COPY_DRAFT"
    assert result.text_to_video_readiness_status == "NEEDS_REVIEW"
    assert "COPY_QUALITY_FALLBACK_DRAFT" in result.warnings


def test_laundry_detergent_refill_generates_laundry_specific_malay_copy():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="5 LITER/5 KG isi ulang- Sabun Dobi Malaya Liquid",
            raw_product_title="5 LITER/5 KG isi ulang- Sabun Dobi Malaya Liquid detergen",
            product_short_name="Sabun Dobi Malaya Liquid",
            category="Home Supplies",
            subcategory="Home Care Supplies",
            type="Household Cleaners",
            product_type="UNIVERSAL",
            language="Malay",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=None,
    )

    combined = " ".join(
        str(result.copy_signals[key])
        for key in ["hook", "usp_1", "usp_2", "usp_3", "cta", "dialogue_opening", "dialogue_body"]
    ).lower()
    assert result.copy_quality_status == "COMMERCIAL_COPY_READY"
    assert result.product_context["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert "sabun dobi" in combined or "laundry" in combined or "basuh" in combined
    assert "rumah nampak lebih tersusun" not in combined
    assert "tanpa banyak barang" not in combined


def test_wrong_baby_taxonomy_laundry_row_is_overridden_by_bosmax_family_for_copy():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="SABUN DOBI LIQUID LAUNDRY IMBA DETERGENT REFILL PACK 2KG",
            raw_product_title="SABUN DOBI LIQUID LAUNDRY IMBA DETERGENT REFILL PACK 2KG",
            product_short_name="SABUN DOBI LIQUID LAUNDRY",
            category="Baby & Maternity",
            subcategory="Baby Care & Health",
            type="Laundry Detergent",
            product_type="UNIVERSAL",
            language="Malay",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=None,
    )

    assert result.product_context["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert "BOSMAX_FAMILY_OVERRIDES_SOURCE_TAXONOMY" in result.truth_warnings
    assert "rumah nampak lebih tersusun" not in result.copy_signals["hook"].lower()


def test_stealth_product_copy_quality_remains_review_required():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="Atlas Relief Capsules",
            raw_product_title="Atlas Relief Capsules",
            type="Supplement Bottle",
            product_type="Supplement",
            category="Health",
            silo="health_supp_stealth_01",
            claim_risk_level="HIGH",
            language="Malay",
        ),
        content_style_mode="UGC_IPHONE",
        dialogue_metaphor_hint="payung tenang untuk rutin harian",
        operator_pack=None,
    )

    assert result.route == "STEALTH"
    assert result.review_status == "REVIEW_REQUIRED"
    assert result.copy_quality_status == "REVIEW_REQUIRED"
    assert result.visual_dialogue_isolation["visual_metaphor_allowed"] is False
    assert result.visual_dialogue_isolation["dialogue_metaphor_allowed"] is True
    assert result.text_to_video_readiness_status == "NEEDS_REVIEW"
    assert result.copy_signals["human_review_reason"]


def test_bad_copy_detector_flags_internal_system_phrases():
    hits = _detect_bad_copy_fields(
        {
            "hook": "Review the prompt package for Atlas Bottle before any execution.",
            "usp_1": "Use Atlas Bottle with use steady hands.",
            "usp_2": "Keep the demo grounded in a vanity setup.",
            "usp_3": "Show the product clearly before any performance implication.",
            "cta": "Preview-only output for execution.",
        }
    )

    assert "review the prompt package" in hits
    assert "before any execution" in hits
    assert "use_product_with_use" in hits


def test_operator_pack_with_internal_copy_is_not_marked_commercial_ready():
    result = build_copy_signal_response_for_product(
        _product(
            product_display_name="Mystery Gadget",
            raw_product_title="Mystery Gadget",
            product_short_name="Mystery Gadget",
            category="General Goods",
            subcategory="Unknown",
            type="Unknown",
            product_type="Unknown",
            language="English",
        ),
        content_style_mode="UGC_IPHONE",
        operator_pack=_operator_pack(
            hook="Mystery Gadget leads with confidence.",
            usp_1="Use Mystery Gadget with use steady hands.",
            usp_2="Keep the demo grounded in a studio setup.",
            usp_3="Show the product clearly before any performance implication.",
            cta="Review the prompt package before any execution.",
        ),
    )

    assert result.copy_quality_status == "FALLBACK_COPY_DRAFT"
    assert result.text_to_video_readiness_status == "NEEDS_REVIEW"


def test_small_product_keeps_scale_lock_and_ugc_camera_lock():
    result = build_copy_signal_response_for_product(
        _product(),
        content_style_mode="UGC_IPHONE",
        operator_pack=_operator_pack(),
    )

    prompt = result.product_context["ugc_camera_lock_prompt"]
    assert "palm-sized beauty or personal-care product scale" in result.product_context["product_scale_prompt"]
    assert result.product_context["scale_truth_status"] == "DERIVED_RELATIVE_SCALE"
    assert result.product_context["scale_warning"] == "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"
    assert result.product_context["camera_capture_mode"] == "UGC_IPHONE_RAW"
    assert "Raw iPhone handheld footage" in prompt
    assert "subtle hand jitter" in prompt


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
