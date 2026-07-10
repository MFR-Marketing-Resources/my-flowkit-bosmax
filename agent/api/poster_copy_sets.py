"""Poster Copy Set + AI Poster Copy Assistant API (POSTER_BUILDER_V2).

Poster-NATIVE copy domain endpoints — fully separate from the video
/api/copy-sets namespace. Nothing here reads or writes the video copy_set table.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.models.poster_copy_set import (
    PosterCopySetApproveRequest,
    PosterCopySetCreateRequest,
    PosterCopySetPatchRequest,
    PosterCopySetRejectRequest,
)
from agent.services import poster_copy_ai_service as ai_svc
from agent.services.poster_copy_set_service import (
    PosterCopySetError,
    PosterCopySetService,
)

router = APIRouter(prefix="/poster/copy-sets", tags=["poster-copy-sets"])


def _http(exc: PosterCopySetError | ai_svc.PosterCopyAIError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    field_errors = getattr(exc, "field_errors", None)
    if field_errors:
        detail["field_errors"] = field_errors
    return HTTPException(status_code=exc.status_code, detail=detail)


class RecommendObjectivesRequest(BaseModel):
    product_id: str
    refresh_ai: bool = False


class RecommendAnglesRequest(BaseModel):
    product_id: str
    archetype: str
    refresh_ai: bool = False


class GenerateDirectionsRequest(BaseModel):
    product_id: str
    archetype: str
    angle: str
    tone: str = ""
    language: str = "ms"
    count: int = Field(default=3, ge=1, le=5)


class RegenerateFieldRequest(BaseModel):
    product_id: str
    archetype: str
    angle: str
    field: str
    language: str = "ms"
    fields: dict[str, Any] = Field(default_factory=dict)


@router.post("/recommend-objectives")
async def recommend_objectives(req: RecommendObjectivesRequest):
    try:
        return await ai_svc.recommend_objectives(req.product_id, refresh_ai=req.refresh_ai)
    except ai_svc.PosterCopyAIError as exc:
        raise _http(exc)


@router.post("/recommend-angles")
async def recommend_angles(req: RecommendAnglesRequest):
    try:
        return await ai_svc.recommend_angles(
            req.product_id, req.archetype, refresh_ai=req.refresh_ai
        )
    except ai_svc.PosterCopyAIError as exc:
        raise _http(exc)


@router.post("/directions")
async def generate_directions(req: GenerateDirectionsRequest):
    try:
        return await ai_svc.generate_directions(
            req.product_id,
            req.archetype,
            req.angle,
            tone=req.tone,
            language=req.language,
            count=req.count,
        )
    except ai_svc.PosterCopyAIError as exc:
        raise _http(exc)


@router.post("/regenerate-field")
async def regenerate_field(req: RegenerateFieldRequest):
    try:
        return await ai_svc.regenerate_field(
            req.product_id,
            req.archetype,
            req.angle,
            req.fields,
            req.field,
            language=req.language,
        )
    except ai_svc.PosterCopyAIError as exc:
        raise _http(exc)


@router.post("")
async def create_poster_copy_set(req: PosterCopySetCreateRequest):
    try:
        return await PosterCopySetService.create_draft(req)
    except PosterCopySetError as exc:
        raise _http(exc)


@router.get("")
async def list_poster_copy_sets(product_id: str):
    return {"poster_copy_sets": await PosterCopySetService.list_for_product(product_id)}


@router.get("/{poster_copy_set_id}")
async def get_poster_copy_set(poster_copy_set_id: str):
    try:
        return await PosterCopySetService.get(poster_copy_set_id)
    except PosterCopySetError as exc:
        raise _http(exc)


@router.patch("/{poster_copy_set_id}")
async def patch_poster_copy_set(
    poster_copy_set_id: str, req: PosterCopySetPatchRequest
):
    try:
        return await PosterCopySetService.patch_draft(poster_copy_set_id, req)
    except PosterCopySetError as exc:
        raise _http(exc)


@router.post("/{poster_copy_set_id}/new-version")
async def new_poster_copy_set_version(
    poster_copy_set_id: str, req: PosterCopySetPatchRequest
):
    """Safe edit flow for APPROVED sets: atomic child DRAFT + parent SUPERSEDED."""
    try:
        return await PosterCopySetService.new_version(poster_copy_set_id, req)
    except PosterCopySetError as exc:
        raise _http(exc)


@router.post("/{poster_copy_set_id}/fork-historical")
async def fork_poster_copy_set_from_historical(
    poster_copy_set_id: str, req: PosterCopySetPatchRequest
):
    """Reopen a saved poster whose copy set is now SUPERSEDED: clone the exact
    historical copy into a fresh DRAFT without mutating the historical record."""
    try:
        return await PosterCopySetService.fork_from_historical(poster_copy_set_id, req)
    except PosterCopySetError as exc:
        raise _http(exc)


@router.post("/{poster_copy_set_id}/approve")
async def approve_poster_copy_set(
    poster_copy_set_id: str, req: PosterCopySetApproveRequest
):
    try:
        return await PosterCopySetService.approve(
            poster_copy_set_id,
            approval_phrase=req.approval_phrase,
            approved_by=req.approved_by,
        )
    except PosterCopySetError as exc:
        raise _http(exc)


@router.post("/{poster_copy_set_id}/reject")
async def reject_poster_copy_set(
    poster_copy_set_id: str, req: PosterCopySetRejectRequest
):
    try:
        return await PosterCopySetService.reject(poster_copy_set_id, reason=req.reason)
    except PosterCopySetError as exc:
        raise _http(exc)
