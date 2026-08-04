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
from agent.services import product_strategy_taxonomy_service as _strategy_taxonomy


import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/product-registration", tags=["product-registration"])


async def _sync_queue_row_after_edit(draft) -> None:
    """After an operator edits a draft, re-sync the linked FastMoss queue row's list
    status FROM THE SAVED DRAFT so the queue UI reflects the edit immediately (a
    filled field clears its MISSING warning; the edit is not clobbered by a HUB
    rebuild). Best-effort — never fail the save on a display-sync error."""
    if not draft:
        return
    try:
        from agent.services.fastmoss_bulk_promotion_service import (
            sync_queue_row_from_draft,
        )

        await sync_queue_row_from_draft(draft)
    except Exception:  # noqa: BLE001 — display sync must not break the save
        logger.warning("queue-row sync after draft edit failed", exc_info=True)


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
    taxonomy = draft.strategy_taxonomy
    if taxonomy and taxonomy.authority_source == "MANUAL_OVERRIDE":
        if not (taxonomy.reviewer_id or "").strip() or not (
            taxonomy.reviewer_note or ""
        ).strip():
            raise HTTPException(
                status_code=409,
                detail="TAXONOMY_REVIEWER_EVIDENCE_REQUIRED",
            )
        try:
            await _strategy_taxonomy.validate_product_strategy_assignment(
                cluster=taxonomy.cluster,
                product_type_group=taxonomy.product_type_group,
                matched_scene_strategy_id=taxonomy.matched_scene_strategy_id,
                scene_coverage_status=taxonomy.scene_coverage_status,
                review_status=taxonomy.review_status,
            )
        except _strategy_taxonomy.ProductStrategyTaxonomyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    await _sync_queue_row_after_edit(draft)
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
    await _sync_queue_row_after_edit(draft)
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
