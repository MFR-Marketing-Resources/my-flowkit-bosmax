import inspect

import pytest

from agent.models.destination_adapters import DestinationAdapterResponse
from agent.models.product_driven_planning import ProductDrivenAutoPlannerResponse
from agent.models.prompt_output_composer import PromptOutputComposerResponse
from agent.models.prompt_preview import PromptPreviewResponse
from agent.models.registry_driven_planning import RegistryDrivenManualPlannerResponse
from agent.models.temporal_block_planner import TemporalBlockPlannerResponse, TemporalPlanBlock
from agent.services.prompt_preview_pipeline import run_prompt_preview_pipeline


def _product_preview_request(output_type: str = "IMAGE_PROMPT", include_temporal_plan: bool = False) -> dict:
    return {
        "source_route": "PRODUCT_DRIVEN_AUTO",
        "destination_mode": "IMAGE" if output_type == "IMAGE_PROMPT" else "TEXT_TO_VIDEO",
        "output_type": output_type,
        "product_payload": {
            "id": "prod-001",
            "product_display_name": "Atlas Bottle",
            "product_short_name": "Atlas",
            "image_url": "https://example.com/product.png",
        },
        "asset_bindings": [],
        "target_duration_seconds": 16,
        "block_duration_seconds": 8,
        "extension_strategy": "EXTEND_CONTINUITY",
        "include_temporal_plan": include_temporal_plan,
        "dry_run_only": True,
    }


def _registry_preview_request(destination_mode: str = "TEXT_TO_VIDEO", output_type: str = "VIDEO_9_SECTION_PROMPT") -> dict:
    return {
        "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
        "destination_mode": destination_mode,
        "output_type": output_type,
        "product_payload": {
            "id": "prod-002",
            "product_display_name": "Signal Serum",
            "product_short_name": "Signal",
        },
        "avatar_id": "avatar-001",
        "scene_context": "Premium mirror vanity with controlled reflections.",
        "camera_style": "Medium shot into close-up.",
        "language": "English",
        "asset_bindings": [
            {"asset_role": "START_FRAME", "asset_source": "UPLOAD", "asset_id": "frame-001"}
        ]
        if destination_mode == "FRAMES"
        else [],
        "target_duration_seconds": 8,
        "block_duration_seconds": 8,
        "extension_strategy": "NONE",
        "include_temporal_plan": False,
        "dry_run_only": True,
    }


def _product_planner_response(status: str = "WARN") -> ProductDrivenAutoPlannerResponse:
    return ProductDrivenAutoPlannerResponse(
        planning_status=status,
        product_context={"product_id": "prod-001", "product_short_name": "Atlas", "image_url": "https://example.com/product.png"},
        inferred_context={"scene_context": "Studio setup", "requested_character": "Confident host"},
        planner_request={"dry_run_only": True},
        planner_output={"planning_status": status, "block_count": 1, "blocks": []},
        warnings=["PLANNER_WARN"] if status == "WARN" else [],
        errors=["PLANNER_ERROR"] if status == "FAIL" else [],
        provenance={"scope": "ROUND_2_PRODUCT_DRIVEN_AUTO_PLANNER_ONLY"},
        not_verified_fields=[],
    )


def _registry_planner_response(status: str = "WARN") -> RegistryDrivenManualPlannerResponse:
    return RegistryDrivenManualPlannerResponse(
        planning_status=status,
        manual_context={"avatar_id": "avatar-001", "scene_context": "Vanity", "product_context": {"product_short_name": "Signal"}},
        selected_fields={"avatar_id": "avatar-001"},
        planner_request={"dry_run_only": True},
        planner_output={"planning_status": status, "block_count": 1, "blocks": []},
        warnings=["REGISTRY_WARN"] if status == "WARN" else [],
        errors=["REGISTRY_ERROR"] if status == "FAIL" else [],
        provenance={"scope": "ROUND_3_REGISTRY_DRIVEN_MANUAL_ASSISTED_PLANNER_ONLY"},
        not_verified_fields=[],
        external_registry_dependencies=[],
        compatibility_status={},
    )


def _adapter_response(destination_mode: str, output_type: str, status: str = "WARN") -> DestinationAdapterResponse:
    mode_payload: dict = {
        "mode": destination_mode,
        "image_generation": True,
        "video_continuation": False,
        "image_intent": "create_character_holding_product",
        "composition": "Three-quarter hero framing.",
        "lighting": "Soft studio lighting.",
        "product_handling": "Hold product upright.",
        "negative_prompt_notes": ["No distortion."],
        "aspect_ratio_or_platform": "vertical_9_16",
    }
    if output_type == "VIDEO_9_SECTION_PROMPT":
        mode_payload = {
            "mode": destination_mode,
            "character_description": "Confident host.",
            "product_description": "Compact bottle.",
            "scene_description": "Premium vanity.",
            "action_description": "Reveal then rotate product.",
            "camera_description": "Medium shot into close-up.",
            "dialogue_or_narration": "Short narration.",
            "overlay_strategy": "Minimal overlay.",
        }
    if destination_mode == "FRAMES":
        mode_payload = {
            "mode": "FRAMES",
            "requires_start_frame": True,
            "supports_end_frame": True,
        }
    return DestinationAdapterResponse(
        adapter_status=status,
        source_route="PRODUCT_DRIVEN_AUTO",
        destination_mode=destination_mode,
        output_type=output_type,
        mode_payload=mode_payload,
        asset_requirements=[
            {"asset_role": "START_FRAME", "required": True, "satisfied": True, "reason": "Required start frame."}
        ]
        if destination_mode == "FRAMES"
        else [],
        missing_assets=[],
        warnings=["ADAPTER_WARN"] if status == "WARN" else [],
        errors=["ADAPTER_ERROR"] if status == "FAIL" else [],
        provenance={"scope": "ROUND_4_DESTINATION_MODE_ADAPTERS_ONLY"},
        planner_block_summary={"block_count": 1, "block_duration_seconds": 8, "extension_strategy": "NONE"},
        execution_allowed=False,
    )


def _composer_response(status: str = "WARN", output_type: str = "IMAGE_PROMPT") -> PromptOutputComposerResponse:
    return PromptOutputComposerResponse(
        composer_status=status,
        source_route="PRODUCT_DRIVEN_AUTO",
        destination_mode="IMAGE" if output_type == "IMAGE_PROMPT" else "TEXT_TO_VIDEO",
        output_type=output_type,
        prompt_text="Offline prompt text." if output_type == "IMAGE_PROMPT" else "1. Section one.\n\n2. Section two.\n\n3. Section three.\n\n4. Section four.\n\n5. Section five.\n\n6. Section six.\n\n7. Section seven.\n\n8. Section eight.\n\n9. Section nine.",
        sections=[] if output_type == "IMAGE_PROMPT" else [f"{index}. Section {index}." for index in range(1, 10)],
        section_count=0 if output_type == "IMAGE_PROMPT" else 9,
        block_summary={"block_count": 2, "block_duration_seconds": 8},
        negative_prompt_notes=["No distortion."],
        aspect_ratio_or_platform="vertical_9_16",
        product_handling_notes="Hold product upright.",
        asset_reference_notes=["PRODUCT asset optional."],
        dialogue_or_narration_notes="Short narration.",
        overlay_notes="Minimal overlay.",
        warnings=["COMPOSER_WARN"] if status == "WARN" else [],
        errors=["COMPOSER_ERROR"] if status == "FAIL" else [],
        provenance={"scope": "ROUND_5_PROMPT_OUTPUT_COMPOSER_ONLY"},
        execution_allowed=False,
    )


def _temporal_response(status: str = "WARN") -> TemporalBlockPlannerResponse:
    return TemporalBlockPlannerResponse(
        temporal_status=status,
        source_route="PRODUCT_DRIVEN_AUTO",
        destination_mode="TEXT_TO_VIDEO",
        output_type="VIDEO_9_SECTION_PROMPT",
        target_duration_seconds=16,
        block_duration_seconds=8,
        block_count=2,
        extension_strategy="EXTEND_CONTINUITY",
        temporal_blocks=[
            TemporalPlanBlock(
                block_index=1,
                duration_seconds=8,
                flow_action_planned="INITIAL_GENERATE",
                prompt_role="OPENING",
                transition_intent="START",
                prompt_text="Opening block prompt.",
            ),
            TemporalPlanBlock(
                block_index=2,
                duration_seconds=8,
                flow_action_planned="EXTEND_CONTINUITY",
                prompt_role="CONTINUATION",
                depends_on_block_index=1,
                transition_intent="FROM_LAST_FRAME",
                continuation_prefix="From the last frame, the same character continues...",
                prompt_text="Continuation block prompt.",
            ),
        ],
        warnings=["TEMPORAL_WARN"] if status == "WARN" else [],
        errors=["TEMPORAL_ERROR"] if status == "FAIL" else [],
        provenance={"scope": "ROUND_6_TEMPORAL_BLOCK_PLANNER_ONLY"},
        execution_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
    )


@pytest.mark.asyncio
async def test_product_driven_image_prompt_preview_runs_through_product_planner_adapter_and_composer(monkeypatch):
    calls = {"product": 0, "registry": 0, "adapter": 0, "composer": 0, "temporal": 0}

    async def fake_product(request):
        calls["product"] += 1
        return _product_planner_response()

    async def fake_registry(request):
        calls["registry"] += 1
        return _registry_planner_response()

    async def fake_adapter(request):
        calls["adapter"] += 1
        return _adapter_response("IMAGE", "IMAGE_PROMPT")

    async def fake_composer(request):
        calls["composer"] += 1
        return _composer_response(output_type="IMAGE_PROMPT")

    async def fake_temporal(request):
        calls["temporal"] += 1
        return _temporal_response()

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_registry_driven_manual_plan", fake_registry)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_temporal_block_plan", fake_temporal)

    result = await run_prompt_preview_pipeline(_product_preview_request())

    assert result.preview_status == "WARN"
    assert result.source_route == "PRODUCT_DRIVEN_AUTO"
    assert result.output_type == "IMAGE_PROMPT"
    assert result.composer_output["prompt_text"] == "Offline prompt text."
    assert calls == {"product": 1, "registry": 0, "adapter": 1, "composer": 1, "temporal": 0}


@pytest.mark.asyncio
async def test_product_driven_video_9_section_prompt_preview_can_include_temporal_planner_when_requested(monkeypatch):
    calls = {"product": 0, "adapter": 0, "composer": 0, "temporal": 0}

    async def fake_product(request):
        calls["product"] += 1
        return _product_planner_response()

    async def fake_adapter(request):
        calls["adapter"] += 1
        return _adapter_response("TEXT_TO_VIDEO", "VIDEO_9_SECTION_PROMPT")

    async def fake_composer(request):
        calls["composer"] += 1
        return _composer_response(output_type="VIDEO_9_SECTION_PROMPT")

    async def fake_temporal(request):
        calls["temporal"] += 1
        return _temporal_response()

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_temporal_block_plan", fake_temporal)

    result = await run_prompt_preview_pipeline(_product_preview_request("VIDEO_9_SECTION_PROMPT", include_temporal_plan=True))

    assert result.preview_status == "WARN"
    assert result.temporal_output["block_count"] == 2
    assert calls == {"product": 1, "adapter": 1, "composer": 1, "temporal": 1}


@pytest.mark.asyncio
async def test_registry_driven_text_to_video_preview_runs_through_registry_planner_adapter_and_composer(monkeypatch):
    calls = {"product": 0, "registry": 0, "adapter": 0, "composer": 0}

    async def fake_product(request):
        calls["product"] += 1
        return _product_planner_response()

    async def fake_registry(request):
        calls["registry"] += 1
        return _registry_planner_response()

    async def fake_adapter(request):
        calls["adapter"] += 1
        return _adapter_response("TEXT_TO_VIDEO", "VIDEO_9_SECTION_PROMPT")

    async def fake_composer(request):
        calls["composer"] += 1
        return _composer_response(output_type="VIDEO_9_SECTION_PROMPT")

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_registry_driven_manual_plan", fake_registry)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)

    result = await run_prompt_preview_pipeline(_registry_preview_request())

    assert result.preview_status == "WARN"
    assert result.source_route == "REGISTRY_DRIVEN_MANUAL_ASSISTED"
    assert result.composer_output["section_count"] == 9
    assert calls == {"product": 0, "registry": 1, "adapter": 1, "composer": 1}


@pytest.mark.asyncio
async def test_registry_driven_frames_preview_preserves_start_frame_asset_requirements(monkeypatch):
    async def fake_registry(request):
        return _registry_planner_response()

    async def fake_adapter(request):
        return _adapter_response("FRAMES", "PROMPT_BLOCK_PLAN")

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_registry_driven_manual_plan", fake_registry)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)

    result = await run_prompt_preview_pipeline(_registry_preview_request(destination_mode="FRAMES", output_type="PROMPT_BLOCK_PLAN"))

    assert result.preview_status == "WARN"
    assert result.adapter_output["asset_requirements"][0]["asset_role"] == "START_FRAME"
    assert result.composer_output == {}


@pytest.mark.asyncio
async def test_include_temporal_plan_false_skips_temporal_planner(monkeypatch):
    calls = {"temporal": 0}

    async def fake_product(request):
        return _product_planner_response()

    async def fake_adapter(request):
        return _adapter_response("TEXT_TO_VIDEO", "VIDEO_9_SECTION_PROMPT")

    async def fake_composer(request):
        return _composer_response(output_type="VIDEO_9_SECTION_PROMPT")

    async def fake_temporal(request):
        calls["temporal"] += 1
        return _temporal_response()

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_temporal_block_plan", fake_temporal)

    result = await run_prompt_preview_pipeline(_product_preview_request("VIDEO_9_SECTION_PROMPT", include_temporal_plan=False))

    assert result.temporal_output == {}
    assert calls["temporal"] == 0


@pytest.mark.asyncio
async def test_include_temporal_plan_true_calls_temporal_planner_for_video_output(monkeypatch):
    calls = {"temporal": 0}

    async def fake_product(request):
        return _product_planner_response()

    async def fake_adapter(request):
        return _adapter_response("TEXT_TO_VIDEO", "VIDEO_9_SECTION_PROMPT")

    async def fake_composer(request):
        return _composer_response(output_type="VIDEO_9_SECTION_PROMPT")

    async def fake_temporal(request):
        calls["temporal"] += 1
        return _temporal_response()

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_temporal_block_plan", fake_temporal)

    result = await run_prompt_preview_pipeline(_product_preview_request("VIDEO_9_SECTION_PROMPT", include_temporal_plan=True))

    assert result.temporal_output["temporal_status"] == "WARN"
    assert calls["temporal"] == 1


@pytest.mark.asyncio
async def test_dry_run_only_false_fails():
    request = _product_preview_request()
    request["dry_run_only"] = False

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "DRY_RUN_ONLY_FALSE_NOT_ALLOWED_IN_ROUND_7" in result.errors


@pytest.mark.asyncio
async def test_unknown_source_route_fails():
    request = _product_preview_request()
    request["source_route"] = "UNKNOWN"

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "UNKNOWN_SOURCE_ROUTE:UNKNOWN" in result.errors


@pytest.mark.asyncio
async def test_unknown_destination_mode_fails():
    request = _product_preview_request()
    request["destination_mode"] = "UNKNOWN"

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "UNKNOWN_DESTINATION_MODE:UNKNOWN" in result.errors


@pytest.mark.asyncio
async def test_unknown_output_type_fails():
    request = _product_preview_request()
    request["output_type"] = "UNKNOWN"

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "UNKNOWN_OUTPUT_TYPE:UNKNOWN" in result.errors


@pytest.mark.asyncio
async def test_downstream_planner_fail_propagates_to_preview_fail(monkeypatch):
    async def fake_product(request):
        return _product_planner_response(status="FAIL")

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)

    result = await run_prompt_preview_pipeline(_product_preview_request())

    assert result.preview_status == "FAIL"
    assert "DOWNSTREAM_PLANNER_FAIL" in result.errors


@pytest.mark.asyncio
async def test_upstream_and_downstream_warnings_are_preserved(monkeypatch):
    async def fake_product(request):
        return _product_planner_response()

    async def fake_adapter(request):
        return _adapter_response("IMAGE", "IMAGE_PROMPT")

    async def fake_composer(request):
        return _composer_response(output_type="IMAGE_PROMPT")

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)

    result = await run_prompt_preview_pipeline(_product_preview_request())

    assert "PLANNER_WARN" in result.warnings
    assert "ADAPTER_WARN" in result.warnings
    assert "COMPOSER_WARN" in result.warnings


@pytest.mark.asyncio
async def test_execution_flags_are_always_false(monkeypatch):
    async def fake_product(request):
        return _product_planner_response()

    async def fake_adapter(request):
        return _adapter_response("IMAGE", "IMAGE_PROMPT")

    async def fake_composer(request):
        return _composer_response(output_type="IMAGE_PROMPT")

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)

    result = await run_prompt_preview_pipeline(_product_preview_request())

    assert result.execution_allowed is False
    assert result.flow_execution_allowed is False
    assert result.batch_execution_allowed is False
    assert result.dry_run_only is True


@pytest.mark.asyncio
async def test_dom_flow_extend_insert_render_and_batch_execution_attempts_fail():
    keys_to_errors = {
        "execute_dom": "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_7",
        "execute_flow": "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_7",
        "execute_extend": "EXTEND_INSERT_EXECUTION_NOT_ALLOWED_IN_ROUND_7",
        "render_complete_detection": "RENDER_COMPLETE_DETECTION_NOT_ALLOWED_IN_ROUND_7",
        "batch_execution": "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_7",
    }

    for key, expected_error in keys_to_errors.items():
        request = _product_preview_request()
        request[key] = True
        result = await run_prompt_preview_pipeline(request)
        assert result.preview_status == "FAIL"
        assert expected_error in result.errors


@pytest.mark.asyncio
async def test_upload_generation_execution_attempts_fail():
    request = _product_preview_request()
    request["execute_generation"] = True

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_7" in result.errors


@pytest.mark.asyncio
async def test_canonical_registry_write_attempt_fails():
    request = _product_preview_request()
    request["canonical_registry_write"] = True

    result = await run_prompt_preview_pipeline(request)

    assert result.preview_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_7" in result.errors


@pytest.mark.asyncio
async def test_dimension_and_claim_invention_attempts_fail():
    dimension_request = _product_preview_request()
    dimension_request["invent_product_dimensions"] = True
    claim_request = _product_preview_request()
    claim_request["invent_product_claims"] = True

    dimension_result = await run_prompt_preview_pipeline(dimension_request)
    claim_result = await run_prompt_preview_pipeline(claim_request)

    assert "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED" in dimension_result.errors
    assert "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED" in claim_result.errors


@pytest.mark.asyncio
async def test_forbidden_marker_leakage_is_flagged(monkeypatch):
    async def fake_product(request):
        return _product_planner_response()

    async def fake_adapter(request):
        return _adapter_response("IMAGE", "IMAGE_PROMPT")

    async def fake_composer(request):
        return PromptOutputComposerResponse(
            composer_status="WARN",
            source_route="PRODUCT_DRIVEN_AUTO",
            destination_mode="IMAGE",
            output_type="IMAGE_PROMPT",
            prompt_text="CTX_BAD image prompt.",
            warnings=["COMPOSER_WARN"],
            errors=[],
            provenance={"scope": "ROUND_5_PROMPT_OUTPUT_COMPOSER_ONLY"},
            execution_allowed=False,
        )

    monkeypatch.setattr("agent.services.prompt_preview_pipeline.create_product_driven_auto_plan", fake_product)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.adapt_destination_mode_payload", fake_adapter)
    monkeypatch.setattr("agent.services.prompt_preview_pipeline.compose_prompt_output", fake_composer)

    result = await run_prompt_preview_pipeline(_product_preview_request())

    assert result.preview_status == "FAIL"
    assert "FORBIDDEN_INTERNAL_MARKER_LEAKAGE" in result.errors


@pytest.mark.asyncio
async def test_service_does_not_import_or_call_extension_flow_batch_dom_ui_or_runtime_modules():
    result = PromptPreviewResponse(preview_status="PASS")
    from agent.services import prompt_preview_pipeline

    source = inspect.getsource(prompt_preview_pipeline)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "simulateFileUpload",
        "agent.api.operator",
        "dashboard.",
        "runtime_orchestrator",
        "chrome.runtime",
    ]

    assert result.execution_allowed is False
    assert result.flow_execution_allowed is False
    assert result.batch_execution_allowed is False
    for token in banned_tokens:
        assert token not in source
