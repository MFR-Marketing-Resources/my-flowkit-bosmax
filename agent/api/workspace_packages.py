from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agent.services.prompt_compiler_runtime_config_service import (
    get_runtime_config,
)
from agent.services.copy_binding_service import CopyBindingError
from agent.services import creative_recipe_service as _recipe
from agent.services.workspace_generation_package_service import (
    QUANTITY_PREVIEW_MAX,
    bind_bulk_manual_fire_result,
    evaluate_copy_pool_readiness,
    get_bulk_manual_fire_handoff,
    plan_bulk_fanout_intents,
    prepare_bulk_fanout_packages,
    preview_quantity_copy_plans,
)
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
from agent.models.workspace_generation_package import BulkManualFireResultRequest
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
    start_frame_asset_id: str | None = None
    end_frame_asset_id: str | None = None
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
    # T2V/Hybrid registry authority: optional AvatarCode + scene Background override
    avatar_id: str | None = None
    scene_context_override: str | None = None
    scene_context_code: str | None = None
    # Recipe descriptors (Step F): selected recipe's scene template + camera preset ids.
    scene_template_id: str | None = None
    camera_preset_code: str | None = None

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
    avatar_id: str | None = None
    scene_context_override: str | None = None
    # Recipe descriptors (Step F): selected recipe's scene template + camera preset ids.
    scene_template_id: str | None = None
    camera_preset_code: str | None = None

class WorkspacePackageReadinessRequest(BaseModel):
    mode: str
    source_mode: str | None = None
    product_ids: list[str]


class QuantityPreviewRequest(BaseModel):
    """Stage-1 quantity preview — credit-free plan of N unique-copy items.
    NEVER fires, approves, enqueues, or spends credit."""
    product_id: str
    mode: str
    source_mode: str | None = None
    generation_mode: str = "SINGLE"
    duration_seconds: int = 8
    requested_total_duration_seconds: int | None = None
    quantity: int = 1
    target_language: str = "BM_MS"


@router.post("/execution-package")
async def post_workspace_execution_package(request: WorkspaceExecutionPackageRequest):
    try:
        _rd = _recipe.resolve_recipe_descriptors(
            request.scene_template_id, request.camera_preset_code
        )
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
            start_frame_asset_id=request.start_frame_asset_id,
            end_frame_asset_id=request.end_frame_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
            style_reference_asset_id=request.style_reference_asset_id,
            blocks=[block.model_dump() for block in request.blocks],
            source_mode=request.source_mode,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            copy_set_id=request.copy_set_id,
            copy_fallback_confirmed=request.copy_fallback_confirmed,
            avatar_id=request.avatar_id,
            scene_context_override=request.scene_context_override,
            scene_context_code=request.scene_context_code,
            scene_template=_rd["scene_template"],
            camera_preset=_rd["camera_preset"],
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
        items.append(
            await get_product_package_readiness(
                product_id,
                normalized_mode,
                source_mode=request.source_mode,
            )
        )
    return {
        "mode": normalized_mode,
        "source_mode": request.source_mode,
        "items": items,
    }


@router.get("/prompt-compiler-config")
async def get_workspace_prompt_compiler_config():
    return get_runtime_config()


@router.post("/ugc-video-prompt-compile")
async def post_workspace_prompt_compile(request: WorkspacePromptCompileRequest):
    try:
        _rd = _recipe.resolve_recipe_descriptors(
            request.scene_template_id, request.camera_preset_code
        )
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
            avatar_id=request.avatar_id,
            scene_context_override=request.scene_context_override,
            scene_template=_rd["scene_template"],
            camera_preset=_rd["camera_preset"],
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


@router.post("/quantity-preview")
async def post_quantity_preview(request: QuantityPreviewRequest):
    """Stage-1 quantity preview: plan + compile N unique-copy items, CREDIT-FREE.

    No provider call, no Flow call, no DB write, no approval, no enqueue, no live
    generation. Dialogue uniqueness is fail-closed — duplicate/pool<N dialogue is a
    BLOCKER, not a warning. Live bulk fan-out remains Stage 2 (unbuilt)."""
    try:
        return await preview_quantity_copy_plans(
            product_id=request.product_id,
            logical_mode=request.mode,
            source_mode=request.source_mode,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            quantity=request.quantity,
            target_language=request.target_language,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 422
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/copy-pool-readiness")
async def post_copy_pool_readiness(request: QuantityPreviewRequest):
    """Can this product supply N UNIQUE approved dialogues? CREDIT-FREE.

    Read-only pool report consumed BEFORE a quantity preview so the operator sees
    the exact shortage instead of a bare DUPLICATE_DIALOGUE_BLOCKED. Compiles
    approved copy sets to count distinct dialogue (a copy set has no dialogue
    column). No provider call, no Flow call, no DB write, no approval, no credit."""
    try:
        return await evaluate_copy_pool_readiness(
            product_id=request.product_id,
            logical_mode=request.mode,
            source_mode=request.source_mode,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            quantity=request.quantity,
            target_language=request.target_language,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 422
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/bulk-fanout-plan")
async def post_bulk_fanout_plan(request: QuantityPreviewRequest):
    """Stage 2A: plan N ITEMIZED live-production intents. CREDIT-FREE.

    Never a blind count:N batch — N separate intents, each with its own
    item_index / copy_variant_id / variation_salt / dialogue_fingerprint /
    per-item status / per-item credit metadata. Fail-closed on copy-pool
    readiness and dialogue uniqueness. Plans only: no package created, nothing
    approved, nothing enqueued, no provider call, no Flow call, no credit."""
    try:
        return await plan_bulk_fanout_intents(
            product_id=request.product_id,
            logical_mode=request.mode,
            source_mode=request.source_mode,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            quantity=request.quantity,
            target_language=request.target_language,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 422
        raise HTTPException(status_code=status_code, detail=message) from exc


class BulkFanoutPrepareRequest(QuantityPreviewRequest):
    """Stage 2C bulk prepare. Inherits the preview/readiness shape so the server
    re-derives the SAME plan it is being asked to prepare."""
    model: str | None = None
    aspect: str = "9:16"
    # Pin the plan the operator actually saw — a stale client preview is refused.
    expect_bulk_plan_fingerprint: str | None = None
    # Image-mode reference slots (shared by every item; only copy varies).
    start_frame_asset_id: str | None = None
    product_reference_asset_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_context_reference_asset_id: str | None = None


@router.post("/bulk-fanout-prepare")
async def post_bulk_fanout_prepare(request: BulkFanoutPrepareRequest):
    """Stage 2C: create -> approve -> enqueue N DURABLE packages. CREDIT-FREE.

    N SEPARATE packages, each bound to its own approved Copy Set — never a
    count:N submission. Fail-closed on copy-pool readiness, dialogue uniqueness,
    a stale plan fingerprint, or any per-item creation failure (all-or-nothing).
    Idempotent per plan. The run is created dry_run=1: no provider call, no Flow
    call, no live generation, no credit. Live firing still requires the
    BULK_FANOUT gate, which stops at the Stage 3 credit boundary."""
    try:
        return await prepare_bulk_fanout_packages(
            product_id=request.product_id,
            logical_mode=request.mode,
            source_mode=request.source_mode,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            quantity=request.quantity,
            target_language=request.target_language,
            model=request.model,
            aspect=request.aspect,
            expect_bulk_plan_fingerprint=request.expect_bulk_plan_fingerprint,
            start_frame_asset_id=request.start_frame_asset_id,
            product_reference_asset_id=request.product_reference_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/bulk-manual-fire-handoff/{production_run_id}")
async def get_bulk_manual_fire_handoff_route(production_run_id: str):
    """Read a dry-run-green bulk batch as operator-only firing instructions."""
    try:
        return await get_bulk_manual_fire_handoff(production_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/bulk-manual-fire-handoff/{production_run_id}/result")
async def post_bulk_manual_fire_result(
    production_run_id: str,
    request: BulkManualFireResultRequest,
):
    """Persist operator-reported result evidence without firing a provider."""
    try:
        return await bind_bulk_manual_fire_result(
            production_run_id=production_run_id,
            workspace_generation_package_id=request.workspace_generation_package_id,
            copy_variant_id=request.copy_variant_id,
            dialogue_fingerprint=request.dialogue_fingerprint,
            provider_job_id=request.provider_job_id,
            flow_media_id=request.flow_media_id,
            result_url=request.result_url,
            result_file_id=request.result_file_id,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    # PI-FINAL-B04: bulk copy import is a copy lane - COPY_ELIGIBLE only.
    from agent.services.copy_eligibility_service import copy_eligibility
    _elig = await copy_eligibility(product_id)
    if not _elig["eligible"]:
        raise HTTPException(409, "COPY_INELIGIBLE:" + ",".join(_elig["reasons"]))
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
_AVATAR_LANE_ID = "AVATAR_REFERENCE"


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
    from agent.db import crud
    profiles = avatar_registry.list_pool()
    generated = await _generated_avatar_asset_ids()
    fits = await crud.list_avatar_product_fits(limit=10_000)
    fit_codes = {str(row.get("avatar_code") or "").upper() for row in fits}
    db = await crud.get_db()
    selection_rows = await (await db.execute(
        "SELECT selected_avatar_code FROM creative_product_selection "
        "WHERE selected_avatar_code IS NOT NULL"
    )).fetchall()
    selected_codes = {str(row[0] or "").upper() for row in selection_rows}
    for profile in profiles:
        asset_id = generated.get(str(profile.get("avatar_code", "")).upper())
        profile["generated_asset_id"] = asset_id
        profile["image_generated"] = bool(asset_id)
        code = str(profile.get("avatar_code", "")).upper()
        profile["cleanup_classification"] = (
            "ACTIVE_PRODUCT_FIT" if code in fit_codes else
            "REFERENCED_BY_SAVED_SELECTION" if code in selected_codes else
            "GENERATED_ASSET_EXISTS" if code in generated else
            "SAFE_ARCHIVE_CANDIDATE"
        )
    return {
        "avatars": profiles,
        "count": len(profiles),
        "generated_count": sum(1 for p in profiles if p["image_generated"]),
        "source": str(avatar_registry._active_pool_file()),
        "bridge_active": avatar_registry._BRIDGE_FILE.exists(),
        "product_fit_mapped_count": len(fit_codes),
        "saved_selection_referenced_count": len(selected_codes),
        "unmapped_review_candidate_count": sum(
            1 for p in profiles
            if str(p.get("avatar_code", "")).upper() not in fit_codes | selected_codes | set(generated)
        ),
    }


@router.get("/avatar-registry/active-product-fit")
async def avatar_registry_active_product_fit():
    """Read-only active product-fit projection; legacy pool rows stay separate."""
    from agent.db import crud
    from agent.services import avatar_registry

    profiles = {str(p.get("avatar_code") or "").upper(): p for p in avatar_registry.list_pool()}
    fits = await crud.list_avatar_product_fits(limit=10_000)
    generated = await _generated_avatar_asset_ids()
    db = await crud.get_db()
    selection_rows = await (await db.execute(
        "SELECT selected_avatar_code FROM creative_product_selection "
        "WHERE selected_avatar_code IS NOT NULL"
    )).fetchall()
    selection_counts: dict[str, int] = {}
    for row in selection_rows:
        code = str(row[0] or "").upper()
        selection_counts[code] = selection_counts.get(code, 0) + 1
    grouped: dict[str, list[dict]] = {}
    for fit in fits:
        grouped.setdefault(str(fit.get("avatar_code") or "").upper(), []).append(fit)
    active: list[dict] = []
    for code, mappings in grouped.items():
        profile = profiles.get(code)
        age_band = str((profile or {}).get("age_band") or "")
        if not profile or "child" in age_band.lower() or "teen" in age_band.lower():
            continue
        clusters = sorted({str(m.get("product_category") or "") for m in mappings if m.get("product_category")})
        active.append({
            **profile,
            "product_clusters": clusters,
            "best_fit_score": max(float(m.get("fit_score") or 0) for m in mappings),
            "generated_asset_id": generated.get(code),
            "image_generated": code in generated,
            "saved_selection_reference_count": selection_counts.get(code, 0),
        })
    active.sort(key=lambda row: (-row["best_fit_score"], row["avatar_code"]))
    return {"avatars": active, "count": len(active), "source": str(avatar_registry._active_pool_file()), "bridge_active": avatar_registry._BRIDGE_FILE.exists()}


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
    asset in the Creative Library, stamped with AVATAR_REFERENCE lane governance
    (allowed_modes=[I2V,IMG], engine_slots=[subject,scene]) and APPROVED so
    Ingredients can select it. Mirrors scene-context-registry/register-generated."""
    from agent.db import crud
    from agent.models.creative_asset import CreativeAssetCreateRequest
    from agent.services import avatar_registry
    from agent.services.creative_asset_service import create_creative_asset
    from agent.services.img_asset_lane_config import derive_asset_governance
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
    # Copy the image OUT of the transient artifact library into permanent
    # creative-asset storage (the base64 path handles file placement + URLs).
    import base64
    from pathlib import Path
    artifact_path = Path(str(artifact.get("local_path") or ""))
    if not artifact_path.is_file():
        raise HTTPException(404, "GENERATED_ARTIFACT_FILE_MISSING")
    image_base64 = base64.b64encode(artifact_path.read_bytes()).decode("ascii")
    gov = derive_asset_governance(_AVATAR_LANE_ID)
    record = await create_creative_asset(CreativeAssetCreateRequest(
        semantic_role="CHARACTER_REFERENCE",
        display_name=f"{identity['character_name']} — {identity['avatar_code']}",
        description=(
            f"{_AVATAR_ASSET_MARKER}{identity['avatar_code']} — generated from "
            "avatar registry PromptV1 via IMG AVATAR_REFERENCE lane"),
        source_type="GENERATED_IMAGE",
        storage_kind="LOCAL_FILE",
        media_id=request.media_id,
        image_base64=image_base64,
        file_name=artifact_path.name,
        # Authoritative lane governance so the asset is correctly selectable
        # across I2V recipes (character_reference maps to subject OR scene).
        generation_recipe_id=gov["generation_recipe_id"],
        asset_subtype=gov["asset_subtype"],
        allowed_modes=gov["allowed_modes"],
        engine_slot_eligibility=gov["engine_slot_eligibility"],
        contains_rendered_text=gov["contains_rendered_text"],
        approved_for_video_support=gov["approved_for_video_support"],
        approved_for_poster=gov["approved_for_poster"],
        # Canonical seeded avatar → immediately selectable. The I2V resolver
        # gates on APPROVED (require_approved=True); pending registry avatars
        # never appear as silent empty options.
        review_status="APPROVED",
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


@router.get("/avatar-registry/vocab")
async def avatar_registry_vocab():
    """Read-only controlled vocabulary + existing personas for the Create Avatar
    dropdowns. Single source of truth (agent/authority/avatar_registry_vocab.json)."""
    from agent.services import avatar_registry
    gender_fields = avatar_registry.gender_specific_fields()
    return {
        "vocab": avatar_registry.load_vocab(),
        "personas": avatar_registry.personas_from_pool(),
        # Gender-aware layer (additive): personas split by pool prefix, which
        # descriptor fields depend on gender, and those fields' per-gender values.
        "personas_by_gender": avatar_registry.personas_by_gender(),
        "gender_specific_fields": gender_fields,
        "vocab_by_gender": {
            g: {f: avatar_registry.vocab_for_gender(g)[f] for f in gender_fields}
            for g in ("F", "M")
        },
    }


# ── Manual add + AI auto-generate (additive). Both build a full pool row and add
# it through the fail-closed avatar_registry.add_avatar() door. Redundancy on the
# descriptor tuple fails closed with 409 so the pool never gains a duplicate face.
# Descriptor values are validated against the controlled vocabulary (fail-closed
# 422) so free-text can never leak into the shared pool.

class AvatarManualAddRequest(BaseModel):
    character_name: str = Field(pattern=r"^[A-Za-z][A-Za-z ]{0,15}$")
    gender: str = Field(pattern="^[FM]$")
    age_band: str = "Adult (30-54)"
    skin_tone: str
    hair_style: str
    wardrobe: str
    hijab: bool = False
    expression: str
    environment: str | None = None
    lighting: str | None = None
    camera: str | None = None
    usage_tags: str | None = None


class AvatarUpdateRequest(BaseModel):
    """Metadata-only avatar edit. Identity descriptors + AvatarCode are immutable
    here; only non-identity presentation metadata (usage_tags) may change."""
    usage_tags: str = Field(min_length=1)


def _build_avatar_pool_row(avatar_registry, payload: dict) -> tuple[str, dict]:
    """Build (avatar_code, full pool row dict) from a validated manual/AI payload."""
    # Name-only descriptor — wardrobe never enters the AvatarCode slug (keeps codes
    # clean, e.g. BOS_F_ALYA_11, not a slugified wardrobe sentence).
    descriptor = str(payload["character_name"])
    avatar_code = avatar_registry.next_avatar_code(payload["gender"], descriptor)
    prompt_profile = {
        "CharacterName": payload["character_name"],
        "AvatarCode": avatar_code,
        "AgeBand": payload["age_band"],
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
        "AgeBand": payload["age_band"],
    }
    return avatar_code, row


@router.post("/avatar-registry/add-manual")
async def avatar_registry_add_manual(request: AvatarManualAddRequest):
    """Manual single-avatar add. Fail-closed 409 on a redundant descriptor
    (same skin+hair+wardrobe+expression+gender combo already in the pool)."""
    from agent.services import avatar_registry
    try:
        avatar_registry.validate_descriptors(request.model_dump())
        # Gender-dependency gate (hijab-on-male, gender-incompatible wardrobe,
        # persona/gender mismatch) on top of the membership check above.
        avatar_registry.validate_gender_compatibility(request.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = avatar_registry.find_duplicate_avatar(
        request.skin_tone, request.hair_style, request.wardrobe,
        request.expression, request.gender, request.age_band)
    if existing is not None:
        raise HTTPException(409, f"AVATAR_REDUNDANT:{existing['avatar_code']}")
    avatar_code, row = _build_avatar_pool_row(avatar_registry, request.model_dump())
    try:
        avatar_registry.add_avatar(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"avatar_code": avatar_code, "character_name": request.character_name,
            "redundant": False}


@router.patch("/avatar-registry/{avatar_code}")
async def avatar_registry_update(avatar_code: str, request: AvatarUpdateRequest):
    """CRUD metadata edit: change one avatar's non-identity metadata (usage_tags)
    while its identity descriptors + AvatarCode stay frozen. 404 if the code is
    absent; 422 on invalid usage tags."""
    from agent.services import avatar_registry
    try:
        return avatar_registry.update_avatar(avatar_code, request.model_dump())
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(404 if "NOT_FOUND" in msg else 422, msg) from exc


class AvatarAutoGenRequest(BaseModel):
    brief: str | None = None
    gender: str | None = None
    age_band: str = "Adult (30-54)"
    hijab: bool | None = None
    environment: str | None = None
    wardrobe: str | None = None
    usage_tag: str | None = None


_AVATAR_AI_REQUIRED_KEYS = (
    "character_name", "gender", "skin_tone", "hair_style", "wardrobe",
    "expression",
)


def _coerce_ai_avatar_profile(data: dict, age_band: str) -> dict | None:
    """Validate + coerce the AI-returned dict into a manual-add payload, or None if
    required keys are missing or a required descriptor is off-vocab. Required
    descriptors are SNAPPED case-insensitively to the controlled vocabulary;
    optional off-vocab descriptors are dropped; usage_tags filtered to in-vocab;
    hijab forced false for male. usage_tags → pipe-delimited string."""
    from agent.services import avatar_registry
    if not isinstance(data, dict):
        return None
    if any(not str(data.get(key) or "").strip() for key in _AVATAR_AI_REQUIRED_KEYS):
        return None
    gender = str(data.get("gender") or "").strip().upper()
    if gender not in ("F", "M"):
        return None
    canonical_age_band = avatar_registry.snap_to_vocab("age_band", age_band)
    if canonical_age_band is None:
        return None
    # Reject an AI name that collides with an existing OTHER-gender persona, so the
    # AI lane can never mint a cross-gender persona code (e.g. male "Alya").
    if avatar_registry.persona_gender(data.get("character_name")) not in (None, gender):
        return None
    gender_fields = set(avatar_registry.gender_specific_fields())
    snapped: dict[str, str] = {}
    for field in ("skin_tone", "hair_style", "wardrobe", "expression"):
        # Gender-specific descriptors (e.g. wardrobe) snap ONLY within the
        # values allowed for the returned gender — an off-gender value is
        # rejected (None → 502) rather than silently kept.
        if field in gender_fields:
            canonical = avatar_registry.snap_to_vocab_for_gender(
                field, data.get(field), gender)
        else:
            canonical = avatar_registry.snap_to_vocab(field, data.get(field))
        if canonical is None:
            return None
        snapped[field] = canonical
    optional = {
        field: avatar_registry.snap_to_vocab(field, data.get(field))
        for field in ("environment", "lighting", "camera")
    }
    raw_tags = data.get("usage_tags")
    if not isinstance(raw_tags, list):
        raw_tags = [raw_tags] if raw_tags else []
    tags = [t for t in (avatar_registry.snap_to_vocab("usage_tags", x) for x in raw_tags) if t]
    return {
        "character_name": str(data["character_name"]).strip()[:16],
        "gender": gender,
        "age_band": canonical_age_band,
        "skin_tone": snapped["skin_tone"],
        "hair_style": snapped["hair_style"],
        "wardrobe": snapped["wardrobe"],
        "hijab": bool(data.get("hijab")) and gender != "M",
        "expression": snapped["expression"],
        "environment": optional["environment"],
        "lighting": optional["lighting"],
        "camera": optional["camera"],
        "usage_tags": "|".join(tags) or None,
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
    # When a gender is requested up-front, offer the AI only that gender's
    # allowed values (e.g. no female-only wardrobe for a male). With no gender
    # constraint the full superset is offered and enforced after the AI returns
    # its gender (via _coerce_ai_avatar_profile's gender-aware snap).
    _req_gender = str(request.gender or "").strip().upper()
    _vocab = (
        avatar_registry.vocab_for_gender(_req_gender)
        if _req_gender in ("F", "M")
        else avatar_registry.load_vocab()
    )

    def _allowed(field: str) -> str:
        return ", ".join(_vocab.get(field, []))

    system = (
        "You generate ONE Malaysian commercial UGC avatar profile as STRICT JSON. "
        "Avoid duplicating any of these existing avatars (do NOT repeat the same "
        "skin+hair+wardrobe+expression combo): " + existing_descriptors + ". "
        "Return JSON keys: character_name(short single word), gender('F'|'M'), "
        "skin_tone, hair_style, wardrobe, hijab(bool), expression, environment, "
        "lighting, camera, usage_tags(array of strings). Each descriptor MUST be "
        "chosen EXACTLY from these allowed values — "
        f"skin_tone: [{_allowed('skin_tone')}]; hair_style: [{_allowed('hair_style')}]; "
        f"wardrobe: [{_allowed('wardrobe')}]; expression: [{_allowed('expression')}]; "
        f"environment: [{_allowed('environment')}]; lighting: [{_allowed('lighting')}]; "
        f"camera: [{_allowed('camera')}]; usage_tags from [{_allowed('usage_tags')}]. "
        f"Age band is fixed to '{request.age_band}'. If it is a child or teen, keep the profile family-safe and non-sexualized. "
        "If gender is 'M', hijab MUST be false."
    )
    constraints = []
    if request.gender:
        constraints.append(f"gender must be '{str(request.gender).strip().upper()}'")
    constraints.append(f"age_band is '{request.age_band}'")
    if request.hijab is not None:
        constraints.append(f"hijab must be {bool(request.hijab)}")
    if request.environment:
        constraints.append(f"environment must be '{request.environment}'")
    if request.wardrobe:
        constraints.append(f"wardrobe must be '{request.wardrobe}'")
    if request.usage_tag:
        constraints.append(f"usage_tags must include '{request.usage_tag}'")
    user = str(request.brief or "Generate a fresh commercial UGC avatar.")
    if constraints:
        user += "\nConstraints: " + "; ".join(constraints) + "."

    try:
        raw = ai_copy_provider_adapter.complete_json(system, user)
    except ai_copy_provider_adapter.AICopyProviderNotConfigured as exc:
        raise HTTPException(503, "TEXT_ASSIST_NOT_CONFIGURED") from exc
    except ai_copy_provider_adapter.AICopyProviderError as exc:
        raise HTTPException(502, "AI_AVATAR_GENERATION_FAILED") from exc

    payload = _coerce_ai_avatar_profile(raw, request.age_band)
    if payload is None:
        raise HTTPException(502, "AI_AVATAR_INVALID")

    duplicate = avatar_registry.find_duplicate_avatar(
        payload["skin_tone"], payload["hair_style"], payload["wardrobe"],
        payload["expression"], payload["gender"], payload["age_band"])
    if duplicate is not None:
        retry_user = user + (
            "\nThe previous result duplicated an existing avatar. You MUST return a "
            "DISTINCT skin+hair+wardrobe+expression combination not already listed.")
        try:
            raw = ai_copy_provider_adapter.complete_json(system, retry_user)
        except ai_copy_provider_adapter.AICopyProviderError as exc:
            raise HTTPException(502, "AI_AVATAR_GENERATION_FAILED") from exc
        payload = _coerce_ai_avatar_profile(raw, request.age_band)
        if payload is None:
            raise HTTPException(502, "AI_AVATAR_INVALID")
        duplicate = avatar_registry.find_duplicate_avatar(
            payload["skin_tone"], payload["hair_style"], payload["wardrobe"],
            payload["expression"], payload["gender"], payload["age_band"])
        if duplicate is not None:
            raise HTTPException(409, "AVATAR_REDUNDANT_AI")

    avatar_code, row = _build_avatar_pool_row(avatar_registry, payload)
    try:
        avatar_registry.add_avatar(row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"avatar_code": avatar_code, "character_name": payload["character_name"],
            "generated": True}


@router.delete("/avatar-registry/{avatar_code}")
async def avatar_registry_delete(avatar_code: str):
    """CRUD delete: remove ONE avatar profile from the pool (fail-closed through
    the same sync door as add) and best-effort ARCHIVE its generated reference
    image so it also leaves the active Library. 404 if the code is absent; the
    image archive never blocks the profile delete."""
    from agent.services import avatar_registry
    from agent.services.creative_asset_service import (
        archive_creative_asset,
        list_creative_assets,
    )
    try:
        result = avatar_registry.delete_avatar(avatar_code)
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(404 if "NOT_FOUND" in msg else 422, msg) from exc
    # Best-effort archive of the linked reference image. Match the AVATAR_CODE
    # marker embedded in the asset description (the code is NOT a model field) —
    # inlined from _generated_avatar_asset_ids so it depends only on the stable
    # list_creative_assets/archive_creative_asset primitives. Never blocks delete.
    archived_asset_id = None
    purged_media_id = None
    try:
        target = avatar_code.strip().upper()
        assets = await list_creative_assets(
            semantic_role="CHARACTER_REFERENCE", status="ACTIVE", limit=1000)
        for asset in assets:
            description = str(getattr(asset, "description", "") or "")
            if _AVATAR_ASSET_MARKER not in description:
                continue
            code = description.split(_AVATAR_ASSET_MARKER, 1)[1].split()[0].strip().upper()
            if code == target:
                await archive_creative_asset(str(asset.asset_id))
                archived_asset_id = str(asset.asset_id)
                # Also purge the linked transient artifact so the image fully
                # leaves the Library now (archiving the saved asset alone un-hides
                # its temp twin). Best-effort; never blocks the delete.
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
