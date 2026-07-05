from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from agent.services.ai_provider_model_catalog import (
    disable_provider_model,
    reset_seed_catalog,
    summarize_model_catalog,
    upsert_provider_model,
)
from agent.services.ai_provider_settings_service import (
    activate_provider,
    clear_lane_settings,
    clear_provider_key,
    deactivate_provider,
    summarize_provider_settings,
    update_lane_settings,
    update_provider_default_model,
    update_provider_key,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]
LaneId = Literal["text_assist", "vision"]


class ModelCatalogModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    label: str
    enabled: bool = True
    lanes: list[str] = []
    source: str = "custom"


class ProviderCatalogEntry(BaseModel):
    label: str
    transport: str
    enabled: bool = True
    supported_lanes: list[str] = []
    models: list[ModelCatalogModel] = []


class ModelCatalogResponse(BaseModel):
    version: int
    providers: dict[str, ProviderCatalogEntry]


class AIProviderSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

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
    configured_by_user: bool = False
    key_present: bool = False
    model_valid: bool = False
    status: str = "NOT_CONFIGURED"
    configured: bool = False


class AIProviderRegistryResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    active_provider: ProviderId | None = None
    providers: list[AIProviderSummary]
    model_catalog: dict[str, ProviderCatalogEntry] = {}
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


class ModelUpsertRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    label: str
    lanes: list[str] = []
    enabled: bool = True


router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"])


def _registry() -> AIProviderRegistryResponse:
    return AIProviderRegistryResponse(**summarize_provider_settings())


@router.get("", response_model=AIProviderRegistryResponse)
async def get_ai_provider_settings():
    return _registry()


@router.get("/model-catalog", response_model=ModelCatalogResponse)
async def get_ai_model_catalog():
    return ModelCatalogResponse(**summarize_model_catalog())


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


@router.put(
    "/model-catalog/{provider_id}/models/{model_id}",
    response_model=AIProviderRegistryResponse,
)
async def put_model_catalog_model(
    provider_id: ProviderId, model_id: str, body: ModelUpsertRequest
):
    try:
        upsert_provider_model(
            provider_id,
            model_id,
            label=body.label,
            lanes=body.lanes,
            enabled=body.enabled,
        )
        return _registry()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/model-catalog/{provider_id}/models/{model_id}/disable",
    response_model=AIProviderRegistryResponse,
)
async def patch_disable_model_catalog_model(provider_id: ProviderId, model_id: str):
    try:
        disable_provider_model(provider_id, model_id)
        return _registry()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/model-catalog/reset-seed", response_model=AIProviderRegistryResponse)
async def post_reset_seed_model_catalog():
    reset_seed_catalog()
    return _registry()


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


@router.delete("/lanes/{lane}", response_model=AIProviderRegistryResponse)
async def delete_ai_provider_lane(lane: LaneId):
    try:
        return AIProviderRegistryResponse(**clear_lane_settings(lane))
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
