"""IMG Asset Factory v1 — API surface.

Endpoints:
  - GET  /img-factory/lanes            list lane recipes (governance authority)
  - POST /img-factory/save             save an approved REAL IMG output -> Library
  - GET  /img-factory/provider-status  honest IMG generation runtime boundary
  - POST /img-factory/f2v-frame-sources resolve F2V start/end frame selections
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent import config

from agent.models.creative_asset import CreativeAssetRecord
from agent.models.f2v_frame_source_resolver import (
    F2VFrameSourceResolverRequest,
    F2VFrameSourceResolverResponse,
)
from agent.models.img_asset_factory import (
    ImgAssetLaneListResponse,
    ImgFastlanePresetListResponse,
    ImgFastlanePromptPreviewRequest,
    ImgFastlanePromptPreviewResponse,
    ImgProviderStatusResponse,
    ProductReferencePackApprovalRequest,
    SaveImgOutputRequest,
)
from agent.models.image_generation_contract import (
    ImageCapabilityAuditResponse,
    ImageOperationPlan,
    ImageOperationPlanRequest,
    ImagePromptCompileRequest,
    ImagePromptCompileResponse,
    ProductReferencePackRecord,
)
from agent.services.f2v_frame_source_resolver_service import resolve_f2v_frame_sources
from agent.services.img_asset_factory_service import (
    build_image_gen_settings,
    compile_img_fastlane_prompt_preview,
    get_img_provider_status,
    list_img_fastlane_presets,
    list_img_lane_summaries,
    save_img_output_to_library,
)
from agent.services.image_prompt_compiler import (
    build_operation_plan,
    compile_image_prompt,
    resolve_image_creative_context,
)
from agent.services.product_reference_pack_service import (
    ProductReferencePackError,
    approve_product_reference_pack,
    ensure_product_reference_pack,
    get_reference_pack,
)
from agent.db import crud


router = APIRouter(prefix="/img-factory", tags=["img-factory"])


@router.get("/lanes", response_model=ImgAssetLaneListResponse)
async def get_img_factory_lanes() -> ImgAssetLaneListResponse:
    items = list_img_lane_summaries()
    return ImgAssetLaneListResponse(items=items, total=len(items))


@router.get("/provider-status", response_model=ImgProviderStatusResponse)
async def get_img_factory_provider_status() -> ImgProviderStatusResponse:
    return get_img_provider_status()


@router.get("/image-gen-settings")
async def get_image_gen_settings() -> dict:
    """Single source of truth for image-generation default settings shared by
    EVERY image-gen surface (IMG Fastlane, Image Gen, IMG Cockpit, Avatar
    Registry): aspect ratios, counts, and the image-model list (from models.json).
    A model is ``pending`` when its Google internal id is not yet configured — the
    UI still lists it, but generation fails closed until the id is set.

    Delegates to ``build_image_gen_settings`` so the Poster Builder Flow Mirror /
    Creative Cockpit read from the exact same SSOT without duplicating the list."""
    return build_image_gen_settings()


@router.get("/capability-audit", response_model=ImageCapabilityAuditResponse)
async def get_image_capability_audit() -> ImageCapabilityAuditResponse:
    """Phase 1A static/no-spend capability audit.

    Transport configuration is evidence of a supported request shape only; it
    is never reported as proof that the provider used every reference role.
    """
    mapping: dict[str, dict] = {}
    for model_key, provider_id in config.IMAGE_MODELS.items():
        configured = bool(provider_id and provider_id != "PENDING_ID")
        mapping[model_key] = {
            "provider_model_id": provider_id,
            "transport_status": "SUPPORTED" if configured else "BLOCKED",
            "behavior_status": "UNPROVEN",
            "credit_status": "UNVERIFIED",
        }
    return ImageCapabilityAuditResponse(
        phase="1A_STATIC_NO_SPEND",
        no_spend=True,
        provider="Google Flow authenticated image transport",
        model_mapping=mapping,
        transport_contract={
            "endpoint": "/api/flow/generate",
            "request_field": "imageInputs",
            "reference_order": [
                "PRODUCT_CANONICAL",
                "PRODUCT_LABEL_CROP",
                "PRODUCT_LOGO_CROP",
                "PRODUCT_SCALE_EVIDENCE",
                "PRODUCT_CUTOUT",
            ],
            "role_semantics": "UNPROVEN_GENERIC_MEDIA_IDS",
            "response_media_id": "SUPPORTED",
            "provider_artifact_count": "UNPROVEN",
        },
        capability_status={
            "multi_reference_roles": "UNPROVEN",
            "product_editing": "UNPROVEN",
            "complete_poster_output": "UNPROVEN",
            "response_media_id": "SUPPORTED",
            "hidden_retry_control": "SUPPORTED",
        },
        blockers=[
            "PHASE_1B_LIVE_BENCHMARK_REQUIRES_EXPLICIT_BOUNDED_CREDIT_AUTHORIZATION",
        ],
        warnings=[
            "Payload acceptance does not prove Nano Banana used or preserved every reference.",
            "No provider operation was submitted by this audit.",
        ],
    )


@router.get("/creative-campaign/status")
async def get_creative_campaign_status() -> dict:
    return {
        "feature_enabled": config.CREATIVE_CAMPAIGN_POSTER_ENABLED,
        "default_mode": "CREATIVE_CAMPAIGN" if config.CREATIVE_CAMPAIGN_POSTER_ENABLED else "EXACT_COMMERCE",
        "production_default": False,
        "legacy_scene_asset_required": False,
        "optional_scene_reference_supported": True,
        "bounded_live_confirmation_required": True,
    }


@router.get("/products/{product_id}/reference-pack", response_model=ProductReferencePackRecord)
async def get_product_reference_pack(product_id: str) -> ProductReferencePackRecord:
    pack = await get_reference_pack(product_id)
    if pack is None:
        try:
            pack = await ensure_product_reference_pack(product_id)
        except ProductReferencePackError as exc:
            status = 404 if exc.code == "PRODUCT_NOT_FOUND" else 409
            raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc
    return pack


@router.post("/products/{product_id}/reference-pack/rebuild", response_model=ProductReferencePackRecord)
async def rebuild_product_reference_pack(product_id: str) -> ProductReferencePackRecord:
    try:
        return await ensure_product_reference_pack(product_id)
    except ProductReferencePackError as exc:
        status = 404 if exc.code == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/products/{product_id}/reference-pack/approve", response_model=ProductReferencePackRecord)
async def approve_product_reference_pack_route(
    product_id: str, request: ProductReferencePackApprovalRequest
) -> ProductReferencePackRecord:
    try:
        return await approve_product_reference_pack(
            product_id, reviewed_by=request.reviewed_by, note=request.note
        )
    except ProductReferencePackError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/creative-campaign/preview", response_model=ImagePromptCompileResponse)
async def preview_creative_campaign_prompt(
    request: ImagePromptCompileRequest,
) -> ImagePromptCompileResponse:
    product = await crud.get_product(request.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    pack = await get_reference_pack(request.product_id)
    if pack is None:
        try:
            pack = await ensure_product_reference_pack(request.product_id)
        except ProductReferencePackError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    creative_context = await resolve_image_creative_context(
        product,
        operator_direction=request.composition,
        objective=request.objective,
        copy_layout=request.copy_layout,
    )
    return compile_image_prompt(product, pack, request, creative_context)


@router.post("/creative-campaign/operation-plan", response_model=ImageOperationPlan)
async def plan_creative_campaign_operations(
    request: ImageOperationPlanRequest,
) -> ImageOperationPlan:
    # This endpoint is intentionally pure planning.  It does not inspect or
    # spend credits and cannot authorize a provider operation by itself.
    return build_operation_plan(request)


@router.get("/creative-campaign/operations/{job_id}")
async def list_creative_campaign_operations(job_id: str) -> dict:
    """Return durable per-submit provenance for cockpit inspection."""
    return {
        "job_id": job_id,
        "operations": await crud.list_image_generation_operations(job_id),
    }


@router.get("/fastlane-presets", response_model=ImgFastlanePresetListResponse)
async def get_img_fastlane_presets() -> ImgFastlanePresetListResponse:
    return list_img_fastlane_presets()


@router.post("/fastlane-preview", response_model=ImgFastlanePromptPreviewResponse)
async def post_img_fastlane_preview(
    request: ImgFastlanePromptPreviewRequest,
) -> ImgFastlanePromptPreviewResponse:
    try:
        return await compile_img_fastlane_prompt_preview(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/save", response_model=CreativeAssetRecord)
async def post_img_factory_save(request: SaveImgOutputRequest) -> CreativeAssetRecord:
    try:
        return await save_img_output_to_library(request)
    except ValueError as exc:
        message = str(exc)
        if message.endswith("NOT_FOUND"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.post("/f2v-frame-sources", response_model=F2VFrameSourceResolverResponse)
async def post_img_factory_f2v_frame_sources(
    request: F2VFrameSourceResolverRequest,
) -> F2VFrameSourceResolverResponse:
    return await resolve_f2v_frame_sources(request)
