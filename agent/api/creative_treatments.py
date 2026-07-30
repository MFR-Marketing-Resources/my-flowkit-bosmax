"""P7.5 Creative Treatment authority API."""

from fastapi import APIRouter, HTTPException, Query

from agent.models.creative_treatment import (
    CreateTreatmentRequest,
    CreateVariationGroupRequest,
    ReviewTreatmentRequest,
    ReviewVariationGroupRequest,
    SubmitTreatmentReviewRequest,
    SubmitVariationGroupReviewRequest,
)
from agent.services import creative_treatment_service as treatments


router = APIRouter(
    prefix="/creative-treatments",
    tags=["creative-treatments"],
)


def _http(exc: treatments.CreativeTreatmentError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@router.post("", status_code=201)
async def create_treatment(body: CreateTreatmentRequest):
    try:
        return await treatments.create_treatment(body)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.get("")
async def list_treatments(
    product_id: str | None = None,
    status: str | None = None,
    variation_group_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return {
        "treatments": await treatments.list_treatments(
            product_id=product_id,
            status=status,
            variation_group_id=variation_group_id,
            limit=limit,
        ),
    }


@router.post("/variation-groups", status_code=201)
async def create_variation_group(body: CreateVariationGroupRequest):
    try:
        return await treatments.create_variation_group(body)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.get("/variation-groups")
async def list_variation_groups(
    product_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return {
        "variation_groups": await treatments.list_variation_groups(
            product_id=product_id,
            status=status,
            limit=limit,
        ),
    }


@router.get("/variation-groups/{group_id}")
async def get_variation_group(group_id: str):
    try:
        return await treatments.get_variation_group(group_id)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/variation-groups/{group_id}/submit-review")
async def submit_variation_group_review(
    group_id: str,
    body: SubmitVariationGroupReviewRequest,
):
    try:
        return await treatments.submit_variation_group_review(
            group_id,
            actor_id=body.actor_id,
        )
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/variation-groups/{group_id}/review")
async def review_variation_group(
    group_id: str,
    body: ReviewVariationGroupRequest,
):
    try:
        return await treatments.review_variation_group(group_id, body)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.get("/{treatment_id}")
async def get_treatment(treatment_id: str):
    try:
        return await treatments.get_treatment(treatment_id)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/{treatment_id}/submit-review")
async def submit_treatment_review(
    treatment_id: str,
    body: SubmitTreatmentReviewRequest,
):
    try:
        return await treatments.submit_treatment_review(
            treatment_id,
            actor_id=body.actor_id,
        )
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/{treatment_id}/review")
async def review_treatment(
    treatment_id: str,
    body: ReviewTreatmentRequest,
):
    try:
        return await treatments.review_treatment(treatment_id, body)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc
