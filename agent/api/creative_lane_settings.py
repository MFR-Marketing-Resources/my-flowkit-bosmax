"""Read-only API for Faceless/Montage controlled lane settings."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import creative_lane_settings_service as cls
from agent.services import faceless_lane_service as fl

router = APIRouter(tags=["creative-lane-settings"])


class ResolveLaneSettingsRequest(BaseModel):
    hook_id: str | None = Field(default=None)
    background_id: str | None = Field(default=None)
    product_cluster: str | None = Field(default=None)
    has_approved_usp: bool = False
    scene_context_hint: str | None = Field(default=None)
    product_id: str | None = Field(default=None)


@router.get("/creative-lane-settings")
async def get_creative_lane_settings(
    lane: str | None = None,
    product_id: str | None = None,
):
    """Controlled vocabulary, with product-filtered Faceless backgrounds."""
    payload = cls.public_settings_payload()
    if str(lane or "").strip().upper() == "FACELESS" and str(product_id or "").strip():
        try:
            authority = await fl.resolve_faceless_scene_authority(
                product_id=str(product_id).strip(),
                background_id="AUTO",
            )
            payload["background"]["options"] = authority["background_options"]
            payload["faceless_context"] = {
                "scene_strategy_id": authority["scene_strategy"]["scene_strategy_id"],
                "choreography_id": authority["choreography"]["choreography_id"],
                "compatible_contexts": authority["compatible_contexts"],
                "compatibility_status": "COMPATIBLE",
            }
        except ValueError as exc:
            # Keep AUTO as the only safe choice when product context is not
            # resolvable. Prepare remains the authoritative server-side gate.
            payload["background"]["options"] = [
                option
                for option in payload["background"]["options"]
                if option["id"] == cls.AUTO_ID
            ]
            payload["faceless_context"] = {
                "compatibility_status": "BLOCKED",
                "error_code": getattr(exc, "code", None)
                or str(exc).split(":", 1)[0],
                "detail": str(exc),
            }
    return payload


@router.post("/creative-lane-settings/resolve")
async def resolve_creative_lane_settings(body: ResolveLaneSettingsRequest):
    """Deterministic resolution — no credit spend, no LLM requirement."""
    try:
        opening_strategy = cls.resolve_opening_strategy(
            body.hook_id,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
        )
        if body.product_id:
            authority = await fl.resolve_faceless_scene_authority(
                product_id=body.product_id,
                hook_id=body.hook_id,
                background_id=body.background_id,
                product_cluster=body.product_cluster,
                has_approved_usp=body.has_approved_usp,
                scene_context_hint=body.scene_context_hint,
            )
            background = authority["background"]
        else:
            background = cls.resolve_background(
                body.background_id,
                scene_context_hint=body.scene_context_hint,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "opening_strategy": opening_strategy,
        # Backward-compatible wire alias.
        "hook": opening_strategy,
        "background": background,
    }
