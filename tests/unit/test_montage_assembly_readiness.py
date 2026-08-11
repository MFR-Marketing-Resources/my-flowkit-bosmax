"""Montage R3 — fail-closed discrete assembly readiness."""
import pytest

from agent.services.montage_assembly_readiness import (
    BLOCKED_INCOMPLETE_SCENE_SET,
    ERR_MONTAGE_MISSING_DIALOGUE,
    ERR_MONTAGE_MISSING_SCENE_CLIP,
    MontageAssemblyError,
    MontageSceneReadiness,
    assess_montage_assembly_readiness,
    preflight_montage_discrete_assembly,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy


def _ready_scene(i: int, clip: str = "clip") -> MontageSceneReadiness:
    return MontageSceneReadiness(
        scene_id=f"s{i}",
        mandatory=True,
        reference_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        product_media_id=f"prod-{i}",
        clip_media_id=f"{clip}-{i}",
        image_ready=True,
        video_ready=True,
        image_generation_required=True,
        video_generation_required=True,
    )


def test_complete_set_reaches_assembly():
    scenes = [_ready_scene(1), _ready_scene(2), _ready_scene(3)]
    report = assess_montage_assembly_readiness(scenes)
    assert report.ok
    assert report.code is None
    assert report.clip_media_ids == ["clip-1", "clip-2", "clip-3"]
    out = preflight_montage_discrete_assembly(scenes)
    assert out["status"] == "READY"
    assert out["assembly_path"] == "DISCRETE_MONTAGE"
    assert len(out["clip_media_ids"]) == 3


def test_missing_mandatory_clip_blocks_with_named_code():
    scenes = [
        _ready_scene(1),
        MontageSceneReadiness(
            scene_id="s2",
            product_media_id="prod-2",
            image_ready=True,
            video_ready=False,
            clip_media_id=None,
        ),
    ]
    report = assess_montage_assembly_readiness(scenes)
    assert not report.ok
    assert report.code == BLOCKED_INCOMPLETE_SCENE_SET
    assert any(b["error_code"] == ERR_MONTAGE_MISSING_SCENE_CLIP for b in report.blockers)

    with pytest.raises(MontageAssemblyError) as ei:
        preflight_montage_discrete_assembly(scenes)
    assert ei.value.code == BLOCKED_INCOMPLETE_SCENE_SET


def test_missing_product_media_blocks():
    scenes = [
        MontageSceneReadiness(
            scene_id="s1",
            reference_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
            product_media_id=None,
            reference_media_ids=(),
            image_ready=True,
            video_ready=True,
            clip_media_id="c1",
        ),
    ]
    report = assess_montage_assembly_readiness(scenes)
    assert not report.ok
    assert report.code == BLOCKED_INCOMPLETE_SCENE_SET
    assert report.blockers


def test_missing_required_dialogue_blocks():
    scene = _ready_scene(1)
    scene.dialogue_required = True
    scene.dialogue_text = ""
    report = assess_montage_assembly_readiness([scene])
    assert not report.ok
    assert any(b["error_code"] == ERR_MONTAGE_MISSING_DIALOGUE for b in report.blockers)


def test_partial_set_never_silently_ok():
    # One ready, one incomplete → must not return ok with partial clips only
    scenes = [
        _ready_scene(1),
        MontageSceneReadiness(
            scene_id="s2",
            product_media_id="p2",
            image_ready=False,
            video_ready=False,
        ),
    ]
    report = assess_montage_assembly_readiness(scenes)
    assert report.ok is False
    # Even if some clips listed, assembly is refused
    with pytest.raises(MontageAssemblyError):
        report.raise_if_blocked()


def test_empty_plan_blocked():
    report = assess_montage_assembly_readiness([])
    assert not report.ok
    assert report.code == BLOCKED_INCOMPLETE_SCENE_SET


def test_laluan_a_preflight_untouched_importable():
    # Sibling module must not break native-extend preflight symbol.
    from agent.services import google_flow_final_timeline_runtime as ft
    assert hasattr(ft, "preflight_segment_durations")
    assert ft.SEGMENT_COUNT_MISMATCH == "SEGMENT_COUNT_MISMATCH"
    # Our code name is distinct
    assert BLOCKED_INCOMPLETE_SCENE_SET != ft.SEGMENT_COUNT_MISMATCH
