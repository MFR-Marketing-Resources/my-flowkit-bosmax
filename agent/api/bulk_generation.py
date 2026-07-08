"""Bulk generation orchestrator API (Google Flow V1)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import bulk_generation_service as svc

router = APIRouter(prefix="/bulk-generation", tags=["bulk-generation"])


class AvatarImageBulkRequest(BaseModel):
    avatar_codes: list[str] = Field(..., min_length=1)
    aspect: str = "9:16"
    count: int = 1
    image_model: str | None = None
    max_parallel_images: int = 2
    skip_already_generated: bool = True
    allow_regenerate: bool = False
    interval_min_seconds: int = 5
    interval_max_seconds: int = 15
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 60
    confirm_credit_burn: bool = False


class VideoBulkRequest(BaseModel):
    package_ids: list[str] = Field(..., min_length=1)
    model: str | None = None
    aspect: str = "9:16"
    duration_s: int | None = None
    interval_min_seconds: int = 5
    interval_max_seconds: int = 15
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 60
    confirm_credit_burn: bool = False


class StartBulkRequest(BaseModel):
    confirm_credit_burn: bool = False
    dry_run: bool = False


@router.post("/avatar-images")
async def create_avatar_image_bulk(body: AvatarImageBulkRequest):
    try:
        return await svc.create_avatar_image_bulk_run(
            body.avatar_codes,
            aspect=body.aspect,
            count=body.count,
            image_model=body.image_model,
            max_parallel_images=body.max_parallel_images,
            skip_already_generated=body.skip_already_generated,
            allow_regenerate=body.allow_regenerate,
            interval_min_seconds=body.interval_min_seconds,
            interval_max_seconds=body.interval_max_seconds,
            cooldown_after_n_jobs=body.cooldown_after_n_jobs,
            cooldown_seconds=body.cooldown_seconds,
            confirm_credit_burn=body.confirm_credit_burn,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/videos")
async def create_video_bulk(body: VideoBulkRequest):
    try:
        return await svc.create_video_bulk_run(
            body.package_ids,
            model=body.model,
            aspect=body.aspect,
            duration_s=body.duration_s,
            interval_min_seconds=body.interval_min_seconds,
            interval_max_seconds=body.interval_max_seconds,
            cooldown_after_n_jobs=body.cooldown_after_n_jobs,
            cooldown_seconds=body.cooldown_seconds,
            confirm_credit_burn=body.confirm_credit_burn,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{bulk_run_id}/start")
async def start_bulk(bulk_run_id: str, body: StartBulkRequest):
    try:
        return await svc.start_bulk_run(
            bulk_run_id,
            confirm_credit_burn=body.confirm_credit_burn,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{bulk_run_id}")
async def get_bulk(bulk_run_id: str):
    detail = await svc.get_bulk_run_detail(bulk_run_id)
    if not detail:
        raise HTTPException(404, "BULK_RUN_NOT_FOUND")
    return detail


@router.post("/{bulk_run_id}/pause")
async def pause_bulk(bulk_run_id: str):
    try:
        return await svc.pause_bulk_run(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{bulk_run_id}/cancel")
async def cancel_bulk(bulk_run_id: str):
    try:
        return await svc.cancel_bulk_run(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{bulk_run_id}/register-avatar-assets")
async def register_avatar_assets(bulk_run_id: str):
    try:
        return await svc.register_avatar_assets_bulk(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/runs")
async def list_bulks(limit: int = 20):
    from agent.db import crud
    runs = await crud.list_bulk_generation_runs(limit=limit)
    return {"runs": runs, "count": len(runs)}