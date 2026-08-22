"""Lapis 2 bulk DRAFT, review-queue, and owner-gated activation router.

Bulk generation remains DRAFT-only. Review approval and copy-authority
activation are separate V2-controlled operations; neither calls a provider or
spends generation credits.
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from agent.services import copy_register_bulk_service as svc
from agent.services import copy_activation_candidate_view_service as candidate_views
from agent.services import copy_register_review_queue_service as review_queue

router = APIRouter(prefix="/copy-register/v2/bulk", tags=["copy-register-v2-bulk"])


class CreateBulkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(min_length=1, max_length=1000)
    label: Optional[str] = Field(default=None)
    # When true, generation starts immediately after the run is created.
    start: bool = Field(default=False)


class BatchApproveDraftsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_ids: list[str] = Field(min_length=1, max_length=500)
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    readiness_proof: dict[str, Any]
    confirmation_phrase: str = Field(min_length=1)


class BatchActivateBlueprintsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The service enforces the exact 50-item cap so over-cap requests receive
    # the stable governance error rather than silently truncating the set.
    blueprint_ids: list[str] = Field(min_length=1, max_length=review_queue.ACTIVATION_BATCH_MAX + 1)
    confirmation_phrase: str = Field(min_length=1)
    owner_authorization: StrictBool


@router.post("/runs")
async def create_bulk_run(request: CreateBulkRunRequest):
    try:
        run = await svc.create_run(request.product_ids, request.label)
        if request.start:
            run = await svc.start_run(run["run_id"])
        return run
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs/{run_id}/start")
async def start_bulk_run(run_id: str):
    try:
        return await svc.start_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_bulk_run(run_id: str):
    try:
        return await svc.cancel_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
async def get_bulk_run(run_id: str):
    try:
        return await svc.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs")
async def list_bulk_runs(limit: int = 50):
    return await svc.list_runs(limit)


@router.get("/review-queue")
async def get_review_queue(
    only_claim_safe: bool = Query(default=False),
    product_id: str | None = Query(default=None),
):
    try:
        return await review_queue.list_review_queue(
            only_claim_safe=only_claim_safe,
            product_id=product_id,
        )
    except review_queue.CopyRegisterReviewQueueError as exc:
        detail: dict[str, Any] = {"error": exc.code, "detail": str(exc)}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.post("/review-queue/approve")
async def approve_review_queue_batch(request: BatchApproveDraftsRequest):
    try:
        return await review_queue.batch_approve_drafts(
            request.blueprint_ids,
            reviewer=request.reviewer,
            rationale=request.rationale,
            readiness_proof_dict=request.readiness_proof,
            confirmation_phrase=request.confirmation_phrase,
        )
    except review_queue.CopyRegisterReviewQueueError as exc:
        detail: dict[str, Any] = {"error": exc.code, "detail": str(exc)}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.get("/activation-candidates")
async def get_activation_candidates(view: str = Query(default="all")):
    try:
        candidates = await review_queue.list_activation_candidates()
        return candidate_views.project_activation_candidate_view(candidates, view=view)
    except review_queue.CopyRegisterReviewQueueError as exc:
        detail: dict[str, Any] = {"error": exc.code, "detail": str(exc)}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.post("/activate")
async def activate_blueprint_batch(request: BatchActivateBlueprintsRequest):
    try:
        return await review_queue.batch_activate(
            request.blueprint_ids,
            confirmation_phrase=request.confirmation_phrase,
            owner_authorization=request.owner_authorization,
        )
    except review_queue.CopyRegisterReviewQueueError as exc:
        detail: dict[str, Any] = {"error": exc.code, "detail": str(exc)}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
