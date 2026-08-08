"""Faceless lane HTTP API — prepare path uses runtime validation + AUTO resolve.

Not a generation engine. Creates a workspace execution package through the
canonical service after faceless_lane_service fail-closed checks.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import faceless_lane_service as fl
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)

router = APIRouter(prefix="/faceless", tags=["faceless"])


class FacelessPrepareRequest(BaseModel):
    product_id: str
    start_frame_asset_id: str
    end_frame_asset_id: Optional[str] = None
    hook_id: str = "AUTO"
    background_id: str = "AUTO"
    duration_seconds: int = 8
    # Product surface (Hybrid parity, no avatar): Single | Extend + model
    generation_mode: str = "SINGLE"
    requested_total_duration_seconds: Optional[int] = None
    model: str = "Veo 3.1 - Lite"
    aspect_ratio: str = "9:16"
    copy_set_id: Optional[str] = None
    copy_fallback_confirmed: bool = True
    product_cluster: Optional[str] = None
    has_approved_usp: bool = False
    scene_context_hint: Optional[str] = None


def _scene_context_from_resolution(resolution: dict[str, Any]) -> str:
    """Compiler-facing context from RESOLVED settings only — never raw AUTO label."""
    hook = resolution["hook"]
    bg = resolution["background"]
    parts = [
        f"Faceless lane strategy={hook['setting_id']} ({hook['display_label']}).",
        str(hook.get("strategy_intent") or "").strip(),
        f"Environment={bg['setting_id']} ({bg['display_label']}).",
        str(bg.get("environment_intent") or "").strip(),
        "Creative strategy and environment intent only — no invented claims, "
        "endorsements, or product-truth overrides.",
    ]
    return " ".join(p for p in parts if p)


@router.post("/prepare")
async def faceless_prepare(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Validate + resolve Hook/BG + create workspace execution package."""
    ref_count = 1
    if str(body.end_frame_asset_id or "").strip():
        ref_count = 2

    ok, code, detail = fl.validate_faceless_inputs(
        product_id=body.product_id,
        start_frame_asset_id=body.start_frame_asset_id,
        hook_id=body.hook_id,
        background_id=body.background_id,
        reference_count=ref_count,
    )
    if not ok:
        raise HTTPException(
            status_code=422,
            detail={"error_code": code, "message": detail},
        )

    try:
        resolution = fl.build_faceless_resolution(
            hook_id=body.hook_id,
            background_id=body.background_id,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
            scene_context_hint=body.scene_context_hint,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "ERR_FACELESS_RESOLVE", "message": str(exc)},
        ) from exc

    scene_context = _scene_context_from_resolution(resolution)
    # Prefer structured environment intent as primary scene context when present.
    env = str(resolution["background"].get("environment_intent") or "").strip()
    if env:
        scene_context = (
            f"{env} "
            f"Strategy {resolution['hook']['setting_id']}: "
            f"{resolution['hook'].get('strategy_intent') or resolution['hook']['display_label']}. "
            "No invented claims or product-truth overrides."
        )

    try:
        gen_mode = str(body.generation_mode or "SINGLE").upper()
        if gen_mode not in ("SINGLE", "EXTEND"):
            gen_mode = "SINGLE"
        duration = int(body.duration_seconds or 8)
        total = body.requested_total_duration_seconds
        if gen_mode == "EXTEND":
            # First block is 8s independent; total drives plan authority.
            duration = 8
            if total is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "ERR_FACELESS_EXTEND_TOTAL_REQUIRED",
                        "message": "Extend requires requested_total_duration_seconds",
                    },
                )
        model = str(body.model or "").strip() or "Veo 3.1 - Lite"
        pkg = await create_workspace_execution_package(
            product_id=body.product_id,
            mode=fl.FACELESS_TRANSPORT_MODE,
            duration_seconds=duration,
            aspect_ratio=body.aspect_ratio,
            model=model,
            manual_override=False,
            generation_mode=gen_mode,
            character_presence=fl.FACELESS_CHARACTER_PRESENCE,
            creator_persona="DEFAULT_CREATOR",
            source_mode=fl.FACELESS_SOURCE_MODE,
            start_frame_asset_id=body.start_frame_asset_id,
            end_frame_asset_id=body.end_frame_asset_id,
            avatar_id=None,
            scene_context_override=scene_context,
            copy_set_id=body.copy_set_id,
            copy_fallback_confirmed=body.copy_fallback_confirmed,
            requested_total_duration_seconds=int(total) if total is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 — surface package errors as 422/400
        msg = str(exc)
        status = 422 if "required" in msg.lower() or "ERR_" in msg else 400
        raise HTTPException(status_code=status, detail=msg) from exc

    return {
        "ok": True,
        "lane": fl.FACELESS_SURFACE_MODE,
        "surface": "PRODUCT_HANDS_BODY_NO_AVATAR",
        "transport_mode": fl.FACELESS_TRANSPORT_MODE,
        "source_mode": fl.FACELESS_SOURCE_MODE,
        "character_presence": fl.FACELESS_CHARACTER_PRESENCE,
        "generation_mode": str(body.generation_mode or "SINGLE").upper(),
        "model": str(body.model or "").strip() or "Veo 3.1 - Lite",
        "duration_seconds": int(body.duration_seconds or 8),
        "requested_total_duration_seconds": body.requested_total_duration_seconds,
        "resolution": {
            "hook": resolution["hook"],
            "background": resolution["background"],
        },
        "scene_context_override": scene_context,
        "package": pkg if isinstance(pkg, dict) else pkg,
    }


@router.post("/validate")
async def faceless_validate(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Credit-free fail-closed validation + resolve preview (no package write)."""
    ref_count = 2 if str(body.end_frame_asset_id or "").strip() else 1
    ok, code, detail = fl.validate_faceless_inputs(
        product_id=body.product_id,
        start_frame_asset_id=body.start_frame_asset_id,
        hook_id=body.hook_id,
        background_id=body.background_id,
        reference_count=ref_count,
    )
    if not ok:
        return {"ok": False, "error_code": code, "detail": detail}
    resolution = fl.build_faceless_resolution(
        hook_id=body.hook_id,
        background_id=body.background_id,
        product_cluster=body.product_cluster,
        has_approved_usp=body.has_approved_usp,
        scene_context_hint=body.scene_context_hint,
    )
    return {
        "ok": True,
        "resolution": {
            "hook": resolution["hook"],
            "background": resolution["background"],
        },
        "scene_context_override": _scene_context_from_resolution(resolution),
    }
