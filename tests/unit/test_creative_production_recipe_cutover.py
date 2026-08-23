"""Production Studio's public three-recipe cutover contract."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agent.models.creative_production import (
    CreativePoolSelection,
    PoolAuthorityRequest,
    ProductVideoAllocation,
    ProductionPlanCreateRequest,
    ProductionPlanUpdateRequest,
    ProductionRecipe,
    TreatmentAvailabilityRequest,
)
from agent.services.creative_production_recipe_service import (
    ProductionRecipeError,
    current_production_recipe_values,
    recipe_for_plan,
    resolve_production_recipe,
)


def _create(**overrides: object) -> ProductionPlanCreateRequest:
    values: dict[str, object] = {
        "request_id": "recipe-cutover-request",
        "operator_id": "recipe-cutover-operator",
        "name": "Recipe cutover plan",
        "product_ids": ["product-1"],
        "product_video_allocations": [
            ProductVideoAllocation(product_id="product-1", video_count=1)
        ],
        "target_video_count": 1,
        "production_recipe": ProductionRecipe.HYBRID,
        "model_keys": ["veo_3_1_lite"],
        "duration_seconds": [8],
        "pools": CreativePoolSelection(),
    }
    values.update(overrides)
    return ProductionPlanCreateRequest(**values)


def test_public_recipe_values_are_exact_and_ordered():
    assert current_production_recipe_values() == ("HYBRID", "FACELESS", "MONTAGE")
    assert tuple(recipe.value for recipe in ProductionRecipe) == (
        "HYBRID",
        "FACELESS",
        "MONTAGE",
    )


@pytest.mark.parametrize("retired", ["T2V", "F2V", "I2V"])
def test_new_plan_rejects_retired_logical_modes(retired: str):
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_RETIRED"):
        _create(logical_mode=retired)
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_RETIRED"):
        _create(production_recipe=retired)


def test_new_plan_requires_recipe_and_video_only_targets():
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_REQUIRED"):
        _create(production_recipe=None)
    with pytest.raises(ValidationError, match="PRODUCTION_STUDIO_VIDEO_ONLY"):
        _create(target_image_count=1)
    with pytest.raises(ValidationError, match="PRODUCTION_STUDIO_VIDEO_ONLY"):
        _create(target_poster_count=1)
    with pytest.raises(ValidationError, match="PRODUCTION_STUDIO_VIDEO_ONLY"):
        _create(target_video_count=0)


def test_montage_uses_the_canonical_single_clip_portrait_contract():
    with pytest.raises(ValidationError, match="MONTAGE_ASPECT_9_16_ONLY"):
        _create(
            production_recipe=ProductionRecipe.MONTAGE,
            execution_policy={"aspect": "16:9"},
        )


def test_update_treatments_and_pool_authority_reject_retired_public_modes():
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_RETIRED"):
        ProductionPlanUpdateRequest(
            request_id="update-request",
            operator_id="operator",
            logical_mode="T2V",
        )
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_RETIRED"):
        PoolAuthorityRequest(product_ids=["product-1"], logical_mode="F2V")
    with pytest.raises(ValidationError, match="PRODUCTION_RECIPE_RETIRED"):
        TreatmentAvailabilityRequest(
            product_video_allocations=[
                ProductVideoAllocation(product_id="product-1", video_count=1)
            ],
            production_recipe=ProductionRecipe.HYBRID,
            logical_mode="I2V",
            model_key="veo_3_1_lite",
            duration_seconds=8,
            creative_format="AUTO",
            treatment_ids=[],
        )


def test_recipe_adapters_preserve_private_transport_primitives():
    hybrid = resolve_production_recipe("HYBRID")
    faceless = resolve_production_recipe("faceless")
    montage = resolve_production_recipe(ProductionRecipe.MONTAGE)
    assert hybrid.internal_logical_mode == "HYBRID"
    assert hybrid.treatment_logical_mode == "HYBRID"
    assert faceless.internal_logical_mode == "F2V"
    assert faceless.treatment_logical_mode == "F2V"
    assert montage.internal_logical_mode == "F2V"
    assert montage.treatment_logical_mode == "F2V"
    assert faceless.canonical_authority.startswith("faceless_lane_service")
    assert montage.canonical_authority.startswith("montage_run_service")


def test_recipe_resolver_preserves_retirement_error_for_private_callers():
    with pytest.raises(ProductionRecipeError) as error:
        resolve_production_recipe("T2V")
    assert error.value.code == "PRODUCTION_RECIPE_RETIRED"


def test_recipe_copy_validation_preserves_surface_and_transport_lanes():
    from agent.services import creative_production_scheduler_service as scheduler

    assert scheduler._copy_validation_lane(
        {"lane": "FACELESS"},
        {"production_recipe": "FACELESS"},
        "PRODUCTION_STUDIO_P6",
    ) == "FACELESS"
    assert scheduler._copy_validation_lane(
        {"lane": "MONTAGE"},
        {"production_recipe": "MONTAGE"},
        "PRODUCTION_STUDIO_P6",
    ) == "MONTAGE"
    assert scheduler._copy_validation_lane(
        {"lane": "FACELESS"},
        {"production_recipe": "HYBRID"},
        "PRODUCTION_STUDIO_P6",
    ) == "PRODUCTION_STUDIO_P6"


def test_historical_plan_recipe_is_not_invented():
    historical = {
        "logical_mode": "T2V",
        "production_recipe": None,
    }
    assert recipe_for_plan(historical) is None
    assert recipe_for_plan({"logical_mode": "F2V"}) is None
    assert recipe_for_plan({"production_recipe": "HYBRID"}).recipe is ProductionRecipe.HYBRID


def _treatment() -> dict[str, object]:
    return {
        "treatment_id": "treatment-1",
        "treatment_sha256": "a" * 64,
        "visual_fingerprint_sha256": "b" * 64,
        "dependency_hashes": {"copy_set_sha256": "c" * 64},
        "variation_group": {"group_sha256": "d" * 64},
        "variation_group_id": "group-1",
        "format": "UGC",
        "generation_mode": "SINGLE",
        "segment_plan": [],
        "shot_grammar": [],
    }


@pytest.mark.asyncio
async def test_hybrid_compiler_delegates_to_canonical_hybrid_authority(monkeypatch):
    from agent.services import creative_production_compile_service as compiler

    hybrid = AsyncMock(
        return_value={
            "workspace_generation_package_id": "wgp-hybrid",
            "final_prompt_text": "approved hybrid prompt",
            "prompt_fingerprint": "e" * 64,
            "status": "READY",
            "blockers_json": "[]",
            "copy_architecture_v2": {"v2_enabled": True, "status": "READY"},
        }
    )
    monkeypatch.setattr(compiler, "resolve_item_treatment", AsyncMock(return_value=_treatment()))
    monkeypatch.setattr(compiler.wgp_service, "create_hybrid_generation_package", hybrid)

    wgp_id, _, evidence = await compiler._compile_video(
        {
            "item_id": "item-hybrid",
            "product_id": "product-1",
            "creative_dna_sha256": "f" * 64,
        },
        {
            "plan_id": "plan-hybrid",
            "logical_mode": "HYBRID",
            "production_recipe": "HYBRID",
            "execution_policy_json": '{"aspect":"9:16"}',
            "pool_snapshot_json": "{}",
        },
        {
            "model_key": "veo_3_1_lite",
            "duration_seconds": 8,
            "generation_mode": "SINGLE",
            "engine_block_duration_seconds": 8,
        },
    )

    assert wgp_id == "wgp-hybrid"
    hybrid.assert_awaited_once()
    assert evidence["recipe_execution"]["canonical_authority"].endswith(
        "create_hybrid_generation_package"
    )


@pytest.mark.asyncio
async def test_faceless_compiler_delegates_to_canonical_faceless_and_wep_authorities(
    monkeypatch,
):
    from agent.services import creative_production_compile_service as compiler
    from agent.services import faceless_lane_service as faceless

    monkeypatch.setattr(compiler, "resolve_item_treatment", AsyncMock(return_value=_treatment()))
    monkeypatch.setattr(
        faceless,
        "validate_faceless_inputs",
        lambda **_: (True, None, None),
    )
    monkeypatch.setattr(
        faceless,
        "resolve_faceless_video_configuration",
        lambda **_: (True, None, None, {"generation_mode": "SINGLE", "engine_block_duration_seconds": 8}),
    )
    monkeypatch.setattr(
        faceless,
        "resolve_faceless_scene_authority",
        AsyncMock(return_value={"background": {}, "scene_strategy": {}, "choreography": {}}),
    )
    monkeypatch.setattr(
        faceless,
        "build_faceless_resolution",
        lambda **_: {
            "transport_mode": "F2V",
            "source_mode": "HYBRID",
            "hook": {"setting_id": "AUTO", "display_label": "Auto"},
            "background": {"setting_id": "AUTO", "display_label": "Auto"},
            "scene_strategy": {},
            "choreography": {},
            "faceless_resolution": {"source_mode": "HYBRID"},
        },
    )
    wep = AsyncMock(
        return_value={
            "workspace_execution_package_id": "wep-faceless",
            "prompt_text": "approved faceless prompt",
            "prompt_fingerprint": "1" * 64,
            "execution_allowed": True,
            "blockers": "[]",
            "mode": "F2V",
            "duration_seconds": 8,
            "aspect_ratio": "9:16",
            "model": "veo_3_1_lite",
            "generation_mode": "SINGLE",
            "asset_slots": "[]",
            "resolved_assets": "[]",
        }
    )
    monkeypatch.setattr(compiler.wep_service, "create_workspace_execution_package", wep)
    bridge = AsyncMock(
        return_value=(
            "p6recipe-faceless",
            "1" * 64,
            {"recipe_execution": {"production_recipe": "FACELESS"}},
        )
    )
    monkeypatch.setattr(compiler, "_create_p6_execution_bridge", bridge)

    wgp_id, _, evidence = await compiler._compile_video(
        {"item_id": "item-faceless", "product_id": "product-1"},
        {
            "plan_id": "plan-faceless",
            "logical_mode": "F2V",
            "production_recipe": "FACELESS",
            "execution_policy_json": '{"aspect":"9:16"}',
            "pool_snapshot_json": "{}",
        },
        {
            "model_key": "veo_3_1_lite",
            "duration_seconds": 8,
            "generation_mode": "SINGLE",
            "engine_block_duration_seconds": 8,
        },
    )

    assert wgp_id == "p6recipe-faceless"
    wep.assert_awaited_once()
    bridge.assert_awaited_once()
    assert bridge.await_args.kwargs["treatment"] == _treatment()
    assert evidence["recipe_execution"]["production_recipe"] == "FACELESS"


@pytest.mark.asyncio
async def test_montage_compiler_delegates_to_canonical_montage_run_authority(
    monkeypatch,
):
    from agent.services import creative_production_compile_service as compiler
    from agent.services import montage_run_service
    from agent.services.montage_scene_reference_policy import SceneReferencePolicy

    monkeypatch.setattr(compiler, "resolve_item_treatment", AsyncMock(return_value=_treatment()))
    create_run = AsyncMock(
        return_value={
            "ok": True,
            "montage_run_id": "montage-run-1",
            "total_scenes": 1,
            "scenes": [
                {
                    "workspace_execution_package_id": "wep-scene-1",
                    "package_prompt": "montage scene prompt",
                }
            ],
        }
    )
    monkeypatch.setattr(montage_run_service, "create_montage_discrete_run", create_run)
    monkeypatch.setattr(
        compiler.core_crud,
        "get_workspace_execution_package",
        AsyncMock(
            return_value={
                "workspace_execution_package_id": "wep-scene-1",
                "prompt_text": "montage scene prompt",
                "prompt_fingerprint": "2" * 64,
                "mode": "F2V",
                "generation_mode": "SINGLE",
                "asset_slots": "[]",
                "resolved_assets": "[]",
            }
        ),
    )
    bridge = AsyncMock(
        return_value=(
            "p6recipe-montage",
            "2" * 64,
            {"recipe_execution": {"production_recipe": "MONTAGE"}},
        )
    )
    monkeypatch.setattr(compiler, "_create_p6_execution_bridge", bridge)

    wgp_id, _, evidence = await compiler._compile_video(
        {"item_id": "item-montage", "product_id": "product-1"},
        {
            "plan_id": "plan-montage",
            "logical_mode": "F2V",
            "production_recipe": "MONTAGE",
            "execution_policy_json": '{"aspect":"9:16"}',
            "pool_snapshot_json": "{}",
        },
        {
            "model_key": "veo_3_1_lite",
            "duration_seconds": 8,
            "generation_mode": "SINGLE",
            "engine_block_duration_seconds": 8,
        },
    )

    assert wgp_id == "p6recipe-montage"
    create_run.assert_awaited_once()
    assert create_run.await_args.kwargs["default_policy"] is SceneReferencePolicy.PRODUCT_ANCHOR
    bridge.assert_awaited_once()
    assert bridge.await_args.kwargs["treatment"] == _treatment()
    assert evidence["montage_run_id"] == "montage-run-1"


def test_recipe_bridge_treatment_lineage_matches_scheduler_contract():
    from agent.services import creative_production_compile_service as compiler

    assert compiler._p6_treatment_lineage(
        _treatment(), generation_mode="SINGLE"
    ) == {
        "treatment_id": "treatment-1",
        "treatment_sha256": "a" * 64,
        "visual_fingerprint_sha256": "b" * 64,
        "dependency_hashes": {"copy_set_sha256": "c" * 64},
        "variation_group": {"group_sha256": "d" * 64},
        "format": "UGC",
        "generation_mode": "SINGLE",
        "segment_plan_sha256": None,
        "ordered_segment_sha256s": [],
    }


@pytest.mark.asyncio
async def test_faceless_scheduler_payload_preserves_canonical_package_lineage(monkeypatch):
    from agent.services import creative_production_scheduler_service as scheduler

    wep = {
        "workspace_execution_package_id": "wep-faceless-runtime",
        "product_id": "product-1",
        "mode": "F2V",
        "prompt_text": "approved faceless prompt",
        "aspect_ratio": "9:16",
        "model": "veo_3_1_lite",
        "duration_seconds": 8,
        "execution_allowed": 1,
        "blockers": "[]",
        "asset_slots": json.dumps(
            [
                {
                    "slot_key": "start_frame",
                    "resolved_asset": {
                        "asset_id": "asset-product-1",
                        "asset_fingerprint": "a" * 64,
                        "asset_source": "PRODUCT_VISUAL_OFFICIAL",
                        "file_name": "product.png",
                        "local_file_path": "output/product.png",
                        "media_id": None,
                    },
                }
            ]
        ),
        "resolved_assets": "[]",
        "request_lineage_payload": json.dumps(
            {
                "product_id": "product-1",
                "compiler": {"source_mode": "HYBRID"},
                "faceless_execution_identity": {
                    "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
                    "lane": "FACELESS",
                    "product_id": "product-1",
                },
            }
        ),
    }
    monkeypatch.setattr(
        scheduler.crud,
        "get_workspace_execution_package",
        AsyncMock(return_value=wep),
    )

    payload, blockers = await scheduler._build_recipe_execution_payload(
        {"product_id": "product-1", "workspace_generation_package_id": "wgp-1"},
        {},
        {
            "generation_mode": "SINGLE",
            "workspace_execution_package_id": "wep-faceless-runtime",
        },
        aspect="9:16",
        metadata={"production_recipe": "FACELESS"},
    )

    assert blockers == []
    assert payload["workspace_execution_package_id"] == "wep-faceless-runtime"
    assert payload["source_mode"] == "HYBRID"
    assert payload["start_asset"]["assetId"] == "asset-product-1"
    assert payload["start_asset"]["officialVisual"] is True
    assert payload["faceless_execution_identity"]["lane"] == "FACELESS"


@pytest.mark.asyncio
async def test_faceless_scheduler_dispatch_uses_package_aware_flow_generate(
    monkeypatch,
):
    from agent.api import flow
    from agent.services import creative_production_scheduler_service as scheduler
    from agent.services import execution_approval_service

    item = {
        "item_id": "item-faceless-runtime",
        "plan_id": "plan-faceless-runtime",
        "product_id": "product-1",
    }
    attempt = {
        "attempt_id": "attempt-faceless-runtime",
        "payload_snapshot_json": json.dumps(
            {
                "mode": "F2V",
                "prompt": "approved faceless prompt",
                "production_recipe": "FACELESS",
                "source_mode": "HYBRID",
                "workspace_execution_package_id": "wep-faceless-runtime",
                "image_media_ids": ["flow-media-1"],
                "start_asset": {"assetId": "asset-product-1"},
                "aspect": "9:16",
                "model": "veo_3_1_lite",
                "duration_s": 8,
                "num_videos": 1,
                "generation_mode": "SINGLE",
                "copy_v2_context": {"lane": "FACELESS"},
                "faceless_execution_identity": {
                    "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
                    "lane": "FACELESS",
                },
            }
        ),
    }
    monkeypatch.setattr(
        scheduler,
        "_acquire_item_lease",
        AsyncMock(
            return_value=(
                {"lane_id": "lane-1", "cooldown_seconds": 0},
                {"lease_id": "lease-1"},
            )
        ),
    )
    monkeypatch.setattr(scheduler.p6db, "update_attempt", AsyncMock(return_value=attempt))
    monkeypatch.setattr(scheduler.p6db, "update_item", AsyncMock())
    monkeypatch.setattr(scheduler, "_persist_provider_observation", AsyncMock(return_value=attempt))
    monkeypatch.setattr(
        execution_approval_service,
        "approved_manifest_id_for_run",
        AsyncMock(return_value="manifest-1"),
    )
    generate = AsyncMock(return_value={"job_id": "flow-job-1", "status": "SUBMITTED"})
    monkeypatch.setattr(flow, "generate", generate)
    monkeypatch.setattr(
        scheduler.make_video,
        "start_generate",
        AsyncMock(side_effect=AssertionError("Faceless must use /api/flow/generate")),
    )
    monkeypatch.setattr(scheduler.make_video, "get_job", lambda _job_id: None)

    result = await scheduler._dispatch_attempt(
        item,
        attempt,
        credit_confirmation="P6_LIVE_CONFIRMATION",
    )

    request = generate.await_args.args[0]
    assert request.workspace_execution_package_id == "wep-faceless-runtime"
    assert request.execution_identity["lane"] == "FACELESS"
    assert request.manifest_id == "manifest-1"
    assert request.manifest_item_key == "item-faceless-runtime"
    assert request.source_mode == "HYBRID"
    assert request.surface_lane == "PRODUCTION_STUDIO_P6"
    assert result["provider_job_id"] == "flow-job-1"
