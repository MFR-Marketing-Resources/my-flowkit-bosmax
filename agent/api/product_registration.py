from fastapi import APIRouter

from agent.models.product_registration import (
    ProductRegistrationEvaluateRequest,
    ProductRegistrationEvaluateResponse,
)
from agent.services.product_registration_service import (
    evaluate_product_registration,
)


router = APIRouter(prefix="/product-registration", tags=["product-registration"])


@router.post("/evaluate", response_model=ProductRegistrationEvaluateResponse)
async def product_registration_evaluate(
    request: ProductRegistrationEvaluateRequest,
) -> ProductRegistrationEvaluateResponse:
    return await evaluate_product_registration(request)
