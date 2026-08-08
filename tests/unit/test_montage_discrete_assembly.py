"""Assembly gate must prevent concat_fn when scene set incomplete."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent.services.montage_assembly_readiness import (
    BLOCKED_INCOMPLETE_SCENE_SET,
    MontageAssemblyError,
    MontageSceneReadiness,
)
from agent.services.montage_discrete_assembly import assemble_montage_discrete
from agent.services.montage_scene_reference_policy import SceneReferencePolicy


def _ready(scene_id: str, clip: str) -> MontageSceneReadiness:
    return MontageSceneReadiness(
        scene_id=scene_id,
        mandatory=True,
        reference_policy=SceneReferencePolicy.NONE,
        clip_media_id=clip,
        image_ready=True,
        video_ready=True,
        image_generation_required=False,
        video_generation_required=True,
    )


@pytest.mark.asyncio
async def test_incomplete_set_never_calls_concat() -> None:
    scenes = [
        _ready("s1", "c1"),
        MontageSceneReadiness(
            scene_id="s2",
            mandatory=True,
            reference_policy=SceneReferencePolicy.NONE,
            clip_media_id=None,
            image_ready=False,
            video_ready=False,
            image_generation_required=False,
            video_generation_required=True,
        ),
    ]
    concat = AsyncMock(return_value={"submitted": True})
    with pytest.raises(MontageAssemblyError) as ei:
        await assemble_montage_discrete(scenes, concat_fn=concat, dry_run=True)
    assert ei.value.code == BLOCKED_INCOMPLETE_SCENE_SET
    concat.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_set_calls_concat_with_clip_ids() -> None:
    scenes = [_ready("s1", "c1"), _ready("s2", "c2"), _ready("s3", "c3")]
    concat = AsyncMock(return_value={"dry_run": True, "status": "SEGMENTS_READY"})
    out = await assemble_montage_discrete(
        scenes, concat_fn=concat, job_id="j1", dry_run=True
    )
    assert out["ok"] is True
    concat.assert_awaited_once()
    kwargs = concat.await_args.kwargs
    assert kwargs["segment_media_ids"] == ["c1", "c2", "c3"]
    assert kwargs["dry_run"] is True
    assert len(kwargs["input_videos"]) == 3
