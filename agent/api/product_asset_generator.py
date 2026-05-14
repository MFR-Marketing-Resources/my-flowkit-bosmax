from fastapi import APIRouter

from agent.models.product_asset_generator import (
    ProductAssetGeneratorRequest,
    ProductAssetGeneratorResponse,
)
from agent.services.product_asset_generator_service import (
    generate_product_asset_preview,
)


router = APIRouter(prefix="/product-asset-generator", tags=["product-asset-generator"])


@router.post("/preview", response_model=ProductAssetGeneratorResponse)
async def product_asset_generator_preview(
    request: ProductAssetGeneratorRequest,
) -> ProductAssetGeneratorResponse:
    return await generate_product_asset_preview(request)
