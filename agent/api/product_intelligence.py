from __future__ import annotations

from fastapi import APIRouter

from agent.models.product_intelligence import ProductIntelligenceResolveRequest
from agent.services.product_intelligence_service import (
    get_product_intelligence_backfill_preview,
    get_product_intelligence_by_id,
    get_product_intelligence_summary,
    resolve_product_intelligence_request,
)
from agent.services.all_product_mapping_audit_service import (
    get_all_product_mapping_audit,
)


router = APIRouter(prefix="/product-intelligence", tags=["product-intelligence"])


@router.get("/summary")
async def product_intelligence_summary() -> dict:
    return await get_product_intelligence_summary()


@router.post("/backfill-preview")
async def product_intelligence_backfill_preview() -> dict:
    return await get_product_intelligence_backfill_preview()


@router.get("/mapping-audit")
async def product_intelligence_mapping_audit(sample_limit: int = 20) -> dict:
    return await get_all_product_mapping_audit(sample_limit=sample_limit)


@router.post("/resolve")
async def product_intelligence_resolve(
    request: ProductIntelligenceResolveRequest,
) -> dict:
    return await resolve_product_intelligence_request(request)


@router.get("/{product_id}")
async def product_intelligence_detail(product_id: str) -> dict:
    return await get_product_intelligence_by_id(product_id)
