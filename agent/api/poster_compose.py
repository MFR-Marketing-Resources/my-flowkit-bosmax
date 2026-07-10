"""Poster compose + deliverable API (POSTER_BUILDER_V2).

Deterministic compositor endpoints: compose a poster from an approved/draft
poster copy set + a clean generated scene, preview the exact bytes, save the
SAME bytes to the Creative Library, and reconstruct saved posters.

Credit-free by construction — composing never calls a generation lane.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.services import poster_compositor_service as compositor
from agent.services.poster_deliverable_service import (
    PosterDeliverableError,
    PosterDeliverableService,
)

router = APIRouter(prefix="/poster", tags=["poster-compose"])


def _http(exc: Exception, code: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(exc)})


class ComposeRequest(BaseModel):
    product_id: str
    poster_copy_set_id: str
    recipe_id: str
    background_media_id: str = ""
    background_local_path: str = ""
    image_model: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


@router.get("/compositor/probe")
async def compositor_probe():
    try:
        return await compositor.probe(force=True)
    except compositor.PosterCompositorError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.post("/compose")
async def compose_poster(req: ComposeRequest):
    try:
        return await PosterDeliverableService.compose_poster(
            product_id=req.product_id,
            poster_copy_set_id=req.poster_copy_set_id,
            recipe_id=req.recipe_id,
            background_media_id=req.background_media_id,
            background_local_path=req.background_local_path,
            image_model=req.image_model,
            settings=req.settings,
        )
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.get("/deliverables")
async def list_deliverables(product_id: str, limit: int = 50):
    return {
        "deliverables": await PosterDeliverableService.list_for_product(product_id, limit)
    }


@router.get("/deliverables/{poster_deliverable_id}")
async def get_deliverable(poster_deliverable_id: str):
    try:
        return await PosterDeliverableService.get_with_manifest(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.get("/deliverables/{poster_deliverable_id}/output")
async def get_deliverable_output(poster_deliverable_id: str):
    try:
        info = await PosterDeliverableService.get_with_manifest(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)
    if not info["output_available"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "POSTER_OUTPUT_FILE_MISSING", "message": "output purged or not composed"},
        )
    return FileResponse(
        info["deliverable"]["output_path"],
        media_type="image/png",
        filename=f"poster_{poster_deliverable_id}.png",
    )


@router.post("/deliverables/{poster_deliverable_id}/save-to-library")
async def save_deliverable_to_library(poster_deliverable_id: str):
    try:
        return await PosterDeliverableService.save_to_library(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)
