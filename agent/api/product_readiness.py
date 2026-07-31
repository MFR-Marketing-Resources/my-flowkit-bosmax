from fastapi import APIRouter, HTTPException

from agent.models.product_readiness import (
    ApplicabilityProfileListResponse,
    ProductReadinessEvaluateRequest,
    ProductReadinessProjection,
)
from agent.services import product_readiness_applicability_service as readiness


router = APIRouter(
    prefix="/product-readiness",
    tags=["product-readiness"],
)


def _http(exc: readiness.ProductReadinessError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@router.get("/applicability-profiles", response_model=ApplicabilityProfileListResponse)
async def list_applicability_profiles() -> ApplicabilityProfileListResponse:
    return readiness.get_applicability_profiles()


@router.post("/evaluate", response_model=ProductReadinessProjection)
async def evaluate_product_readiness(
    body: ProductReadinessEvaluateRequest,
) -> ProductReadinessProjection:
    try:
        return await readiness.evaluate_product_readiness(body)
    except readiness.ProductReadinessError as exc:
        raise _http(exc) from exc
