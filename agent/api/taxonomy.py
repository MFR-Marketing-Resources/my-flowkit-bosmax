"""Canonical copywriting taxonomy authority endpoints."""

from fastapi import APIRouter, HTTPException

from agent.models.copywriting_taxonomy import (
    CopywritingTaxonomyProductResolution,
    CopywritingTaxonomyTreeResponse,
)
from agent.services.copywriting_taxonomy_service import (
    get_copywriting_taxonomy_tree,
    resolve_product_taxonomy,
)

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("/tree", response_model=CopywritingTaxonomyTreeResponse)
async def copywriting_taxonomy_tree():
    """Return the canonical Category -> Subcategory -> Type cascade tree."""
    try:
        return await get_copywriting_taxonomy_tree()
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": str(exc)},
        ) from exc


@router.get(
    "/product/{product_id}",
    response_model=CopywritingTaxonomyProductResolution,
)
async def copywriting_taxonomy_product(product_id: str):
    """Return exact match or reconciliation evidence for an existing product."""
    resolution = await resolve_product_taxonomy(product_id)
    if resolution is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "PRODUCT_NOT_FOUND", "product_id": product_id},
        )
    return resolution
