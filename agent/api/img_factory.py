"""IMG Asset Factory v1 — API surface.

Endpoints:
  - GET  /img-factory/lanes            list lane recipes (governance authority)
  - POST /img-factory/save             save an approved REAL IMG output -> Library
  - GET  /img-factory/provider-status  honest IMG generation runtime boundary
  - POST /img-factory/f2v-frame-sources resolve F2V start/end frame selections
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
    SaveImgOutputRequest,
)
from agent.services.f2v_frame_source_resolver_service import resolve_f2v_frame_sources
from agent.services.img_asset_factory_service import (
    compile_img_fastlane_prompt_preview,
    get_img_provider_status,
    list_img_fastlane_presets,
    list_img_lane_summaries,
    save_img_output_to_library,
)


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
    UI still lists it, but generation fails closed until the id is set."""
    from agent.config import IMAGE_MODELS

    labels = {
        "NANO_BANANA_PRO": "Nano Banana Pro",
        "NANO_BANANA_2": "Nano Banana 2",
        "NANO_BANANA_2_LITE": "Nano Banana 2 Lite",
    }
    models = [
        {
            "key": key,
            "label": labels.get(key, key.replace("_", " ").title()),
            "pending": (not str(internal).strip()) or "PENDING" in str(internal).upper(),
        }
        for key, internal in IMAGE_MODELS.items()
    ]
    return {
        "models": models,
        "default_model": "Nano Banana 2",
        "aspect_options": ["9:16", "1:1", "16:9", "4:3", "3:4"],
        "default_aspect": "9:16",
        "count_options": [1, 2, 3, 4],
        "default_count": 1,
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
