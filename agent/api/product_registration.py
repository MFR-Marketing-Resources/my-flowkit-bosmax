from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import List

from agent.models.product_registration import (
    ProductRegistrationEvaluateRequest,
    ProductRegistrationEvaluateResponse,
    RegistrationReviewDraft,
    RegistrationReviewDraftFieldDecisions,
    RegistrationCommitRequest,
    RegistrationReviewDraftEvidencePatchRequest,
)
from agent.models.product_knowledge import ProductKnowledgeCompleteResponse
from agent.services.product_registration_service import (
    evaluate_product_registration,
    create_registration_review_draft,
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
from agent.services.registration_commit_service import RegistrationCommitService
from agent.services.registration_draft_evidence_editor_service import (
    patch_registration_draft_evidence,
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


@router.patch("/review-drafts/{draft_id}/evidence", response_model=RegistrationReviewDraft)
async def update_draft_evidence(
    draft_id: str,
    request: RegistrationReviewDraftEvidencePatchRequest,
) -> RegistrationReviewDraft:
    try:
        draft = patch_registration_draft_evidence(draft_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/review-drafts/{draft_id}/image")
async def get_review_draft_image(draft_id: str):
    draft = RegistrationDraftStorageService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    local_image_path = str(draft.declared_evidence_fields.get("local_image_path") or "").strip()
    if not local_image_path:
        raise HTTPException(status_code=404, detail="Draft image not found")
    image_path = Path(local_image_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Draft image path missing on disk")
    return FileResponse(image_path)


@router.delete("/review-drafts/{draft_id}", status_code=204)
async def delete_review_draft(draft_id: str) -> None:
    deleted = RegistrationDraftStorageService.delete_draft(draft_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")


@router.post("/review-drafts/{draft_id}/commit")
async def commit_review_draft(draft_id: str, request: RegistrationCommitRequest):
    if draft_id != request.draft_id:
        raise HTTPException(status_code=400, detail="Draft ID mismatch")
    return await RegistrationCommitService.commit_draft(request)
