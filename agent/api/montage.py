"""Montage operator APIs — plan, orchestrate scenes, readiness, gated assembly.

R2 orchestration creates workspace packages via the canonical factory (no second
engine). R3 assembly refuses concat when the mandatory scene set is incomplete.
Credit-bearing generate/concat only when callers inject live runners; default
API paths are package-prepare + dry-run assembly.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services.montage_assembly_readiness import (
    BLOCKED_INCOMPLETE_SCENE_SET,
    MontageAssemblyError,
    MontageSceneReadiness,
    assess_montage_assembly_readiness,
)
from agent.services.montage_discrete_assembly import assemble_montage_discrete
from agent.services.montage_scene_execution_routing import (
    plan_scenes_from_story,
    plan_to_dict,
)
from agent.services.montage_scene_orchestrator import orchestrate_montage_scenes
from agent.services.montage_scene_reference_policy import (
    SceneReferencePolicy,
    parse_scene_reference_policy,
)
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)

router = APIRouter(prefix="/montage", tags=["montage"])


class MontageBeatInput(BaseModel):
    beat_id: str
    role: str = "BODY"
    objective: str = ""
    visual_action: str = ""


class MontagePlanRequest(BaseModel):
    product_id: str
    beats: list[MontageBeatInput] = Field(default_factory=list)
    default_policy: str = "PRODUCT_ANCHOR"
    product_media_id: Optional[str] = None
    per_beat_policy: Optional[dict[str, str]] = None
    hook_id: str = "AUTO"
    background_id: str = "AUTO"


class MontageExecuteRequest(MontagePlanRequest):
    """Prepare packages for each scene (optional fire only if explicitly allowed)."""
    scene_context_override: Optional[str] = None
    copy_fallback_confirmed: bool = True
    # Hard lock: API never auto-fires credit unless this is True AND a live
    # runner is wired. Default False = packages only.
    allow_live_generate: bool = False


class MontageSceneReadyInput(BaseModel):
    scene_id: str
    mandatory: bool = True
    reference_policy: str = "PRODUCT_ANCHOR"
    product_media_id: Optional[str] = None
    reference_media_ids: list[str] = Field(default_factory=list)
    previous_clip_media_id: Optional[str] = None
    clip_media_id: Optional[str] = None
    image_ready: bool = False
    video_ready: bool = False
    dialogue_required: bool = False
    dialogue_text: Optional[str] = None
    image_generation_required: bool = True
    video_generation_required: bool = True


class MontageReadinessRequest(BaseModel):
    scenes: list[MontageSceneReadyInput]


class MontageAssembleRequest(BaseModel):
    scenes: list[MontageSceneReadyInput]
    job_id: str = "montage-discrete"
    dry_run: bool = True
    # Live concat requires explicit confirmation; default dry-run only.
    confirm_live_credit_burn: bool = False


def _default_beats() -> list[MontageBeatInput]:
    return [
        MontageBeatInput(
            beat_id="hook",
            role="HOOK",
            objective="Open with product truth",
            visual_action="Hero product plate",
        ),
        MontageBeatInput(
            beat_id="body",
            role="BODY",
            objective="Demonstrate use",
            visual_action="Product in context",
        ),
        MontageBeatInput(
            beat_id="cta",
            role="CTA",
            objective="Close with approved CTA",
            visual_action="Pack shot + CTA",
        ),
    ]


def _parse_scenes(raw_scenes: list[MontageSceneReadyInput]) -> list[MontageSceneReadiness]:
    scenes: list[MontageSceneReadiness] = []
    for raw in raw_scenes:
        try:
            policy = parse_scene_reference_policy(raw.reference_policy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        scenes.append(
            MontageSceneReadiness(
                scene_id=raw.scene_id,
                mandatory=raw.mandatory,
                reference_policy=policy,
                product_media_id=raw.product_media_id,
                reference_media_ids=tuple(raw.reference_media_ids),
                previous_clip_media_id=raw.previous_clip_media_id,
                clip_media_id=raw.clip_media_id,
                image_ready=raw.image_ready,
                video_ready=raw.video_ready,
                dialogue_required=raw.dialogue_required,
                dialogue_text=raw.dialogue_text,
                image_generation_required=raw.image_generation_required,
                video_generation_required=raw.video_generation_required,
            )
        )
    return scenes


@router.post("/plan")
async def montage_plan(body: MontagePlanRequest) -> dict[str, Any]:
    """Expand beats into discrete scene execution plans (credit-free)."""
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    try:
        default_policy = parse_scene_reference_policy(body.default_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    beats = body.beats or _default_beats()
    plans = plan_scenes_from_story(
        story_beats=beats,
        default_policy=default_policy,
        per_beat_policy=body.per_beat_policy,
        product_media_id=body.product_media_id,
    )
    return {
        "product_id": body.product_id,
        "hook_id": body.hook_id,
        "background_id": body.background_id,
        "scene_count": len(plans),
        "scenes": [plan_to_dict(p) for p in plans],
        "assembly_path": "DISCRETE_MONTAGE",
        "credit_spend": False,
        "execution_supported": True,
    }


@router.post("/execute-scenes")
async def montage_execute_scenes(body: MontageExecuteRequest) -> dict[str, Any]:
    """R2 operational path: beat → route → workspace package (existing factory).

    Does not spend credits by default. Live generate is refused unless
    allow_live_generate is set (still not wired to a credit runner here — fail
    closed).
    """
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    if body.allow_live_generate:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live montage generate is not enabled on this endpoint — "
                "prepare packages then use /api/flow/generate per scene package"
            ),
        )
    try:
        default_policy = parse_scene_reference_policy(body.default_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    beats = body.beats or _default_beats()
    report = await orchestrate_montage_scenes(
        product_id=body.product_id,
        story_beats=beats,
        package_factory=create_workspace_execution_package,
        default_policy=default_policy,
        per_beat_policy=body.per_beat_policy,
        product_media_id=body.product_media_id,
        generate_fn=None,
        scene_context_override=body.scene_context_override,
        copy_fallback_confirmed=body.copy_fallback_confirmed,
    )
    payload = report.to_dict()
    payload["hook_id"] = body.hook_id
    payload["background_id"] = body.background_id
    payload["execution_supported"] = True
    return payload


@router.post("/assembly-readiness")
async def montage_assembly_readiness(body: MontageReadinessRequest) -> dict[str, Any]:
    """Fail-closed readiness check — never concatenates; report only."""
    scenes = _parse_scenes(body.scenes)
    report = assess_montage_assembly_readiness(scenes)
    return {
        "ok": report.ok,
        "code": report.code,
        "detail": report.detail,
        "blockers": report.blockers,
        "ready_scene_ids": report.ready_scene_ids,
        "clip_media_ids": report.clip_media_ids,
        "blocked_incomplete_scene_set": (
            None if report.ok else BLOCKED_INCOMPLETE_SCENE_SET
        ),
        "assembly_path": "DISCRETE_MONTAGE",
        "credit_spend": False,
    }


@router.post("/assemble")
async def montage_assemble(body: MontageAssembleRequest) -> dict[str, Any]:
    """R3 enforcement: readiness gate then concat boundary (dry-run default)."""
    if body.confirm_live_credit_burn and not body.dry_run:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live montage concat is not authorized on this endpoint without "
                "owner credit confirmation path — use dry_run=true"
            ),
        )
    scenes = _parse_scenes(body.scenes)

    async def _concat_boundary(**kwargs: Any) -> dict[str, Any]:
        # Dry-run boundary: prove concat would be invoked with valid ids only.
        return {
            "dry_run": True,
            "status": "SEGMENTS_READY",
            "job_id": kwargs.get("job_id"),
            "segment_media_ids": kwargs.get("segment_media_ids"),
            "input_videos": kwargs.get("input_videos"),
            "requested_seconds": kwargs.get("requested_seconds"),
            "endpoint": "/v1:runVideoFxConcatenation",
        }

    try:
        return await assemble_montage_discrete(
            scenes,
            concat_fn=_concat_boundary,
            job_id=body.job_id,
            dry_run=True if body.dry_run else body.dry_run,
        )
    except MontageAssemblyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": exc.code,
                "message": exc.detail,
                "blockers": exc.blockers,
                "blocked_incomplete_scene_set": BLOCKED_INCOMPLETE_SCENE_SET,
            },
        ) from exc


@router.get("/policies")
async def montage_policies() -> dict[str, Any]:
    return {
        "reference_policies": [p.value for p in SceneReferencePolicy],
        "assembly_path": "DISCRETE_MONTAGE",
        "execution_supported": True,
        "live_generate_via": "/api/flow/generate",
        "live_concat_via": "assemble dry_run only on this router",
    }
