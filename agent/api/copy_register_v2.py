"""Formula-native Copy Register V2 workflow API.

The route surface is intentionally separate from the legacy copy endpoints.
No handler in this module calls the legacy copy service or returns a legacy
row.  The existing text_assist provider is called only by the three explicit
authoring actions (angle generation, complete formula generation, and stage
regeneration). Startup, reads, approval, binding, and tests make no live call.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agent.models.copy_blueprint_v2 import (
    CopyBlueprintV2FeatureFlagState,
    ProductionReadinessProof,
    SemanticReviewProof,
)
from agent.services import copy_register_v2_service as service


router = APIRouter(prefix="/copy-register/v2", tags=["copy-register-v2"])


class AngleOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    formula_id: str = Field(min_length=1)
    objective: str = Field(default="conversion", min_length=1)


class GenerateBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    formula_id: str = Field(min_length=1)
    objective_id: str = Field(min_length=1)
    objective_definition: str = Field(min_length=1)
    angle_id: str = Field(min_length=1)
    angle_definition: str = Field(min_length=1)
    evidence_fact_ids: list[str] = Field(min_length=1, max_length=5)
    target_duration_seconds: float | None = Field(default=None, gt=0)


class ApproveBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1)
    semantic_review: SemanticReviewProof
    readiness_proof: ProductionReadinessProof


class BindBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str = Field(min_length=1)
    lane: str = Field(min_length=1)


def _raise(error: service.CopyRegisterV2Error) -> None:
    detail: dict[str, Any] = {"error": error.code, "detail": str(error)}
    if error.details is not None:
        detail["details"] = error.details
    raise HTTPException(status_code=error.status_code, detail=detail)


def _blueprint_payload(blueprint) -> dict[str, Any]:
    payload = blueprint.model_dump(mode="json")
    try:
        payload["derived_projection"] = blueprint.derived_projections().model_dump(mode="json")
    except Exception:
        payload["derived_projection"] = None
    payload["v2_badge"] = "V2 PRODUCTION_VALID" if blueprint.status == "PRODUCTION_VALID" else None
    return payload


@router.get("/formulas")
async def get_formulas():
    return {
        "version": "2",
        "formulas": service.list_formulas(),
        "explicit_formula_required": True,
        "default_formula": None,
        "provider_calls": 0,
    }


@router.get("/lanes")
async def get_lanes():
    return {"version": "2", "items": await service.list_binding_matrix()}


@router.get("/provider-status")
async def get_provider_status():
    """Secret-free status for the existing text_assist lane."""

    return service.get_text_assist_provider_status()


@router.get("/product/{product_id}/truth")
async def get_truth(product_id: str):
    try:
        return await service.get_product_truth_proof(product_id)
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/angle-options")
async def generate_angles(request: AngleOptionsRequest):
    try:
        return await service.generate_angle_options(request.product_id, request.formula_id, request.objective)
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/blueprints/generate")
async def generate_blueprint(request: GenerateBlueprintRequest):
    try:
        blueprint = await service.generate_blueprint(**request.model_dump())
        return {
            "blueprint": _blueprint_payload(blueprint),
            "status": blueprint.status,
            "production_valid": False,
            "provider_calls": 1,
            "credit_spend": 0,
            "legacy_copy_rows_written": 0,
        }
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.get("/product/{product_id}/blueprints")
async def list_product_blueprints(product_id: str):
    try:
        items = await service.list_blueprints(product_id)
        return {
            "product_id": product_id,
            "items": [_blueprint_payload(item) for item in items],
            "activation": await service.get_activation_status(product_id),
            "legacy_copy_rows_read": 0,
        }
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.get("/blueprints/{blueprint_id}")
async def get_blueprint(blueprint_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        return _blueprint_payload(await service.get_blueprint(blueprint_id, revision))
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/blueprints/{blueprint_id}/stages/{stage_key}/regenerate")
async def regenerate_stage(blueprint_id: str, stage_key: str):
    try:
        blueprint = await service.regenerate_stage(blueprint_id, stage_key)
        return {"blueprint": _blueprint_payload(blueprint), "new_revision": blueprint.revision, "provider_calls": 1, "credit_spend": 0}
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/blueprints/{blueprint_id}/approve")
async def approve_blueprint(blueprint_id: str, request: ApproveBlueprintRequest):
    try:
        blueprint = await service.approve_blueprint(
            blueprint_id,
            approved_by=request.approved_by,
            semantic_review=request.semantic_review,
            readiness_proof=request.readiness_proof,
        )
        return {
            "blueprint": _blueprint_payload(blueprint),
            "status": blueprint.status,
            "production_valid": blueprint.status == "PRODUCTION_VALID",
            "badge": "V2 PRODUCTION_VALID" if blueprint.status == "PRODUCTION_VALID" else None,
            "automatic_approval": False,
        }
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/bindings")
async def bind_blueprint(request: BindBlueprintRequest):
    try:
        canonical_flags = CopyBlueprintV2FeatureFlagState.from_environment()
        binding = await service.bind_blueprint(
            blueprint_id=request.blueprint_id,
            lane=request.lane,
            feature_flags=canonical_flags,
        )
        return {"binding": binding.model_dump(mode="json"), "persisted": True, "compiler_mutation": False}
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.post("/blueprints/{blueprint_id}/activate")
async def activate_blueprint(blueprint_id: str):
    """Atomically bind one human-approved blueprint to all required lanes."""

    try:
        bindings = await service.activate_blueprint_for_required_lanes(blueprint_id)
        return {
            "blueprint_id": blueprint_id,
            "activated": True,
            "bindings": [binding.model_dump(mode="json") for binding in bindings],
            "required_lane_count": len(bindings),
            "automatic_approval": False,
            "provider_calls": 0,
            "credit_spend": 0,
        }
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.get("/bindings/{product_id}/{lane}")
async def get_binding(product_id: str, lane: str):
    try:
        return {"binding": (await service.get_binding(product_id, lane)).model_dump(mode="json")}
    except service.CopyRegisterV2Error as error:
        _raise(error)


@router.get("/bindings/{product_id}/{lane}/resolution")
async def get_binding_resolution(product_id: str, lane: str):
    """Return the same persisted, revalidated projection used by consumers."""

    from agent.services.copy_execution_resolver import (
        CopyExecutionResolutionError,
        resolve_persisted_copy_execution_binding,
    )

    try:
        resolution = await resolve_persisted_copy_execution_binding(product_id, lane)
        payload = resolution.to_metadata()
        payload.update(
            {
                "ready": resolution.ready,
                "blueprint_id": resolution.binding.blueprint_id if resolution.binding else None,
                "revision": resolution.binding.revision if resolution.binding else None,
                "formula_id": resolution.binding.formula_id if resolution.binding else None,
                "formula_version": resolution.binding.formula_version if resolution.binding else None,
                "approval_snapshot_id": (
                    resolution.binding.approval_snapshot_id if resolution.binding else None
                ),
            }
        )
        return payload
    except CopyExecutionResolutionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"error": error.code, "detail": error.details or str(error)},
        ) from error


__all__ = ["router"]
