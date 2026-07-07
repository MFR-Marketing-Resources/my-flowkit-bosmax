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


# ── Manual add + AI auto-generate (additive, mirror of avatar-registry). Both
# build a full pool row and add it through the fail-closed add_scene() door.
# Redundancy fails closed with 409 so the pool never gains a duplicate scene.

class SceneManualAddRequest(BaseModel):
    scene_name: str
    background_prompt: str
    route_fit: str | None = None
    usage_tags: str | None = None


def _build_scene_pool_row(scene_context_registry, payload: dict) -> tuple[str, dict]:
    """Build (scene_code, full pool row dict) from a validated manual/AI payload."""
    scene_code = scene_context_registry.next_scene_code(payload["scene_name"])
    background = str(payload["background_prompt"]).strip()
    background_cell = background if background.lower().startswith("background") \
        else f"Background: {background}"
    prompt_v1 = scene_context_registry.build_scene_prompt_v1(
        payload["scene_name"], background)
    row = {
        "SceneName": payload["scene_name"],
        "SceneCode": scene_code,
        "BackgroundPrompt": background_cell,
        "RouteFit": str(payload.get("route_fit") or "").strip(),
        "SafetyBlock": "STANDARD_SCENE_SAFETY_BLOCK",
        "PromptV1": prompt_v1,
        "approved_flag": "TRUE",
        "usage_tags": str(payload.get("usage_tags") or "").strip(),
    }
    return scene_code, row


@router.post("/scene-context-registry/add-manual")
async def scene_context_registry_add_manual(request: SceneManualAddRequest):
    """Manual single-scene add. Fail-closed 409 on a redundant scene (same
    normalized scene_name or identical background text already in the pool)."""
    from agent.services import scene_context_registry
    existing = scene_context_registry.find_duplicate_scene(
        request.scene_name, request.background_prompt)
    if existing is not None:
        raise HTTPException(409, f"SCENE_REDUNDANT:{existing['scene_code']}")
    scene_code, row = _build_scene_pool_row(
        scene_context_registry, request.model_dump())
    try:
        scene_context_registry.add_scene(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"scene_code": scene_code, "scene_name": request.scene_name}


class SceneAutoGenRequest(BaseModel):
    brief: str | None = None


_SCENE_AI_REQUIRED_KEYS = ("scene_name", "background_prompt")


def _coerce_ai_scene_profile(data: dict) -> dict | None:
    """Validate + coerce the AI-returned dict into a manual-add payload, or None
    if required keys are missing. usage_tags array → pipe-delimited string."""
    if not isinstance(data, dict):
        return None
    if any(not str(data.get(key) or "").strip() for key in _SCENE_AI_REQUIRED_KEYS):
        return None
    usage_tags = data.get("usage_tags")
    if isinstance(usage_tags, list):
        usage_tags = "|".join(str(t).strip() for t in usage_tags if str(t).strip())
    return {
        "scene_name": str(data["scene_name"]).strip(),
        "background_prompt": str(data["background_prompt"]).strip(),
        "route_fit": str(data.get("route_fit") or "").strip() or None,
        "usage_tags": str(usage_tags or "").strip() or None,
    }


@router.post("/scene-context-registry/auto-generate")
async def scene_context_registry_auto_generate(request: SceneAutoGenRequest):
    """AI auto-generate ONE non-duplicate background scene via the configured
    text_assist lane. Fail-closed: 503 if unconfigured, 502 on invalid AI JSON,
    409 if the AI keeps returning a duplicate after one stronger retry."""
    from agent.services import ai_copy_provider_adapter
    from agent.services import scene_context_registry
    if not ai_copy_provider_adapter.is_configured():
        raise HTTPException(503, "TEXT_ASSIST_NOT_CONFIGURED")

    existing_names = ", ".join(
        p["scene_name"] for p in scene_context_registry.list_pool())
    system = (
        "Generate ONE Malaysian commercial background SCENE as STRICT JSON, avoid "
        "duplicating: " + existing_names + ". Keys: scene_name, background_prompt"
        "(one clean 'Background: ...' style env description, no people/product), "
        "usage_tags(array)."
    )
    user = str(request.brief or "Generate a fresh commercial background scene.")

    try:
        raw = ai_copy_provider_adapter.complete_json(system, user)
    except ai_copy_provider_adapter.AICopyProviderNotConfigured as exc:
        raise HTTPException(503, "TEXT_ASSIST_NOT_CONFIGURED") from exc
    except ai_copy_provider_adapter.AICopyProviderError as exc:
        raise HTTPException(502, "AI_SCENE_GENERATION_FAILED") from exc

    payload = _coerce_ai_scene_profile(raw)
    if payload is None:
        raise HTTPException(502, "AI_SCENE_INVALID")

    duplicate = scene_context_registry.find_duplicate_scene(
        payload["scene_name"], payload["background_prompt"])
    if duplicate is not None:
        retry_user = user + (
            "\nThe previous result duplicated an existing scene. You MUST return a "
            "DISTINCT scene_name and background not already listed.")
        try:
            raw = ai_copy_provider_adapter.complete_json(system, retry_user)
        except ai_copy_provider_adapter.AICopyProviderError as exc:
            raise HTTPException(502, "AI_SCENE_GENERATION_FAILED") from exc
        payload = _coerce_ai_scene_profile(raw)
        if payload is None:
            raise HTTPException(502, "AI_SCENE_INVALID")
        duplicate = scene_context_registry.find_duplicate_scene(
            payload["scene_name"], payload["background_prompt"])
        if duplicate is not None:
            raise HTTPException(409, "SCENE_REDUNDANT_AI")

    scene_code, row = _build_scene_pool_row(scene_context_registry, payload)
    try:
        scene_context_registry.add_scene(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"scene_code": scene_code, "scene_name": payload["scene_name"],
            "generated": True}


@router.delete("/scene-context-registry/{scene_code}")
async def scene_context_registry_delete(scene_code: str):
    """CRUD delete: remove ONE scene profile from the pool (fail-closed through the
    same sync door as add) and best-effort ARCHIVE its generated background image
    so it also leaves the active Library. 404 if the code is absent; the image
    archive never blocks the profile delete."""
    from agent.services import scene_context_registry
    from agent.services.creative_asset_service import (
        archive_creative_asset,
        list_creative_assets,
    )
    try:
        result = scene_context_registry.delete_scene(scene_code)
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(404 if "NOT_FOUND" in msg else 422, msg) from exc
    # Best-effort archive of the linked background image + purge its 48h temp
    # artifact so the image fully leaves the Library now (archiving the saved
    # asset alone un-hides its temp twin). Match the SCENE_CODE marker in the
    # asset description. Never blocks the profile delete.
    archived_asset_id = None
    purged_media_id = None
    try:
        target = scene_code.strip().upper()
        assets = await list_creative_assets(
            semantic_role="SCENE_CONTEXT_REFERENCE", status="ACTIVE", limit=1000)
        for asset in assets:
            description = str(getattr(asset, "description", "") or "")
            if _SCENE_ASSET_MARKER not in description:
                continue
            code = description.split(_SCENE_ASSET_MARKER, 1)[1].split()[0].strip().upper()
            if code == target:
                await archive_creative_asset(str(asset.asset_id))
                archived_asset_id = str(asset.asset_id)
                media_id = getattr(asset, "media_id", None)
                if media_id:
                    try:
                        from agent.db import crud
                        await crud.delete_generated_artifact(str(media_id))
                        purged_media_id = str(media_id)
                    except Exception:
                        purged_media_id = None
                break
    except Exception:
        pass
    return {**result, "archived_asset_id": archived_asset_id,
            "purged_media_id": purged_media_id}
