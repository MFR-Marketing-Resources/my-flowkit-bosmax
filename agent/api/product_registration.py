from fastapi import APIRouter, HTTPException
from typing import List

from agent.models.product_registration import (
    ProductRegistrationEvaluateRequest,
    ProductRegistrationEvaluateResponse,
    RegistrationReviewDraft,
    RegistrationReviewDraftFieldDecisions,
    RegistrationCommitRequest
)
from agent.models.product_knowledge import ProductKnowledgeCompleteResponse
from agent.services.product_registration_service import (
    evaluate_product_registration,
    create_registration_review_draft,
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
from agent.services.registration_commit_service import RegistrationCommitService


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


@router.get("/review-drafts", response_model=List[RegistrationReviewDraft])
async def list_review_drafts() -> List[RegistrationReviewDraft]:
    return RegistrationDraftStorageService.list_drafts()


@router.post("/review-drafts", response_model=RegistrationReviewDraft)
async def save_review_draft(draft: RegistrationReviewDraft) -> RegistrationReviewDraft:
    return RegistrationDraftStorageService.save_draft(draft)


@router.get("/review-drafts/{draft_id}", response_model=RegistrationReviewDraft)
async def get_review_draft(draft_id: str) -> RegistrationReviewDraft:
    draft = RegistrationDraftStorageService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.patch("/review-drafts/{draft_id}/field-decisions", response_model=RegistrationReviewDraft)
async def update_draft_field_decisions(
    draft_id: str, 
    decisions: RegistrationReviewDraftFieldDecisions
) -> RegistrationReviewDraft:
    draft = RegistrationDraftStorageService.update_field_decisions(draft_id, decisions)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.post("/review-drafts/{draft_id}/commit")
async def commit_review_draft(draft_id: str, request: RegistrationCommitRequest):
    if draft_id != request.draft_id:
        raise HTTPException(status_code=400, detail="Draft ID mismatch")
    return await RegistrationCommitService.commit_draft(request)
