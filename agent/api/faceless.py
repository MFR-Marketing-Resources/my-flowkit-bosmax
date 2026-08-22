"""Faceless lane HTTP API — product-first prepare + canonical settings.

Operator chooses product, opening strategy, background, SINGLE|EXTEND, model,
duration. ``hook_id`` remains the backward-compatible wire field.
Internal transport: F2V + HYBRID product-anchor for ordinary Faceless, the
exact-product scene-scaffold route uses T2V with server-side deterministic
compositing, and FRAMES remains an explicit advanced override.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services import faceless_lane_service as fl
from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
)
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled

router = APIRouter(prefix="/faceless", tags=["faceless"])


class FacelessPrepareRequest(BaseModel):
    product_id: str
    staff_id: Optional[str] = None
    # Optional Advanced override only — not required for normal product-first path
    start_frame_asset_id: Optional[str] = None
    end_frame_asset_id: Optional[str] = None
    hook_id: str = "AUTO"
    background_id: str = "AUTO"
    actor_profile: str = "AUTO"
    # Canonical Hybrid-parity settings (no hardcoded 8s / empty model)
    model: str = Field(..., min_length=1, description="Canonical video model ui_label")
    generation_mode: str = "SINGLE"  # SINGLE | EXTEND
    duration_seconds: Optional[int] = None  # SINGLE clip duration
    total_duration_seconds: Optional[int] = None  # EXTEND authorized total
    aspect_ratio: str = "9:16"
    copy_set_id: Optional[str] = None
    copy_fallback_confirmed: bool = False
    product_cluster: Optional[str] = None
    has_approved_usp: bool = False
    scene_context_hint: Optional[str] = None
    copy_v2_context: dict[str, Any] | None = None


async def _require_faceless_staff(staff_id: str | None) -> dict[str, Any]:
    from agent.services.staff_identity_service import (
        StaffIdentityError,
        resolve_staff_identity,
    )

    try:
        return await resolve_staff_identity(staff_id)
    except StaffIdentityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error_code": exc.code, "message": exc.message},
        ) from exc


@router.post("/prepare")
async def faceless_prepare(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Validate + resolve Hook/BG + create workspace execution package."""
    staff_profile = await _require_faceless_staff(body.staff_id)
    if body.copy_set_id and not legacy_copy_maintenance_enabled():
        raise HTTPException(
            status_code=410,
            detail={
                "error": "LEGACY_COPY_STORAGE_DISABLED",
                "message": "Faceless production accepts Copy Register V2 bindings only.",
            },
        )
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
        actor_profile=body.actor_profile,
        require_model=True,
        reference_override=reference_override,
    )
    if not ok:
        raise HTTPException(
            status_code=422,
            detail={"error_code": code, "message": detail},
        )

    ok_video, code_video, detail_video, orchestration = (
        fl.resolve_faceless_video_configuration(
            model=body.model,
            generation_mode=gen_mode,
            duration_seconds=body.duration_seconds,
            total_duration_seconds=body.total_duration_seconds,
        )
    )
    if not ok_video or not orchestration:
        raise HTTPException(
            status_code=422,
            detail={"error_code": code_video, "message": detail_video},
        )

    try:
        scene_authority = await fl.resolve_faceless_scene_authority(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
            actor_profile=body.actor_profile,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
            scene_context_hint=body.scene_context_hint,
        )
        resolution = fl.build_faceless_resolution(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
            actor_profile=body.actor_profile,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
            scene_context_hint=body.scene_context_hint,
            start_frame_asset_id=body.start_frame_asset_id,
            scene_authority=scene_authority,
        )
    except ValueError as exc:
        error_code = getattr(exc, "code", None) or str(exc).split(":", 1)[0]
        raise HTTPException(
            status_code=422,
            detail={"error_code": error_code, "message": str(exc)},
        ) from exc

    scene_context = fl.build_faceless_scene_context(resolution)

    # The package is the server-owned authority consumed by the durable full-video
    # lifecycle. EXTEND keeps the canonical multi-block compiler lineage; it is not
    # reduced to a SINGLE base package with a routing hint.
    pkg_duration = int(orchestration["engine_block_duration_seconds"])
    pkg_gen_mode = str(orchestration["generation_mode"])

    source_mode = resolution["source_mode"]
    transport_mode = resolution.get("transport_mode") or fl.FACELESS_TRANSPORT_MODE
    exact_product_video = resolution.get("exact_product_video")
    exact_faceless_route = bool(
        isinstance(exact_product_video, dict)
        and exact_product_video.get("selected_execution_route")
        == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    )
    start_id = body.start_frame_asset_id if reference_override else None
    end_id = body.end_frame_asset_id if reference_override else None

    # Exact-product Faceless requests are admitted only through the
    # deterministic scene-scaffold/composite route. This preflight is still
    # credit-free and performs no upload, approval, provider, or DB product
    # mutation. FRAMES remains an explicit finished-frame override.
    if source_mode != "FRAMES":
        from agent.services.product_visual_custody_service import (
            ProductVisualCustodyError,
            build_product_visual_custody_receipt,
            exact_product_required,
            validate_pre_dispatch_route,
        )
        from agent.services.product_visual_grounding_resolver import (
            ProductVisualReferenceRequiredError,
            build_official_product_visual_asset,
        )

        product_row = await crud.get_product(body.product_id)
        if product_row and exact_product_required(product_row):
            custody_receipt = None
            try:
                if not exact_faceless_route:
                    raise ProductVisualCustodyError(
                        "ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN",
                        "Exact Faceless product requires the deterministic composite route.",
                    )
                official_asset = build_official_product_visual_asset(
                    product_row,
                    slot_key="canonical_product_asset",
                    label="Canonical Product Truth cutout",
                )
                custody_receipt = build_product_visual_custody_receipt(
                    product_row,
                    official_asset,
                    mode=transport_mode,
                    source_mode=source_mode,
                    prompt="EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                    provider_route="EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                    generation_type="scene_video_scaffold_then_deterministic_composite",
                )
                validate_pre_dispatch_route(
                    custody_receipt,
                    provider_route="EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                    generation_type="scene_video_scaffold_then_deterministic_composite",
                )
            except ProductVisualReferenceRequiredError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED",
                        "message": str(exc),
                        "product_visual_custody": custody_receipt,
                    },
                ) from exc
            except ProductVisualCustodyError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                        "product_visual_custody": custody_receipt,
                    },
                ) from exc

    try:
        pkg = await create_workspace_execution_package(
            product_id=body.product_id,
            mode=transport_mode,
            duration_seconds=pkg_duration,
            aspect_ratio=body.aspect_ratio,
            model=str(body.model).strip(),
            manual_override=False,
            staff_id=staff_profile["staff_id"],
            staff_display_name_snapshot=staff_profile["display_name"],
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
            copy_v2_context=body.copy_v2_context,
            faceless_resolution=resolution.get("faceless_resolution"),
            requested_total_duration_seconds=(
                int(body.total_duration_seconds)
                if gen_mode == "EXTEND"
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 — surface package errors as 422/400
        msg = str(exc)
        status = 422 if "required" in msg.lower() or "ERR_" in msg else 400
        detail: Any = msg
        if getattr(exc, "code", None):
            detail = {
                "error_code": exc.code,
                "message": msg,
                "details": getattr(exc, "detail", None) or getattr(exc, "details", None),
            }
        raise HTTPException(status_code=status, detail=detail) from exc

    if not isinstance(pkg, dict) or not bool(pkg.get("execution_allowed")):
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "ERR_FACELESS_PACKAGE_BLOCKED",
                "message": "Workspace execution package is not execution-ready.",
                "blockers": (pkg.get("blockers") if isinstance(pkg, dict) else None),
                "product_visual_custody": (
                    pkg.get("product_visual_custody")
                    if isinstance(pkg, dict)
                    else None
                ),
            },
        )

    if not reference_override and not exact_faceless_route:
        start_asset = None
        for slot in pkg.get("asset_slots") or []:
            if slot.get("slot_key") == "start_frame":
                start_asset = slot.get("resolved_asset")
                break
        if not isinstance(start_asset, dict):
            start_asset = next(
                (
                    asset
                    for asset in (pkg.get("resolved_assets") or [])
                    if isinstance(asset, dict) and asset.get("slot_key") == "start_frame"
                ),
                None,
            )
        is_product_anchor = bool(
            (start_asset or {}).get("official_visual")
            or str((start_asset or {}).get("asset_source") or "").startswith(
                "PRODUCT_VISUAL_OFFICIAL"
            )
            or str((start_asset or {}).get("source") or "").startswith(
                "PRODUCT_VISUAL_OFFICIAL"
            )
        )
        has_transport = bool(
            (start_asset or {}).get("media_id")
            or (start_asset or {}).get("local_file_path")
            or (start_asset or {}).get("download_url")
            or (start_asset or {}).get("preview_url")
        )
        has_lineage = bool(
            (start_asset or {}).get("asset_fingerprint")
            and (start_asset or {}).get("asset_source")
        )
        if not is_product_anchor or not has_transport or not has_lineage:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "ERR_FACELESS_PRODUCT_ANCHOR_UNRESOLVED",
                    "message": (
                        "Approved product package did not resolve a transportable "
                        "start-frame anchor. Prepare is blocked until product image truth "
                        "is ready."
                    ),
                },
            )

    return {
        "ok": True,
        "lane": fl.FACELESS_SURFACE_MODE,
        "copy_policy": "REQUIRED",
        "copy_architecture_v2": (
            pkg.get("copy_architecture_v2") if isinstance(pkg, dict) else None
        ),
        # Operator-facing (no transport chrome)
        "generation_mode": gen_mode,
        "model": str(body.model).strip(),
        "duration_seconds": pkg_duration,
        "total_duration_seconds": body.total_duration_seconds,
        "character_presence": fl.FACELESS_CHARACTER_PRESENCE,
        "avatar_id": None,
        "actor_profile": resolution.get("actor_profile"),
        "visual_law": fl.FACELESS_VISUAL_LAW,
        "staff_id": staff_profile["staff_id"],
        "staff_display_name": staff_profile["display_name"],
        # Debug-only internals (still returned for audit, FE hides from normal UI)
        "debug": {
            "transport_mode": transport_mode,
            "source_mode": source_mode,
            "reference_override": reference_override,
            "provider_product_reference_forbidden": exact_faceless_route,
        },
        "selected_execution_route": pkg.get("selected_execution_route")
        or (exact_product_video or {}).get("selected_execution_route"),
        "generate_eligibility": pkg.get("generate_eligibility")
        if isinstance(pkg, dict)
        else None,
        "product_fidelity": (
            "EXACT_PRODUCT"
            if exact_faceless_route
            else "REFERENCE_CONDITIONED"
        ),
        "exact_product_video": pkg.get("exact_product_video")
        or exact_product_video,
        "product_visual_custody": pkg.get("product_visual_custody")
        if isinstance(pkg, dict)
        else None,
        "resolution": {
            "opening_strategy": resolution["opening_strategy"],
            # Backward-compatible response alias; never actual Copy V2 text.
            "hook": resolution["hook"],
            "background": resolution["background"],
            "scene_strategy": resolution.get("scene_strategy"),
            "choreography": resolution.get("choreography"),
        },
        "faceless_resolution": resolution.get("faceless_resolution"),
        "scene_context_override": scene_context,
        "package": pkg if isinstance(pkg, dict) else pkg,
        "durable_lifecycle": (
            {
                "plan": "/api/flow/video-jobs/plan",
                "authorize": "/api/flow/video-jobs/{job_id}/authorize",
                "start": "/api/flow/video-jobs/{job_id}/start",
                "status": "/api/flow/video-jobs/{job_id}/status",
                "base_clip_duration_seconds": pkg_duration,
                "total_duration_seconds": body.total_duration_seconds,
            }
            if gen_mode == "EXTEND"
            else None
        ),
    }


@router.post("/validate")
async def faceless_validate(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Credit-free fail-closed validation + resolve preview (no package write)."""
    staff_profile = await _require_faceless_staff(body.staff_id)
    gen_mode = str(body.generation_mode or "SINGLE").strip().upper()
    reference_override = bool(str(body.start_frame_asset_id or "").strip())
    try:
        v2_resolution = await resolve_persisted_copy_execution_binding(
            body.product_id,
            "FACELESS",
            body.copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "detail": exc.details or str(exc),
            "copy_policy": "REQUIRED",
            "copy_architecture_v2": None,
        }
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
        actor_profile=body.actor_profile,
        require_model=True,
        reference_override=reference_override,
    )
    if not ok:
        return {
            "ok": False,
            "error_code": code,
            "detail": detail,
            "copy_policy": "REQUIRED",
            "copy_architecture_v2": v2_resolution.to_metadata()
            if v2_resolution.v2_enabled
            else None,
        }
    ok_video, code_video, detail_video, orchestration = (
        fl.resolve_faceless_video_configuration(
            model=body.model,
            generation_mode=gen_mode,
            duration_seconds=body.duration_seconds,
            total_duration_seconds=body.total_duration_seconds,
        )
    )
    if not ok_video or not orchestration:
        return {
            "ok": False,
            "error_code": code_video,
            "detail": detail_video,
            "copy_policy": "REQUIRED",
            "copy_architecture_v2": v2_resolution.to_metadata()
            if v2_resolution.v2_enabled
            else None,
        }
    try:
        scene_authority = await fl.resolve_faceless_scene_authority(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
            actor_profile=body.actor_profile,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
            scene_context_hint=body.scene_context_hint,
        )
        resolution = fl.build_faceless_resolution(
            product_id=body.product_id,
            hook_id=body.hook_id,
            background_id=body.background_id,
            actor_profile=body.actor_profile,
            product_cluster=body.product_cluster,
            has_approved_usp=body.has_approved_usp,
            scene_context_hint=body.scene_context_hint,
            start_frame_asset_id=body.start_frame_asset_id,
            scene_authority=scene_authority,
        )
    except ValueError as exc:
        error_code = getattr(exc, "code", None) or str(exc).split(":", 1)[0]
        return {
            "ok": False,
            "error_code": error_code,
            "detail": str(exc),
            "copy_policy": "REQUIRED",
            "copy_architecture_v2": v2_resolution.to_metadata(
                consumer_context=body.copy_v2_context
            ) if v2_resolution.v2_enabled else None,
        }
    return {
        "ok": True,
        "copy_policy": "REQUIRED",
        "copy_architecture_v2": v2_resolution.to_metadata(
            consumer_context=body.copy_v2_context
        ) if v2_resolution.v2_enabled else None,
        "generation_mode": gen_mode,
        "model": body.model,
        "duration_seconds": orchestration["engine_block_duration_seconds"],
        "total_duration_seconds": body.total_duration_seconds,
        "actor_profile": resolution.get("actor_profile"),
        "selected_execution_route": (
            (resolution.get("exact_product_video") or {}).get(
                "selected_execution_route"
            )
            or resolution.get("transport_mode")
        ),
        "generate_eligibility": (
            (resolution.get("exact_product_video") or {}).get(
                "generate_eligibility"
            )
            if resolution.get("exact_product_video")
            else True
        ),
        "product_fidelity": (
            "EXACT_PRODUCT"
            if resolution.get("exact_product_video")
            else "REFERENCE_CONDITIONED"
        ),
        "exact_product_video": resolution.get("exact_product_video"),
        "debug": {
            "transport_mode": resolution.get("transport_mode"),
            "source_mode": resolution.get("source_mode"),
            "provider_product_reference_forbidden": bool(
                resolution.get("exact_product_video")
            ),
        },
        "resolution": {
            "opening_strategy": resolution["opening_strategy"],
            "hook": resolution["hook"],
            "background": resolution["background"],
            "scene_strategy": resolution.get("scene_strategy"),
            "choreography": resolution.get("choreography"),
        },
        "faceless_resolution": resolution.get("faceless_resolution"),
        "scene_context_override": fl.build_faceless_scene_context(resolution),
        "visual_law": fl.FACELESS_VISUAL_LAW,
        "staff_id": staff_profile["staff_id"],
        "staff_display_name": staff_profile["display_name"],
    }
