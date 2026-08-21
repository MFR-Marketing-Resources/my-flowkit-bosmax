"""Typed API surface for the P6 Batch Creative Production Orchestrator."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from agent.models.creative_production import (
    AttemptTransitionRequest,
    CapacityPreflightResponse,
    DryRunRequest,
    LanePatchRequest,
    P58CohortAuthorityResponse,
    PlanActionRequest,
    PoolAuthorityRequest,
    ProductionPlanCreateRequest,
    ProductionPlanDetailResponse,
    ProductionPlanUpdateRequest,
    QaDecisionRequest,
    StartPlanRequest,
    TreatmentAvailabilityRequest,
    WaveAssignmentRequest,
)
from agent.services import creative_production_compile_service as compiler
from agent.services import creative_production_plan_service as plans
from agent.services import creative_production_scheduler_service as scheduler
from agent.services.creative_production_recipe_service import (
    ProductionRecipeError,
    resolve_production_recipe,
)


router = APIRouter(
    prefix="/creative-production",
    tags=["creative-production"],
)


def _http(exc: plans.CreativeProductionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@router.get(
    "/cohort-authority",
    response_model=P58CohortAuthorityResponse,
)
async def cohort_authority(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> P58CohortAuthorityResponse:
    return await plans.load_p58_cohort_authority(
        query=q,
        limit=limit,
        offset=offset,
    )


@router.post("/plans", status_code=201)
async def create_plan(body: ProductionPlanCreateRequest):
    try:
        return await plans.create_plan(body)
    except ProductionRecipeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": exc.code, "message": str(exc), "details": {}},
        ) from exc
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.get("/plans")
async def list_plans(
    limit: int = Query(default=50, ge=1, le=200),
):
    return {"plans": await plans.list_plans(limit)}


@router.post("/pool-authority")
async def pool_authority(body: PoolAuthorityRequest):
    try:
        return await plans.get_governed_pool_authority(body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/treatment-availability")
async def treatment_availability(body: TreatmentAvailabilityRequest):
    try:
        recipe_adapter = resolve_production_recipe(body.production_recipe)
        return await plans.resolve_treatment_availability(
            product_video_allocations=[
                item.model_dump(mode="json")
                for item in body.product_video_allocations
            ],
            logical_mode=recipe_adapter.treatment_logical_mode,
            model_key=body.model_key,
            duration_seconds=body.duration_seconds,
            creative_format=body.creative_format,
            treatment_ids=body.treatment_ids,
        )
    except ProductionRecipeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": exc.code, "message": str(exc), "details": {}},
        ) from exc
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.get(
    "/plans/{plan_id}",
    response_model=ProductionPlanDetailResponse,
)
async def get_plan(plan_id: str) -> ProductionPlanDetailResponse:
    try:
        return await plans.get_plan_detail(plan_id)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.patch("/plans/{plan_id}")
async def update_plan(plan_id: str, body: ProductionPlanUpdateRequest):
    try:
        return await plans.update_plan(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post(
    "/plans/{plan_id}/preflight",
    response_model=CapacityPreflightResponse,
)
async def preflight_plan(
    plan_id: str,
    body: PlanActionRequest,
) -> CapacityPreflightResponse:
    try:
        return await plans.run_capacity_preflight(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/content-matrix")
async def materialize_content_matrix(plan_id: str, body: PlanActionRequest):
    try:
        return await plans.materialize_content_matrix(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/compile")
async def compile_plan(plan_id: str, body: PlanActionRequest):
    try:
        return await compiler.compile_plan(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, body: PlanActionRequest):
    try:
        return await plans.approve_plan(
            plan_id,
            request_id=body.request_id,
            operator_id=body.operator_id,
        )
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/waves")
async def assign_waves(plan_id: str, body: WaveAssignmentRequest):
    try:
        return await plans.assign_waves(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/dry-run")
async def dry_run_plan(plan_id: str, body: DryRunRequest):
    try:
        return await scheduler.dry_run_plan(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/materialize-approval-manifest")
async def materialize_plan_approval_manifest(plan_id: str, body: DryRunRequest):
    """Freeze the plan's per-item FINAL prompts into an Approved Generation
    Manifest (run_ref = plan id) for human WYSIWYG review before live dispatch.
    ``aspect`` must be the SAME aspect the operator will start the plan with, so
    each frozen item hash-matches its dispatch. Provider-free — nothing fires."""
    from agent.services import execution_approval_service as _eas
    try:
        items = await scheduler.build_studio_plan_manifest_items(
            plan_id, aspect=body.aspect,
        )
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc
    if not items:
        raise HTTPException(422, detail={"error": "NO_DISPATCHABLE_ITEMS"})
    return await _eas.create_manifest(
        surface="production_studio", run_ref=plan_id,
        logical_mode="VIDEO", items=items, created_by="operator",
    )


@router.post("/plans/{plan_id}/start")
async def start_plan(plan_id: str, body: StartPlanRequest):
    try:
        return await scheduler.start_plan(plan_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/pause")
async def pause_plan(plan_id: str, body: PlanActionRequest):
    try:
        return await scheduler.control_plan(plan_id, "PAUSE", body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/resume")
async def resume_plan(plan_id: str, body: PlanActionRequest):
    try:
        return await scheduler.control_plan(plan_id, "RESUME", body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str, body: PlanActionRequest):
    try:
        return await scheduler.control_plan(plan_id, "CANCEL", body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.get("/lanes")
async def list_lanes():
    return {
        "lanes": await scheduler.list_lanes(),
        "live_execution_certified": scheduler.live_execution_certified(),
    }


@router.patch("/lanes/{lane_id}")
async def patch_lane(lane_id: str, body: LanePatchRequest):
    try:
        return await scheduler.patch_lane(lane_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/attempts/{attempt_id}/transition")
async def transition_attempt(
    attempt_id: str,
    body: AttemptTransitionRequest,
):
    try:
        return await scheduler.transition_attempt(attempt_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/attempts/{attempt_id}/reconcile")
async def reconcile_attempt(attempt_id: str):
    try:
        return await scheduler.reconcile_attempt(attempt_id)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/attempts/{attempt_id}/retry")
async def retry_attempt(attempt_id: str, body: PlanActionRequest):
    try:
        return await scheduler.retry_attempt(attempt_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc


@router.post("/recovery/reconcile")
async def recover_after_restart():
    return await scheduler.recover_after_restart()


@router.post("/items/{item_id}/qa")
async def qa_decision(item_id: str, body: QaDecisionRequest):
    try:
        return await scheduler.qa_decision(item_id, body)
    except plans.CreativeProductionError as exc:
        raise _http(exc) from exc
