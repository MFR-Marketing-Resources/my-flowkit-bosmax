from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from agent.services.ai_provider_settings_service import (
    activate_provider,
    clear_provider_key,
    deactivate_provider,
    summarize_provider_settings,
    update_lane_settings,
    update_provider_default_model,
    update_provider_key,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]
LaneId = Literal["text_assist", "vision"]


class AIProviderModelOption(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    label: str
    lanes: list[str]
    default_for: list[str] = []


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
    default_model: str | None = None
    supported_lanes: list[str] = []


class AIProviderLaneSetting(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    lane: LaneId
    label: str
    provider_id: ProviderId | None = None
    model_id: str | None = None
    execution_enabled: bool = False
    configured: bool = False


class AIProviderRegistryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    active_provider: ProviderId | None = None
    providers: list[AIProviderSummary]
    model_catalog: dict[str, list[AIProviderModelOption]] = {}
    lanes: list[AIProviderLaneSetting] = []


class AIProviderKeyUpdateRequest(BaseModel):
    api_key: str


class AIProviderModelUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str


class AIProviderLaneUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider_id: ProviderId
    model_id: str
    execution_enabled: bool | None = None


router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"])


def _coerce_summary_response() -> AIProviderRegistryResponse:
    return AIProviderRegistryResponse(**summarize_provider_settings())


@router.get("", response_model=AIProviderRegistryResponse)
async def get_ai_provider_settings():
    return _coerce_summary_response()


@router.put("/{provider_id}/key", response_model=AIProviderRegistryResponse)
async def put_ai_provider_key(provider_id: ProviderId, body: AIProviderKeyUpdateRequest):
    try:
        return AIProviderRegistryResponse(**update_provider_key(provider_id, body.api_key))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{provider_id}/key", response_model=AIProviderRegistryResponse)
async def delete_ai_provider_key(provider_id: ProviderId):
    try:
        return AIProviderRegistryResponse(**clear_provider_key(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{provider_id}/model", response_model=AIProviderRegistryResponse)
async def put_ai_provider_model(provider_id: ProviderId, body: AIProviderModelUpdateRequest):
    try:
        return AIProviderRegistryResponse(
            **update_provider_default_model(provider_id, body.model_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/lanes/{lane}", response_model=AIProviderRegistryResponse)
async def put_ai_provider_lane(lane: LaneId, body: AIProviderLaneUpdateRequest):
    try:
        return AIProviderRegistryResponse(
            **update_lane_settings(
                lane,
                body.provider_id,
                body.model_id,
                execution_enabled=body.execution_enabled,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{provider_id}/activate", response_model=AIProviderRegistryResponse)
async def post_activate_ai_provider(provider_id: ProviderId):
    try:
        return AIProviderRegistryResponse(**activate_provider(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/deactivate", response_model=AIProviderRegistryResponse)
async def post_deactivate_ai_provider():
    return AIProviderRegistryResponse(**deactivate_provider())
