"""Faceless lane HTTP API — product-first prepare + canonical settings.

Operator chooses product, hook, background, SINGLE|EXTEND, model, duration.
Internal transport: F2V + HYBRID product-anchor (or FRAMES only when Advanced
override supplies a start frame). No new generation engine.
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
    # Optional Advanced override only — not required for normal product-first path
    start_frame_asset_id: Optional[str] = None
    end_frame_asset_id: Optional[str] = None
    hook_id: str = "AUTO"
    background_id: str = "AUTO"
    # Canonical Hybrid-parity settings (no hardcoded 8s / empty model)
    model: str = Field(..., min_length=1, description="Canonical video model ui_label")
    generation_mode: str = "SINGLE"  # SINGLE | EXTEND
    duration_seconds: Optional[int] = None  # SINGLE clip duration
    total_duration_seconds: Optional[int] = None  # EXTEND authorized total
    aspect_ratio: str = "9:16"
    copy_set_id: Optional[str] = None
    copy_fallback_confirmed: bool = True
    product_cluster: Optional[str] = None
    has_approved_usp: bool = False
    scene_context_hint: Optional[str] = None


@router.post("/prepare")
async def faceless_prepare(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Validate + resolve Hook/BG + create workspace execution package."""
    gen_mode = str(body.generation_mode or "SINGLE").strip().upper()
    reference_override = bool(str(body.start_frame_asset_id or "").strip())

    ok, code, detail = fl.validate_faceless_inputs(
        product_id=body.product_id,
        start_frame_asset_id=body.start_frame_asset_id,
        end_frame_asset_id=body.end_frame_asset_id,
        hook_id=body.hook_id,
        background_id=body.background_id,
        model=body.model,
        generation_mode=gen_mode,
        duration_seconds=body.duration_seconds,
        total_duration_seconds=body.total_duration_seconds,
        require_model=True,
        reference_override=reference_override,
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
            start_frame_asset_id=body.start_frame_asset_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "ERR_FACELESS_RESOLVE", "message": str(exc)},
        ) from exc

    scene_context = fl.build_faceless_scene_context(resolution)

    # Package duration: SINGLE uses clip duration; EXTEND packages base 8s block
    # (native-extend continues after base — same as Hybrid Laluan-A).
    if gen_mode == "EXTEND":
        pkg_duration = 8
        pkg_gen_mode = "SINGLE"  # base clip package; extend is separate authority
    else:
        pkg_duration = int(body.duration_seconds or 0)
        pkg_gen_mode = "SINGLE"

    source_mode = resolution["source_mode"]
    start_id = body.start_frame_asset_id if reference_override else None
    end_id = body.end_frame_asset_id if reference_override else None

    try:
        pkg = await create_workspace_execution_package(
            product_id=body.product_id,
            mode=fl.FACELESS_TRANSPORT_MODE,
            duration_seconds=pkg_duration,
            aspect_ratio=body.aspect_ratio,
            model=str(body.model).strip(),
            manual_override=False,
            generation_mode=pkg_gen_mode,
            character_presence=fl.FACELESS_CHARACTER_PRESENCE,
            creator_persona="DEFAULT_CREATOR",
            source_mode=source_mode,
            # HYBRID: product anchor from approved package (no start_frame ids)
            # FRAMES override: explicit composite start frame
            start_frame_asset_id=start_id,
            end_frame_asset_id=end_id,
            product_reference_asset_id=None,
            avatar_id=None,
            scene_context_override=scene_context,
            copy_set_id=body.copy_set_id,
            copy_fallback_confirmed=body.copy_fallback_confirmed,
        )
    except Exception as exc:  # noqa: BLE001 — surface package errors as 422/400
        msg = str(exc)
        status = 422 if "required" in msg.lower() or "ERR_" in msg else 400
        raise HTTPException(status_code=status, detail=msg) from exc

    return {
        "ok": True,
        "lane": fl.FACELESS_SURFACE_MODE,
        # Operator-facing (no transport chrome)
        "generation_mode": gen_mode,
        "model": str(body.model).strip(),
        "duration_seconds": body.duration_seconds,
        "total_duration_seconds": body.total_duration_seconds,
        "character_presence": fl.FACELESS_CHARACTER_PRESENCE,
        "avatar_id": None,
        "visual_law": fl.FACELESS_VISUAL_LAW,
        # Debug-only internals (still returned for audit, FE hides from normal UI)
        "debug": {
            "transport_mode": fl.FACELESS_TRANSPORT_MODE,
            "source_mode": source_mode,
            "reference_override": reference_override,
        },
        "resolution": {
            "hook": resolution["hook"],
            "background": resolution["background"],
        },
        "scene_context_override": scene_context,
        "package": pkg if isinstance(pkg, dict) else pkg,
        "extend_routing": (
            {
                "authority": "NATIVE_EXTEND",
                "base_clip_duration_seconds": 8,
                "total_duration_seconds": body.total_duration_seconds,
                "note": (
                    "After base clip completes, continue via existing native-extend "
                    "authority — do not multi-block through single /api/flow/generate."
                ),
            }
            if gen_mode == "EXTEND"
            else None
        ),
    }


@router.post("/validate")
async def faceless_validate(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Credit-free fail-closed validation + resolve preview (no package write)."""
    gen_mode = str(body.generation_mode or "SINGLE").strip().upper()
    reference_override = bool(str(body.start_frame_asset_id or "").strip())
    ok, code, detail = fl.validate_faceless_inputs(
        product_id=body.product_id,
        start_frame_asset_id=body.start_frame_asset_id,
        end_frame_asset_id=body.end_frame_asset_id,
        hook_id=body.hook_id,
        background_id=body.background_id,
        model=body.model,
        generation_mode=gen_mode,
        duration_seconds=body.duration_seconds,
        total_duration_seconds=body.total_duration_seconds,
        require_model=True,
        reference_override=reference_override,
    )
    if not ok:
        return {"ok": False, "error_code": code, "detail": detail}
    resolution = fl.build_faceless_resolution(
        hook_id=body.hook_id,
        background_id=body.background_id,
        product_cluster=body.product_cluster,
        has_approved_usp=body.has_approved_usp,
        scene_context_hint=body.scene_context_hint,
        start_frame_asset_id=body.start_frame_asset_id,
    )
    return {
        "ok": True,
        "generation_mode": gen_mode,
        "model": body.model,
        "resolution": {
            "hook": resolution["hook"],
            "background": resolution["background"],
        },
        "scene_context_override": fl.build_faceless_scene_context(resolution),
        "visual_law": fl.FACELESS_VISUAL_LAW,
    }
