"""Montage R2 operational orchestrator — plan → existing package/generate primitives.

No second video engine. No DOM lane. Credit fire only via injected generate_fn
(default: None — prepare packages only). Operators / workers call existing
`/api/flow/generate` with package ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence

from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
    plan_scenes_from_story,
    plan_to_dict,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy

PackageFactory = Callable[..., Awaitable[dict[str, Any]]]
GenerateFn = Callable[..., Awaitable[dict[str, Any]]]
ImagePrepareFn = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class SceneJobState:
    """Durable-enough runtime state for one montage scene."""

    scene_id: str
    beat_id: str
    block_index: int
    route: str
    transport_mode: str
    source_mode: str
    reference_policy: str
    status: str = "PLANNED"
    image_job_id: Optional[str] = None
    image_media_id: Optional[str] = None
    video_job_id: Optional[str] = None
    video_media_id: Optional[str] = None
    workspace_execution_package_id: Optional[str] = None
    error_code: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "beat_id": self.beat_id,
            "block_index": self.block_index,
            "route": self.route,
            "transport_mode": self.transport_mode,
            "source_mode": self.source_mode,
            "reference_policy": self.reference_policy,
            "status": self.status,
            "image_job_id": self.image_job_id,
            "image_media_id": self.image_media_id,
            "video_job_id": self.video_job_id,
            "video_media_id": self.video_media_id,
            "workspace_execution_package_id": self.workspace_execution_package_id,
            "error_code": self.error_code,
            "detail": self.detail,
        }


@dataclass
class MontageOrchestrationReport:
    product_id: str
    scenes: list[SceneJobState] = field(default_factory=list)
    credit_spend: bool = False
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "scene_count": len(self.scenes),
            "scenes": [s.to_dict() for s in self.scenes],
            "credit_spend": self.credit_spend,
            "ok": self.ok,
            "detail": self.detail,
            "assembly_path": "DISCRETE_MONTAGE",
        }


def _start_frame_for_plan(plan: MontageSceneExecutionPlan) -> Optional[str]:
    if plan.reference_media_ids:
        return plan.reference_media_ids[0]
    return plan.product_media_id


async def execute_scene_plan(
    plan: MontageSceneExecutionPlan,
    *,
    product_id: str,
    package_factory: PackageFactory,
    image_prepare_fn: Optional[ImagePrepareFn] = None,
    generate_fn: Optional[GenerateFn] = None,
    scene_context_override: Optional[str] = None,
    copy_fallback_confirmed: bool = True,
) -> SceneJobState:
    """Run one planned scene through existing package (+ optional generate) path."""
    state = SceneJobState(
        scene_id=plan.scene_id,
        beat_id=plan.beat_id,
        block_index=plan.block_index,
        route=plan.route.value,
        transport_mode=plan.transport_mode,
        source_mode=plan.source_mode,
        reference_policy=plan.reference_policy.value,
    )

    if plan.route == SceneExecutionRoute.INHERIT_PREVIOUS:
        if not plan.previous_clip_media_id:
            state.status = "BLOCKED"
            state.error_code = "ERR_MONTAGE_MISSING_PREVIOUS_CLIP"
            state.detail = "INHERIT_PREVIOUS requires previous_clip_media_id"
            return state
        state.video_media_id = plan.previous_clip_media_id
        state.status = "VIDEO_READY"
        return state

    # IMAGE_FIRST: optional image prepare hook before video package
    start_frame = _start_frame_for_plan(plan)
    if plan.route == SceneExecutionRoute.IMAGE_FIRST and plan.image_generation_required:
        if image_prepare_fn is not None and not start_frame:
            img = await image_prepare_fn(
                product_id=product_id,
                scene_id=plan.scene_id,
                policy=plan.reference_policy.value,
            )
            start_frame = str(img.get("media_id") or img.get("image_media_id") or "") or None
            state.image_job_id = img.get("job_id")
            state.image_media_id = start_frame
            state.status = "IMAGE_READY" if start_frame else "IMAGE_PENDING"
        elif start_frame:
            state.image_media_id = start_frame
            state.status = "IMAGE_BOUND"
        else:
            state.status = "BLOCKED"
            state.error_code = "ERR_MONTAGE_IMAGE_REQUIRED"
            state.detail = (
                f"IMAGE_FIRST scene {plan.scene_id} needs product/start frame "
                "or image_prepare_fn result"
            )
            return state

    if not plan.video_generation_required:
        state.status = "SKIPPED_VIDEO"
        return state

    # DIRECT_VIDEO or IMAGE_FIRST → create workspace execution package via canonical factory
    mode = plan.transport_mode
    source_mode = plan.source_mode if plan.source_mode != mode else None
    kwargs: dict[str, Any] = {
        "product_id": product_id,
        "mode": mode,
        "duration_seconds": 8,
        "aspect_ratio": "9:16",
        "model": "",
        "manual_override": False,
        "generation_mode": "SINGLE",
        "source_mode": source_mode,
        "copy_fallback_confirmed": copy_fallback_confirmed,
        "scene_context_override": scene_context_override,
    }
    if start_frame and mode in ("F2V", "I2V", "FRAMES"):
        kwargs["start_frame_asset_id"] = start_frame
    if plan.product_media_id and mode in ("T2V", "HYBRID"):
        kwargs["product_reference_asset_id"] = plan.product_media_id

    try:
        pkg = await package_factory(**kwargs)
    except Exception as exc:  # noqa: BLE001
        state.status = "PACKAGE_FAILED"
        state.error_code = "ERR_MONTAGE_PACKAGE"
        state.detail = str(exc)[:400]
        return state

    state.workspace_execution_package_id = str(
        pkg.get("workspace_execution_package_id") or ""
    ) or None
    state.status = "PACKAGE_READY"

    if generate_fn is None:
        # Default: stop at package — operator fires one-door generate explicitly
        return state

    gen = await generate_fn(
        product_id=product_id,
        mode=mode,
        workspace_execution_package_id=state.workspace_execution_package_id,
        prompt=pkg.get("prompt_text") or "",
        scene_id=plan.scene_id,
    )
    state.video_job_id = str(gen.get("job_id") or gen.get("id") or "") or None
    state.video_media_id = str(
        gen.get("media_id") or gen.get("video_media_id") or ""
    ) or None
    state.status = "VIDEO_SUBMITTED" if state.video_job_id else "GENERATE_RETURNED"
    if state.video_media_id:
        state.status = "VIDEO_READY"
    return state


async def orchestrate_montage_scenes(
    *,
    product_id: str,
    story_beats: Sequence[Any],
    package_factory: PackageFactory,
    default_policy: SceneReferencePolicy | str = SceneReferencePolicy.PRODUCT_ANCHOR,
    per_beat_policy: Optional[dict[str, str]] = None,
    product_media_id: Optional[str] = None,
    image_prepare_fn: Optional[ImagePrepareFn] = None,
    generate_fn: Optional[GenerateFn] = None,
    scene_context_override: Optional[str] = None,
    copy_fallback_confirmed: bool = True,
) -> MontageOrchestrationReport:
    """Beat → route → package (/ optional generate) for the full scene set."""
    if not str(product_id or "").strip():
        return MontageOrchestrationReport(
            product_id=product_id or "",
            ok=False,
            detail="product_id required",
        )
    plans = plan_scenes_from_story(
        story_beats=story_beats,
        default_policy=default_policy,
        per_beat_policy=per_beat_policy,
        product_media_id=product_media_id,
    )
    report = MontageOrchestrationReport(
        product_id=product_id,
        credit_spend=generate_fn is not None,
    )
    previous_clip: Optional[str] = None
    for plan in plans:
        # feed inherit chain
        if plan.route == SceneExecutionRoute.INHERIT_PREVIOUS and previous_clip:
            from dataclasses import replace

            plan = replace(plan, previous_clip_media_id=previous_clip)
        state = await execute_scene_plan(
            plan,
            product_id=product_id,
            package_factory=package_factory,
            image_prepare_fn=image_prepare_fn,
            generate_fn=generate_fn,
            scene_context_override=scene_context_override,
            copy_fallback_confirmed=copy_fallback_confirmed,
        )
        report.scenes.append(state)
        if state.video_media_id:
            previous_clip = state.video_media_id
        if state.status in ("BLOCKED", "PACKAGE_FAILED"):
            report.ok = False
    if not report.scenes:
        report.ok = False
        report.detail = "no scenes planned"
    return report


def plans_as_public_dicts(plans: Sequence[MontageSceneExecutionPlan]) -> list[dict[str, Any]]:
    return [plan_to_dict(p) for p in plans]
