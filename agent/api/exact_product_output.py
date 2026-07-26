"""Exact product final-output API.

Fail-closed compose path for products with exact_product_composite_required.
Raw Google Flow plates stay internal; only the deterministic composite is
returned as a final media artifact.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent.services.exact_product_compositor_service import ExactProductCompositeError
from agent.services import exact_product_final_output_service as svc

router = APIRouter(prefix="/exact-product", tags=["exact-product-output"])


class ComposeFromPlateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., min_length=1)
    background_media_id: str | None = None
    background_local_path: str | None = None
    lane: str = "studio"
    job_id: str | None = None


class SceneOnlyPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)


def _http(exc: ExactProductCompositeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "detail": exc.message},
    )


@router.get("/policy/{product_id}")
async def get_exact_product_policy(product_id: str):
    """Pre-generation policy + canonical validity (no credits)."""
    try:
        return await svc.get_policy_for_product(product_id)
    except ExactProductCompositeError as exc:
        raise _http(exc) from exc


@router.post("/validate/{product_id}")
async def validate_exact_product(product_id: str):
    """Fail-closed pre-credit canonical check."""
    try:
        policy = await svc.get_policy_for_product(product_id)
        if not policy.get("exact_product_composite_required"):
            return {**policy, "ok": True}
        if not policy.get("canonical_valid"):
            err = policy.get("error") or {}
            raise ExactProductCompositeError(
                err.get("code") or "CANONICAL_PRODUCT_SOURCE_INVALID",
                err.get("message") or "canonical invalid",
                status_code=422,
            )
        return {**policy, "ok": True}
    except ExactProductCompositeError as exc:
        raise _http(exc) from exc


@router.post("/scene-only-prompt")
async def build_scene_only_prompt(req: SceneOnlyPromptRequest):
    """Augment operator/poster prompt for exact-policy scene plates."""
    try:
        policy = await svc.get_policy_for_product(req.product_id)
        if not policy.get("exact_product_composite_required"):
            return {
                "product_id": req.product_id,
                "exact_product_composite_required": False,
                "prompt": req.prompt,
                "send_product_reference_to_flow": True,
            }
        if policy.get("exact_product_composite_required") and not policy.get(
            "canonical_valid"
        ):
            err = policy.get("error") or {}
            raise ExactProductCompositeError(
                err.get("code") or "CANONICAL_PRODUCT_SOURCE_INVALID",
                err.get("message") or "canonical invalid",
                status_code=422,
            )
        return {
            "product_id": req.product_id,
            "exact_product_composite_required": True,
            "prompt": svc.build_scene_only_prompt(req.prompt),
            "send_product_reference_to_flow": False,
            "scene_only_prompt_block": policy.get("scene_only_prompt_block"),
        }
    except ExactProductCompositeError as exc:
        raise _http(exc) from exc


@router.post("/compose-from-plate")
async def compose_from_plate(req: ComposeFromPlateRequest):
    """Insert canonical cutout onto a retrieved scene plate; return final only."""
    try:
        return await svc.compose_final_for_product(
            product_id=req.product_id,
            background_media_id=req.background_media_id or "",
            background_local_path=req.background_local_path or "",
            lane=req.lane or "studio",
            job_id=req.job_id,
        )
    except ExactProductCompositeError as exc:
        raise _http(exc) from exc
