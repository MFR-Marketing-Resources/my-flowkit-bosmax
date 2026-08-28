from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

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
    assert exact._dynamic_choreography(result) is False


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
    assert "PRODUCT_PRESENT_TO_CAMERA" not in prompt
    assert "placement bounding box" not in prompt
    assert "compositor motion contract" in prompt.lower()
    assert "preserve the real product" not in prompt.lower()
    assert "no visible face" in prompt.lower()


def test_faceless_scene_scaffold_removes_product_handling_contradictions():
    plan = {
        "selected_execution_route": exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "choreography": {"choreography_id": exact.PRODUCT_PRESENT_TO_CAMERA},
    }
    prompt = exact.build_exact_scene_scaffold_prompt(
        "SECTION 1 - ROLE & OBJECTIVE\n"
        "Keep the social scene natural.\n"
        "SECTION 4 - VISUAL STORY\n"
        "Hands bring the product into frame and hold it clearly.\n"
        "SECTION 5 - SHOT & CAMERA RULES\n"
        "Keep the same product grip throughout.\n"
        "SECTION 6 - SPOKEN DIALOGUE\n"
        "Dapatkan sekarang.\n"
        "SECTION 8 - CTA & END FRAME\n"
        "End with the product held clearly to camera.\n",
        plan,
        scene_context=(
            "Hands must physically handle the product. Product hero on table. "
            "A product-only clip with no visible hands is a FAILED Faceless render."
        ),
    )
    low = prompt.lower()

    assert "bring the product" not in low
    assert "product grip" not in low
    assert "product held clearly" not in low
    assert "physically handle the product" not in low
    assert "product hero on table" not in low
    assert "product-free scene" in low
    assert "never point, frame, present toward, hold, touch, or interact" in low
    assert "reserved product region" not in low
    assert "reserved box" not in low
    assert "dapatkan sekarang" in low


def test_faceless_scene_scaffold_scrubs_actual_failed_prompt_cues_but_keeps_dialogue():
    plan = {
        "selected_execution_route": exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "choreography": {
            "choreography_id": exact.PRODUCT_PRESENT_TO_CAMERA,
            "track_policy": "STATIC_RIGID_PRODUCT_TRUTH_TRACK",
        },
    }
    prompt = exact.build_exact_scene_scaffold_prompt(
        "SECTION 1 - ROLE & OBJECTIVE\n"
        "Present a real health & personal care product, not a generic prop.\n"
        "SECTION 6 - SPOKEN DIALOGUE\n"
        "Anak menangis malam kerana perut kembung? Minyak Warisan ini teman urutan keluarga.\n"
        "SECTION 7 - AUDIO & PERFORMANCE\n"
        "Time the gesture over the product handling.\n",
        plan,
        scene_context=(
            "Product identity, packaging, and scale remain locked. "
            "Warm practical bathroom lighting remains consistent."
        ),
    )
    low = prompt.lower()

    assert "real health & personal care product" not in low
    assert "generic prop" not in low
    assert "over the product handling" not in low
    assert "product identity, packaging, and scale remain locked" not in low
    assert "anak menangis malam kerana perut kembung" in low
    assert "dialogue is audio only" in low
    assert "never visualize, cast, illustrate, or cut to" in low
    assert "do not depict a baby, child, adult head, or adult face, directly or indirectly" in low
    assert "reflections, portraits, photos, screens, or background people" in low
    assert "only hands, forearms, arms, and partial torso may appear" in low
    assert "no placeholder or guide" in low
    assert "do not render a blank card, sheet of paper" in low
    assert "freestanding upright proxy props" in low
    assert "keep the scene sparse and natural" in low
    assert "warm practical bathroom lighting remains consistent" in low
    assert "reserved product region" not in low
    assert "reserved box" not in low
    assert "point toward" not in low
    assert "product_present_to_camera" not in low


def test_dynamic_choreography_rejects_track_policy_mismatch():
    with pytest.raises(
        exact.ExactProductVideoCompositeError,
        match="Exact choreography and transform-track policy disagree",
    ) as exc:
        exact._dynamic_choreography({
            "choreography_id": exact.PRODUCT_HAND_HOLD,
            "track_policy": "STATIC_RIGID_PRODUCT_TRUTH_TRACK",
        })

    assert exc.value.code == "EXACT_COMPOSITE_TRACK_POLICY_MISMATCH"


def test_presenter_visible_scaffold_drops_product_sections_and_adds_interaction_zone():
    # Exact-product HYBRID: the canonical (SECTION N - NAME) compiler integrates
    # "presenter holds and renders the exact product" throughout its product-visual
    # sections. The presenter-visible scaffold DROPS those sections wholesale and
    # replaces them with the presenter-product interaction-zone choreography, while
    # keeping the presenter fully visible and preserving the spoken dialogue for
    # lip-sync. The presenter presents TOWARD an empty reserved region (never holds
    # the product — hand-hold needs per-frame occlusion masks).
    plan = {
        "selected_execution_route": exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "choreography": {"choreography_id": exact.PRODUCT_PRESENT_TO_CAMERA},
    }
    canonical = (
        "SECTION 1 - ROLE & OBJECTIVE\n"
        "You are generating an 8-second vertical commercial video block.\n"
        "SECTION 2 - PRODUCT TRUTH LOCK\n"
        "Preserve the exact real-world appearance; when a presenter holds the product, keep it in a natural grip.\n"
        "SECTION 4 - VISUAL STORY\n"
        "Creator-led opening with the bottle already in hand, matching the uploaded product image exactly.\n"
        "SECTION 5 - SHOT & CAMERA RULES\n"
        "Handheld vertical 9:16; if the presenter is holding the product, keep it in hand.\n"
        "SECTION 6 - SPOKEN DIALOGUE\n"
        "Kembung perut? Sapu dan urut perlahan-lahan untuk lega.\n"
        "SECTION 7 - VOICE & DELIVERY\n"
        "Warm, reassuring female voice.\n"
    )
    prompt = exact.build_exact_scene_scaffold_prompt(
        canonical, plan, scene_context="Bright home studio.", presenter_visible=True
    )
    low = prompt.lower()

    # Product-render / product-hold sections are removed wholesale — no contradiction.
    assert "preserve the exact real-world appearance" not in low
    assert "already in hand" not in low
    assert "uploaded product image" not in low
    assert "keep it in hand" not in low
    assert "natural grip" not in low
    # The provider is forbidden from rendering any product.
    assert "SCENE-ONLY PLATE" in prompt
    assert "reserved region stays empty" in low
    # Presenter is required and NOT face-banned; interaction-zone choreography present.
    assert "no visible face" not in low
    assert "fully visible" in low
    assert "lip-synced" in low
    assert "interaction zone" in low
    assert "present toward" in low
    # Speech survives for lip-sync + the presenter's voice section is preserved.
    assert "sapu dan urut perlahan-lahan" in low
    assert "warm, reassuring female voice" in low


def _video_plan_for_test():
    return {
        "selected_execution_route": exact.EXACT_PRODUCT_DETERMINISTIC_COMPOSITE,
        "generate_eligibility": True,
        "placement_region": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
        "product_truth": {"canonical_cutout_sha256": "b" * 64},
        "choreography": {
            "choreography_id": exact.PRODUCT_STATIC_TABLE,
            "classification": exact.SUPPORTED_EXACT,
        },
    }


def _patch_video_runtime(monkeypatch, tmp_path, *, frame_count: int = 2):
    out_root = tmp_path / "out"
    out_root.mkdir()
    scene_path = out_root / "scene.mp4"
    scene_path.write_bytes(b"provider-scene-scaffold")
    cutout_path = out_root / "canonical-cutout.png"
    from PIL import ImageDraw

    cutout = Image.new("RGBA", (20, 40), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle((4, 2, 16, 37), fill=(20, 120, 60, 255))
    cutout.save(cutout_path)

    canonical = {
        "product_id": "p1",
        "canonical_media_id": "media-1",
        "source_sha256": "a" * 64,
        "cutout_media_id": "cutout-1",
        "cutout_sha256": "b" * 64,
        "alpha_mask_sha256": "c" * 64,
        "cutout_path": str(cutout_path),
    }
    monkeypatch.setattr(exact, "OUTPUT_DIR", out_root)
    monkeypatch.setattr(exact, "validate_canonical_or_raise", lambda _product: canonical)
    monkeypatch.setattr(
        exact,
        "_probe_video",
        lambda _path: {"width": 120, "height": 120, "fps": 24.0, "duration": 1.0, "has_audio": False},
    )
    monkeypatch.setattr(exact, "_tool", lambda name, env_name: name)

    def fake_prepare_layer(_product, _region, _canvas):
        return {
            "asset_ref": str(cutout_path),
            "transform": {
                "x": 10,
                "y": 10,
                "w": 20,
                "h": 40,
                "source_crop": {},
                "rotation_degrees": 0.0,
                "perspective_skew_x": 0.0,
                "shadow_opacity": 0.0,
                "shadow_blur_px": 1.0,
            },
        }

    monkeypatch.setattr(exact, "prepare_layer", fake_prepare_layer)

    def fake_run(command):
        target = str(command[-1])
        if "%08d.png" in target:
            frame_dir = Path(target).parent
            frame_dir.mkdir(parents=True, exist_ok=True)
            for index in range(1, frame_count + 1):
                Image.new("RGBA", (120, 120), (245, 245, 245, 255)).save(
                    frame_dir / f"{index:08d}.png"
                )
        else:
            Path(target).write_bytes(b"deterministic-final-video")

    monkeypatch.setattr(exact, "_run", fake_run)
    return scene_path, canonical, cutout_path


def test_video_compositor_static_scene_is_measured_and_deterministic(tmp_path, monkeypatch):
    scene_path, _canonical, _cutout = _patch_video_runtime(monkeypatch, tmp_path)
    plan = _video_plan_for_test()
    scene = {"media_id": "scene-1", "local_path": str(scene_path)}

    first = exact.compose_exact_product_video_artifact(
        product={"id": "p1"}, plan=plan, scene_artifact=scene, job_id="job-1"
    )
    second = exact.compose_exact_product_video_artifact(
        product={"id": "p1"}, plan=plan, scene_artifact=scene, job_id="job-1"
    )

    assert first["media_id"] == second["media_id"]
    assert first["output_sha256"] == second["output_sha256"]
    assert first["media_id"] != scene["media_id"]
    lineage = first["exact_product_lineage"]
    assert lineage["raw_scene_final_authority"] is False
    assert lineage["product_fidelity_qc"]["status"] == "PRODUCT_FIDELITY_QC_PASS"
    assert lineage["product_fidelity_qc"]["verified"] is True
    assert all(
        item["status"] == "PASS"
        for item in lineage["product_fidelity_qc"]["dimensions"].values()
    )
    assert all(row["qa"]["exact_product_count"] == 1 for row in lineage["transform_track_lineage"])
    assert lineage["transform_track"]["required"] is False
    assert lineage["transform_track"]["verified"] is True
    assert lineage["transform_track"]["source"] == "DETERMINISTIC_STATIC_PLAN"
    assert lineage["transform_track"]["frame_count"] == 2
    assert len(lineage["transform_track"]["sha256"]) == 64
    assert lineage["canonical_product_asset"]["canonical_cutout_sha256"] == "b" * 64
    assert lineage["compositor_output"]["media_id"] == first["media_id"]
    assert lineage["compositor_output"]["sha256"] == first["output_sha256"]
    assert lineage["final_registered_media"] is None


def test_video_compositor_fails_closed_for_dynamic_action_without_track_or_masks(tmp_path, monkeypatch):
    scene_path, _canonical, _cutout = _patch_video_runtime(monkeypatch, tmp_path)
    plan = _video_plan_for_test()
    plan["choreography"] = {
        "choreography_id": exact.PRODUCT_HAND_HOLD,
        "classification": exact.REQUIRES_OCCLUSION_MASK,
    }
    with pytest.raises(exact.ExactProductVideoCompositeError) as exc:
        exact.compose_exact_product_video_artifact(
            product={"id": "p1"},
            plan=plan,
            scene_artifact={"media_id": "scene-1", "local_path": str(scene_path)},
        )
    assert exc.value.code == "EXACT_COMPOSITE_TRANSFORM_TRACK_REQUIRED"


def test_video_compositor_rejects_incomplete_mask_sequence(tmp_path, monkeypatch):
    scene_path, _canonical, _cutout = _patch_video_runtime(monkeypatch, tmp_path)
    plan = _video_plan_for_test()
    plan["choreography"] = {
        "choreography_id": exact.PRODUCT_STATIC_TABLE,
        "classification": exact.REQUIRES_OCCLUSION_MASK,
    }
    with pytest.raises(exact.ExactProductVideoCompositeError) as exc:
        exact.compose_exact_product_video_artifact(
            product={"id": "p1"},
            plan=plan,
            scene_artifact={"media_id": "scene-1", "local_path": str(scene_path)},
            foreground_masks=[{"verified": True}],
        )
    assert exc.value.code == "EXACT_COMPOSITE_OCCLUSION_MASK_COUNT_MISMATCH"


def test_video_compositor_does_not_claim_pass_when_a_final_frame_is_missing_product(tmp_path, monkeypatch):
    scene_path, _canonical, _cutout = _patch_video_runtime(monkeypatch, tmp_path)
    plan = _video_plan_for_test()
    original_composite = exact.composite
    calls = {"count": 0}

    def missing_on_second_frame(output_path, layer):
        calls["count"] += 1
        if calls["count"] == 2:
            return {"composition_ok": False, "product_region_match": False, "exact_product_count": 0}
        return original_composite(output_path, layer)

    monkeypatch.setattr(exact, "composite", missing_on_second_frame)
    with pytest.raises(exact.ExactProductVideoCompositeError) as exc:
        exact.compose_exact_product_video_artifact(
            product={"id": "p1"},
            plan=plan,
            scene_artifact={"media_id": "scene-1", "local_path": str(scene_path)},
        )
    assert exc.value.code == "EXACT_COMPOSITE_QA_FAILED"


def test_plate_scan_rejects_duplicate_canonical_shape_outside_reserved_region(tmp_path):
    from PIL import ImageDraw

    cutout_path = tmp_path / "cutout.png"
    cutout = Image.new("RGBA", (20, 40), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle((4, 2, 16, 37), fill=(20, 120, 60, 255))
    cutout.save(cutout_path)
    frame_path = tmp_path / "frame.png"
    frame = Image.new("RGBA", (120, 120), (245, 245, 245, 255))
    frame.alpha_composite(cutout, (80, 30))
    frame.save(frame_path)

    scan = exact._plate_product_scan(
        frame_path,
        reserved_box={"x": 10, "y": 10, "w": 20, "h": 40},
        canonical_cutout_path=cutout_path,
        static_scene=True,
    )
    assert scan["status"] == "FAIL"
    assert scan["reference_like_duplicates"] >= 1


def test_plate_scan_rejects_generic_provider_product_inside_reserved_region(tmp_path):
    from PIL import ImageDraw

    cutout_path = tmp_path / "cutout.png"
    cutout = Image.new("RGBA", (20, 40), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle((4, 2, 16, 37), fill=(20, 120, 60, 255))
    cutout.save(cutout_path)
    frame_path = tmp_path / "frame.png"
    frame = Image.new("RGBA", (120, 120), (245, 245, 245, 255))
    ImageDraw.Draw(frame).rectangle((12, 12, 28, 48), fill=(180, 120, 20, 255))
    frame.save(frame_path)

    scan = exact._plate_product_scan(
        frame_path,
        reserved_box={"x": 10, "y": 10, "w": 20, "h": 40},
        canonical_cutout_path=cutout_path,
        static_scene=True,
    )

    assert scan["status"] == "FAIL"
    assert scan["reserved_region_hits"] >= 1


def test_dynamic_qc_leaves_unverified_dimension_honest():
    dimensions = exact._qc_dimensions(
        [{"transform": {"x": 1}, "qa": {"composition_ok": True, "product_region_match": True}}],
        dynamic_track=True,
        dynamic_track_verified=False,
        plate_scans=[{"status": "PASS"}],
    )
    assert dimensions["frame_morph"]["status"] == "NOT_VERIFIED"
    assert dimensions["duplication"]["status"] == "PASS"
