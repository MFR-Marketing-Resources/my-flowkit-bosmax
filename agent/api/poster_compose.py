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

from agent.models.poster_campaign_qa import CampaignReviewRequest, CampaignVariantsRequest
from agent.services import poster_compositor_service as compositor
from agent.services.poster_campaign_variant_service import (
    CampaignVariantError,
    build_campaign_variants,
    render_campaign_variant,
)
from agent.services.poster_deliverable_service import (
    PosterDeliverableError,
    PosterDeliverableService,
)
from agent.services.creative_direction_service import CreativeDirectionError
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)
from agent.api.legacy_copy_guard import require_legacy_copy_maintenance
from agent.db import crud

router = APIRouter(prefix="/poster", tags=["poster-compose"])


async def _require_deliverable_product(poster_deliverable_id: str, *, lane: str) -> dict:
    row = await crud.get_poster_deliverable(poster_deliverable_id)
    if not row:
        raise HTTPException(404, "POSTER_DELIVERABLE_NOT_FOUND")
    from agent.services.product_release_service import (
        ProductOperationalVisibilityError,
        require_product_operational_visibility,
    )
    try:
        await require_product_operational_visibility(row.get("product_id"), lane=lane)
    except ProductOperationalVisibilityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
    return row


def _http(exc: Exception, code: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(exc)})


class ComposeRequest(BaseModel):
    product_id: str
    staff_id: str | None = None
    # Legacy callers may still provide an approved poster Copy Set.  V2
    # callers bind from the explicit blueprint context and do not need a
    # legacy identifier.
    poster_copy_set_id: str = ""
    recipe_id: str
    background_media_id: str = ""
    background_local_path: str = ""
    image_model: str = ""
    creative_mode: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    copy_v2_context: dict[str, Any] | None = None


class CompositionPlanPreviewRequest(BaseModel):
    product_id: str
    creative_mode: str
    recipe_id: str = ""
    poster_copy_set_id: str = ""
    human_presence_mode: str = ""
    frame_ratio: str = ""


@router.get("/compositor/probe")
async def compositor_probe():
    try:
        return await compositor.probe(force=True)
    except compositor.PosterCompositorError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.post("/composition-plan")
async def composition_plan_preview(req: CompositionPlanPreviewRequest):
    """Backend-resolved composition plan for the Poster Guided summary.

    Read-only: resolves the SAME canonical plan a compile would preserve (same
    resolver, same constraint assembly). No mutation, no generation, no credit
    spend."""
    from agent.services.product_release_service import (
        ProductReleaseError,
        ensure_product_operationally_visible,
    )

    try:
        await ensure_product_operationally_visible(req.product_id, lane="POSTER_BUILDER")
    except ProductReleaseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
    if req.poster_copy_set_id:
        require_legacy_copy_maintenance()
    try:
        return await PosterDeliverableService.preview_composition_plan(
            product_id=req.product_id,
            creative_mode=req.creative_mode,
            recipe_id=req.recipe_id,
            poster_copy_set_id=req.poster_copy_set_id,
            human_presence_mode=req.human_presence_mode,
            frame_ratio=req.frame_ratio,
        )
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)
    except CreativeDirectionError as exc:
        raise _http(exc, str(exc), 422)


@router.post("/compose")
async def compose_poster(req: ComposeRequest):
    from agent.services.product_release_service import (
        ProductReleaseError,
        ensure_product_operationally_visible,
    )

    try:
        await ensure_product_operationally_visible(req.product_id, lane="POSTER_BUILDER")
    except ProductReleaseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
    if req.poster_copy_set_id:
        require_legacy_copy_maintenance()
    try:
        from agent.services.staff_identity_service import (
            StaffIdentityError,
        )
        from agent.security.access_control import resolve_request_staff

        try:
            staff_profile = await resolve_request_staff(req.staff_id)
        except StaffIdentityError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"error": exc.code, "message": exc.message},
            ) from exc
        resolution = await resolve_persisted_copy_execution_binding(
            req.product_id,
            "POSTER_BUILDER",
            req.copy_v2_context,
        )
        result = await PosterDeliverableService.compose_poster(
            product_id=req.product_id,
            poster_copy_set_id=req.poster_copy_set_id,
            recipe_id=req.recipe_id,
            background_media_id=req.background_media_id,
            background_local_path=req.background_local_path,
            image_model=req.image_model,
            creative_mode=req.creative_mode,
            settings=req.settings,
            staff_id=staff_profile["staff_id"],
            staff_display_name_snapshot=staff_profile["display_name"],
            copy_v2_projection=(
                {
                    **resolution.projection.model_dump(mode="json"),
                    "metadata": resolution.to_metadata(
                        consumer_context=req.copy_v2_context
                    ),
                }
                if resolution.v2_enabled and resolution.projection is not None
                else None
            ),
        )
        if resolution.v2_enabled:
            result["copy_architecture_v2"] = resolution.to_metadata(
                consumer_context=req.copy_v2_context
            )
            if resolution.binding is not None:
                result["copy_execution_binding"] = resolution.binding.model_dump(mode="json")
            deliverable = dict(result.get("deliverable") or {})
            deliverable.pop("poster_copy_set_id", None)
            result["deliverable"] = deliverable
        return result
    except CopyExecutionResolutionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.details or str(exc)},
        ) from exc
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)
    except CreativeDirectionError as exc:
        raise _http(exc, str(exc), 422)


@router.get("/deliverables")
async def list_deliverables(product_id: str, limit: int = 50):
    return {
        "deliverables": await PosterDeliverableService.list_for_product(product_id, limit)
    }


@router.get("/deliverables/by-asset/{creative_asset_id}")
async def get_deliverable_by_asset(creative_asset_id: str):
    """Creative Library round trip: reopen a saved poster from its asset id."""
    try:
        return await PosterDeliverableService.get_by_creative_asset(creative_asset_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.get("/deliverables/{poster_deliverable_id}")
async def get_deliverable(poster_deliverable_id: str):
    try:
        return await PosterDeliverableService.get_with_manifest(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.get("/deliverables/{poster_deliverable_id}/output")
async def get_deliverable_output(poster_deliverable_id: str):
    # Serve the ORIGINAL saved bytes from the most durable source (deliverable
    # file → Creative Library asset), sha-verified. Never regenerates.
    try:
        durable = await PosterDeliverableService.get_output_file(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)
    return FileResponse(
        durable["path"],
        media_type="image/png",
        filename=f"poster_{poster_deliverable_id}.png",
        headers={"X-Poster-Output-Source": durable["source"]},
    )


@router.post("/deliverables/{poster_deliverable_id}/save-to-library")
async def save_deliverable_to_library(poster_deliverable_id: str):
    try:
        return await PosterDeliverableService.save_to_library(poster_deliverable_id)
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.post("/deliverables/{poster_deliverable_id}/review")
async def review_campaign_deliverable(
    poster_deliverable_id: str,
    req: CampaignReviewRequest,
):
    try:
        return await PosterDeliverableService.review_campaign_deliverable(
            poster_deliverable_id, req
        )
    except PosterDeliverableError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.post("/deliverables/{poster_deliverable_id}/variants")
async def campaign_variants(
    poster_deliverable_id: str,
    req: CampaignVariantsRequest = CampaignVariantsRequest(),
):
    require_legacy_copy_maintenance()
    await _require_deliverable_product(
        poster_deliverable_id, lane="POSTER_CAMPAIGN_VARIANTS"
    )
    try:
        return await build_campaign_variants(poster_deliverable_id, req)
    except CampaignVariantError as exc:
        raise _http(exc, exc.code, exc.status_code)


@router.get("/deliverables/{poster_deliverable_id}/variants/{variant_id}/output")
async def campaign_variant_output(poster_deliverable_id: str, variant_id: str):
    require_legacy_copy_maintenance()
    await _require_deliverable_product(
        poster_deliverable_id, lane="POSTER_CAMPAIGN_VARIANT_OUTPUT"
    )
    try:
        out_path, selected = await render_campaign_variant(
            poster_deliverable_id, variant_id
        )
    except CampaignVariantError as exc:
        raise _http(exc, exc.code, exc.status_code)
    return FileResponse(
        out_path,
        media_type="image/png",
        filename=f"poster_{poster_deliverable_id}_{selected.variant_id}.png",
        headers={
            "X-Poster-Variant-Sha256": selected.manifest_sha256,
            "X-Poster-Provider-Operations": "0",
        },
    )
