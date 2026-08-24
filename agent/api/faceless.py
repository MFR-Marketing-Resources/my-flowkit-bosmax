"""Faceless lane HTTP API — product-first prepare + canonical settings.

Operator chooses product, opening strategy, background, SINGLE|EXTEND, model,
duration. ``hook_id`` remains the backward-compatible wire field.
Internal transport: F2V + HYBRID product-anchor for ordinary Faceless, the
exact-product scene-scaffold route uses T2V with server-side deterministic
compositing, and FRAMES remains an explicit advanced override.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

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


class FacelessProfileCertificationRequest(BaseModel):
    """One bounded representative proof for the shared active 8s profile."""

    product_id: str = Field(..., min_length=1)
    copy_id: str | None = None
    model: str = Field("veo_3_1_lite", min_length=1)
    duration_seconds: int = Field(8, ge=1)
    aspect_ratio: str = "9:16"
    confirm_live_credit_burn: bool = False
    maximum_provider_operations: int = Field(1, ge=1, le=1)
    max_retry_operations: int = Field(0, ge=0, le=0)
    request_id: str | None = None


class FacelessProfileCertificationFinalizeRequest(BaseModel):
    frame_qc: dict[str, Any]


async def _require_faceless_staff(staff_id: str | None) -> dict[str, Any]:
    from agent.services.staff_identity_service import (
        StaffIdentityError,
    )
    from agent.security.access_control import resolve_request_staff

    try:
        return await resolve_request_staff(staff_id)
    except StaffIdentityError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error_code": exc.code, "message": exc.message},
        ) from exc


def _require_profile_certification_owner():
    from agent.security.access_control import get_current_auth_context

    context = get_current_auth_context()
    roles = {str(role).upper() for role in (context.role_codes if context else ())}
    permissions = {
        str(permission) for permission in (context.permission_codes if context else ())
    }
    if context is None or "OWNER" not in roles or "production.execute" not in permissions:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PROFILE_CERTIFICATION_OWNER_REQUIRED",
                "message": "An authenticated OWNER with production.execute is required.",
            },
        )
    return context


def _current_runtime_proof() -> dict[str, Any]:
    from agent import runtime_release
    from agent.config import DB_PATH

    proof = runtime_release.resolve_provenance(runtime_release.source_root(), DB_PATH)
    if not proof.get("canonical_runtime") or not proof.get("runtime_sha"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "PROFILE_CERTIFICATION_RUNTIME_NOT_CANONICAL",
                "runtime": proof,
            },
        )
    return proof


@router.post("/profile-certification")
async def faceless_profile_certification(
    body: FacelessProfileCertificationRequest,
) -> dict[str, Any]:
    """Run exactly one authenticated active-Faceless profile proof.

    The endpoint creates and approves the current execution snapshot through
    the existing approval service, then dispatches the normal Faceless T2V
    scene-scaffold/compositor route with a bounded certification boundary. It
    never edits the model registry, direct-lane flags, or snapshot table.
    """

    owner = _require_profile_certification_owner()
    runtime = _current_runtime_proof()
    from agent.services.flow_client import get_flow_client
    from agent.services import make_video as _mv
    from agent.services import provider_certification_service as _certifications
    from agent.services import video_execution_profile_service as _profiles
    from agent.services import execution_approval_service as _eas
    from agent.services import copy_register_v2_service as _copy_register

    client = get_flow_client()
    if not client.connected:
        raise HTTPException(503, "PROFILE_CERTIFICATION_FLOW_TRANSPORT_NOT_CONNECTED")
    try:
        credits = await client.get_credits()
    except Exception as exc:  # noqa: BLE001 — no provider operation on quote failure
        raise HTTPException(
            502,
            detail={
                "error_code": "PROFILE_CERTIFICATION_CREDITS_QUOTE_FAILED",
                "message": str(exc),
            },
        ) from exc
    balance = _mv._capture_credit_balance(credits)
    if balance is None:
        raise HTTPException(
            502,
            detail={
                "error_code": "PROFILE_CERTIFICATION_CREDITS_QUOTE_UNPROVEN",
                "response": credits,
            },
        )

    if (
        body.model.strip() != "veo_3_1_lite"
        or body.duration_seconds != 8
        or body.aspect_ratio != "9:16"
        or body.confirm_live_credit_burn is not True
        or body.maximum_provider_operations != 1
        or body.max_retry_operations != 0
    ):
        raise HTTPException(
            422,
            detail={
                "error_code": "PROFILE_CERTIFICATION_TUPLE_INVALID",
                "required": {
                    "model": "veo_3_1_lite",
                    "duration_seconds": 8,
                    "aspect_ratio": "9:16",
                    "maximum_provider_operations": 1,
                    "max_retry_operations": 0,
                    "confirm_live_credit_burn": True,
                },
            },
        )

    prepared = await faceless_prepare(
        FacelessPrepareRequest(
            product_id=body.product_id,
            staff_id=owner.staff_id,
            model=body.model,
            generation_mode="SINGLE",
            duration_seconds=8,
            aspect_ratio="9:16",
            copy_v2_context={"lane": "FACELESS"},
        )
    )
    package = prepared.get("package") if isinstance(prepared, dict) else None
    if not isinstance(package, dict) or not package.get("execution_allowed"):
        raise HTTPException(
            422,
            detail={
                "error_code": "PROFILE_CERTIFICATION_PACKAGE_NOT_READY",
                "blockers": (package or {}).get("blockers") if isinstance(package, dict) else None,
            },
        )
    if prepared.get("selected_execution_route") != "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE":
        raise HTTPException(
            422,
            detail={
                "error_code": "PROFILE_CERTIFICATION_ACTIVE_ROUTE_REQUIRED",
                "selected_execution_route": prepared.get("selected_execution_route"),
            },
        )

    try:
        copy_resolution = await resolve_persisted_copy_execution_binding(
            body.product_id, "FACELESS", {"lane": "FACELESS"}
        )
        truth = await _copy_register.get_product_truth_proof(body.product_id)
        blueprint = await _copy_register.get_blueprint(
            copy_resolution.binding.blueprint_id,
            copy_resolution.binding.revision,
        ) if copy_resolution.binding is not None else None
    except Exception as exc:  # noqa: BLE001 — authority resolution is fail-closed
        raise HTTPException(
            409,
            detail={"error_code": "PROFILE_CERTIFICATION_AUTHORITY_RESOLUTION_FAILED", "message": str(exc)},
        ) from exc
    if not copy_resolution.ready or copy_resolution.binding is None:
        raise HTTPException(
            409,
            detail={
                "error_code": "PROFILE_CERTIFICATION_COPY_NOT_READY",
                "status": copy_resolution.status,
            },
        )
    copy_digest = (
        blueprint.approval_snapshot.blueprint_digest
        if blueprint is not None and blueprint.approval_snapshot is not None
        else None
    )
    if not copy_digest:
        raise HTTPException(
            409,
            detail={"error_code": "PROFILE_CERTIFICATION_COPY_DIGEST_UNPROVEN"},
        )
    copy_id = copy_resolution.binding.blueprint_id
    if body.copy_id and body.copy_id != copy_id:
        raise HTTPException(
            409,
            detail={
                "error_code": "PROFILE_CERTIFICATION_COPY_BINDING_MISMATCH",
                "resolved_copy_id": copy_id,
                "requested_copy_id": body.copy_id,
            },
        )
    product_digest = (
        (truth.get("product_truth") or {}).get("snapshot") or {}
    ).get("digest")
    if not truth.get("ready_for_copy") or not product_digest:
        raise HTTPException(
            409,
            detail={
                "error_code": "PROFILE_CERTIFICATION_PRODUCT_TRUTH_NOT_READY",
                "blockers": truth.get("blockers") or [],
            },
        )

    profile = _profiles.resolve_duration_model_profile(
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        logical_mode="T2V",
        source_mode="T2V",
        generation_mode="SINGLE",
        reference_count=0,
        prompt_block_count=1,
    )
    profile_context = _profiles.build_approval_context(
        profile,
        lane="FACELESS",
        product_digest=str(product_digest),
        copy_digest=copy_digest,
    )
    custody = package.get("product_visual_custody")
    execution_identity = package.get("faceless_execution_identity") or {
        "workspace_execution_package_id": package.get("workspace_execution_package_id"),
        "prompt_fingerprint": package.get("prompt_fingerprint"),
        "surface_lane": "FACELESS",
    }
    copy_binding = package.get("copy_execution_binding") or copy_resolution.binding.model_dump(
        mode="json"
    )
    prompt = str(package.get("prompt_text") or "").strip()
    if not prompt or not isinstance(custody, dict):
        raise HTTPException(
            422,
            detail={"error_code": "PROFILE_CERTIFICATION_PACKAGE_LINEAGE_INCOMPLETE"},
        )

    reservation, created = await _certifications.reserve_capture(
        profile=profile,
        representative_lane="FACELESS",
        product_id=body.product_id,
        copy_id=copy_id,
        product_digest=str(product_digest),
        copy_digest=copy_digest,
        sweetwps_digest=_profiles.sweetwps_digest(),
        compositor_digest=_profiles.compositor_digest(),
        compiler_digest=_profiles.compiler_digest(),
        lane_adapter_digest=_profiles.lane_adapter_digest("FACELESS"),
        runtime_sha=str(runtime["runtime_sha"]),
    )
    if not created:
        # The unique profile reservation is the no-resubmit guard. A completed
        # proof is reusable; every other state is returned for reconciliation.
        return {
            "status": reservation.get("status"),
            "certification": reservation,
            "profile": profile,
            "provider_calls": 0,
            "credit_spend": 0,
            "reused_reservation": True,
        }

    snapshot = None
    capture_request_id = body.request_id or ("pcert_" + uuid4().hex)
    try:
        snapshot = await _eas.create_review_snapshot(
            surface="FACELESS",
            logical_mode="T2V",
            final_prompt_text=prompt,
            product_id=body.product_id,
            source_mode="T2V",
            model="veo_3_1_lite",
            aspect="9:16",
            duration_s=8,
            count=1,
            execution_identity=execution_identity,
            execution_profile_context=profile_context,
            created_by=owner.staff_id,
        )
        snapshot = await _eas.approve_snapshot(
            snapshot["snapshot_id"], approved_by=owner.staff_id
        )
        result = await _mv.start_generate(
            "T2V",
            prompt,
            aspect="9:16",
            tier="PAYGATE_TIER_ONE",
            model="veo_3_1_lite",
            duration_s=8,
            num_videos=1,
            product_id=body.product_id,
            source_mode="T2V",
            staff_id=owner.staff_id,
            staff_display_name_snapshot=owner.display_name,
            copy_execution_binding=copy_binding,
            execution_identity=execution_identity,
            execution_profile_context=profile_context,
            product_visual_custody=custody,
            request_id=capture_request_id,
            idempotency_key=capture_request_id,
            production_recipe="FACELESS",
            surface_lane="FACELESS",
            confirm_live_credit_burn=True,
            maximum_provider_operations=1,
            max_retry_operations=0,
            profile_certification_capture=True,
        )
    except Exception as exc:  # noqa: BLE001 — no provider result is claimed
        await _certifications.mark_failed(
            reservation["certification_id"],
            code="PROFILE_CERTIFICATION_DISPATCH_FAILED",
            detail=str(exc),
        )
        raise HTTPException(
            409,
            detail={"error_code": "PROFILE_CERTIFICATION_DISPATCH_FAILED", "message": str(exc)},
        ) from exc
    if not isinstance(result, dict) or result.get("status") == "REJECTED" or not result.get("job_id"):
        await _certifications.mark_failed(
            reservation["certification_id"],
            code=(result or {}).get("error", "PROFILE_CERTIFICATION_DISPATCH_REJECTED")
            if isinstance(result, dict)
            else "PROFILE_CERTIFICATION_DISPATCH_REJECTED",
            detail=str(result),
        )
        if snapshot and snapshot.get("approval_state") == "APPROVED":
            await _eas.invalidate_snapshot(
                snapshot["snapshot_id"], reason="PROFILE_CERTIFICATION_DISPATCH_REJECTED"
            )
        raise HTTPException(409, detail=result or {"error_code": "PROFILE_CERTIFICATION_DISPATCH_REJECTED"})

    submitted = await _certifications.mark_submitted(
        reservation["certification_id"],
        job_id=result["job_id"],
        snapshot_id=snapshot["snapshot_id"],
    )
    return {
        "status": "SUBMITTED",
        "certification": submitted,
        "profile": profile,
        "snapshot": snapshot,
        "job": result,
        "credit_quote": {"balance_before": balance, "profile_cost_ceiling": 10},
        "provider_calls": 1,
        "credit_spend": "PENDING_ARTIFACT_DELTA",
    }


@router.post("/profile-certification/{job_id}/finalize")
async def finalize_faceless_profile_certification(
    job_id: str,
    body: FacelessProfileCertificationFinalizeRequest,
) -> dict[str, Any]:
    """Record owner-reviewed frame evidence for one returned certification artifact."""

    _require_profile_certification_owner()
    from agent.db import provider_certification_crud as _cert_crud
    from agent.services import make_video as _mv
    from agent.services import provider_certification_service as _certifications

    certification = await _cert_crud.get_by_job_id(job_id)
    if certification is None:
        raise HTTPException(404, "PROFILE_CERTIFICATION_NOT_FOUND")
    job = _mv.get_job(job_id)
    if job is None:
        job = await _mv.get_durable_job(job_id, reconcile=False)
    if not job:
        raise HTTPException(404, "PROFILE_CERTIFICATION_JOB_NOT_FOUND")
    try:
        result = await _certifications.finalize_capture(
            certification["certification_id"],
            job=job,
            frame_qc=body.frame_qc,
        )
    except _certifications.ProviderCertificationError as exc:
        raise HTTPException(
            409,
            detail={"error_code": exc.code, "message": str(exc), "details": exc.details},
        ) from exc
    return {
        "status": result.get("status"),
        "certification": result,
        "job": job,
    }


@router.post("/prepare")
async def faceless_prepare(body: FacelessPrepareRequest) -> dict[str, Any]:
    """Validate + resolve Hook/BG + create workspace execution package."""
    staff_profile = await _require_faceless_staff(body.staff_id)
    from agent.services.product_release_service import (
        ProductReleaseError,
        ensure_product_operationally_visible,
    )

    try:
        await ensure_product_operationally_visible(body.product_id, lane="FACELESS")
    except ProductReleaseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
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
    from agent.services.product_release_service import (
        ProductReleaseError,
        ensure_product_operationally_visible,
    )

    try:
        await ensure_product_operationally_visible(body.product_id, lane="FACELESS")
    except ProductReleaseError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
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
