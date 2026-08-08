"""Orchestration tests — prove package/generate chain is invoked (mocked)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.services.montage_scene_orchestrator import (
    ERR_MONTAGE_AVATAR_SELECTION_REQUIRED,
    execute_scene_plan,
    orchestrate_montage_scenes,
)
from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)


@pytest.mark.asyncio
async def test_image_first_calls_package_factory_with_f2v_start_frame() -> None:
    plan = MontageSceneExecutionPlan(
        scene_id="scene-1-hook",
        beat_id="hook",
        block_index=0,
        route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.START_FRAME,
        transport_mode="F2V",
        source_mode="FRAMES",
        image_generation_required=True,
        video_generation_required=True,
        objective="open",
        visual_action="hero",
        product_media_id="pm1",
        reference_media_ids=("sf1",),
    )
    pkg_factory = AsyncMock(
            return_value={
                "workspace_execution_package_id": "wep-1",
                "prompt_text": "hello",
                "execution_allowed": True,
            }
    )
    gen = AsyncMock(return_value={"job_id": "job-9", "media_id": "clip-9"})
    state = await execute_scene_plan(
        plan,
        product_id="p1",
        package_factory=pkg_factory,
        generate_fn=gen,
        model="Veo 3.1 - Lite",
        duration_seconds=8,
    )
    assert state.status == "VIDEO_READY"
    assert state.workspace_execution_package_id == "wep-1"
    assert state.video_media_id == "clip-9"
    kwargs = pkg_factory.await_args.kwargs
    assert kwargs["mode"] == "F2V"
    assert kwargs["start_frame_asset_id"] == "sf1"
    gen.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrate_full_story_calls_package_per_scene() -> None:
    beats = [
        SimpleNamespace(beat_id="hook", role="HOOK", objective="o1", visual_action="v1"),
        SimpleNamespace(beat_id="body", role="BODY", objective="o2", visual_action="v2"),
    ]
    pkg_factory = AsyncMock(
        side_effect=[
            {
                "workspace_execution_package_id": "wep-a",
                "prompt_text": "a",
                "execution_allowed": True,
                "asset_slots": [{"slot_key": "start_frame", "resolved_asset": {"download_url": "https://cdn.example/a.png"}}],
            },
            {
                "workspace_execution_package_id": "wep-b",
                "prompt_text": "b",
                "execution_allowed": True,
                "asset_slots": [{"slot_key": "start_frame", "resolved_asset": {"download_url": "https://cdn.example/b.png"}}],
            },
        ]
    )
    report = await orchestrate_montage_scenes(
        product_id="p1",
        story_beats=beats,
        package_factory=pkg_factory,
        product_media_id="pm1",
        default_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        model="Veo 3.1 - Lite",
        duration_seconds=8,
    )
    assert report.ok is True
    assert len(report.scenes) == 2
    assert pkg_factory.await_count == 2
    assert all(s.status == "PACKAGE_READY" for s in report.scenes)
    assert report.credit_spend is False
    assert all(
        call.kwargs["character_presence"] == "FACELESS"
        and call.kwargs["avatar_id"] is None
        for call in pkg_factory.await_args_list
    )


@pytest.mark.asyncio
async def test_product_anchor_real_package_compiler_path_reaches_ready(monkeypatch) -> None:
    product_id = "montage-product-1"
    stored: dict[str, object] = {}

    async def fake_approved_package(requested_product_id: str, mode: str):
        assert requested_product_id == product_id
        assert mode == "F2V"
        return {
            "prompt_package_snapshot_id": "montage-approved-package-1",
            "product_id": product_id,
            "product_name": "Montage Product",
            "mode": mode,
            "production_generation_allowed": True,
            "prompt_text": "Approved Montage product package.",
            "asset_slots": [
                {
                    "slot_key": "start_frame",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE",
                    "resolved_asset": {
                        "asset_id": f"product-image:{product_id}:start_frame",
                        "asset_fingerprint": "montage-anchor-fingerprint",
                        "slot_key": "start_frame",
                        "asset_source": "PRODUCT_IMAGE_CACHE",
                        "media_id": "montage-product-media-1",
                        "preview_url": "https://cdn.example/montage-product.png",
                        "download_url": "https://cdn.example/montage-product.png",
                    },
                },
                {"slot_key": "end_frame", "required": False, "resolved_asset": None},
            ],
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "source_of_truth_notes": ["Approved product fixture"],
            "claim_safe_rewrite": "A claim-safe product routine.",
            "scene_context": "Clean product-first room scene.",
        }

    async def fake_product(requested_product_id: str):
        return {
            "id": requested_product_id,
            "raw_product_title": "Montage Product",
            "product_display_name": "Montage Product",
            "category": "BEAUTY",
            "product_type": "BEAUTY_BOTTLE_OR_TUBE",
            "recommended_grip": "one hand",
            "handling_notes": "steady handling",
            "camera_handling_notes": "label forward",
            "scene_context": "Clean product-first room scene.",
        }

    async def fake_enrich(product, persist=False):
        return product

    async def fake_claim_safe_package(requested_product_id: str):
        return None

    async def fake_store(**kwargs):
        stored.update(kwargs)
        return kwargs

    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.get_approved_product_package",
        fake_approved_package,
    )
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.get_product",
        fake_product,
    )
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.enrich_product",
        fake_enrich,
    )
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.get_stored_claim_safe_package",
        fake_claim_safe_package,
    )
    monkeypatch.setattr(
        "agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package",
        fake_store,
    )

    plan = MontageSceneExecutionPlan(
        scene_id="scene-1-hook",
        beat_id="hook",
        block_index=0,
        route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        transport_mode="F2V",
        source_mode="HYBRID",
        image_generation_required=True,
        video_generation_required=True,
        objective="open",
        visual_action="product reveal",
    )
    state = await execute_scene_plan(
        plan,
        product_id=product_id,
        package_factory=create_workspace_execution_package,
        copy_fallback_confirmed=True,
        model="Veo 3.1 - Lite",
        duration_seconds=8,
    )

    assert state.status == "PACKAGE_READY"
    assert state.workspace_execution_package_id
    assert state.start_asset_snapshot["mediaId"] == "montage-product-media-1"
    compiler_lineage = json.loads(stored["request_lineage_payload"])["compiler"]
    assert compiler_lineage["character_presence"] == "FACELESS"
    assert compiler_lineage["avatar_id"] is None


@pytest.mark.asyncio
async def test_avatar_product_without_explicit_identity_fails_closed() -> None:
    plan = MontageSceneExecutionPlan(
        scene_id="scene-avatar",
        beat_id="avatar",
        block_index=0,
        route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.AVATAR_PRODUCT,
        transport_mode="F2V",
        source_mode="HYBRID",
        image_generation_required=True,
        video_generation_required=True,
        objective="present",
        visual_action="presenter holds product",
    )
    pkg_factory = AsyncMock()
    image_prepare = AsyncMock()

    state = await execute_scene_plan(
        plan,
        product_id="p1",
        package_factory=pkg_factory,
        image_prepare_fn=image_prepare,
    )

    assert state.status == "PACKAGE_FAILED"
    assert state.error_code == ERR_MONTAGE_AVATAR_SELECTION_REQUIRED
    assert "Avatar Registry" in state.detail
    pkg_factory.assert_not_awaited()
    image_prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_first_blocked_without_frame_or_image_fn() -> None:
    plan = MontageSceneExecutionPlan(
        scene_id="scene-x",
        beat_id="b",
        block_index=0,
        route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.START_FRAME,
        transport_mode="F2V",
        source_mode="FRAMES",
        image_generation_required=True,
        video_generation_required=True,
        objective="",
        visual_action="",
    )
    pkg_factory = AsyncMock()
    state = await execute_scene_plan(
        plan, product_id="p1", package_factory=pkg_factory
    )
    assert state.status == "IMAGE_PENDING"
    assert state.error_code == "ERR_MONTAGE_IMAGE_REQUIRED"
    pkg_factory.assert_not_awaited()
