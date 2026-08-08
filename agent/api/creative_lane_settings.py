"""Read-only API for Faceless/Montage Hook + Background controlled settings."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import creative_lane_settings_service as cls

router = APIRouter(tags=["creative-lane-settings"])


class ResolveLaneSettingsRequest(BaseModel):
    hook_id: str | None = Field(default=None)
    background_id: str | None = Field(default=None)
    product_cluster: str | None = Field(default=None)
    has_approved_usp: bool = False
    scene_context_hint: str | None = Field(default=None)


@router.get("/creative-lane-settings")
async def get_creative_lane_settings():
    """Controlled Hook/Background vocab (SSOT)."""
    return cls.public_settings_payload()


@router.post("/creative-lane-settings/resolve")
async def resolve_creative_lane_settings(body: ResolveLaneSettingsRequest):
    """Deterministic AUTO resolution — no credit spend, no LLM requirement."""
    try:
        hook = cls.resolve_hook(
            body.hook_id,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
        )
        background = cls.resolve_background(
            body.background_id,
            scene_context_hint=body.scene_context_hint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"hook": hook, "background": background}
