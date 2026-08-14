"""Read-only Phase 2 Copy Architecture V2 contract endpoints.

These endpoints validate and describe additive V2 artifacts.  They do not
persist blueprints, approve copy, call a provider, invoke the compiler, or
change any legacy CopySet path.  Consumer/page cutover remains Phase 3.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent.authority.copy_lane_matrix import producer_consumer_matrix
from agent.models.copy_blueprint_v2 import (
    AdapterContext,
    CopyBlueprintV2,
    CopyBlueprintV2FeatureFlagState,
    EvidenceFact,
    EvidenceRegistry,
    ProductTruthLineage,
)
from agent.services.copy_blueprint_v2_service import (
    CopyBlueprintV2Error,
    bind_copy_blueprint_v2,
    validate_copy_blueprint_v2,
)


router = APIRouter(prefix="/copy-architecture/v2", tags=["copy-architecture-v2"])


class CopyBlueprintV2ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint: CopyBlueprintV2
    current_product_truth: ProductTruthLineage | None = None
    evidence_facts: tuple[EvidenceFact, ...] = Field(default_factory=tuple)
    require_approval: bool = False
    duration_word_limit: int | None = Field(default=None, ge=1)
    max_words_per_second: float | None = Field(default=None, gt=0)


class CopyBlueprintV2BindRequest(CopyBlueprintV2ValidateRequest):
    lane: str = Field(min_length=1)
    feature_flags: CopyBlueprintV2FeatureFlagState = Field(
        default_factory=CopyBlueprintV2FeatureFlagState
    )
    compiler_binding_version: str = "copy-execution-binding-v2"
    context: AdapterContext | None = None


def _raise(error: CopyBlueprintV2Error) -> None:
    raise HTTPException(
        status_code=409,
        detail={"error": error.code, "detail": error.details or str(error)},
    )


@router.get("/lanes")
async def get_copy_architecture_v2_lanes():
    return {"version": "2", "items": producer_consumer_matrix()}


@router.get("/consumer-status")
async def get_copy_architecture_v2_consumer_status():
    """Expose the read-only consumer feature state for lane UIs.

    This is observability only: it neither resolves a blueprint nor asserts
    production readiness.  Consumers still need to submit a complete V2
    context to the central binding resolver when the flag is enabled.
    """

    flags = CopyBlueprintV2FeatureFlagState.from_environment()
    return {
        "version": "2",
        "feature_flags": flags.model_dump(mode="json"),
        "legacy_path_unchanged": not flags.enabled,
        "binding_required_when_enabled": True,
        "provider_calls": 0,
        "credit_spend": False,
    }


@router.post("/validate")
async def validate_copy_architecture_v2(request: CopyBlueprintV2ValidateRequest):
    registry = EvidenceRegistry(facts=request.evidence_facts)
    result = validate_copy_blueprint_v2(
        request.blueprint,
        current_product_truth=request.current_product_truth,
        evidence_registry=registry,
        require_approval=request.require_approval,
        duration_word_limit=request.duration_word_limit,
        max_words_per_second=request.max_words_per_second,
    )
    return result.model_dump(mode="json")


@router.post("/bind")
async def bind_copy_architecture_v2(request: CopyBlueprintV2BindRequest):
    if request.current_product_truth is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "COPY_V2_PRODUCT_TRUTH_LINEAGE_MISSING"},
        )
    registry = EvidenceRegistry(facts=request.evidence_facts)
    try:
        binding = bind_copy_blueprint_v2(
            request.blueprint,
            lane=request.lane,
            current_product_truth=request.current_product_truth,
            evidence_registry=registry,
            feature_flags=request.feature_flags,
            compiler_binding_version=request.compiler_binding_version,
        )
    except CopyBlueprintV2Error as error:
        _raise(error)
    return {"binding": binding.model_dump(mode="json")}
