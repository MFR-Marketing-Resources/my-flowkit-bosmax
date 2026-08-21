from agent.services import exact_product_video_compositor_service as exact


def _canonical() -> dict:
    return {
        "product_id": "p1",
        "canonical_media_id": "ca_source",
        "source_sha256": "b" * 64,
        "cutout_media_id": "ca_cutout",
        "cutout_sha256": "a" * 64,
        "alpha_mask_sha256": "c" * 64,
        "allowed_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
        "anchor_point": {"x": 0.5, "y": 0.5},
        "min_scale": 0.1,
        "max_scale": 1.0,
        "allowed_rotation": 5,
        "allowed_perspective": 0,
        "product_truth_lock_schema_version": "PRODUCT_TRUTH_LOCK_V1",
    }


def test_v1_choreography_classification_is_fail_closed():
    assert exact.classify_exact_choreography(exact.PRODUCT_STATIC_TABLE)[
        "classification"
    ] == exact.SUPPORTED_EXACT
    assert exact.classify_exact_choreography(exact.PRODUCT_HAND_HOLD)[
        "classification"
    ] == exact.REQUIRES_OCCLUSION_MASK
    assert exact.classify_exact_choreography("AI_INVENTED_ACTION")[
        "classification"
    ] == exact.UNSUPPORTED_EXACT


def test_faceless_default_records_original_scene_and_safe_exact_action():
    result = exact.resolve_faceless_exact_choreography(
        {
            "choreography_id": "traditional_herbal_oil.v0",
            "allowed_action": "hold, open, apply, and close",
        }
    )

    assert result["choreography_id"] == exact.PRODUCT_PRESENT_TO_CAMERA
    assert result["requested_scene_choreography_id"] == "traditional_herbal_oil.v0"
    assert result["selection_reason"] == "FACELESS_V1_EXACT_SAFE_DEFAULT"
    assert result["classification"] == exact.SUPPORTED_EXACT


def test_exact_plan_carries_product_truth_geometry(monkeypatch):
    monkeypatch.setattr(exact, "validate_canonical_or_raise", lambda _product: _canonical())

    plan = exact.build_exact_product_video_plan(
        {"id": "p1"},
        exact.PRODUCT_PRESENT_TO_CAMERA,
    )

    assert plan["selected_execution_route"] == exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE
    assert plan["generate_eligibility"] is True
    assert plan["provider_product_reference_forbidden"] is True
    assert plan["product_truth"]["canonical_source_sha256"] == "b" * 64
    assert plan["face_qc"] == {"status": "NOT_RUN", "verified": False}


def test_scene_scaffold_prompt_forbids_provider_product_pixels():
    plan = {
        "selected_execution_route": exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "choreography": {"choreography_id": exact.PRODUCT_PRESENT_TO_CAMERA},
    }
    prompt = exact.build_exact_scene_scaffold_prompt(
        "Show the exact product label and preserve the real product.",
        plan,
        scene_context="Aesthetic table, faceless hands.",
    )

    assert "SCENE-ONLY PLATE" in prompt
    assert "provider output is an internal plate" in prompt
    assert "PRODUCT_PRESENT_TO_CAMERA" in prompt
    assert "preserve the real product" not in prompt.lower()
    assert "no visible face" in prompt.lower()
