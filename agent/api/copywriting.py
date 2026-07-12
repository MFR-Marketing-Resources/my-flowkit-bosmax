"""Copywriting readiness API — the shared contract for generation-surface gates.

Read-only; no token spend. Composes product-intelligence snapshot + copy
grounding + copy sets + formula into one payload.
"""
from fastapi import APIRouter, HTTPException

from agent.services.copy_set_service import CopySetError
from agent.services.copywriting_readiness_service import get_copywriting_readiness
from agent.services.fastmoss_product_reference_service import (
    is_fastmoss_reference_product_id,
)

router = APIRouter(prefix="/copywriting", tags=["copywriting"])


@router.get("/readiness/{product_id}")
async def copywriting_readiness(product_id: str):
    """Shared copywriting readiness for a product. Drives the generation-surface
    readiness card + 'Prepare Product for Copywriting' CTA + copy-bind gate."""
    if is_fastmoss_reference_product_id(product_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "REFERENCE_ONLY_PRODUCT",
                "detail": {
                    "product_id": product_id,
                    "conversion_instruction": (
                        "Convert/Register this FastMoss reference before requesting "
                        "copywriting readiness."
                    ),
                },
            },
        )
    try:
        return await get_copywriting_readiness(product_id)
    except CopySetError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.detail},
        ) from exc
