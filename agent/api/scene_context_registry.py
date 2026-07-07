"""Scene-context registry API — reusable background/scene reference library.

Mirror of the avatar-registry bridge (in workspace_packages.py) for SCENE
CONTEXTS. The retained scene pool is authored upstream; runtime growth arrives as
an explicit validated CSV sync. Registering a generated scene image creates a
``SCENE_CONTEXT_REFERENCE`` Creative Library asset stamped with the authoritative
``SCENE_REFERENCE`` lane governance, so it is immediately selectable in the IMG
Fastlane scene picker and the I2V scene/style dropdown (which filter on
``semantic_role=SCENE_CONTEXT_REFERENCE`` + ``allowed_mode`` + ``APPROVED``).
"""
from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/workspace", tags=["scene-context-registry"])

_SCENE_ASSET_MARKER = "SCENE_CODE:"
_SCENE_LANE_ID = "SCENE_REFERENCE"


async def _generated_scene_asset_ids() -> dict[str, str]:
    """Map scene_code -> creative asset_id for every ACTIVE SCENE_CONTEXT_REFERENCE
    asset carrying the SCENE_CODE marker in its description."""
    from agent.services.creative_asset_service import list_creative_assets
    assets = await list_creative_assets(
        semantic_role="SCENE_CONTEXT_REFERENCE", status="ACTIVE", limit=1000)
    mapping: dict[str, str] = {}
    for asset in assets:
        description = str(getattr(asset, "description", "") or "")
        if _SCENE_ASSET_MARKER in description:
            code = description.split(_SCENE_ASSET_MARKER, 1)[1].split()[0].strip()
            if code:
                mapping[code.upper()] = asset.asset_id
    return mapping


@router.get("/scene-context-registry/pool")
async def scene_context_registry_pool():
    from agent.services import scene_context_registry
    profiles = scene_context_registry.list_pool()
    generated = await _generated_scene_asset_ids()
    for profile in profiles:
        asset_id = generated.get(str(profile.get("scene_code", "")).upper())
        profile["generated_asset_id"] = asset_id
        profile["image_generated"] = bool(asset_id)
    return {
        "scenes": profiles,
        "count": len(profiles),
        "generated_count": sum(1 for p in profiles if p["image_generated"]),
        "source": str(scene_context_registry._active_pool_file()),
        "bridge_active": scene_context_registry._BRIDGE_FILE.exists(),
    }


@router.get("/scene-context-registry/status")
async def scene_context_registry_status():
    from agent.services import scene_context_registry
    pool = scene_context_registry._load_pool()
    return {
        "approved_scenes": len(pool),
        "source": str(scene_context_registry._active_pool_file()),
        "bridge_active": scene_context_registry._BRIDGE_FILE.exists(),
    }


@router.post("/scene-context-registry/sync")
async def sync_scene_context_registry(request: Request):
    csv_bytes = await request.body()
    if not csv_bytes:
        raise HTTPException(422, "CSV body required")
    from agent.services import scene_context_registry
    try:
        return scene_context_registry.sync_pool_csv(csv_bytes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class SceneGenerateImageRequest(BaseModel):
    scene_code: str
    confirm_credit_burn: bool = False
    aspect: str = "9:16"
    count: int = 1                       # 1-4; clamped in start_generate
    image_model: str | None = None       # Nano Banana Pro/2/2 Lite; None → default


@router.post("/scene-context-registry/generate-image")
async def scene_context_registry_generate_image(request: SceneGenerateImageRequest):
    """Scene image factory: fire ONE IMG job on the proven one-door lane using the
    scene's registry PromptV1 (a clean empty background plate). Fail-closed:
    explicit credit confirmation required (engineering lockdown — no credit spend
    without user approval; image gen is credit-free but the gate stays honest)."""
    if not request.confirm_credit_burn:
        raise HTTPException(422, "CONFIRM_CREDIT_BURN_REQUIRED")
    from agent.services import scene_context_registry
    from agent.services import make_video
    try:
        scene = scene_context_registry.get_generation_prompt(request.scene_code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    result = await make_video.start_generate(
        "IMG", scene["prompt"], aspect=request.aspect,
        num_videos=request.count, image_model=request.image_model)
    return {
        "job_id": result.get("job_id"),
        "status": result.get("status"),
        "scene_code": scene["scene_code"],
        "scene_name": scene["scene_name"],
        "poll": f"/api/flow/generate-job/{result.get('job_id')}",
    }


class SceneRegisterGeneratedRequest(BaseModel):
    scene_code: str
    media_id: str


@router.post("/scene-context-registry/register-generated")
async def scene_context_registry_register_generated(request: SceneRegisterGeneratedRequest):
    """Register a finished IMG-lane artifact as the scene's SCENE_CONTEXT_REFERENCE
    asset in the Creative Library, stamped with the authoritative SCENE_REFERENCE
    lane governance (allowed_modes=[I2V,IMG], engine_slots=[scene,style]) and
    APPROVED so it is immediately selectable in Fastlane + I2V."""
    from agent.db import crud
    from agent.models.creative_asset import CreativeAssetCreateRequest
    from agent.services import scene_context_registry
    from agent.services.creative_asset_service import create_creative_asset
    from agent.services.img_asset_lane_config import derive_asset_governance
    try:
        scene = scene_context_registry.get_generation_prompt(request.scene_code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    artifacts = await crud.list_generated_artifacts(limit=200, kind="image")
    artifact = next(
        (a for a in artifacts if a.get("media_id") == request.media_id), None)
    if artifact is None:
        raise HTTPException(404, "GENERATED_ARTIFACT_NOT_FOUND")
    existing = await _generated_scene_asset_ids()
    if scene["scene_code"].upper() in existing:
        raise HTTPException(409, f"SCENE_ALREADY_REGISTERED:{existing[scene['scene_code'].upper()]}")
    artifact_path = Path(str(artifact.get("local_path") or ""))
    if not artifact_path.is_file():
        raise HTTPException(404, "GENERATED_ARTIFACT_FILE_MISSING")
    image_base64 = base64.b64encode(artifact_path.read_bytes()).decode("ascii")
    gov = derive_asset_governance(_SCENE_LANE_ID)
    record = await create_creative_asset(CreativeAssetCreateRequest(
        semantic_role="SCENE_CONTEXT_REFERENCE",
        display_name=f"{scene['scene_name']} — {scene['scene_code']}",
        description=(
            f"{_SCENE_ASSET_MARKER}{scene['scene_code']} — generated from "
            "scene context registry PromptV1 via IMG SCENE_REFERENCE lane"),
        source_type="GENERATED_IMAGE",
        storage_kind="LOCAL_FILE",
        media_id=request.media_id,
        image_base64=image_base64,
        file_name=artifact_path.name,
        # Authoritative lane governance so the asset is correctly selectable.
        generation_recipe_id=gov["generation_recipe_id"],
        asset_subtype=gov["asset_subtype"],
        allowed_modes=gov["allowed_modes"],
        engine_slot_eligibility=gov["engine_slot_eligibility"],
        contains_rendered_text=gov["contains_rendered_text"],
        approved_for_video_support=gov["approved_for_video_support"],
        approved_for_poster=gov["approved_for_poster"],
        scene_context_dna=scene_context_registry.scene_background_prose(
            {"background_prompt": scene.get("scene_name", "")}),
        # Canonical seeded scene → immediately selectable. The I2V/F2V resolver
        # (validate_selectable_asset, require_approved=True) gates on APPROVED, so a
        # registered scene must be APPROVED to actually appear as a picker option.
        review_status="APPROVED",
    ))
    return {"asset_id": record.asset_id, "scene_code": scene["scene_code"]}
