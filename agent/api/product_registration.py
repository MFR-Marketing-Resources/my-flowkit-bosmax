from fastapi import APIRouter

from agent.models.product_registration import (
    ProductRegistrationEvaluateRequest,
    ProductRegistrationEvaluateResponse,
    RegistrationReviewDraft,
)
from agent.models.product_knowledge import ProductKnowledgeCompleteResponse
from agent.services.product_registration_service import (
    evaluate_product_registration,
    create_registration_review_draft,
)


router = APIRouter(prefix="/product-registration", tags=["product-registration"])


@router.post("/evaluate", response_model=ProductRegistrationEvaluateResponse)
async def product_registration_evaluate(
    request: ProductRegistrationEvaluateRequest,
) -> ProductRegistrationEvaluateResponse:
    return await evaluate_product_registration(request)


@router.post("/review-draft", response_model=RegistrationReviewDraft)
async def product_registration_review_draft(
    completion: ProductKnowledgeCompleteResponse,
) -> RegistrationReviewDraft:
    return create_registration_review_draft(completion)
