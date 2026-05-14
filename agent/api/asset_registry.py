from fastapi import APIRouter, HTTPException, Query

from agent.models.asset_registry import (
    AssetCatalogResponse,
    AssetCompatibilityRequest,
    AssetCompatibilityResponse,
    AssetDetailResponse,
    AssetOptionsResponse,
    AssetSelectionRequest,
    AssetSelectionResponse,
)
from agent.services.asset_registry_service import (
    compatibility_check,
    get_asset_by_id,
    get_asset_catalog,
    list_assets_by_type,
    resolve_asset_selection,
)


router = APIRouter(prefix="/asset-registry", tags=["asset-registry"])


@router.get("/catalog", response_model=AssetCatalogResponse)
async def asset_registry_catalog() -> AssetCatalogResponse:
    return await get_asset_catalog()


@router.get("/assets", response_model=AssetOptionsResponse)
async def asset_registry_assets(asset_type: str = Query(...)) -> AssetOptionsResponse:
    return await list_assets_by_type(asset_type)


@router.get("/assets/{asset_id}", response_model=AssetDetailResponse)
async def asset_registry_asset_detail(asset_id: str) -> AssetDetailResponse:
    detail = await get_asset_by_id(asset_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")
    return detail


@router.post("/resolve-selection", response_model=AssetSelectionResponse)
async def asset_registry_resolve_selection(request: AssetSelectionRequest) -> AssetSelectionResponse:
    return await resolve_asset_selection(request)


@router.post("/compatibility-check", response_model=AssetCompatibilityResponse)
async def asset_registry_compatibility_check(request: AssetCompatibilityRequest) -> AssetCompatibilityResponse:
    return await compatibility_check(request)
