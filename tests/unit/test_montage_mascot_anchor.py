"""Feature B — Montage Mascot Anchor: START_FRAME/FRAMES lineage, fail-closed
resolution, and proof the global Official Product Visual gate is untouched."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.db import crud
from agent.services import product_mascot_service
from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
    plan_scenes_from_story,
)
from agent.services.montage_scene_orchestrator import execute_scene_plan
from agent.services.montage_scene_reference_policy import SceneReferencePolicy

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)

MASCOT_START_ASSET = {
    "assetId": "ca_mascot1",
    "mediaId": None,
    "downloadUrl": "https://cdn.example/mascot.png",
    "previewUrl": "https://cdn.example/mascot.png",
    "localFilePath": "/tmp/mascot.png",
    "fileName": "mascot",
    "label": "Product Mascot Key Visual",
    "assetSource": "PRODUCT_MASCOT_KEY_VISUAL",
}


async def _seed_product(title: str = "Mascot Montage Product") -> str:
    row = await crud.create_product(
        raw_product_title=title,
        product_display_name=title,
        product_short_name=title[:20],
    )
    return row["id"]


def _patch_copy_disabled(monkeypatch) -> None:
    """Isolate the mascot orchestration unit from the Copy V2 binding subsystem.

    Copy V2 remains the mandatory fail-closed authority for the montage lane
    (unchanged by this feature); a bare test product has no persisted V2 binding
    and would fail closed at copy resolution. These tests target ONLY the mascot
    start-frame injection mechanics, so we stub copy resolution to disabled.
    """

    async def _copy_disabled(*_a, **_k):
        return SimpleNamespace(v2_enabled=False)

    monkeypatch.setattr(
        "agent.services.montage_scene_orchestrator.resolve_persisted_copy_execution_binding",
        _copy_disabled,
    )


def test_mascot_plan_uses_start_frame_frames_lineage():
    beats = [SimpleNamespace(beat_id="hook", role="HOOK", objective="o", visual_action="v")]
    plans = plan_scenes_from_story(
        story_beats=beats, default_policy=SceneReferencePolicy.START_FRAME
    )
    assert plans[0].reference_policy is SceneReferencePolicy.START_FRAME
    assert plans[0].transport_mode == "F2V"
    assert plans[0].source_mode == "FRAMES"


async def test_mascot_start_frame_scene_preserves_frames_and_mascot_start_asset(monkeypatch):
    _patch_copy_disabled(monkeypatch)
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
        visual_action="mascot hero",
    )

    from unittest.mock import AsyncMock

    pkg_factory = AsyncMock(
        return_value={
            "workspace_execution_package_id": "wep-m",
            "prompt_text": "mascot scene",
            "execution_allowed": True,
        }
    )
    captured: dict = {}

    async def gen(**kwargs):
        captured.update(kwargs)
        return {"job_id": "job-m", "media_id": "clip-m"}

    state = await execute_scene_plan(
        plan,
        product_id="p1",
        package_factory=pkg_factory,
        generate_fn=gen,
        model="Veo 3.1 - Lite",
        duration_seconds=8,
        mascot_start_asset=MASCOT_START_ASSET,
        mascot_scene_context="MASCOT CONTEXT",
    )

    # FRAMES lineage preserved end-to-end on the scene state.
    assert state.source_mode == "FRAMES"
    assert state.transport_mode == "F2V"
    # The mascot IS the scene start asset — never the Official Product Visual.
    assert state.start_asset_snapshot == MASCOT_START_ASSET
    assert state.status == "VIDEO_READY"
    assert state.video_media_id == "clip-m"

    # Package built as a plain F2V prompt/copy package: NO FRAMES frame binding
    # (a CHARACTER_REFERENCE mascot can't pass COMPOSITE_FRAME_REFERENCE
    # validation), presenter-free, with the mascot scene context.
    kw = pkg_factory.await_args.kwargs
    assert kw["mode"] == "F2V"
    assert kw.get("source_mode") is None
    assert "start_frame_asset_id" not in kw
    assert kw["character_presence"] == "FACELESS"
    assert kw["avatar_id"] is None
    assert kw["scene_context_override"] == "MASCOT CONTEXT"

    # The live generate boundary receives FRAMES + the mascot start asset.
    assert captured["source_mode"] == "FRAMES"
    assert captured["start_asset"] == MASCOT_START_ASSET
    assert captured["mode"] == "F2V"


async def test_non_mascot_start_frame_scene_unchanged(monkeypatch):
    """Regression guard: without a mascot, START_FRAME still binds the operator
    frame through the package factory (existing behavior, byte-for-byte)."""
    _patch_copy_disabled(monkeypatch)
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

    from unittest.mock import AsyncMock

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
    kw = pkg_factory.await_args.kwargs
    # Non-mascot START_FRAME still routes the operator frame through the factory.
    assert kw["start_frame_asset_id"] == "sf1"


async def test_official_visual_gate_preserves_mascot_start_asset_for_frames():
    """The GLOBAL gate is unmodified: F2V + FRAMES keeps the operator start asset
    (here the mascot) and never substitutes the Official Product Visual."""
    from agent.api.flow import _apply_video_product_visual_gate

    start_asset, refs, gated = await _apply_video_product_visual_gate(
        product_id="p1",
        mode="F2V",
        source_mode="FRAMES",
        request_refs={},
        start_asset=MASCOT_START_ASSET,
    )
    assert gated is False  # not overwritten by the Official Product Visual
    assert start_asset == MASCOT_START_ASSET  # mascot preserved verbatim
    assert refs == {}


async def test_montage_mascot_fail_closed_when_absent():
    from agent.api.montage import _resolve_mascot_start_asset_or_409

    product_id = await _seed_product("No Mascot Product")
    with pytest.raises(HTTPException) as exc:
        await _resolve_mascot_start_asset_or_409(product_id)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


async def test_montage_mascot_resolution_returns_transportable_start_asset():
    from agent.api.montage import _resolve_mascot_start_asset_or_409

    product_id = await _seed_product("Has Mascot Product")
    await product_mascot_service.set_product_mascot(
        product_id, image_base64=PNG_B64, file_name="m.png"
    )
    sa = await _resolve_mascot_start_asset_or_409(product_id)
    assert sa["assetSource"] == "PRODUCT_MASCOT_KEY_VISUAL"
    # Transportable via the local file so the generate lane can upload it.
    assert sa["localFilePath"]
    assert sa["localImagePathPresent"] is True
