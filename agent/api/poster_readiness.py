from fastapi import APIRouter, HTTPException

from agent.services.poster_readiness_service import PosterReadinessService

router = APIRouter(tags=["poster-readiness"])


@router.get("/products/{product_id}/poster-readiness")
async def get_product_poster_readiness(product_id: str):
    """Read-only poster readiness gate + repair actions for a single product."""
    result = await PosterReadinessService.evaluate_product_id(product_id)
    if result is None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    return result.model_dump(mode="json")