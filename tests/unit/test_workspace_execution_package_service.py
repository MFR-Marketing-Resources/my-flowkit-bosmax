import copy
import json

import pytest

from agent.services.workspace_execution_package_service import (
    _bind_f2v_reference_assets,
    _workspace_execution_package_id,
    compile_workspace_prompt_preview,
    create_workspace_execution_package,
    list_workspace_execution_packages,
)


def test_package_id_binds_reference_selection_identity():
    # Two packages that differ ONLY in their operator-selected reference
    # bindings must never share one wep_ id — a same-id create_or_replace
    # silently swapped resolved assets under an already-planned job.
    common = (
        "prod-001", "F2V", "prompt_fp", 16, "9:16", "Veo 3.1 - Lite",
        False, "EXTEND", "BM_MS", "UGC_IPHONE_RAW", "VISIBLE_CREATOR",
    )
    id_a = _workspace_execution_package_id(*common, ["asset_fp_a"])
    id_b = _workspace_execution_package_id(*common, ["asset_fp_b"])
    id_a_again = _workspace_execution_package_id(*common, ["asset_fp_a"])
    assert id_a != id_b
    assert id_a == id_a_again


def _fake_asset(**overrides):
    fields = {
        "asset_id": "ca_ref",
        "display_name": "Reference asset",
        "source_type": "UPLOAD",
        "local_file_path": "C:/tmp/ref.png",
        "remote_source_url": None,
        "preview_url": "/api/creative-assets/ca_ref/preview",
        "download_url": "/api/creative-assets/ca_ref/download",
        "media_id": "media-ref",
        "product_id": None,
    }
    fields.update(overrides)
    return type("Asset", (), fields)()


def _fake_validation(asset=None, blockers=None):
    return type(
        "ValidationResult",
        (),
        {"valid": not blockers, "blockers": blockers or [], "asset": asset},
    )()


_ANCHOR_SLOTS = [
    {
        "slot_key": "start_frame",
        "required": True,
        "default_source": "PRODUCT_IMAGE_CACHE",
        "resolved_asset": {
            "asset_id": "product-image:prod-001:start_frame",
            "asset_fingerprint": "asset_fp_001",
            "slot_key": "start_frame",
            "asset_source": "PRODUCT_IMAGE_CACHE",
            "media_id": "media-product",
        },
    },
    {"slot_key": "end_frame", "required": False, "resolved_asset": None},
]


@pytest.mark.asyncio
async def test_hybrid_binding_defaults_to_package_product_anchor():
    # HYBRID automatic product-anchor authority (pre-PR#338 proven behavior):
    # no manual pick → the approved package's own resolved anchor stands, and
    # exactly one effective product reference remains.
    merged = await _bind_f2v_reference_assets(
        copy.deepcopy(_ANCHOR_SLOTS),
        product_id="prod-001",
        source_mode="HYBRID",
        product_reference_asset_id=None,
        start_frame_asset_id=None,
        end_frame_asset_id=None,
    )
    assert merged == _ANCHOR_SLOTS
    resolved = [slot["resolved_asset"] for slot in merged if slot.get("resolved_asset")]
    assert len(resolved) == 1
    assert resolved[0]["asset_id"] == "product-image:prod-001:start_frame"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_reference_asset_id", "start_frame_asset_id", "end_frame_asset_id"),
    [
        ("ca_product", "ca_extra", None),
        ("ca_product", None, "ca_extra"),
        (None, "ca_extra", None),
        (None, None, "ca_extra"),
    ],
)
async def test_hybrid_reference_binding_rejects_frame_selections(
    product_reference_asset_id,
    start_frame_asset_id,
    end_frame_asset_id,
):
    with pytest.raises(ValueError, match="HYBRID_EXACTLY_ONE_PRODUCT_REFERENCE_REQUIRED"):
        await _bind_f2v_reference_assets(
            [],
            product_id="prod-001",
            source_mode="HYBRID",
            product_reference_asset_id=product_reference_asset_id,
            start_frame_asset_id=start_frame_asset_id,
            end_frame_asset_id=end_frame_asset_id,
        )


@pytest.mark.asyncio
async def test_frames_binding_requires_explicit_start_frame():
    # FRAMES server-side truth: the raw product image must never silently stand
    # in for a finished composite start frame.
    with pytest.raises(ValueError, match="FRAMES_START_FRAME_REFERENCE_REQUIRED"):
        await _bind_f2v_reference_assets(
            copy.deepcopy(_ANCHOR_SLOTS),
            product_id="prod-001",
            source_mode="FRAMES",
            product_reference_asset_id=None,
            start_frame_asset_id=None,
            end_frame_asset_id=None,
        )


@pytest.mark.asyncio
async def test_binding_rejects_cross_product_reference(monkeypatch):
    async def fake_validate(asset_id: str, **kwargs):
        return _fake_validation(asset=_fake_asset(product_id="prod-OTHER"))

    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.validate_selectable_asset",
        fake_validate,
    )
    with pytest.raises(ValueError, match="START_FRAME_REFERENCE_INVALID:WRONG_PRODUCT"):
        await _bind_f2v_reference_assets(
            copy.deepcopy(_ANCHOR_SLOTS),
            product_id="prod-001",
            source_mode="FRAMES",
            product_reference_asset_id=None,
            start_frame_asset_id="ca_other_product",
            end_frame_asset_id=None,
        )


@pytest.mark.asyncio
async def test_binding_rejects_reference_without_media_identity(monkeypatch):
    async def fake_validate(asset_id: str, **kwargs):
        return _fake_validation(asset=_fake_asset(product_id="prod-001", media_id=None))

    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.validate_selectable_asset",
        fake_validate,
    )
    with pytest.raises(ValueError, match="START_FRAME_REFERENCE_INVALID:MEDIA_IDENTITY_MISSING"):
        await _bind_f2v_reference_assets(
            copy.deepcopy(_ANCHOR_SLOTS),
            product_id="prod-001",
            source_mode="HYBRID",
            product_reference_asset_id="ca_no_media",
            start_frame_asset_id=None,
            end_frame_asset_id=None,
        )


@pytest.mark.asyncio
async def test_hybrid_explicit_pick_overrides_anchor(monkeypatch):
    captured_kwargs = {}

    async def fake_validate(asset_id: str, **kwargs):
        captured_kwargs.update(kwargs)
        return _fake_validation(
            asset=_fake_asset(asset_id=asset_id, product_id="prod-001"),
        )

    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.validate_selectable_asset",
        fake_validate,
    )
    merged = await _bind_f2v_reference_assets(
        copy.deepcopy(_ANCHOR_SLOTS),
        product_id="prod-001",
        source_mode="HYBRID",
        product_reference_asset_id="ca_pick",
        start_frame_asset_id=None,
        end_frame_asset_id=None,
    )
    # picker parity: the binder enforces the same rendered-text ban as the
    # eligibility-audit surfaces.
    assert captured_kwargs["disallow_rendered_text"] is True
    assert captured_kwargs["semantic_role"] == "PRODUCT_REFERENCE"
    start = next(s for s in merged if s["slot_key"] == "start_frame")
    assert start["resolved_asset"]["asset_id"] == "ca_pick"
    assert start["resolved_asset"]["semantic_role"] == "PRODUCT_REFERENCE"


@pytest.mark.asyncio
async def test_workspace_execution_package_frames_binds_selected_start_frame(monkeypatch):
    captured = {}

    async def fake_package(product_id: str, mode: str):
        return {
            "prompt_package_snapshot_id": "pkg_123",
            "product_id": product_id,
            "product_name": "Bosmax Herbs 5 ML",
            "mode": mode,
            "production_generation_allowed": False,
            "prompt_text": "Frames prompt",
            "prompt_fingerprint": "fingerprint_123",
            "asset_slots": [
                {
                    "slot_key": "start_frame",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "USER_UPLOAD"],
                    "resolved_asset": {
                        "asset_id": "product-image:prod-001:start_frame",
                        "asset_fingerprint": "asset_fp_001",
                        "slot_key": "start_frame",
                        "asset_source": "PRODUCT_IMAGE_CACHE",
                        "label": "Product cached image",
                        "file_name": "prod-001.jpg",
                        "preview_url": "/api/products/prod-001/image",
                        "download_url": "/api/products/prod-001/image",
                        "media_id": None,
                    },
                },
                {
                    "slot_key": "end_frame",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
            ],
            "manual_fallback": {"copy_prompt_available": True, "execution_checklist": ["Copy prompt"]},
            "blockers": [],
            "source_of_truth_notes": ["Product truth remains on the product row."],
            "claim_safe_rewrite": "Safe rewrite",
        }

    async def fake_compile(**kwargs):
        return {
            "final_compiled_prompt_text": "Block 1 (ANCHOR)\nUse one visible creator persona.",
            "prompt_blocks": [
                {
                    "block_id": "block_1",
                    "block_index": 1,
                    "block_role": "ANCHOR",
                    "duration_seconds": 8,
                    "shot_count": 2,
                    "dialogue_word_budget": 13,
                    "continuation_from_block_id": None,
                    "compiled_prompt_text": "Block 1",
                    "shot_plan": ["Shot 1", "Shot 2"],
                }
            ],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "source_mode": "HYBRID",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [{"block_index": 1, "shot_count": 2, "shots": ["Shot 1", "Shot 2"]}],
            "dialogue_word_budget_per_block": [13],
            "prompt_fingerprint": "compiled_fp_001",
            "canonical_package_fingerprint": "canonical_fp_001",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": ["Compiler note"],
            "continuation_lineage": [],
            "runtime_config_snapshot": {"defaults": {"block_duration_seconds": 8}},
            "planner_result": {
                "plan_version": "full_storyboard_first_extend_planner_v1",
                "planner_fingerprint": "planner_fp_001",
                "full_story_plan": {"story_beats": [{"beat_id": "beat_1"}]},
                "full_dialogue_plan": {"utterances": [{"utterance_id": "utterance_1"}]},
                "block_allocations": [{"block_index": 1}],
            },
            "planner_version": "full_storyboard_first_extend_planner_v1",
            "planner_fingerprint": "planner_fp_001",
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    async def fake_validate(asset_id: str, **kwargs):
        assert asset_id == "ca_start"
        assert kwargs == {
            "semantic_role": "COMPOSITE_FRAME_REFERENCE",
            "allowed_mode": "F2V",
            "engine_slot": "start_frame",
            "disallow_rendered_text": True,
            "require_approved": True,
        }
        return _fake_validation(
            asset=_fake_asset(
                asset_id="ca_start",
                display_name="Operator selected start frame",
                local_file_path="C:/tmp/start.png",
                preview_url="/api/creative-assets/ca_start/preview",
                download_url="/api/creative-assets/ca_start/download",
                media_id="media-start",
                product_id="prod-001",
            ),
        )

    monkeypatch.setattr("agent.services.workspace_execution_package_service.get_approved_product_package", fake_package)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.compile_workspace_prompt_preview", fake_compile)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package", fake_store)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.validate_selectable_asset", fake_validate)

    # copy_fallback_confirmed=True: this test exercises package mechanics, not the
    # copy gate; no Copy Set is selected so fallback must be intentionally confirmed
    # (Explicit-Fallback-Confirmation V1).
    result = await create_workspace_execution_package(
        "prod-001",
        "F2V",
        8,
        "9:16",
        "Veo 3.1 - Lite",
        False,
        source_mode="FRAMES",
        start_frame_asset_id="ca_start",
        copy_fallback_confirmed=True,
    )

    assert result["readiness"] == "READY"
    assert result["resolved_assets"][0]["asset_source"] == "UPLOAD"
    assert result["resolved_assets"][0]["media_id"] == "media-start"
    assert result["resolved_assets"][0]["slot_key"] == "start_frame"
    assert result["prompt_text"].startswith("Block 1")
    assert result["generation_mode"] == "SINGLE"
    assert result["source_mode"] == "HYBRID"
    assert result["camera_style"] == "UGC_IPHONE_RAW"
    assert result["request_lineage_payload"]["prompt_package_snapshot_id"] == "pkg_123"
    assert captured["workspace_execution_package_id"].startswith("wep_")
    assert captured["duration_seconds"] == 8
    assert result["planner_result"]["planner_fingerprint"] == "planner_fp_001"
    assert result["canonical_package_fingerprint"] == "canonical_fp_001"
    stored_lineage = json.loads(captured["request_lineage_payload"])
    assert stored_lineage["compiler"]["planner_result"] == result["planner_result"]
    assert stored_lineage["compiler"]["canonical_package_fingerprint"] == "canonical_fp_001"


@pytest.mark.asyncio
async def test_workspace_execution_package_hybrid_uses_automatic_product_anchor(
    monkeypatch,
):
    """HYBRID with NO manual pick persists the package's own product anchor —
    the selected product package supplies the reference authority automatically
    (regression guard for the PR#338 mandatory-manual-pick break)."""
    captured = {}

    async def fake_package(product_id: str, mode: str):
        return {
            "prompt_package_snapshot_id": "pkg_hybrid",
            "product_id": product_id,
            "product_name": "Minyak Warisan Tok Cap Burung 25ml",
            "mode": mode,
            "production_generation_allowed": False,
            "prompt_text": "Hybrid prompt",
            "prompt_fingerprint": "fingerprint_hybrid",
            "asset_slots": copy.deepcopy(_ANCHOR_SLOTS),
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "source_of_truth_notes": ["Product truth remains on the product row."],
            "claim_safe_rewrite": "Safe rewrite",
        }

    async def fake_compile(**kwargs):
        return {
            "final_compiled_prompt_text": "Block 1 (ANCHOR)",
            "prompt_blocks": [
                {
                    "block_id": "block_1",
                    "block_index": 1,
                    "block_role": "ANCHOR",
                    "duration_seconds": 8,
                    "shot_count": 2,
                    "dialogue_word_budget": 13,
                    "continuation_from_block_id": None,
                    "compiled_prompt_text": "Block 1",
                    "shot_plan": ["Shot 1"],
                }
            ],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "source_mode": "HYBRID",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [{"block_index": 1, "shot_count": 1, "shots": ["Shot 1"]}],
            "dialogue_word_budget_per_block": [13],
            "prompt_fingerprint": "compiled_fp_hybrid",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": ["Compiler note"],
            "continuation_lineage": [],
            "runtime_config_snapshot": {"defaults": {"block_duration_seconds": 8}},
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    async def fail_validate(asset_id: str, **kwargs):
        raise AssertionError(
            "validate_selectable_asset must not run for the automatic anchor",
        )

    monkeypatch.setattr("agent.services.workspace_execution_package_service.get_approved_product_package", fake_package)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.compile_workspace_prompt_preview", fake_compile)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package", fake_store)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.validate_selectable_asset", fail_validate)

    result = await create_workspace_execution_package(
        "prod-001",
        "F2V",
        8,
        "9:16",
        "Veo 3.1 - Lite",
        False,
        source_mode="HYBRID",
        copy_fallback_confirmed=True,
    )

    assert result["readiness"] == "READY"
    assert len(result["resolved_assets"]) == 1
    assert result["resolved_assets"][0]["asset_source"] == "PRODUCT_IMAGE_CACHE"
    assert result["resolved_assets"][0]["asset_id"] == "product-image:prod-001:start_frame"
    stored_assets = json.loads(captured["resolved_assets"])
    assert stored_assets[0]["media_id"] == "media-product"


@pytest.mark.asyncio
async def test_workspace_execution_package_history_parses_snapshot_rows(monkeypatch):
    async def fake_list(**kwargs):
        return [
            {
                "workspace_execution_package_id": "wep_123",
                "product_id": "prod-001",
                "mode": "IMG",
                "prompt_package_snapshot_id": "pkg_123",
                "prompt_fingerprint": "fp_123",
                "readiness": "READY",
                "execution_allowed": 1,
                "manual_override": 0,
                "asset_slots": '[{"slot_key":"subject"}]',
                "resolved_assets": '[{"slot_key":"subject","asset_source":"PRODUCT_IMAGE_CACHE"}]',
                "manual_fallback": '{"copy_prompt_available": true}',
                "blockers": '[]',
                "request_lineage_payload": '{"product_id":"prod-001","compiler":{"source_mode":"HYBRID"}}',
                "source_of_truth_notes": '["note"]',
                "prompt_text": "Prompt preview",
                "created_at": "2026-05-17T00:00:00Z",
                "updated_at": "2026-05-17T00:00:00Z",
            }
        ]

    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.list_workspace_execution_packages", fake_list)

    items = await list_workspace_execution_packages(product_id="prod-001", mode="IMG")

    assert items[0]["workspace_execution_package_id"] == "wep_123"
    assert items[0]["source_mode"] == "HYBRID"
    assert items[0]["resolved_assets"][0]["asset_source"] == "PRODUCT_IMAGE_CACHE"
    assert items[0]["prompt_preview"] == "Prompt preview"


@pytest.mark.asyncio
async def test_workspace_execution_package_preserves_extend_lineage(monkeypatch):
    captured = {}

    async def fake_package(product_id: str, mode: str):
        return {
            "prompt_package_snapshot_id": "pkg_extend",
            "product_id": product_id,
            "product_name": "Glad2Glow Body Serum",
            "mode": mode,
            "production_generation_allowed": False,
            "prompt_text": "Legacy package prompt",
            "prompt_fingerprint": "legacy_fp",
            "asset_slots": [],
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "source_of_truth_notes": ["Package note"],
            "claim_safe_rewrite": "Safe rewrite",
        }

    async def fake_compile(**kwargs):
        return {
            "final_compiled_prompt_text": "Block 1 (ANCHOR)\n...\n\nBlock 2 (CONTINUATION)\n...",
            "prompt_blocks": [
                {
                    "block_id": "block_1",
                    "block_index": 1,
                    "block_role": "ANCHOR",
                    "duration_seconds": 10,
                    "shot_count": 3,
                    "dialogue_word_budget": 17,
                    "continuation_from_block_id": None,
                    "compiled_prompt_text": "Block 1",
                    "shot_plan": ["Shot 1", "Shot 2", "Shot 3"],
                },
                {
                    "block_id": "block_2",
                    "block_index": 2,
                    "block_role": "CONTINUATION",
                    "duration_seconds": 6,
                    "shot_count": 1,
                    "dialogue_word_budget": 10,
                    "continuation_from_block_id": "block_1",
                    "compiled_prompt_text": "Block 2",
                    "shot_plan": ["Shot 1"],
                },
            ],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "generation_mode": "EXTEND",
            "total_duration_seconds": 16,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [
                {"block_index": 1, "shot_count": 3, "shots": ["Shot 1", "Shot 2", "Shot 3"]},
                {"block_index": 2, "shot_count": 1, "shots": ["Shot 1"]},
            ],
            "dialogue_word_budget_per_block": [17, 10],
            "prompt_fingerprint": "extend_fp_001",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": ["Compiler note"],
            "continuation_lineage": [
                {
                    "block_index": 2,
                    "continuation_from_block_id": "block_1",
                    "continuation_strategy": "SAME_CREATOR_PRODUCT_SCENE_CAMERA_COPY_ROUTE",
                }
            ],
            "runtime_config_snapshot": {"defaults": {"block_duration_seconds": 8}},
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr("agent.services.workspace_execution_package_service.get_approved_product_package", fake_package)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.compile_workspace_prompt_preview", fake_compile)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package", fake_store)

    result = await create_workspace_execution_package(
        "prod-extend",
        "F2V",
        8,
        "9:16",
        "Veo 3.1 - Lite",
        False,
        generation_mode="EXTEND",
        blocks=[
            {"block_index": 1, "duration_seconds": 10},
            {"block_index": 2, "duration_seconds": 6},
        ],
        copy_fallback_confirmed=True,  # no Copy Set selected — fallback confirmed
    )

    assert result["generation_mode"] == "EXTEND"
    assert result["total_duration_seconds"] == 16
    assert result["prompt_blocks"][1]["continuation_from_block_id"] == "block_1"
    assert result["continuation_lineage"][0]["continuation_from_block_id"] == "block_1"
    assert captured["duration_seconds"] == 16


@pytest.mark.asyncio
async def test_workspace_execution_package_img_preview_uses_img_contract(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "product_display_name": "Bidasari Kurung Cotton Embroidery Cutwork",
            "raw_product_title": "Bidasari Kurung Cotton Embroidery Cutwork",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "image_readiness_status": "IMAGE_CACHE_READY",
        }

    async def fake_package(product_id: str, mode: str):
        return {
            "prompt_package_snapshot_id": "pkg_img_001",
            "product_id": product_id,
            "product_name": "Bidasari Kurung Cotton Embroidery Cutwork",
            "mode": mode,
            "production_generation_allowed": True,
            "prompt_text": "Subject: Photorealistic apparel hero image.",
            "image_prompt": "Subject: Photorealistic apparel hero image.",
            "prompt_fingerprint": "img_fp_001",
            "asset_slots": [],
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "warnings": [],
            "source_of_truth_notes": ["IMG authority note"],
            "metadata_handoff": {"image_prompt_metadata_isolated": True, "route": "ECOMMERCE_FASHION_HERO"},
            "overlay_spec": {"render_text_inside_image": False, "recommended_text": None},
            "export_spec": {"recommended_aspect_ratio": "1:1", "color_profile": "sRGB"},
            "image_route": "ECOMMERCE_FASHION_HERO",
        }

    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.get_approved_product_package", fake_package)

    result = await compile_workspace_prompt_preview(
        product_id="prod-img",
        mode="IMG",
        duration_seconds=8,
        camera_style="UGC_IPHONE_RAW",
        character_presence="VISIBLE_CREATOR",
        creator_persona="DEFAULT_CREATOR",
    )

    assert result["compiler_version"] == "img_prompt_compiler_v1"
    assert result["final_compiled_prompt_text"] == "Subject: Photorealistic apparel hero image."
    assert result["metadata_handoff"]["route"] == "ECOMMERCE_FASHION_HERO"
    assert result["overlay_spec"]["render_text_inside_image"] is False
    assert result["export_spec"]["color_profile"] == "sRGB"
