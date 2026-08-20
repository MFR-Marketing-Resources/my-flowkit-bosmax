"""Lapis 2 Phase 1 — bulk DRAFT copy generation router (credit-free, DRAFT-only).

Thin transport over `copy_register_bulk_service`. Every run produces DRAFT blueprints
only; it NEVER approves or activates (human batch-approval stays the sole production
path). Text-assist generation spends no Flow credits.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent.services import copy_register_bulk_service as svc

router = APIRouter(prefix="/copy-register/v2/bulk", tags=["copy-register-v2-bulk"])


class CreateBulkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(min_length=1, max_length=1000)
    label: Optional[str] = Field(default=None)
    # When true, generation starts immediately after the run is created.
    start: bool = Field(default=False)


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
