"""Montage R2 — route storyboard beats to discrete scene execution plans.

Reuses FullStoryPlan / StoryBeat / BlockAllocation shapes. Does NOT invent
promptVideoN schemas. Does NOT create a new generation engine — each scene
routes to existing primitives: image-first, direct-video, or inherit-previous.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence

from agent.services.montage_scene_reference_policy import (
    SceneReferenceDeclaration,
    SceneReferencePolicy,
    parse_scene_reference_policy,
    policy_image_generation_required,
    policy_video_generation_required,
)


class SceneExecutionRoute(str, Enum):
    """How a beat/scene is realized on the existing scene/image/video path."""

    DIRECT_VIDEO = "DIRECT_VIDEO"          # T2V / prompt-only clip
    IMAGE_FIRST = "IMAGE_FIRST"            # generate/bind image → animate (I2V/F2V)
    INHERIT_PREVIOUS = "INHERIT_PREVIOUS"  # reuse previous clip media


# Default route for each reference policy when the planner does not override.
_DEFAULT_ROUTE: dict[SceneReferencePolicy, SceneExecutionRoute] = {
    SceneReferencePolicy.NONE: SceneExecutionRoute.DIRECT_VIDEO,
    SceneReferencePolicy.PRODUCT_ANCHOR: SceneExecutionRoute.IMAGE_FIRST,
    SceneReferencePolicy.START_FRAME: SceneExecutionRoute.IMAGE_FIRST,
    SceneReferencePolicy.START_END_FRAMES: SceneExecutionRoute.IMAGE_FIRST,
    SceneReferencePolicy.AVATAR_PRODUCT: SceneExecutionRoute.IMAGE_FIRST,
    SceneReferencePolicy.INGREDIENT_REFERENCES: SceneExecutionRoute.IMAGE_FIRST,
    SceneReferencePolicy.INHERIT_PREVIOUS_CLIP: SceneExecutionRoute.INHERIT_PREVIOUS,
}


@dataclass(frozen=True)
class MontageSceneExecutionPlan:
    """One discrete scene ready for the existing worker/one-door primitives."""

    scene_id: str
    beat_id: str
    block_index: int
    route: SceneExecutionRoute
    reference_policy: SceneReferencePolicy
    transport_mode: str
    source_mode: str
    image_generation_required: bool
    video_generation_required: bool
    objective: str
    visual_action: str
    # Optional binding fields filled by the operator/runtime later.
    product_media_id: Optional[str] = None
    reference_media_ids: tuple[str, ...] = ()
    previous_clip_media_id: Optional[str] = None
    role: str = ""

    def to_reference_declaration(self) -> SceneReferenceDeclaration:
        return SceneReferenceDeclaration(
            scene_id=self.scene_id,
            policy=self.reference_policy,
            reference_media_ids=self.reference_media_ids,
            product_media_id=self.product_media_id,
            previous_clip_media_id=self.previous_clip_media_id,
            image_generation_required=self.image_generation_required,
            video_generation_required=self.video_generation_required,
        )


def route_for_policy(policy: SceneReferencePolicy) -> SceneExecutionRoute:
    return _DEFAULT_ROUTE[policy]


def transport_for_policy(policy: SceneReferencePolicy) -> tuple[str, str]:
    from agent.services.montage_scene_reference_policy import _POLICY_MODE
    transport, source = _POLICY_MODE[policy]
    return transport, source or transport


def plan_scene_from_beat(
    *,
    beat: Any,
    block_index: int = 0,
    reference_policy: SceneReferencePolicy | str = SceneReferencePolicy.PRODUCT_ANCHOR,
    product_media_id: Optional[str] = None,
    previous_clip_media_id: Optional[str] = None,
    reference_media_ids: Sequence[str] = (),
    route_override: Optional[SceneExecutionRoute | str] = None,
) -> MontageSceneExecutionPlan:
    """Map one StoryBeat-like object to a discrete scene execution plan."""
    policy = (
        reference_policy
        if isinstance(reference_policy, SceneReferencePolicy)
        else parse_scene_reference_policy(reference_policy)
    )
    if route_override is None:
        route = route_for_policy(policy)
    else:
        route = (
            route_override
            if isinstance(route_override, SceneExecutionRoute)
            else SceneExecutionRoute(str(route_override).strip().upper())
        )

    beat_id = str(getattr(beat, "beat_id", None) or getattr(beat, "id", None) or f"beat-{block_index}")
    scene_id = f"scene-{block_index + 1}-{beat_id}"
    transport, source = transport_for_policy(policy)

    return MontageSceneExecutionPlan(
        scene_id=scene_id,
        beat_id=beat_id,
        block_index=int(block_index),
        route=route,
        reference_policy=policy,
        transport_mode=transport,
        source_mode=source,
        image_generation_required=policy_image_generation_required(policy),
        video_generation_required=policy_video_generation_required(policy),
        objective=str(getattr(beat, "objective", "") or ""),
        visual_action=str(getattr(beat, "visual_action", "") or ""),
        product_media_id=product_media_id,
        reference_media_ids=tuple(str(x) for x in reference_media_ids if str(x or "").strip()),
        previous_clip_media_id=previous_clip_media_id,
        role=str(getattr(beat, "role", "") or ""),
    )


def plan_scenes_from_story(
    *,
    story_beats: Sequence[Any],
    default_policy: SceneReferencePolicy | str = SceneReferencePolicy.PRODUCT_ANCHOR,
    per_beat_policy: Optional[dict[str, SceneReferencePolicy | str]] = None,
    product_media_id: Optional[str] = None,
) -> list[MontageSceneExecutionPlan]:
    """Expand a storyboard beat list into ordered discrete scene plans.

    Continuity: when a beat policy is INHERIT_PREVIOUS_CLIP, previous_clip is
    left for the runtime to fill after the prior scene completes; the plan still
    records the route so assembly readiness can demand it later.
    """
    per = per_beat_policy or {}
    plans: list[MontageSceneExecutionPlan] = []
    for i, beat in enumerate(story_beats):
        beat_id = str(getattr(beat, "beat_id", None) or getattr(beat, "id", None) or f"beat-{i}")
        policy = per.get(beat_id, default_policy)
        plans.append(
            plan_scene_from_beat(
                beat=beat,
                block_index=i,
                reference_policy=policy,
                product_media_id=product_media_id,
            )
        )
    return plans


def plan_to_dict(plan: MontageSceneExecutionPlan) -> dict[str, Any]:
    return {
        "scene_id": plan.scene_id,
        "beat_id": plan.beat_id,
        "block_index": plan.block_index,
        "route": plan.route.value,
        "reference_policy": plan.reference_policy.value,
        "transport_mode": plan.transport_mode,
        "source_mode": plan.source_mode,
        "image_generation_required": plan.image_generation_required,
        "video_generation_required": plan.video_generation_required,
        "objective": plan.objective,
        "visual_action": plan.visual_action,
        "product_media_id": plan.product_media_id,
        "reference_media_ids": list(plan.reference_media_ids),
        "previous_clip_media_id": plan.previous_clip_media_id,
        "role": plan.role,
    }
