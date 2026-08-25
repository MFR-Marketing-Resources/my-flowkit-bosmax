"""HTTP surface for the Benefit-Centric Creative Factory (Round 1).

Benefit Registry CRUD + deterministic PI re-check + audited manual review
(VERIFY / BLOCK) + the one-call-per-benefit Creative Atom build + governed batch
build + deterministic capacity reads.

Thin handlers delegate to ``creative_factory_service``. Mutations require an
authenticated actor with ``products.update``; the reviewer identity for manual
resolution comes from that authenticated actor (never the request body). Reads
are provider-free; the build endpoints are the only ones that may spend a
provider call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent.models.creative_factory import (
    BenefitCreateRequest,
    BenefitReviewRequest,
    BenefitUpdateRequest,
    BuildRequest,
    BuildVerifiedRequest,
)
from agent.security.access_control import get_current_auth_context
from agent.services import creative_factory_service as svc

router = APIRouter(prefix="/creative-factory", tags=["creative-factory"])

_MUTATION_PERMISSION = "products.update"


def _raise(exc: svc.CreativeFactoryError):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message, "details": exc.details},
    ) from exc


def _require_actor():
    actor = get_current_auth_context()
    if actor is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "AUTHENTICATION_REQUIRED", "message": "An authenticated session is required."},
        )
    return actor


def _require_mutation_actor():
    actor = _require_actor()
    if _MUTATION_PERMISSION not in actor.permission_codes:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "PERMISSION_DENIED",
                "message": f"This action requires the {_MUTATION_PERMISSION} permission.",
            },
        )
    return actor


# --------------------------------------------------------------------------
# Benefit Registry
# --------------------------------------------------------------------------
@router.get("/benefits")
async def list_benefits(product_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    items = await svc.list_benefits(product_id)
    return {"product_id": product_id, "benefits": items, "count": len(items)}


@router.post("/benefits")
async def create_benefit(req: BenefitCreateRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.create_benefit(req.product_id, req.benefit, req.usage_hint)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


@router.get("/benefits/{benefit_id}")
async def get_benefit(benefit_id: str) -> dict[str, Any]:
    benefit = await svc.get_benefit(benefit_id)
    if benefit is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "BENEFIT_NOT_FOUND", "message": "Unknown benefit_id."},
        )
    return benefit


@router.patch("/benefits/{benefit_id}")
async def update_benefit(benefit_id: str, req: BenefitUpdateRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.update_benefit(
            benefit_id,
            benefit_text=req.benefit,
            usage_hint=req.usage_hint,
            usage_hint_provided="usage_hint" in req.model_fields_set,
        )
    except svc.CreativeFactoryError as exc:
        _raise(exc)


@router.delete("/benefits/{benefit_id}")
async def delete_benefit(benefit_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.delete_benefit(benefit_id)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


@router.post("/benefits/{benefit_id}/recheck")
async def recheck_benefit(benefit_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.recheck_benefit(benefit_id)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# Audited manual review resolution (amendment 9)
# --------------------------------------------------------------------------
@router.get("/benefits/{benefit_id}/review-context")
async def review_context(benefit_id: str) -> dict[str, Any]:
    try:
        return await svc.review_context(benefit_id)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


@router.post("/benefits/{benefit_id}/review")
async def resolve_review(benefit_id: str, req: BenefitReviewRequest) -> dict[str, Any]:
    actor = _require_mutation_actor()
    try:
        return await svc.resolve_review(
            benefit_id, req.action, actor.user_id, req.reviewer_note
        )
    except svc.CreativeFactoryError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# Creative Atom build
# --------------------------------------------------------------------------
@router.post("/build")
async def build(req: BuildRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.build_benefit_atoms(req.product_id, req.benefit_id)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


@router.get("/build-plan")
async def build_plan(product_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    return await svc.build_plan(product_id)


@router.post("/build-verified")
async def build_verified(req: BuildVerifiedRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.build_verified(req.product_id, confirm=req.confirm)
    except svc.CreativeFactoryError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# Deterministic capacity reads (ZERO provider calls)
# --------------------------------------------------------------------------
@router.get("/capacity")
async def capacity(product_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    return await svc.product_capacity(product_id)


@router.get("/atoms")
async def atoms(
    benefit_id: str = Query(..., min_length=1),
    status: str = Query(default="ACTIVE"),
) -> dict[str, Any]:
    try:
        return await svc.benefit_atoms(benefit_id, status=status)
    except svc.CreativeFactoryError as exc:
        _raise(exc)
