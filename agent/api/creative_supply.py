"""P7 Creative Supply Factory API.

Generation remains on the existing P6 router. This API authors text one
explicit step at a time and may prepare/upload reviewed zero-credit F2V input
anchors through the existing Flow upload helper.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import creative_supply_factory_service as service

router = APIRouter(prefix="/creative-supply", tags=["creative-supply"])


class RosterItem(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str = ""
    rank: int = Field(ge=1, le=10)
    role: Literal["HERO", "TOP10"]
    selection_basis: str = ""


class AnglePlanItem(BaseModel):
    product_id: str = Field(min_length=1)
    angle_key: str = Field(min_length=1)
    angle_label: str = ""


class ComponentTargets(BaseModel):
    HOOK: int = Field(ge=1, le=12)
    SUBHOOK: int = Field(ge=1, le=12)
    USP_SET: int = Field(ge=1, le=12)
    CTA: int = Field(ge=1, le=12)


class RoleTargetPolicy(BaseModel):
    components: ComponentTargets
    minimum_capacity: int = Field(ge=1)


class TargetPolicy(BaseModel):
    HERO: RoleTargetPolicy
    TOP10: RoleTargetPolicy


class CreateRunRequest(BaseModel):
    mission_id: str = Field(min_length=1)
    roster: list[RosterItem] = Field(min_length=10, max_length=10)
    angle_plan: list[AnglePlanItem] = Field(min_length=20, max_length=40)
    target_policy: TargetPolicy
    provider_budget_max: int = Field(default=120, ge=1, le=120)
    reviewer_id: str = Field(default=service.DEFAULT_REVIEWER_ID, min_length=1)


class ControlRequest(BaseModel):
    action: Literal["PAUSE", "RESUME"]
    reason: str = ""


class ReviewRequest(BaseModel):
    task_id: str = Field(min_length=1)
    component_id: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED"]
    reviewed_content_sha256: str = Field(min_length=64, max_length=64)
    reasons: list[str] = Field(min_length=1, max_length=12)
    reviewer_id: str = Field(min_length=1)


class ComposeRequest(BaseModel):
    product_id: str = Field(min_length=1)
    count: int = Field(default=8, ge=1, le=100)
    dry_run: bool = True


class SelectedComposeRequest(BaseModel):
    product_id: str = Field(min_length=1)
    hook_component_id: str = Field(min_length=1)
    subhook_component_id: str = Field(min_length=1)
    usp_set_component_id: str = Field(min_length=1)
    cta_component_id: str = Field(min_length=1)


class ProductOnlyFrameAliasRequest(BaseModel):
    product_id: str = Field(min_length=1)
    source_asset_id: str = Field(min_length=1)
    reviewer_id: str = Field(default=service.DEFAULT_REVIEWER_ID, min_length=1)


class AnchorUploadRequest(BaseModel):
    confirmation: str = Field(min_length=1)


class ReconcileInterruptedRequest(BaseModel):
    evidence_reason: str = Field(min_length=1)


class ManualRemediationRequest(BaseModel):
    product_id: str = Field(min_length=1)
    angle_key: str = Field(min_length=1)
    component_type: Literal["HOOK", "SUBHOOK", "USP_SET", "CTA"]
    contents: list[str | list[str]] = Field(min_length=1, max_length=12)
    authored_by: str = Field(min_length=1)


def _raise(error: service.CreativeSupplyError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"error": error.code, "message": str(error), "details": error.details},
    ) from error


@router.get("/runs")
async def list_runs():
    return await service.list_runs()


@router.post("/runs")
async def create_run(request: CreateRunRequest):
    try:
        return await service.create_run(
            mission_id=request.mission_id,
            roster=[item.model_dump(mode="json") for item in request.roster],
            angle_plan=[item.model_dump(mode="json") for item in request.angle_plan],
            target_policy=request.target_policy.model_dump(mode="json"),
            provider_budget_max=request.provider_budget_max,
            reviewer_id=request.reviewer_id,
        )
    except service.CreativeSupplyError as error:
        _raise(error)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    try:
        return await service.status(run_id)
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/step")
async def execute_step(run_id: str):
    try:
        return await service.step(run_id)
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/control")
async def control_run(run_id: str, request: ControlRequest):
    try:
        return await service.control(run_id, request.action, request.reason)
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/tasks/{task_id}/retry")
async def retry_task(run_id: str, task_id: str):
    try:
        task_status = await service.retry_transient(task_id)
        if str(task_status.get("run", {}).get("run_id")) != run_id:
            raise service.CreativeSupplyError(
                "TASK_RUN_MISMATCH",
                "Retry task does not belong to the requested run.",
                status_code=409,
            )
        return task_status
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/tasks/{task_id}/requeue-unsubmitted")
async def requeue_unsubmitted_task(run_id: str, task_id: str):
    try:
        task_status = await service.requeue_unsubmitted(task_id)
        if str(task_status.get("run", {}).get("run_id")) != run_id:
            raise service.CreativeSupplyError(
                "TASK_RUN_MISMATCH",
                "Requeued task does not belong to the requested run.",
                status_code=409,
            )
        return task_status
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/tasks/{task_id}/reconcile-interrupted")
async def reconcile_interrupted_task(
    run_id: str, task_id: str, request: ReconcileInterruptedRequest
):
    try:
        task_status = await service.reconcile_interrupted_running_task(
            task_id, request.evidence_reason
        )
        if str(task_status.get("run", {}).get("run_id")) != run_id:
            raise service.CreativeSupplyError(
                "TASK_RUN_MISMATCH",
                "Interrupted task does not belong to the requested run.",
                status_code=409,
            )
        return task_status
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/review")
async def review_component(run_id: str, request: ReviewRequest):
    try:
        return await service.review_component(
            run_id=run_id,
            task_id=request.task_id,
            component_id=request.component_id,
            decision=request.decision,
            reviewed_content_sha256=request.reviewed_content_sha256,
            reasons=request.reasons,
            reviewer_id=request.reviewer_id,
        )
    except service.CreativeSupplyError as error:
        _raise(error)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"error": str(error)},
        ) from error


@router.post("/runs/{run_id}/manual-remediation")
async def register_manual_remediation(
    run_id: str, request: ManualRemediationRequest
):
    try:
        return await service.register_manual_remediation(
            run_id=run_id,
            product_id=request.product_id,
            angle_key=request.angle_key,
            component_type=request.component_type,
            contents=request.contents,
            authored_by=request.authored_by,
        )
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/settle-satisfied")
async def settle_satisfied(run_id: str):
    try:
        return await service.settle_satisfied_tasks(run_id)
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/compose")
async def compose_sample(run_id: str, request: ComposeRequest):
    try:
        return await service.compose_sample(
            run_id, request.product_id, request.count, request.dry_run
        )
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/compose-selected")
async def compose_selected(run_id: str, request: SelectedComposeRequest):
    try:
        return await service.compose_selected_components(
            run_id=run_id,
            product_id=request.product_id,
            hook_component_id=request.hook_component_id,
            subhook_component_id=request.subhook_component_id,
            usp_set_component_id=request.usp_set_component_id,
            cta_component_id=request.cta_component_id,
        )
    except service.CreativeSupplyError as error:
        _raise(error)


@router.post("/runs/{run_id}/product-only-frame-alias")
async def register_product_only_frame_alias(
    run_id: str, request: ProductOnlyFrameAliasRequest
):
    try:
        return await service.register_product_only_f2v_frame_alias(
            run_id=run_id,
            product_id=request.product_id,
            source_asset_id=request.source_asset_id,
            reviewer_id=request.reviewer_id,
        )
    except service.CreativeSupplyError as error:
        _raise(error)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"error": str(error)},
        ) from error


@router.post("/runs/{run_id}/anchors/{asset_id}/upload")
async def upload_product_only_anchor(
    run_id: str, asset_id: str, request: AnchorUploadRequest
):
    try:
        return await service.upload_product_only_f2v_anchor_916(
            run_id=run_id,
            asset_id=asset_id,
            confirmation=request.confirmation,
        )
    except service.CreativeSupplyError as error:
        _raise(error)
