"""Copywriting readiness API — the shared contract for generation-surface gates.

Read-only; no token spend. Composes product-intelligence snapshot + copy
grounding + copy sets + formula into one payload.
"""
from fastapi import APIRouter, HTTPException

from agent.models.lip_color_copy_strategy import (
    LipColorCopyStrategyResponse,
    LipColorDurationSeconds,
)
from agent.models.rempah_copy_strategy import (
    RempahCopyStrategyResponse,
    RempahDurationSeconds,
)
from agent.services.copy_set_service import CopySetError
from agent.services.copywriting_readiness_service import get_copywriting_readiness
from agent.services.fastmoss_product_reference_service import (
    is_fastmoss_reference_product_id,
)
from agent.services.lip_color_copy_strategy_service import (
    LipColorCopyStrategyError,
    build_lip_color_copy_strategy,
)
from agent.services.rempah_copy_strategy_service import (
    RempahCopyStrategyError,
    build_rempah_copy_strategy,
)

router = APIRouter(prefix="/copywriting", tags=["copywriting"])


@router.get(
    "/p3a/lip-color/{product_id}",
    response_model=LipColorCopyStrategyResponse,
)
async def p3a_lip_color_copy_strategy(
    product_id: str,
    duration_seconds: LipColorDurationSeconds = LipColorDurationSeconds.SECONDS_8,
):
    """Preview direct-BM P3A copy without provider calls or persistence."""
    try:
        return await build_lip_color_copy_strategy(product_id, duration_seconds)
    except LipColorCopyStrategyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.code,
                "product_id": exc.product_id,
                "blocked_reasons": exc.blocked_reasons,
            },
        ) from exc


@router.get(
    "/p3b/rempah/{product_id}",
    response_model=RempahCopyStrategyResponse,
)
async def p3b_rempah_copy_strategy(
    product_id: str,
    duration_seconds: RempahDurationSeconds = RempahDurationSeconds.SECONDS_8,
):
    """Preview Direct BM P3B rempah copy without provider calls or persistence."""
    try:
        return await build_rempah_copy_strategy(product_id, duration_seconds)
    except RempahCopyStrategyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.code,
                "product_id": exc.product_id,
                "blocked_reasons": exc.blocked_reasons,
            },
        ) from exc


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
