"""Montage R2 — storyboard beats → discrete scene execution routing."""
from types import SimpleNamespace

from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
    plan_scene_from_beat,
    plan_scenes_from_story,
    plan_to_dict,
    route_for_policy,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy


def _beat(i: int, role: str = "BODY"):
    return SimpleNamespace(
        beat_id=f"beat-{i}",
        role=role,
        objective=f"objective-{i}",
        visual_action=f"action-{i}",
    )


def test_default_routes_by_policy():
    assert route_for_policy(SceneReferencePolicy.NONE) == SceneExecutionRoute.DIRECT_VIDEO
    assert route_for_policy(SceneReferencePolicy.PRODUCT_ANCHOR) == SceneExecutionRoute.IMAGE_FIRST
    assert route_for_policy(SceneReferencePolicy.START_FRAME) == SceneExecutionRoute.IMAGE_FIRST
    assert route_for_policy(SceneReferencePolicy.INHERIT_PREVIOUS_CLIP) == SceneExecutionRoute.INHERIT_PREVIOUS


def test_plan_scene_from_beat_image_first():
    plan = plan_scene_from_beat(
        beat=_beat(0),
        block_index=0,
        reference_policy=SceneReferencePolicy.START_FRAME,
        product_media_id="prod-1",
    )
    assert isinstance(plan, MontageSceneExecutionPlan)
    assert plan.route == SceneExecutionRoute.IMAGE_FIRST
    assert plan.transport_mode == "F2V"
    assert plan.source_mode == "FRAMES"
    assert plan.image_generation_required is True
    assert plan.video_generation_required is True
    assert plan.beat_id == "beat-0"
    assert "scene-1" in plan.scene_id


def test_plan_scenes_from_story_ordered():
    beats = [_beat(0, "HOOK"), _beat(1, "BODY"), _beat(2, "CTA")]
    plans = plan_scenes_from_story(
        story_beats=beats,
        default_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        product_media_id="pm",
    )
    assert len(plans) == 3
    assert [p.block_index for p in plans] == [0, 1, 2]
    assert all(p.route == SceneExecutionRoute.IMAGE_FIRST for p in plans)
    assert all(p.product_media_id == "pm" for p in plans)


def test_per_beat_policy_override_including_inherit():
    beats = [_beat(0), _beat(1)]
    plans = plan_scenes_from_story(
        story_beats=beats,
        default_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        per_beat_policy={"beat-1": SceneReferencePolicy.INHERIT_PREVIOUS_CLIP},
        product_media_id="pm",
    )
    assert plans[0].route == SceneExecutionRoute.IMAGE_FIRST
    assert plans[1].route == SceneExecutionRoute.INHERIT_PREVIOUS
    assert plans[1].video_generation_required is False


def test_direct_video_route_for_none_policy():
    plan = plan_scene_from_beat(
        beat=_beat(0),
        reference_policy="NONE",
    )
    assert plan.route == SceneExecutionRoute.DIRECT_VIDEO
    assert plan.transport_mode == "T2V"
    assert plan.image_generation_required is False


def test_plan_to_dict_stable_keys():
    plan = plan_scene_from_beat(beat=_beat(0), product_media_id="x")
    d = plan_to_dict(plan)
    assert d["route"] == "IMAGE_FIRST"
    assert d["reference_policy"] == "PRODUCT_ANCHOR"
    assert d["product_media_id"] == "x"
    # No competitor flat schema keys
    assert "promptVideo1" not in d
    assert "videoScript1" not in d


def test_reference_declaration_roundtrip():
    plan = plan_scene_from_beat(
        beat=_beat(0),
        reference_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        product_media_id="pm",
    )
    decl = plan.to_reference_declaration()
    assert decl.scene_id == plan.scene_id
    assert decl.policy == SceneReferencePolicy.PRODUCT_ANCHOR
    assert decl.product_media_id == "pm"
