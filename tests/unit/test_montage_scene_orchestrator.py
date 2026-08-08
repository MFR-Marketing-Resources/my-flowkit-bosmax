"""Orchestration tests — prove package/generate chain is invoked (mocked)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.services.montage_scene_orchestrator import (
    execute_scene_plan,
    orchestrate_montage_scenes,
)
from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy


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
