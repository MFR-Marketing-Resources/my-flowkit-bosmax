"""Montage operator APIs — plan, orchestrate scenes, readiness, gated assembly.

R2 orchestration creates workspace packages via the canonical factory (no second
engine). R3 assembly refuses concat when the mandatory scene set is incomplete.
Credit-bearing generate/concat only when callers inject live runners; default
API paths are package-prepare + dry-run assembly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
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
from agent.services.montage_run_service import (
    assemble_from_montage_run,
    authorize_montage_run_generation,
    bind_montage_scene_result,
    create_montage_discrete_run,
    estimate_montage_run_generation,
    get_montage_discrete_run,
    readiness_from_montage_run,
)
from agent.services.montage_scene_reference_policy import (
    SceneReferencePolicy,
    parse_scene_reference_policy,
)
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)
from agent.services import product_mascot_service
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)

router = APIRouter(prefix="/montage", tags=["montage"])

# Minimum mascot-specific context injected into the existing Montage scene/story
# compiler — the current planner treats the supplied mascot as the recurring
# on-screen product character. No new planner, no second engine.
MASCOT_SCENE_CONTEXT = (
    "PRODUCT MASCOT MODE: The supplied Product Mascot Key Visual is the recurring "
    "on-screen product character/hero across every scene. Treat the mascot as the "
    "consistent visual identity and the start-frame subject to animate from. "
    "Presenter-free (faceless) — no human creator."
)


def _mascot_to_start_asset(mascot: dict[str, Any]) -> dict[str, Any]:
    """Map a resolved Product Mascot Key Visual to a transportable start-asset."""
    download = mascot.get("download_url") or mascot.get("preview_url")
    return {
        "assetId": mascot.get("asset_id"),
        "mediaId": mascot.get("media_id"),
        "downloadUrl": download,
        "previewUrl": mascot.get("preview_url"),
        "localFilePath": mascot.get("local_file_path"),
        "fileName": mascot.get("display_name") or "product-mascot",
        "label": mascot.get("display_name") or "Product Mascot Key Visual",
        "assetSource": "PRODUCT_MASCOT_KEY_VISUAL",
        "semanticRole": "COMPOSITE_FRAME_REFERENCE",
        "localImagePathPresent": bool(mascot.get("local_file_path")),
        "remoteImageUrlPresent": bool(download),
    }


async def _resolve_mascot_start_asset_or_409(product_id: str) -> dict[str, Any]:
    """Fail-closed mascot resolution for the Montage lane.

    Raises HTTP 409 PRODUCT_MASCOT_KEY_VISUAL_REQUIRED when no current mascot is
    resolvable — never a silent fallback to the Official Product Visual.
    """
    try:
        mascot = await product_mascot_service.resolve_mascot_for_montage(product_id)
    except product_mascot_service.ProductMascotUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "detail": str(exc), "product_id": product_id},
        ) from exc
    return _mascot_to_start_asset(mascot)


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
    model: str = Field(..., min_length=1)
    duration_seconds: int = Field(..., gt=0)
    copy_v2_context: dict[str, Any] | None = None
    # Mascot Montage: resolve the product's current Product Mascot Key Visual and
    # drive scenes as START_FRAME (F2V / FRAMES lineage) with the mascot as the
    # start-frame visual. Fail-closed if no mascot (PRODUCT_MASCOT_KEY_VISUAL_REQUIRED).
    use_product_mascot: bool = False


class MontageExecuteRequest(MontagePlanRequest):
    """Prepare packages for each scene (optional fire only if explicitly allowed)."""
    scene_context_override: Optional[str] = None
    copy_fallback_confirmed: bool = False
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
    from agent.services.montage_run_service import _resolve_montage_single_settings

    try:
        model, duration_seconds = _resolve_montage_single_settings(
            body.model, body.duration_seconds
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    beats = body.beats or _default_beats()
    try:
        copy_resolution = await resolve_persisted_copy_execution_binding(
            body.product_id,
            "MONTAGE",
            body.copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.details or str(exc)},
        ) from exc
    if body.use_product_mascot:
        # Fail-closed mascot resolution; plan drives START_FRAME (F2V/FRAMES).
        await _resolve_mascot_start_asset_or_409(body.product_id)
        default_policy = SceneReferencePolicy.START_FRAME
    plans = plan_scenes_from_story(
        story_beats=beats,
        default_policy=default_policy,
        per_beat_policy=body.per_beat_policy,
        product_media_id=None if body.use_product_mascot else body.product_media_id,
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
        "model": model,
        "duration_seconds": duration_seconds,
        "copy_policy": "REQUIRED",
        "copy_architecture_v2": (
            copy_resolution.to_metadata(consumer_context=body.copy_v2_context)
            if copy_resolution and copy_resolution.v2_enabled
            else None
        ),
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
    from agent.services.montage_run_service import _resolve_montage_single_settings

    try:
        model, duration_seconds = _resolve_montage_single_settings(
            body.model, body.duration_seconds
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    beats = body.beats or _default_beats()
    mascot_start_asset = None
    if body.use_product_mascot:
        mascot_start_asset = await _resolve_mascot_start_asset_or_409(body.product_id)
        default_policy = SceneReferencePolicy.START_FRAME
    report = await orchestrate_montage_scenes(
        product_id=body.product_id,
        story_beats=beats,
        package_factory=create_workspace_execution_package,
        default_policy=default_policy,
        per_beat_policy=body.per_beat_policy,
        product_media_id=None if body.use_product_mascot else body.product_media_id,
        generate_fn=None,
        scene_context_override=body.scene_context_override,
        copy_fallback_confirmed=body.copy_fallback_confirmed,
        model=model,
        duration_seconds=duration_seconds,
        copy_v2_context=body.copy_v2_context,
        mascot_start_asset=mascot_start_asset,
        mascot_scene_context=MASCOT_SCENE_CONTEXT if body.use_product_mascot else None,
    )
    payload = report.to_dict()
    payload["hook_id"] = body.hook_id
    payload["background_id"] = body.background_id
    payload["execution_supported"] = True
    payload["copy_policy"] = "REQUIRED"
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




class MontageRunCreateRequest(MontageExecuteRequest):
    """Create durable montage run + packages (no credit)."""


class MontageBindResultRequest(BaseModel):
    scene_id: str
    media_id: str
    result_kind: str = "video"
    job_id: Optional[str] = None


class MontageRunAssembleRequest(BaseModel):
    dry_run: bool = True
    job_id: str = "montage-discrete-run"
    confirm_live_credit_burn: bool = False


@router.post("/runs")
async def montage_create_run(body: MontageRunCreateRequest) -> dict[str, Any]:
    """M-02 durable path: plan → packages → persisted scene job ledger."""
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    if body.allow_live_generate:
        raise HTTPException(
            status_code=403,
            detail="Live credit generate is not auto-started on run create",
        )
    try:
        default_policy = parse_scene_reference_policy(body.default_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    beats = body.beats or _default_beats()
    mascot_start_asset = None
    if body.use_product_mascot:
        mascot_start_asset = await _resolve_mascot_start_asset_or_409(body.product_id)
        default_policy = SceneReferencePolicy.START_FRAME
    try:
        return await create_montage_discrete_run(
            product_id=body.product_id,
            story_beats=beats,
            package_factory=create_workspace_execution_package,
            default_policy=default_policy,
            per_beat_policy=body.per_beat_policy,
            product_media_id=None if body.use_product_mascot else body.product_media_id,
            scene_context_override=body.scene_context_override,
            copy_fallback_confirmed=body.copy_fallback_confirmed,
            hook_id=body.hook_id,
            background_id=body.background_id,
            model=body.model,
            duration_seconds=body.duration_seconds,
            copy_v2_context=body.copy_v2_context,
            mascot_start_asset=mascot_start_asset,
            mascot_scene_context=MASCOT_SCENE_CONTEXT if body.use_product_mascot else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
async def montage_get_run(run_id: str) -> dict[str, Any]:
    try:
        return await get_montage_discrete_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/bind-result")
async def montage_bind_run_result(run_id: str, body: MontageBindResultRequest) -> dict[str, Any]:
    try:
        return await bind_montage_scene_result(
            run_id,
            scene_id=body.scene_id,
            media_id=body.media_id,
            result_kind=body.result_kind,
            job_id=body.job_id,
        )
    except ValueError as exc:
        code = 404 if "NOT_FOUND" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/runs/{run_id}/assembly-readiness")
async def montage_run_readiness(run_id: str) -> dict[str, Any]:
    try:
        return await readiness_from_montage_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/assemble")
async def montage_run_assemble(run_id: str, body: MontageRunAssembleRequest) -> dict[str, Any]:
    """Assemble from durable run state — readiness gate then real concat path.

    dry_run=True (default): readiness + concat contract shape only.
    dry_run=False + confirm_live_credit_burn=True: invoke Flow video concatenation
    via the existing client primitive (not Laluan-A native-extend).
    """

    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    from agent.services.montage_run_service import _resolve_montage_single_settings

    try:
        _model, clip_duration = _resolve_montage_single_settings(
            cfg.get("model"), cfg.get("duration_seconds")
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scene_count = int(state.get("total_scenes") or 0)
    if scene_count <= 0:
        raise HTTPException(status_code=409, detail="ERR_MONTAGE_EMPTY_PLAN")
    requested_seconds = clip_duration * scene_count

    async def _concat_boundary(**kwargs: Any) -> dict[str, Any]:
        segment_ids = list(kwargs.get("segment_media_ids") or [])
        effective_job_id = str(kwargs.get("job_id") or body.job_id)
        from agent.services.google_flow_final_timeline_runtime import finalize_timeline

        if body.dry_run:
            return await finalize_timeline(
                None,
                job_id=effective_job_id,
                segment_media_ids=segment_ids,
                requested_seconds=int(kwargs.get("requested_seconds") or requested_seconds),
                segment_seconds=clip_duration,
                out_dir=Path("output") / "retrieved",
                dry_run=True,
                confirm_live_credit_burn=False,
            )
        if not body.confirm_live_credit_burn:
            raise ValueError("ERR_MONTAGE_LIVE_CONCAT_CONFIRM_REQUIRED")

        # The existing final-timeline primitive owns concat submit, polling,
        # artifact save, and final identity persistence. Use the connected
        # client singleton and create only this run's lifecycle owner row.
        from agent.db import crud
        from agent.services.flow_client import get_flow_client

        logical_key = f"montage:{run_id}"
        existing = await crud.get_video_production_job_by_logical_key(logical_key)
        if existing:
            effective_job_id = str(existing["job_id"])
        else:
            # The legacy request default is shared by every Montage run. Derive a
            # durable per-run owner so a second run can never resume or overwrite
            # another run's final-timeline job.
            effective_job_id = f"montage-final-{run_id}"
            await crud.create_video_production_job_full(
                effective_job_id,
                logical_job_key=logical_key,
                status="CREATED",
                requested_duration_seconds=requested_seconds,
                product_id=cfg.get("product_id"),
                model=cfg.get("model"),
                aspect_ratio="9:16",
                segment_media_ids_json=json.dumps(segment_ids),
                whole_plan_json=json.dumps({
                    "execution_mode": "MONTAGE_DISCRETE",
                    "requested_seconds": requested_seconds,
                    "segment_seconds": clip_duration,
                    "segment_count": len(segment_ids),
                }),
            )
        result = await finalize_timeline(
            get_flow_client(),
            job_id=effective_job_id,
            segment_media_ids=segment_ids,
            requested_seconds=int(kwargs.get("requested_seconds") or requested_seconds),
            segment_seconds=clip_duration,
            out_dir=Path("output") / "retrieved",
            dry_run=False,
            confirm_live_credit_burn=True,
        )
        if result.get("final_media_id"):
            await crud.insert_generated_artifact(
                result["final_media_id"],
                job_id=effective_job_id,
                mode="MONTAGE",
                artifact_kind="video",
                local_path=result.get("local_path"),
                size_mb=result.get("size_mb"),
                model_used=cfg.get("model"),
                duration_used=result.get("measured_duration_s"),
            )
        return result

    try:
        return await assemble_from_montage_run(
            run_id,
            concat_fn=_concat_boundary,
            dry_run=body.dry_run,
            job_id=body.job_id,
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
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class MontageAuthorizeGenerationRequest(BaseModel):
    """Operator-authorized multi-scene generation (M-04).

    dry_run=True (default): validate credit count only — no generate boundary.
    dry_run=False + confirm_credit_burn=True: dispatch per pending scene via
    one-door generate boundary (startAsset/image_media_ids, not package-id-only).
    """

    confirm_credit_burn: bool = False
    expected_video_generations: int
    expected_provider_operations: int
    dry_run: bool = True


@router.get("/runs/{run_id}/generation-estimate")
async def montage_run_generation_estimate(run_id: str) -> dict[str, Any]:
    """Credit estimate: N scenes → N video generations (no spend)."""
    try:
        return await estimate_montage_run_generation(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/authorize-generation")
async def montage_authorize_generation(
    run_id: str,
    body: MontageAuthorizeGenerationRequest,
    request: Request,
) -> dict[str, Any]:
    """M-04: explicit credit authorization before multi-scene generate.

    Live path (dry_run=false) calls existing /api/flow/generate contract per scene
    with startAsset / image_media_ids from package snapshot — never package-id-only.
    """
    generate_fn = None
    poll_fn = None
    if not body.dry_run:
        from agent.api.flow import GenerateRequest
        from agent.api.flow import generate as flow_generate

        async def generate_fn(**kwargs: Any) -> dict[str, Any]:
            """Canonical GenerateRequest one-door — single body arg only (MON-02)."""
            start_asset = kwargs.get("start_asset")
            image_media_ids: list[str] = []
            mid = kwargs.get("image_media_id")
            if mid:
                image_media_ids.append(str(mid))
            if isinstance(start_asset, dict):
                sm = start_asset.get("mediaId") or start_asset.get("media_id")
                if sm and str(sm) not in image_media_ids:
                    image_media_ids.append(str(sm))
            gen_body = GenerateRequest(
                mode=str(kwargs.get("mode") or "F2V"),
                prompt=str(kwargs.get("prompt") or f"Montage scene {kwargs.get('scene_id')}"),
                product_id=kwargs.get("product_id") or None,
                aspect="9:16",
                # Thread the source lineage + package id the run persisted. For a
                # mascot START_FRAME scene source_mode="FRAMES" makes the global
                # product-visual gate honor the mascot start asset (its existing
                # FRAMES exemption) rather than replacing it with the Official
                # Product Visual. The gate itself is unchanged.
                source_mode=kwargs.get("source_mode") or None,
                workspace_execution_package_id=kwargs.get("workspace_execution_package_id") or None,
                model=kwargs.get("model") or None,
                duration_s=kwargs.get("duration_s"),
                generation_mode="SINGLE",
                engine="GOOGLE_FLOW",
                startAsset=start_asset if isinstance(start_asset, dict) else None,
                image_media_ids=image_media_ids or None,
                # Montage scenes fire an operator-authorized run (confirm_credit_burn);
                # materialise the upstream approval so the enforced gate never blocks
                # a legitimately-authorized montage generation.
                upstream_approved_provenance="montage",
            )
            result = await flow_generate(gen_body)
            if isinstance(result, dict):
                return {
                    "job_id": result.get("job_id") or result.get("id"),
                    "media_id": result.get("media_id")
                    or result.get("video_media_id")
                    or (result.get("result") or {}).get("media_id"),
                    **result,
                }
            return {"job_id": None, "media_id": None}

        async def poll_fn(job_id: str) -> dict[str, Any]:
            from agent.services import make_video

            status = make_video.get_job(job_id)
            if isinstance(status, dict):
                return status
            return {
                "status": "FAILED",
                "job_id": job_id,
                "error": "ERR_MONTAGE_CANONICAL_JOB_NOT_FOUND",
            }

    try:
        return await authorize_montage_run_generation(
            run_id,
            confirm_credit_burn=body.confirm_credit_burn,
            expected_video_generations=body.expected_video_generations,
            expected_provider_operations=body.expected_provider_operations,
            dry_run=body.dry_run,
            generate_fn=generate_fn,
            poll_fn=poll_fn,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 400
        if "NOT_FOUND" in msg:
            code = 404
        if "CREDIT_CONFIRM" in msg or "COUNT_MISMATCH" in msg:
            code = 403
        raise HTTPException(status_code=code, detail=msg) from exc


@router.get("/policies")
async def montage_policies() -> dict[str, Any]:
    return {
        "reference_policies": [p.value for p in SceneReferencePolicy],
        "assembly_path": "DISCRETE_MONTAGE",
        "execution_supported": True,
        "live_generate_via": "/api/montage/runs/{id}/authorize-generation → /api/flow/generate per scene",
        "live_concat_via": (
            "/api/montage/runs/{id}/assemble with dry_run=false and "
            "confirm_live_credit_burn=true -> existing final-timeline runtime"
        ),
    }
