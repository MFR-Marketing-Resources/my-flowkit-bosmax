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
    build_montage_manifest_items,
    create_montage_discrete_run,
    estimate_montage_run_generation,
    get_montage_discrete_run,
    load_montage_execution_identity,
    readiness_from_montage_run,
    resume_montage_run,
)
from agent.services.montage_scene_reference_policy import (
    SceneReferencePolicy,
    parse_scene_reference_policy,
)
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)
from agent.services import product_mascot_service
from agent.services import montage_mascot_creative_grammar as mascot_grammar
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
    staff_id: Optional[str] = None
    beats: list[MontageBeatInput] = Field(default_factory=list)
    default_policy: str = "PRODUCT_ANCHOR"
    product_media_id: Optional[str] = None
    per_beat_policy: Optional[dict[str, str]] = None
    hook_id: str = "AUTO"
    background_id: str = "AUTO"
    model: str = Field(..., min_length=1)
    duration_seconds: int = Field(..., gt=0)
    copy_v2_context: dict[str, Any] | None = None
    # Mascot Montage V1.1 — the FINAL video duration (8/10/16/20/24/30). Resolved
    # THROUGH the canonical block-plan + capability authorities into block count
    # (= scene count), atomic block seconds, and compatible model(s). Mascot mode
    # only; non-mascot montage behavior is unchanged. When omitted in mascot mode
    # it defaults to the per-clip duration_seconds (a single-block final).
    final_video_duration_seconds: Optional[int] = None
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


async def _require_montage_staff(staff_id: str | None) -> dict[str, Any]:
    from agent.services.staff_identity_service import (
        StaffIdentityError,
    )
    from agent.security.access_control import resolve_request_staff

    try:
        return await resolve_request_staff(staff_id)
    except StaffIdentityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error_code": exc.code, "message": exc.message},
        ) from exc


async def _require_montage_product(product_id: str) -> None:
    from agent.services.product_release_service import (
        ProductReleaseError,
        ensure_product_operationally_visible,
    )

    try:
        await ensure_product_operationally_visible(product_id, lane="MONTAGE")
    except ProductReleaseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc


async def _resolve_exact_product_montage_resolution(
    *,
    product_id: str,
    hook_id: str,
    background_id: str,
) -> dict[str, Any] | None:
    """Resolve the shared exact-product receipt for the Montage surface.

    Montage keeps its own surface lane and scene plan.  For an exact product,
    however, its provider package must use the same deterministic scaffold /
    server-composite authority as Faceless.  Reuse only that receipt; do not
    expose Faceless as a user-facing Montage mode and do not pass a product
    reference to the provider.
    """
    from agent.db import crud
    from agent.services.product_visual_custody_service import exact_product_required
    from agent.services import faceless_lane_service as fl

    product = await crud.get_product(product_id)
    if not product or not exact_product_required(product):
        return None
    try:
        authority = await fl.resolve_faceless_scene_authority(
            product_id=product_id,
            hook_id=hook_id,
            background_id=background_id,
            actor_profile="AUTO",
        )
        resolution = fl.build_faceless_resolution(
            product_id=product_id,
            hook_id=hook_id,
            background_id=background_id,
            actor_profile="AUTO",
            scene_authority=authority,
        )
    except ValueError as exc:
        error_code = getattr(exc, "code", None) or str(exc).split(":", 1)[0]
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": error_code,
                "message": str(exc),
                "surface_lane": "MONTAGE",
            },
        ) from exc

    receipt = resolution.get("faceless_resolution")
    exact_video = resolution.get("exact_product_video")
    if (
        not isinstance(receipt, dict)
        or not isinstance(exact_video, dict)
        or exact_video.get("selected_execution_route")
        != "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
        or receipt.get("exact_product_video") is None
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "ERR_MONTAGE_EXACT_PRODUCT_ROUTE_NOT_PROVEN",
                "message": (
                    "Exact-product Montage requires a canonical deterministic "
                    "scene-scaffold/composite receipt."
                ),
                "surface_lane": "MONTAGE",
            },
        )
    return receipt


def _montage_uses_product_anchor(
    default_policy: SceneReferencePolicy,
    per_beat_policy: Optional[dict[str, str]],
) -> bool:
    """Return true only when every declared Montage scene is product-anchor."""
    if default_policy is not SceneReferencePolicy.PRODUCT_ANCHOR:
        return False
    return all(
        parse_scene_reference_policy(value) is SceneReferencePolicy.PRODUCT_ANCHOR
        for value in (per_beat_policy or {}).values()
    )


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


async def _prepare_mascot_montage(body: "MontagePlanRequest") -> dict[str, Any]:
    """Mascot Montage V1.1 resolution (fail-closed).

    Resolves the current Product Mascot Key Visual (409 if absent) AND the FINAL
    video duration through the canonical authorities into a discrete block plan:
    scene count = block count, atomic block seconds, and the compatible SINGLE
    model(s). Returns the resolved run inputs. Fail-closed 409 / 422 — never
    fabricates a plan.
    """
    mascot_start_asset = await _resolve_mascot_start_asset_or_409(body.product_id)
    final = body.final_video_duration_seconds or body.duration_seconds
    try:
        plan = mascot_grammar.resolve_final_duration_plan(int(final))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": mascot_grammar.ERR_UNSUPPORTED_FINAL_DURATION,
                "detail": str(exc),
                "supported_final_durations": list(mascot_grammar.V11_FINAL_DURATIONS),
            },
        ) from exc
    # Honor an operator-chosen model ONLY if it validates for the atomic block;
    # otherwise the capability authority's default for that atomic duration.
    model = body.model if body.model in plan.models else plan.default_model
    beats = [
        MontageBeatInput(
            beat_id=b["beat_id"],
            role=b["role"],
            objective=b["objective"],
            visual_action=b["visual_action"],
        )
        for b in mascot_grammar.scene_beats(plan.block_count)
    ]
    return {
        "mascot_start_asset": mascot_start_asset,
        "beats": beats,
        "model": model,
        "duration_seconds": plan.atomic_seconds,
        "block_count": plan.block_count,
        "atomic_seconds": plan.atomic_seconds,
        "plan": plan.to_dict(),
    }


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
    staff_profile = await _require_montage_staff(body.staff_id)
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    await _require_montage_product(body.product_id)
    try:
        default_policy = parse_scene_reference_policy(body.default_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from agent.services.montage_run_service import _resolve_montage_single_settings

    mascot_duration_plan: dict[str, Any] | None = None
    assembly_path = "DISCRETE_MONTAGE"
    if body.use_product_mascot:
        # V1.1: mascot anchor (409) + FINAL duration -> canonical block plan ->
        # scene count / atomic block / model. Fail-closed before copy resolution.
        prep = await _prepare_mascot_montage(body)
        default_policy = SceneReferencePolicy.START_FRAME
        beats = prep["beats"]
        model, duration_seconds = prep["model"], prep["duration_seconds"]
        mascot_duration_plan = prep["plan"]
        assembly_path = prep["plan"]["assembly"]
    else:
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
    plans = plan_scenes_from_story(
        story_beats=beats,
        default_policy=default_policy,
        per_beat_policy=body.per_beat_policy,
        product_media_id=None if body.use_product_mascot else body.product_media_id,
    )
    return {
        "product_id": body.product_id,
        "staff_id": staff_profile["staff_id"],
        "staff_display_name": staff_profile["display_name"],
        "hook_id": body.hook_id,
        "background_id": body.background_id,
        "scene_count": len(plans),
        "scenes": [plan_to_dict(p) for p in plans],
        "assembly_path": assembly_path,
        "credit_spend": False,
        "execution_supported": True,
        "model": model,
        "duration_seconds": duration_seconds,
        "mascot_duration_plan": mascot_duration_plan,
        "copy_policy": "REQUIRED",
        "copy_architecture_v2": (
            copy_resolution.to_metadata(consumer_context=body.copy_v2_context)
            if copy_resolution and copy_resolution.v2_enabled
            else None
        ),
    }


@router.get("/mascot-duration-options")
async def montage_mascot_duration_options() -> dict[str, Any]:
    """V1.1 operator menu: the supported FINAL video durations for Mascot Montage,
    each resolved THROUGH the canonical block-plan + capability authorities into
    scene count, atomic block seconds, compatible model(s), and assembly mode."""
    return {"options": mascot_grammar.duration_options()}


@router.post("/execute-scenes")
async def montage_execute_scenes(body: MontageExecuteRequest) -> dict[str, Any]:
    """R2 operational path: beat → route → workspace package (existing factory).

    Does not spend credits by default. Live generate is refused unless
    allow_live_generate is set (still not wired to a credit runner here — fail
    closed).
    """
    staff_profile = await _require_montage_staff(body.staff_id)
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    await _require_montage_product(body.product_id)
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
    exact_product_resolution = None
    if not body.use_product_mascot and _montage_uses_product_anchor(
        default_policy, body.per_beat_policy
    ):
        exact_product_resolution = await _resolve_exact_product_montage_resolution(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
        )
    from agent.services.montage_run_service import _resolve_montage_single_settings

    mascot_start_asset = None
    mascot_block_count = None
    mascot_atomic_seconds = None
    if body.use_product_mascot:
        prep = await _prepare_mascot_montage(body)
        mascot_start_asset = prep["mascot_start_asset"]
        default_policy = SceneReferencePolicy.START_FRAME
        beats = prep["beats"]
        model, duration_seconds = prep["model"], prep["duration_seconds"]
        mascot_block_count = prep["block_count"]
        mascot_atomic_seconds = prep["atomic_seconds"]
    else:
        try:
            model, duration_seconds = _resolve_montage_single_settings(
                body.model, body.duration_seconds
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        beats = body.beats or _default_beats()
    report = await orchestrate_montage_scenes(
        product_id=body.product_id,
        staff_id=staff_profile["staff_id"],
        staff_display_name_snapshot=staff_profile["display_name"],
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
        mascot_block_count=mascot_block_count,
        mascot_atomic_seconds=mascot_atomic_seconds,
        faceless_resolution=exact_product_resolution,
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
    staff_profile = await _require_montage_staff(body.staff_id)
    if not str(body.product_id or "").strip():
        raise HTTPException(status_code=400, detail="product_id required")
    await _require_montage_product(body.product_id)
    if body.allow_live_generate:
        raise HTTPException(
            status_code=403,
            detail="Live credit generate is not auto-started on run create",
        )
    try:
        default_policy = parse_scene_reference_policy(body.default_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    exact_product_resolution = None
    if not body.use_product_mascot and _montage_uses_product_anchor(
        default_policy, body.per_beat_policy
    ):
        exact_product_resolution = await _resolve_exact_product_montage_resolution(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
        )
    mascot_start_asset = None
    mascot_block_count = None
    mascot_atomic_seconds = None
    run_model = body.model
    run_duration = body.duration_seconds
    if body.use_product_mascot:
        prep = await _prepare_mascot_montage(body)
        mascot_start_asset = prep["mascot_start_asset"]
        default_policy = SceneReferencePolicy.START_FRAME
        beats = prep["beats"]
        run_model, run_duration = prep["model"], prep["duration_seconds"]
        mascot_block_count = prep["block_count"]
        mascot_atomic_seconds = prep["atomic_seconds"]
    else:
        beats = body.beats or _default_beats()
    try:
        return await create_montage_discrete_run(
            product_id=body.product_id,
            staff_id=staff_profile["staff_id"],
            staff_display_name_snapshot=staff_profile["display_name"],
            story_beats=beats,
            package_factory=create_workspace_execution_package,
            default_policy=default_policy,
            per_beat_policy=body.per_beat_policy,
            product_media_id=None if body.use_product_mascot else body.product_media_id,
            scene_context_override=body.scene_context_override,
            copy_fallback_confirmed=body.copy_fallback_confirmed,
            hook_id=body.hook_id,
            background_id=body.background_id,
            model=run_model,
            duration_seconds=run_duration,
            copy_v2_context=body.copy_v2_context,
            mascot_start_asset=mascot_start_asset,
            mascot_block_count=mascot_block_count,
            mascot_atomic_seconds=mascot_atomic_seconds,
            faceless_resolution=exact_product_resolution,
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
    run_product_id = str(cfg.get("product_id") or state.get("product_id") or "").strip()
    if not run_product_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PRODUCT_ID_REQUIRED",
                "message": "A canonical product identity is required before Montage assembly.",
            },
        )
    await _require_montage_product(run_product_id)
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

        # The run's initiating staff identity is the authority for the final
        # Montage output. Re-resolve it immediately before the provider concat
        # boundary so an inactive profile cannot authorize a new operation, and
        # so the final lifecycle/artifact rows receive the server snapshot.
        from agent.services.staff_identity_service import (
            StaffIdentityError,
            resolve_staff_identity,
        )

        try:
            final_staff = await resolve_staff_identity(cfg.get("staff_id"))
        except StaffIdentityError as exc:
            raise ValueError(exc.code) from exc

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
                staff_id=final_staff["staff_id"],
                staff_display_name_snapshot=final_staff["display_name"],
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
        from agent.services.product_release_service import (
            ProductOperationalVisibilityError,
            require_product_operational_visibility,
        )
        try:
            await require_product_operational_visibility(
                run_product_id, lane="MONTAGE_CONCAT_PROVIDER"
            )
        except ProductOperationalVisibilityError as exc:
            raise ValueError(f"{exc.code}:{exc}") from exc
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
            from agent.services.video_artifact_delivery_service import (
                register_final_video_artifact,
            )

            try:
                await register_final_video_artifact(
                    result,
                    job_id=effective_job_id,
                    mode="MONTAGE",
                    surface_lane="MONTAGE",
                    project_id=cfg.get("project_id"),
                    request_id=f"montage:{run_id}",
                    product_id=cfg.get("product_id"),
                    prompt=str(cfg.get("scene_context_override") or ""),
                    aspect_ratio="9:16",
                    staff_id=final_staff["staff_id"],
                    staff_display_name_snapshot=final_staff["display_name"],
                )
            except Exception as exc:  # noqa: BLE001 — final delivery is recoverable, not green
                await crud.update_video_production_job_full(
                    effective_job_id,
                    status="FINAL_ARTIFACT_DELIVERY_FAILED",
                    error_code="FINAL_ARTIFACT_DELIVERY_FAILED",
                )
                raise ValueError(
                    f"FINAL_ARTIFACT_DELIVERY_FAILED:{str(exc)[:240]}"
                ) from exc
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
    staff_id: Optional[str] = None
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


@router.post("/runs/{run_id}/materialize-approval-manifest")
async def montage_materialize_approval_manifest(
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    """M-04a: freeze the run's per-scene FINAL prompts into an Approved Generation
    Manifest for human WYSIWYG review. The operator reviews/edits each scene's
    prompt, then approves the manifest; authorize-generation then resolves each
    scene's approved item by envelope hash. Provider-free — nothing generates."""
    from agent.services import execution_approval_service as _eas

    derived = await build_montage_manifest_items(run_id)
    if not derived["items"]:
        raise HTTPException(422, "ERR_MONTAGE_NO_PENDING_SCENES")
    await _require_montage_product(str(derived.get("product_id") or ""))
    run_snapshot = await get_montage_discrete_run(run_id)
    run_config = run_snapshot.get("config") or {}
    created_by = str(run_config.get("staff_id") or "").strip()
    if not created_by:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "STAFF_IDENTITY_REQUIRED",
                "message": "Historical montage runs without canonical staff identity cannot create a new manifest.",
            },
        )
    manifest = await _eas.create_manifest(
        surface="montage",
        run_ref=run_id,
        product_id=derived["product_id"],
        logical_mode="F2V",
        items=derived["items"],
        created_by=created_by,
    )
    return manifest


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
    staff_profile = await _require_montage_staff(body.staff_id)
    run_snapshot = await get_montage_discrete_run(run_id)
    run_product_id = str(
        (run_snapshot or {}).get("product_id")
        or ((run_snapshot or {}).get("config") or {}).get("product_id")
        or ""
    ).strip()
    if not run_product_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PRODUCT_ID_REQUIRED",
                "message": "A canonical product identity is required before Montage generation.",
            },
        )
    await _require_montage_product(run_product_id)
    generate_fn = None
    poll_fn = None
    _run_manifest_id = None
    if not body.dry_run:
        from agent.api.flow import GenerateRequest
        from agent.api.flow import generate as flow_generate
        from agent.services import execution_approval_service as _eas

        # Human-approved Generation Manifest for this run (materialised + approved
        # via the manifest review UI before authorize-generation). Each scene
        # dispatch resolves its approved item by envelope hash; if the run has no
        # approved manifest, the enforced gate blocks every scene (fail-closed —
        # never auto-approved from provenance).
        _run_manifest_id = await _eas.approved_manifest_id_for_run(
            run_id, surface="montage",
        )

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
            execution_identity = await load_montage_execution_identity(
                kwargs.get("workspace_execution_package_id")
            )
            gen_body = GenerateRequest(
                mode=str(kwargs.get("mode") or "F2V"),
                prompt=str(kwargs.get("prompt") or f"Montage scene {kwargs.get('scene_id')}"),
                request_id=(
                    f"montage:{run_id}:{str(kwargs.get('scene_id') or '')}"
                ),
                product_id=kwargs.get("product_id") or None,
                production_recipe="MONTAGE",
                staff_id=staff_profile["staff_id"],
                aspect="9:16",
                # Thread the source lineage + package id the run persisted. For a
                # mascot START_FRAME scene source_mode="FRAMES" makes the global
                # product-visual gate honor the mascot start asset (its existing
                # FRAMES exemption) rather than replacing it with the Official
                # Product Visual. The gate itself is unchanged.
                source_mode=kwargs.get("source_mode") or None,
                surface_lane="MONTAGE",
                workspace_execution_package_id=kwargs.get("workspace_execution_package_id") or None,
                execution_identity=execution_identity,
                model=kwargs.get("model") or None,
                duration_s=kwargs.get("duration_s"),
                generation_mode="SINGLE",
                engine="GOOGLE_FLOW",
                startAsset=start_asset if isinstance(start_asset, dict) else None,
                image_media_ids=image_media_ids or None,
                # Resolve THIS scene against the run's human-approved manifest item
                # (by envelope hash). No provenance string manufactures approval.
                manifest_id=_run_manifest_id,
                manifest_item_key=str(kwargs.get("scene_id") or "") or None,
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
            durable = await make_video.get_durable_job(job_id)
            if isinstance(durable, dict):
                return durable
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
            staff_id=staff_profile["staff_id"],
            staff_display_name_snapshot=staff_profile["display_name"],
            generate_fn=generate_fn,
            poll_fn=poll_fn,
            async_worker=not body.dry_run,
            poll_interval_s=5.0,
            manifest_id=_run_manifest_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 400
        if "NOT_FOUND" in msg:
            code = 404
        if "CREDIT_CONFIRM" in msg or "COUNT_MISMATCH" in msg:
            code = 403
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/runs/{run_id}/resume-generation")
async def resume_montage_generation(run_id: str) -> dict[str, Any]:
    """Poll one durable scene job and advance its lease; never re-submit."""
    from agent.services import make_video

    run_snapshot = await get_montage_discrete_run(run_id)
    run_product_id = str(
        (run_snapshot or {}).get("product_id")
        or ((run_snapshot or {}).get("config") or {}).get("product_id")
        or ""
    ).strip()
    if not run_product_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PRODUCT_ID_REQUIRED",
                "message": "A canonical product identity is required before Montage recovery.",
            },
        )
    await _require_montage_product(run_product_id)

    async def poll_fn(job_id: str) -> dict[str, Any]:
        from agent.services import make_video

        status = make_video.get_job(job_id)
        if isinstance(status, dict):
            state = str(status.get("status") or "").upper()
            if state not in {"RECOVERY_REQUIRED", "RECOVERY_UNRECOVERABLE"}:
                return status
        durable = await make_video.reconcile_durable_single_job(job_id)
        return durable or {
            "job_id": job_id,
            "status": "GENERATED_BUT_UNRETRIEVED",
            "error": "ERR_MONTAGE_CANONICAL_JOB_NOT_FOUND",
        }

    try:
        return await resume_montage_run(run_id, poll_fn=poll_fn, max_items=1)
    except ValueError as exc:
        code = 404 if "NOT_FOUND" in str(exc) else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc


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
