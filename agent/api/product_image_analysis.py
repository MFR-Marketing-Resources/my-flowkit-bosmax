from __future__ import annotations

from fastapi import APIRouter

from agent.models.product_intelligence import ProductImageAnalysisResolveRequest
from agent.services.product_image_analysis_service import (
    get_product_image_analysis_by_id,
    resolve_product_image_analysis_request,
)


router = APIRouter(prefix="/product-image-analysis", tags=["product-image-analysis"])


@router.get("/{product_id}")
async def product_image_analysis_detail(product_id: str) -> dict:
    return await get_product_image_analysis_by_id(product_id)


@router.post("/resolve")
async def product_image_analysis_resolve(
    request: ProductImageAnalysisResolveRequest,
) -> dict:
    return await resolve_product_image_analysis_request(request)
