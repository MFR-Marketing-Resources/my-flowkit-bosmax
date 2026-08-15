from fastapi import APIRouter, HTTPException, Query

from agent.models.product_treatment_factory import (
    CreateFactoryPlanRequest,
    FactoryPlanControlRequest,
    FactoryPlanListResponse,
    FactoryPlanProjection,
    PrepareFactoryPlanRequest,
)
from agent.services import product_treatment_factory_service as factory


router = APIRouter(
    prefix="/product-treatment-factory",
    tags=["product-treatment-factory"],
)


def _http(exc: factory.ProductTreatmentFactoryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@router.post("/plans", response_model=FactoryPlanProjection)
async def create_factory_plan(
    body: CreateFactoryPlanRequest,
) -> FactoryPlanProjection:
    try:
        return await factory.create_plan(body)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc


@router.get("/plans", response_model=FactoryPlanListResponse)
async def list_factory_plans(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> FactoryPlanListResponse:
    try:
        plans = await factory.list_plans(status=status, limit=limit)
        return FactoryPlanListResponse(plans=plans)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc


@router.get("/plans/{plan_id}", response_model=FactoryPlanProjection)
async def get_factory_plan(plan_id: str) -> FactoryPlanProjection:
    try:
        return await factory.get_plan(plan_id)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/prepare", response_model=FactoryPlanProjection)
async def prepare_factory_plan(
    plan_id: str,
    body: PrepareFactoryPlanRequest,
) -> FactoryPlanProjection:
    try:
        return await factory.prepare_plan(plan_id, body)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/pause", response_model=FactoryPlanProjection)
async def pause_factory_plan(
    plan_id: str,
    body: FactoryPlanControlRequest,
) -> FactoryPlanProjection:
    try:
        return await factory.pause_plan(plan_id, body)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/resume", response_model=FactoryPlanProjection)
async def resume_factory_plan(
    plan_id: str,
    body: FactoryPlanControlRequest,
) -> FactoryPlanProjection:
    try:
        return await factory.resume_plan(plan_id, body)
    except factory.ProductTreatmentFactoryError as exc:
        raise _http(exc) from exc
