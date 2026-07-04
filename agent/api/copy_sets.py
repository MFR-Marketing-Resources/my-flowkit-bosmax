"""Copy Set API — Copy Strategy Studio Phase 1.

Backend foundation for the approved Copy Set workflow:

    POST   /api/copy-sets/generate
    GET    /api/copy-sets/product/{product_id}
    GET    /api/copy-sets/{copy_set_id}
    PATCH  /api/copy-sets/{copy_set_id}
    POST   /api/copy-sets/{copy_set_id}/approve
    POST   /api/copy-sets/{copy_set_id}/reject
    POST   /api/copy-sets/{copy_set_id}/regenerate

No Google Flow execution, no credit spend, no compiler mutation — this router
only creates/reviews/approves Copy Sets. Errors fail closed with operator-readable
codes.
"""
from fastapi import APIRouter, HTTPException

from agent.models.copy_set import (
    APPROVAL_PHRASE,
    AICopyAssistRequest,
    CopySetApproveRequest,
    CopySetGenerateRequest,
    CopySetPatchRequest,
    CopySetRegenerateRequest,
    CopySetRejectRequest,
)
from agent.services import ai_copy_assist_service as ai_svc
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_set_service as svc

router = APIRouter(prefix="/copy-sets", tags=["copy-sets"])


def _raise(error: svc.CopySetError):
    raise HTTPException(status_code=error.status_code, detail={"error": error.code, "detail": error.detail})


@router.post("/generate")
async def generate_copy_set(request: CopySetGenerateRequest):
    try:
        return await svc.generate_copy_set(request)
    except svc.CopySetError as error:
        _raise(error)


@router.post("/ai-assist")
async def ai_assist_copy_candidate(request: AICopyAssistRequest):
    """AI Copy Assist — generate reviewable candidate Copy Set(s). Candidates are
    saved COPY_REVIEW_REQUIRED (never approved, never bound). Fails closed when the
    provider is not configured or returns an invalid response."""
    try:
        return await ai_svc.generate_ai_copy_candidate(request)
    except ai_provider.AICopyProviderNotConfigured as error:
        raise HTTPException(
            status_code=409, detail={"error": error.code}
        ) from error
    except ai_provider.AICopyProviderError as error:
        raise HTTPException(
            status_code=502, detail={"error": error.code, "detail": error.detail}
        ) from error
    except svc.CopySetError as error:
        _raise(error)


@router.get("/product/{product_id}")
async def list_copy_sets_for_product(product_id: str):
    return {"product_id": product_id, "items": await svc.list_copy_sets(product_id)}


@router.get("/{copy_set_id}")
async def get_copy_set(copy_set_id: str):
    result = await svc.get_copy_set(copy_set_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "COPY_SET_NOT_FOUND"})
    return result


@router.patch("/{copy_set_id}")
async def patch_copy_set(copy_set_id: str, request: CopySetPatchRequest):
    try:
        return await svc.patch_copy_set(copy_set_id, request)
    except svc.CopySetError as error:
        _raise(error)


@router.post("/{copy_set_id}/approve")
async def approve_copy_set(copy_set_id: str, request: CopySetApproveRequest):
    try:
        return await svc.approve_copy_set(copy_set_id, request)
    except svc.CopySetPermissionError as error:
        raise HTTPException(
            status_code=400,
            detail={"error": error.code, "approval_phrase": APPROVAL_PHRASE},
        )
    except svc.CopySetError as error:
        _raise(error)


@router.post("/{copy_set_id}/reject")
async def reject_copy_set(copy_set_id: str, request: CopySetRejectRequest):
    try:
        return await svc.reject_copy_set(copy_set_id, request)
    except svc.CopySetError as error:
        _raise(error)


@router.post("/{copy_set_id}/regenerate")
async def regenerate_copy_set(copy_set_id: str, request: CopySetRegenerateRequest | None = None):
    overrides = request.model_dump(exclude_none=True) if request else None
    try:
        return await svc.regenerate_copy_set(copy_set_id, overrides or None)
    except svc.CopySetError as error:
        _raise(error)
