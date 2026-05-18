from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from agent.models.creative_asset import (
    CreativeAssetCreateRequest,
    CreativeAssetListResponse,
    CreativeAssetRecord,
    CreativeAssetUpdateRequest,
)
from agent.services.creative_asset_service import (
    archive_creative_asset,
    create_creative_asset,
    get_creative_asset,
    get_creative_asset_file_path,
    list_creative_assets,
    unarchive_creative_asset,
    update_creative_asset,
)


router = APIRouter(prefix="/creative-assets", tags=["creative-assets"])


@router.get("", response_model=CreativeAssetListResponse)
async def get_creative_assets(
    semantic_role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    allowed_mode: str | None = Query(default=None),
    engine_slot: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> CreativeAssetListResponse:
    items = await list_creative_assets(
        semantic_role=semantic_role,
        status=status,
        allowed_mode=allowed_mode,
        engine_slot=engine_slot,  # type: ignore[arg-type]
        product_id=product_id,
        search=search,
        limit=limit,
    )
    return CreativeAssetListResponse(items=items, total=len(items))


@router.post("", response_model=CreativeAssetRecord)
async def post_creative_asset(request: CreativeAssetCreateRequest) -> CreativeAssetRecord:
    return await create_creative_asset(request)


@router.get("/{asset_id}", response_model=CreativeAssetRecord)
async def get_creative_asset_detail(asset_id: str) -> CreativeAssetRecord:
    item = await get_creative_asset(asset_id)
    if not item:
        raise HTTPException(status_code=404, detail="CREATIVE_ASSET_NOT_FOUND")
    return item


@router.patch("/{asset_id}", response_model=CreativeAssetRecord)
async def patch_creative_asset(
    asset_id: str,
    request: CreativeAssetUpdateRequest,
) -> CreativeAssetRecord:
    try:
        return await update_creative_asset(asset_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{asset_id}/archive", response_model=CreativeAssetRecord)
async def post_archive_creative_asset(asset_id: str) -> CreativeAssetRecord:
    try:
        return await archive_creative_asset(asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{asset_id}/unarchive", response_model=CreativeAssetRecord)
async def post_unarchive_creative_asset(asset_id: str) -> CreativeAssetRecord:
    try:
        return await unarchive_creative_asset(asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{asset_id}/preview")
async def get_creative_asset_preview(asset_id: str):
    item = await get_creative_asset(asset_id)
    if not item:
        raise HTTPException(status_code=404, detail="CREATIVE_ASSET_NOT_FOUND")
    if item.local_file_path:
        file_path = await get_creative_asset_file_path(asset_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="CREATIVE_ASSET_FILE_MISSING")
        return FileResponse(file_path)
    if item.preview_url:
        raise HTTPException(status_code=409, detail="REMOTE_PREVIEW_ONLY")
    raise HTTPException(status_code=404, detail="CREATIVE_ASSET_PREVIEW_UNAVAILABLE")


@router.get("/{asset_id}/download")
async def get_creative_asset_download(asset_id: str):
    item = await get_creative_asset(asset_id)
    if not item:
        raise HTTPException(status_code=404, detail="CREATIVE_ASSET_NOT_FOUND")
    if item.local_file_path:
        file_path = await get_creative_asset_file_path(asset_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="CREATIVE_ASSET_FILE_MISSING")
        return FileResponse(file_path, filename=file_path.name)
    if item.download_url:
        raise HTTPException(status_code=409, detail="REMOTE_DOWNLOAD_ONLY")
    raise HTTPException(status_code=404, detail="CREATIVE_ASSET_DOWNLOAD_UNAVAILABLE")
