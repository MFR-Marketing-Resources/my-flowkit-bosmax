from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.services.ai_provider_settings_service import (
    activate_provider,
    clear_provider_key,
    deactivate_provider,
    summarize_provider_settings,
    update_provider_key,
)

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]

router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"])


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


@router.post("/{provider_id}/activate", response_model=AIProviderRegistryResponse)
async def post_activate_ai_provider(provider_id: ProviderId):
    try:
        return AIProviderRegistryResponse(**activate_provider(provider_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/deactivate", response_model=AIProviderRegistryResponse)
async def post_deactivate_ai_provider():
    return AIProviderRegistryResponse(**deactivate_provider())

