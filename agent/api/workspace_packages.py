from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agent.services.prompt_compiler_runtime_config_service import (
    get_runtime_config,
)
from agent.services.copy_binding_service import CopyBindingError
from agent.services.workspace_execution_package_service import (
    compile_workspace_prompt_preview,
    create_workspace_execution_package,
    list_workspace_execution_packages,
)
from agent.services.i2v_semantic_slot_resolver_service import (
    resolve_i2v_semantic_slots,
)
from agent.models.i2v_semantic_slot_resolver import (
    I2VSemanticSlotResolverRequest,
)
from agent.services.approved_product_package_service import (
    get_product_package_readiness,
    normalize_mode,
)


router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspacePromptBlockRequest(BaseModel):
    block_index: int
    duration_seconds: int


class WorkspaceExecutionPackageRequest(BaseModel):
    product_id: str
    mode: str
    duration_seconds: int = 8
    aspect_ratio: str = "9:16"
    model: str = ""
    manual_override: bool = False
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008): default off
    source_mode: str | None = None  # explicit T2V|HYBRID|FRAMES|INGREDIENTS|IMAGES
    engine_duration_target: str | None = None  # GOOGLE_FLOW | GROK (workbook block plans)
    requested_total_duration_seconds: int | None = None  # derive 1-7 block chain from workbook
    dialogue_enabled: bool = True
    recipe_id: str = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
    product_reference_asset_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_context_reference_asset_id: str | None = None
    style_reference_asset_id: str | None = None
    blocks: list[WorkspacePromptBlockRequest] = Field(default_factory=list)
    # Copy Selection & Compiler Binding V1: operator-selected approved Copy Set.
    # Optional — when absent the compiler uses its existing fallback copy.
    copy_set_id: str | None = None
    # Explicit-Fallback-Confirmation V1: final generation with NO approved Copy
    # Set requires the operator to intentionally confirm fallback usage. Preview
    # never needs this (see WorkspacePromptCompileRequest — deliberately absent).
    copy_fallback_confirmed: bool = False


class WorkspacePromptCompileRequest(BaseModel):
    product_id: str
    mode: str
    duration_seconds: int = 8
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008): default off
    source_mode: str | None = None  # explicit T2V|HYBRID|FRAMES|INGREDIENTS|IMAGES
    engine_duration_target: str | None = None  # GOOGLE_FLOW | GROK (workbook block plans)
    requested_total_duration_seconds: int | None = None  # derive 1-7 block chain from workbook
    dialogue_enabled: bool = True
    blocks: list[WorkspacePromptBlockRequest] = Field(default_factory=list)
    # Copy Selection & Compiler Binding V1: operator-selected approved Copy Set.
    copy_set_id: str | None = None


class WorkspacePackageReadinessRequest(BaseModel):
    mode: str
    product_ids: list[str]


@router.post("/execution-package")
async def post_workspace_execution_package(request: WorkspaceExecutionPackageRequest):
    try:
        return await create_workspace_execution_package(
            product_id=request.product_id,
            mode=request.mode,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            model=request.model,
            manual_override=request.manual_override,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            recipe_id=request.recipe_id,
            product_reference_asset_id=request.product_reference_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
            style_reference_asset_id=request.style_reference_asset_id,
            blocks=[block.model_dump() for block in request.blocks],
            source_mode=request.source_mode,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            copy_set_id=request.copy_set_id,
            copy_fallback_confirmed=request.copy_fallback_confirmed,
        )
    except CopyBindingError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.detail},
        ) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/execution-packages")
async def get_workspace_execution_packages(
    product_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    return await list_workspace_execution_packages(product_id=product_id, mode=mode, limit=limit)


@router.post("/package-readiness")
async def post_workspace_package_readiness(
    request: WorkspacePackageReadinessRequest,
):
    normalized_mode = normalize_mode(request.mode)
    items = []
    for product_id in request.product_ids:
        items.append(await get_product_package_readiness(product_id, normalized_mode))
    return {
        "mode": normalized_mode,
        "items": items,
    }


@router.get("/prompt-compiler-config")
async def get_workspace_prompt_compiler_config():
    return get_runtime_config()


@router.post("/ugc-video-prompt-compile")
async def post_workspace_prompt_compile(request: WorkspacePromptCompileRequest):
    try:
        return await compile_workspace_prompt_preview(
            product_id=request.product_id,
            mode=request.mode,
            duration_seconds=request.duration_seconds,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            blocks=[block.model_dump() for block in request.blocks],
            source_mode=request.source_mode,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            copy_set_id=request.copy_set_id,
        )
    except CopyBindingError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.detail},
        ) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/i2v/resolve-slots")
async def post_i2v_semantic_slot_resolver(
    request: I2VSemanticSlotResolverRequest,
):
    try:
        return await resolve_i2v_semantic_slots(request=request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message in {"PRODUCT_NOT_FOUND", "CREATIVE_ASSET_NOT_FOUND"} else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


# ── Copywriting landbank (ADR-008): operator-uploaded COPY_MASTER rows.
# SECONDARY reference for the canonical compiler — helps dialogue quality,
# never overrides explicit operator copy, never fails a compile when absent.

@router.post("/copywriting-landbank/{product_id}")
async def upload_copywriting_landbank(product_id: str, request: Request):
    csv_bytes = await request.body()
    if not csv_bytes:
        raise HTTPException(422, "CSV body required")
    from agent.services import copy_landbank_service
    try:
        return copy_landbank_service.save_csv(product_id, csv_bytes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/copywriting-landbank")
async def list_copywriting_landbank():
    from agent.services import copy_landbank_service
    return {"products": copy_landbank_service.list_products()}


@router.get("/copywriting-landbank/{product_id}")
async def get_copywriting_landbank(product_id: str, angle: str = None):
    from agent.services import copy_landbank_service
    row = copy_landbank_service.lookup(product_id, angle=angle)
    if row is None:
        raise HTTPException(404, "LANDBANK_NOT_FOUND")
    return row


# ── Avatar registry bridge (ADR-008 avatar law): the live Notion registry is
# authored upstream; runtime growth arrives as an explicit validated CSV sync.

@router.post("/avatar-registry/sync")
async def sync_avatar_registry(request: Request):
    csv_bytes = await request.body()
    if not csv_bytes:
        raise HTTPException(422, "CSV body required")
    from agent.services import avatar_registry
    try:
        return avatar_registry.sync_pool_csv(csv_bytes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


_AVATAR_ASSET_MARKER = "AVATAR_CODE:"


async def _generated_avatar_asset_ids() -> dict[str, str]:
    """Map avatar_code -> creative asset_id for every ACTIVE CHARACTER_REFERENCE
    asset carrying the AVATAR_CODE marker in its description."""
    from agent.services.creative_asset_service import list_creative_assets
    assets = await list_creative_assets(
        semantic_role="CHARACTER_REFERENCE", status="ACTIVE", limit=1000)
    mapping: dict[str, str] = {}
    for asset in assets:
        description = str(getattr(asset, "description", "") or "")
        if _AVATAR_ASSET_MARKER in description:
            code = description.split(_AVATAR_ASSET_MARKER, 1)[1].split()[0].strip()
            if code:
                mapping[code.upper()] = asset.asset_id
    return mapping


@router.get("/avatar-registry/pool")
async def avatar_registry_pool():
    from agent.services import avatar_registry
    profiles = avatar_registry.list_pool()
    generated = await _generated_avatar_asset_ids()
    for profile in profiles:
        asset_id = generated.get(str(profile.get("avatar_code", "")).upper())
        profile["generated_asset_id"] = asset_id
        profile["image_generated"] = bool(asset_id)
    return {
        "avatars": profiles,
        "count": len(profiles),
        "generated_count": sum(1 for p in profiles if p["image_generated"]),
        "source": str(avatar_registry._active_pool_file()),
        "bridge_active": avatar_registry._BRIDGE_FILE.exists(),
    }


class AvatarGenerateImageRequest(BaseModel):
    avatar_code: str
    confirm_credit_burn: bool = False
    aspect: str = "9:16"
    count: int = 1                       # 1-4; clamped in start_generate
    image_model: str | None = None       # Nano Banana Pro/2/2 Lite; None → default


@router.post("/avatar-registry/generate-image")
async def avatar_registry_generate_image(request: AvatarGenerateImageRequest):
    """Avatar image factory: fire ONE IMG job on the proven one-door lane using
    the avatar's registry PromptV1. Fail-closed: explicit credit confirmation
    required (engineering lockdown — no credit spend without user approval)."""
    if not request.confirm_credit_burn:
        raise HTTPException(422, "CONFIRM_CREDIT_BURN_REQUIRED")
    from agent.services import avatar_registry
    from agent.services import make_video
    try:
        identity = avatar_registry.get_generation_prompt(request.avatar_code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    result = await make_video.start_generate(
        "IMG", identity["prompt"], aspect=request.aspect,
        num_videos=request.count, image_model=request.image_model)
    return {
        "job_id": result.get("job_id"),
        "status": result.get("status"),
        "avatar_code": identity["avatar_code"],
        "character_name": identity["character_name"],
        "poll": f"/api/flow/generate-job/{result.get('job_id')}",
    }


class AvatarRegisterGeneratedRequest(BaseModel):
    avatar_code: str
    media_id: str


@router.post("/avatar-registry/register-generated")
async def avatar_registry_register_generated(request: AvatarRegisterGeneratedRequest):
    """Register a finished IMG-lane artifact as the avatar's CHARACTER_REFERENCE
    asset in the Creative Library, tagged with the AVATAR_CODE marker so the
    registry shows it as generated and Frames/Ingredients can pick it up."""
    from agent.db import crud
    from agent.models.creative_asset import CreativeAssetCreateRequest
    from agent.services import avatar_registry
    from agent.services.creative_asset_service import create_creative_asset
    try:
        identity = avatar_registry.get_generation_prompt(request.avatar_code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    artifacts = await crud.list_generated_artifacts(limit=200, kind="image")
    artifact = next(
        (a for a in artifacts if a.get("media_id") == request.media_id), None)
    if artifact is None:
        raise HTTPException(404, "GENERATED_ARTIFACT_NOT_FOUND")
    existing = await _generated_avatar_asset_ids()
    if identity["avatar_code"].upper() in existing:
        raise HTTPException(409, f"AVATAR_ALREADY_REGISTERED:{existing[identity['avatar_code'].upper()]}")
    # Copy the image OUT of the 48h-retention artifact library into permanent
    # creative-asset storage (the base64 path handles file placement + URLs).
    import base64
    from pathlib import Path
    artifact_path = Path(str(artifact.get("local_path") or ""))
    if not artifact_path.is_file():
        raise HTTPException(404, "GENERATED_ARTIFACT_FILE_MISSING")
    image_base64 = base64.b64encode(artifact_path.read_bytes()).decode("ascii")
    record = await create_creative_asset(CreativeAssetCreateRequest(
        semantic_role="CHARACTER_REFERENCE",
        display_name=f"{identity['character_name']} — {identity['avatar_code']}",
        description=(
            f"{_AVATAR_ASSET_MARKER}{identity['avatar_code']} — generated from "
            "avatar registry PromptV1 via IMG lane"),
        source_type="GENERATED_IMAGE",
        storage_kind="LOCAL_FILE",
        media_id=request.media_id,
        image_base64=image_base64,
        file_name=artifact_path.name,
    ))
    return {"asset_id": record.asset_id, "avatar_code": identity["avatar_code"]}


@router.get("/avatar-registry/status")
async def avatar_registry_status():
    from agent.services import avatar_registry
    pool = avatar_registry._load_pool()
    return {
        "approved_avatars": len(pool),
        "source": str(avatar_registry._active_pool_file()),
        "bridge_active": avatar_registry._BRIDGE_FILE.exists(),
    }


# ── Manual add + AI auto-generate (additive). Both build a full pool row and add
# it through the fail-closed avatar_registry.add_avatar() door. Redundancy on the
# descriptor tuple fails closed with 409 so the pool never gains a duplicate face.

class AvatarManualAddRequest(BaseModel):
    character_name: str
    gender: str = Field(pattern="^[FM]$")
    skin_tone: str
    hair_style: str
    wardrobe: str
    hijab: bool = False
    expression: str
    environment: str | None = None
    lighting: str | None = None
    camera: str | None = None
    usage_tags: str | None = None


def _build_avatar_pool_row(avatar_registry, payload: dict) -> tuple[str, dict]:
    """Build (avatar_code, full pool row dict) from a validated manual/AI payload."""
    descriptor = f"{payload['character_name']} {payload['wardrobe']}"
    avatar_code = avatar_registry.next_avatar_code(payload["gender"], descriptor)
    prompt_profile = {
        "CharacterName": payload["character_name"],
        "AvatarCode": avatar_code,
        "SkinTone": payload["skin_tone"],
        "HairStyle": payload["hair_style"],
        "Wardrobe": payload["wardrobe"],
        "Expression": payload["expression"],
        "Environment": payload.get("environment") or "",
        "Lighting": payload.get("lighting") or "",
        "Camera": payload.get("camera") or "",
        "hijab": bool(payload.get("hijab")),
    }
    prompt_v1 = avatar_registry.build_avatar_prompt_v1(prompt_profile)
    row = {
        "CharacterName": payload["character_name"],
        "Variant": "",
        "AvatarCode": avatar_code,
        "SkinTone": payload["skin_tone"],
        "HairStyle": payload["hair_style"],
        "Wardrobe": payload["wardrobe"],
        "Environment": payload.get("environment") or "",
        "Lighting": payload.get("lighting") or "",
        "Camera": payload.get("camera") or "",
        "Expression": payload["expression"],
        "SafetyBlock": "STANDARD_SAFETY_BLOCK",
        "PromptV1": prompt_v1,
        "approved_flag": "TRUE",
        "usage_tags": str(payload.get("usage_tags") or "").strip(),
    }
    return avatar_code, row


@router.post("/avatar-registry/add-manual")
async def avatar_registry_add_manual(request: AvatarManualAddRequest):
    """Manual single-avatar add. Fail-closed 409 on a redundant descriptor
    (same skin+hair+wardrobe+expression+gender combo already in the pool)."""
    from agent.services import avatar_registry
    existing = avatar_registry.find_duplicate_avatar(
        request.skin_tone, request.hair_style, request.wardrobe,
        request.expression, request.gender)
    if existing is not None:
        raise HTTPException(409, f"AVATAR_REDUNDANT:{existing['avatar_code']}")
    avatar_code, row = _build_avatar_pool_row(avatar_registry, request.model_dump())
    try:
        avatar_registry.add_avatar(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"avatar_code": avatar_code, "character_name": request.character_name,
            "redundant": False}


class AvatarAutoGenRequest(BaseModel):
    brief: str | None = None
    gender: str | None = None
    hijab: bool | None = None


_AVATAR_AI_REQUIRED_KEYS = (
    "character_name", "gender", "skin_tone", "hair_style", "wardrobe",
    "expression",
)


def _coerce_ai_avatar_profile(data: dict) -> dict | None:
    """Validate + coerce the AI-returned dict into a manual-add payload, or None
    if required keys are missing. usage_tags array → pipe-delimited string."""
    if not isinstance(data, dict):
        return None
    if any(not str(data.get(key) or "").strip() for key in _AVATAR_AI_REQUIRED_KEYS):
        return None
    gender = str(data.get("gender") or "").strip().upper()
    if gender not in ("F", "M"):
        return None
    usage_tags = data.get("usage_tags")
    if isinstance(usage_tags, list):
        usage_tags = "|".join(str(t).strip() for t in usage_tags if str(t).strip())
    return {
        "character_name": str(data["character_name"]).strip(),
        "gender": gender,
        "skin_tone": str(data["skin_tone"]).strip(),
        "hair_style": str(data["hair_style"]).strip(),
        "wardrobe": str(data["wardrobe"]).strip(),
        "hijab": bool(data.get("hijab")),
        "expression": str(data["expression"]).strip(),
        "environment": str(data.get("environment") or "").strip() or None,
        "lighting": str(data.get("lighting") or "").strip() or None,
        "camera": str(data.get("camera") or "").strip() or None,
        "usage_tags": str(usage_tags or "").strip() or None,
    }


@router.post("/avatar-registry/auto-generate")
async def avatar_registry_auto_generate(request: AvatarAutoGenRequest):
    """AI auto-generate ONE non-duplicate avatar profile via the configured
    text_assist lane. Fail-closed: 503 if the lane is unconfigured, 502 on invalid
    AI JSON, 409 if the AI keeps returning a duplicate after one stronger retry."""
    from agent.services import ai_copy_provider_adapter
    from agent.services import avatar_registry
    if not ai_copy_provider_adapter.is_configured():
        raise HTTPException(503, "TEXT_ASSIST_NOT_CONFIGURED")

    existing_descriptors = ", ".join(
        "+".join(avatar_registry.descriptor_key(p)) for p in avatar_registry.list_pool()
    )
    system = (
        "You generate ONE Malaysian commercial UGC avatar profile as STRICT JSON. "
        "Avoid duplicating any of these existing avatars (do NOT repeat the same "
        "skin+hair+wardrobe+expression combo): " + existing_descriptors + ". "
        "Return JSON keys: character_name, gender('F'|'M'), skin_tone, hair_style, "
        "wardrobe, hijab(bool), expression, environment, lighting, camera, "
        "usage_tags(array of strings)."
    )
    constraints = []
    if request.gender:
        constraints.append(f"gender must be '{str(request.gender).strip().upper()}'")
    if request.hijab is not None:
        constraints.append(f"hijab must be {bool(request.hijab)}")
    user = str(request.brief or "Generate a fresh commercial UGC avatar.")
    if constraints:
        user += "\nConstraints: " + "; ".join(constraints) + "."

    try:
        raw = ai_copy_provider_adapter.complete_json(system, user)
    except ai_copy_provider_adapter.AICopyProviderNotConfigured as exc:
        raise HTTPException(503, "TEXT_ASSIST_NOT_CONFIGURED") from exc
    except ai_copy_provider_adapter.AICopyProviderError as exc:
        raise HTTPException(502, "AI_AVATAR_GENERATION_FAILED") from exc

    payload = _coerce_ai_avatar_profile(raw)
    if payload is None:
        raise HTTPException(502, "AI_AVATAR_INVALID")

    duplicate = avatar_registry.find_duplicate_avatar(
        payload["skin_tone"], payload["hair_style"], payload["wardrobe"],
        payload["expression"], payload["gender"])
    if duplicate is not None:
        retry_user = user + (
            "\nThe previous result duplicated an existing avatar. You MUST return a "
            "DISTINCT skin+hair+wardrobe+expression combination not already listed.")
        try:
            raw = ai_copy_provider_adapter.complete_json(system, retry_user)
        except ai_copy_provider_adapter.AICopyProviderError as exc:
            raise HTTPException(502, "AI_AVATAR_GENERATION_FAILED") from exc
        payload = _coerce_ai_avatar_profile(raw)
        if payload is None:
            raise HTTPException(502, "AI_AVATAR_INVALID")
        duplicate = avatar_registry.find_duplicate_avatar(
            payload["skin_tone"], payload["hair_style"], payload["wardrobe"],
            payload["expression"], payload["gender"])
        if duplicate is not None:
            raise HTTPException(409, "AVATAR_REDUNDANT_AI")

    avatar_code, row = _build_avatar_pool_row(avatar_registry, payload)
    try:
        avatar_registry.add_avatar(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"avatar_code": avatar_code, "character_name": payload["character_name"],
            "generated": True}


# ── Avatar Registry CSV Factory: seed-schema candidate CSVs go through
# validate -> stage -> operator review -> export/sync. Candidates NEVER write
# the runtime bridge directly; sync merges approved rows through the existing
# fail-closed sync_pool_csv door.

class AvatarCsvFactoryReviewDecision(BaseModel):
    row_index: int
    decision: str = Field(pattern="(?i)^(approve|reject)$")


class AvatarCsvFactoryReviewRequest(BaseModel):
    decisions: list[AvatarCsvFactoryReviewDecision] = Field(min_length=1)


@router.post("/avatar-registry/csv-factory/validate")
async def avatar_csv_factory_validate(request: Request):
    csv_bytes = await request.body()
    if not csv_bytes:
        raise HTTPException(422, "CSV body required")
    from agent.services import avatar_csv_factory_service
    report, _rows = avatar_csv_factory_service.validate_seed_csv(csv_bytes)
    return report


@router.post("/avatar-registry/csv-factory/import")
async def avatar_csv_factory_import(request: Request, filename: str | None = Query(None)):
    csv_bytes = await request.body()
    if not csv_bytes:
        raise HTTPException(422, "CSV body required")
    from agent.services import avatar_csv_factory_service
    try:
        return avatar_csv_factory_service.import_seed_csv(csv_bytes, source_filename=filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/avatar-registry/csv-factory/batches")
async def avatar_csv_factory_batches():
    from agent.services import avatar_csv_factory_service
    return {"batches": avatar_csv_factory_service.list_batches()}


@router.get("/avatar-registry/csv-factory/batches/{batch_id}")
async def avatar_csv_factory_batch_detail(batch_id: str):
    from agent.services import avatar_csv_factory_service
    try:
        return avatar_csv_factory_service.get_batch(batch_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/avatar-registry/csv-factory/batches/{batch_id}/review")
async def avatar_csv_factory_review(batch_id: str, request: AvatarCsvFactoryReviewRequest):
    from agent.services import avatar_csv_factory_service
    decisions = [d.model_dump() for d in request.decisions]
    try:
        return avatar_csv_factory_service.review_rows(batch_id, decisions)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/avatar-registry/csv-factory/batches/{batch_id}/export")
async def avatar_csv_factory_export(batch_id: str):
    from agent.services import avatar_csv_factory_service
    try:
        csv_text = avatar_csv_factory_service.export_approved_csv(batch_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="{batch_id}.approved.seed.csv"',
        },
    )


@router.post("/avatar-registry/csv-factory/batches/{batch_id}/sync")
async def avatar_csv_factory_sync(batch_id: str):
    from agent.services import avatar_csv_factory_service
    try:
        return avatar_csv_factory_service.sync_approved_to_bridge(batch_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
