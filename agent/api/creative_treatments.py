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
from agent.api.legacy_copy_guard import require_legacy_copy_maintenance
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled


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


def _active_projection(row: dict) -> dict:
    if legacy_copy_maintenance_enabled():
        return row
    result = dict(row)
    binding_id = str(result.get("copy_execution_binding_id_v2") or "").strip()
    # V2-native treatments keep binding + dialogue; legacy receipt fields stay
    # historical-only and are excluded from the active projection.
    for field in (
        "copy_set_id",
        "copy_set_sha256",
    ):
        result.pop(field, None)
    if not binding_id:
        for field in (
            "content_angle",
            "dialogue_text",
            "dialogue_sha256",
        ):
            result.pop(field, None)
        result["historical_copy_excluded"] = True
    else:
        result["historical_copy_excluded"] = False
    if isinstance(result.get("members"), list):
        result["members"] = [
            _active_projection(member)
            for member in result["members"]
            if isinstance(member, dict)
        ]
    result["copy_authority"] = "COPY_REGISTER_V2_ONLY"
    return result


@router.post("", status_code=201)
async def create_treatment(body: CreateTreatmentRequest):
    # V2-native create is the normal production path. Legacy copy_set_id create
    # remains available only under explicit offline maintenance.
    if (body.copy_execution_binding_id_v2 or "").strip():
        try:
            return _active_projection(await treatments.create_treatment(body))
        except treatments.CreativeTreatmentError as exc:
            raise _http(exc) from exc
    require_legacy_copy_maintenance()
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
        "treatments": [
            _active_projection(row)
            for row in await treatments.list_treatments(
                product_id=product_id,
                status=status,
                variation_group_id=variation_group_id,
                limit=limit,
            )
        ],
    }


@router.post("/variation-groups", status_code=201)
async def create_variation_group(body: CreateVariationGroupRequest):
    require_legacy_copy_maintenance()
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
        "variation_groups": [
            _active_projection(row)
            for row in await treatments.list_variation_groups(
                product_id=product_id,
                status=status,
                limit=limit,
            )
        ],
    }


@router.get("/variation-groups/{group_id}")
async def get_variation_group(group_id: str):
    try:
        return _active_projection(await treatments.get_variation_group(group_id))
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/variation-groups/{group_id}/submit-review")
async def submit_variation_group_review(
    group_id: str,
    body: SubmitVariationGroupReviewRequest,
):
    require_legacy_copy_maintenance()
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
    require_legacy_copy_maintenance()
    try:
        return await treatments.review_variation_group(group_id, body)
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.get("/{treatment_id}")
async def get_treatment(treatment_id: str):
    try:
        return _active_projection(await treatments.get_treatment(treatment_id))
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/{treatment_id}/submit-review")
async def submit_treatment_review(
    treatment_id: str,
    body: SubmitTreatmentReviewRequest,
):
    try:
        return _active_projection(
            await treatments.submit_treatment_review(
                treatment_id,
                actor_id=body.actor_id,
            )
        )
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc


@router.post("/{treatment_id}/review")
async def review_treatment(
    treatment_id: str,
    body: ReviewTreatmentRequest,
):
    try:
        return _active_projection(await treatments.review_treatment(treatment_id, body))
    except treatments.CreativeTreatmentError as exc:
        raise _http(exc) from exc
