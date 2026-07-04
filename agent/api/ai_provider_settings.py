from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services.ai_provider_settings_service import (
    activate_provider,
    clear_provider_key,
    deactivate_provider,
    reset_ai_routing,
    summarize_ai_model_catalog,
    summarize_ai_routing,
    summarize_effective_ai_routing,
    summarize_provider_settings,
    update_ai_lane_routing,
    update_provider_key,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]
RoutingProviderId = Literal[
    "qwen",
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
    "deterministic",
]
ExecutionMode = Literal["disabled", "registry_only", "live"]
LaneId = Literal[
    "product_image_analysis",
    "copywriting_assist",
    "angle_hook_subhook_expansion",
    "claim_risk_qa",
    "product_truth_extraction",
    "video_review",
    "final_prompt_compiler",
]
ModelCatalogStatus = Literal["available", "registry_only", "experimental", "deprecated"]
ProviderKeyStatus = Literal["CONFIGURED", "MISSING", "NOT_REQUIRED"]

router = APIRouter(tags=["ai-providers"])


class AIProviderSummary(BaseModel):
    provider_id: ProviderId
    label: str
    env_var: str
    has_key: bool
    masked_key: str | None = None
    status: str
    is_active: bool
    updated_at: str | None = None
    activated_at: str | None = None
    activation_scope: str
    current_capabilities: list[str]


class AIProviderRegistryResponse(BaseModel):
    active_provider: ProviderId | None = None
    providers: list[AIProviderSummary]


class AIProviderKeyUpdateRequest(BaseModel):
    api_key: str


class AIModelCatalogEntry(BaseModel):
    provider_id: RoutingProviderId
    model_id: str
    label: str
    capability_tags: list[str]
    recommended_lanes: list[LaneId]
    status: ModelCatalogStatus
    notes: str | None = None
    default_for_lanes: list[LaneId] = Field(default_factory=list)
    locked: bool = False


class AIModelCatalogProvider(BaseModel):
    provider_id: RoutingProviderId
    label: str
    models: list[AIModelCatalogEntry]


class AIModelCatalogResponse(BaseModel):
    providers: list[AIModelCatalogProvider]


class AIRoutingLane(BaseModel):
    lane_id: LaneId
    label: str
    description: str
    provider_id: RoutingProviderId
    provider_label: str
    model_id: str
    model_label: str
    enabled: bool
    execution_mode: ExecutionMode
    locked: bool
    updated_at: str | None = None
    source: str
    provider_has_key: bool
    provider_key_status: ProviderKeyStatus
    live_supported: bool
    is_executable_now: bool
    warnings: list[str]


class AIRoutingRegistryResponse(BaseModel):
    lanes: list[AIRoutingLane]


class AIRoutingLaneUpdateRequest(BaseModel):
    provider_id: RoutingProviderId
    model_id: str
    enabled: bool
    execution_mode: ExecutionMode


def _coerce_summary_response() -> AIProviderRegistryResponse:
    return AIProviderRegistryResponse(**summarize_provider_settings())


def _coerce_catalog_response() -> AIModelCatalogResponse:
    return AIModelCatalogResponse(**summarize_ai_model_catalog())


def _coerce_routing_response() -> AIRoutingRegistryResponse:
    return AIRoutingRegistryResponse(**summarize_ai_routing())


def _coerce_effective_routing_response() -> AIRoutingRegistryResponse:
    return AIRoutingRegistryResponse(**summarize_effective_ai_routing())


@router.get("/api/ai-providers", response_model=AIProviderRegistryResponse)
async def get_ai_provider_settings():
    return _coerce_summary_response()


@router.put("/api/ai-providers/{provider_id}/key", response_model=AIProviderRegistryResponse)
async def put_ai_provider_key(provider_id: ProviderId, body: AIProviderKeyUpdateRequest):
    try:
        return AIProviderRegistryResponse(**update_provider_key(provider_id, body.api_key))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/ai-providers/{provider_id}/key", response_model=AIProviderRegistryResponse)
async def delete_ai_provider_key(provider_id: ProviderId):
    try:
        return AIProviderRegistryResponse(**clear_provider_key(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/ai-providers/{provider_id}/activate", response_model=AIProviderRegistryResponse)
async def post_activate_ai_provider(provider_id: ProviderId):
    try:
        return AIProviderRegistryResponse(**activate_provider(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/ai-providers/deactivate", response_model=AIProviderRegistryResponse)
async def post_deactivate_ai_provider():
    return AIProviderRegistryResponse(**deactivate_provider())


@router.get("/api/ai-model-catalog", response_model=AIModelCatalogResponse)
async def get_ai_model_catalog():
    return _coerce_catalog_response()


@router.get("/api/ai-routing", response_model=AIRoutingRegistryResponse)
async def get_ai_routing():
    return _coerce_routing_response()


@router.get("/api/ai-routing/effective", response_model=AIRoutingRegistryResponse)
async def get_ai_routing_effective():
    return _coerce_effective_routing_response()


@router.post("/api/ai-routing/reset", response_model=AIRoutingRegistryResponse)
async def post_ai_routing_reset():
    return AIRoutingRegistryResponse(**reset_ai_routing())


@router.put("/api/ai-routing/{lane_id}", response_model=AIRoutingRegistryResponse)
async def put_ai_routing_lane(lane_id: LaneId, body: AIRoutingLaneUpdateRequest):
    try:
        return AIRoutingRegistryResponse(
            **update_ai_lane_routing(
                lane_id,
                provider_id=body.provider_id,
                model_id=body.model_id,
                enabled=body.enabled,
                execution_mode=body.execution_mode,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
