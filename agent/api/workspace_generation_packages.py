"""API router for workspace_generation_package (Prompt Handoff Bank)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
import json

# Known blocker codes that map to 409 Conflict (not 500 Internal Error).
_BLOCKER_409 = frozenset({
    "REFERENCE_ONLY_PRODUCT",
    "CLAIM_SAFE_PACKAGE_NOT_READY",
    "PRODUCTION_APPROVAL_REQUIRED",
    "PRODUCT_ARCHIVED",
    "PACKAGE_SCAN_FAILED",
    "UNSUPPORTED_MODE",
    "START_FRAME_REQUIRED",
    "SUBJECT_REQUIRED",
})

# Known error codes that map to 404 Not Found.
_ERROR_404 = frozenset({
    "PRODUCT_NOT_FOUND",
    "EXECUTION_PACKAGE_NOT_FOUND",
    "GENERATION_PACKAGE_NOT_FOUND",
})


def _http_exc_for(exc: Exception) -> HTTPException:
    """Convert a ValueError blocker into a structured 409/404 or fall back to 500."""
    message = str(exc)
    if isinstance(exc, ValueError):
        if message in _BLOCKER_409:
            return HTTPException(
                status_code=409,
                detail={"blocker": message, "error": message},
            )
        if message in _ERROR_404:
            return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=500, detail=message)

from agent.models.workspace_generation_package import (
    F2VGenerationPackageRequest,
    I2VGenerationPackageRequest,
    WorkspaceGenerationPackagePatchRequest,
)
from pydantic import BaseModel as _BaseModel
from typing import List as _List

from agent.services.workspace_generation_package_service import (
    create_f2v_generation_package,
    create_i2v_generation_package,
    create_t2v_generation_package,
    create_img_generation_package,
    get_workspace_generation_package,
    list_workspace_generation_packages,
    start_batch_generation,
    start_batch_prompt_run,
    get_batch_generation_run_status,
    list_batch_generation_runs,
    cancel_batch_generation_run,
    retry_batch_generation_run,
    create_scheduled_batch_run,
    list_scheduled_batch_runs_service,
    cancel_scheduled_batch_run,
)

router = APIRouter(prefix="/workspace/generation-packages", tags=["workspace-generation-packages"])


class T2VGenerationPackageRequest(_BaseModel):
    product_id: str
    workspace_execution_package_id: str | None = None
    generation_mode: str = "SINGLE"
    duration_seconds: int = 8
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True
    blocks: list = []
    engine_duration_target: str | None = None  # GOOGLE_FLOW | GROK
    requested_total_duration_seconds: int | None = None  # workbook derives N blocks
    operator_notes: str | None = None


class IMGGenerationPackageRequest(_BaseModel):
    product_id: str
    workspace_execution_package_id: str | None = None
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True
    subject_asset_id: str | None = None
    subject_preview_url: str | None = None
    subject_download_url: str | None = None
    scene_context_asset_id: str | None = None
    scene_context_preview_url: str | None = None
    scene_context_download_url: str | None = None
    style_asset_id: str | None = None
    style_preview_url: str | None = None
    style_download_url: str | None = None
    operator_notes: str | None = None


class BatchGenerationRequest(_BaseModel):
    product_id: str
    product_ids: _List[str] = []  # P3A: multi-product; overrides product_id when non-empty
    modes: _List[str] = ["F2V"]
    quantity_per_mode: int = 10
    interval_seconds: int = 5
    generation_mode: str = "SINGLE"
    # P1: Creative Library asset slots for combination matrix
    character_asset_ids: _List[str] = []
    scene_asset_ids: _List[str] = []
    style_asset_ids: _List[str] = []
    # P2A: IMG custom photorealistic prompt template (use {character_dna}, {scene_context_dna}, {style_mood_dna})
    img_prompt_template: str | None = None


@router.get("")
async def list_packages(
    mode: str | None = Query(None),
    status: str | None = Query(None),
    product_id: str | None = Query(None),
    batch_run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List saved workspace generation packages with optional filters."""
    try:
        packages = await list_workspace_generation_packages(
            mode=mode, status=status, product_id=product_id, batch_run_id=batch_run_id, limit=limit
        )
        return {"packages": packages, "count": len(packages)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/f2v")
async def create_f2v_package(request: F2VGenerationPackageRequest):
    """Create a durable F2V generation package (Prompt Handoff Bank entry)."""
    try:
        package = await create_f2v_generation_package(
            product_id=request.product_id,
            workspace_execution_package_id=request.workspace_execution_package_id,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            source_mode=request.source_mode,
            blocks=request.blocks,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            start_frame_asset_id=request.start_frame_asset_id,
            start_frame_preview_url=request.start_frame_preview_url,
            start_frame_download_url=request.start_frame_download_url,
            end_frame_asset_id=request.end_frame_asset_id,
            end_frame_preview_url=request.end_frame_preview_url,
            end_frame_download_url=request.end_frame_download_url,
            operator_notes=request.operator_notes,
        )
        return package
    except Exception as exc:
        raise _http_exc_for(exc) from exc


@router.post("/i2v")
async def create_i2v_package(request: I2VGenerationPackageRequest):
    """Create a durable I2V generation package (Prompt Handoff Bank entry)."""
    try:
        package = await create_i2v_generation_package(
            product_id=request.product_id,
            workspace_execution_package_id=request.workspace_execution_package_id,
            recipe_id=request.recipe_id,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=overlay_enabled if (overlay_enabled := request.overlay_enabled) is not None else False,  # NO_OVERLAY law
            dialogue_enabled=request.dialogue_enabled,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            product_reference_asset_id=request.product_reference_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
            style_reference_asset_id=request.style_reference_asset_id,
            operator_notes=request.operator_notes,
        )
        return package
    except Exception as exc:
        raise _http_exc_for(exc) from exc


@router.post("/from-execution-package")
async def create_from_execution_package(
    workspace_execution_package_id: str = Query(...),
    mode: str = Query("F2V"),
):
    """Convenience: look up an execution package and seed a generation package from it."""
    from agent.db import crud as _crud

    try:
        wep = await _crud.get_workspace_generation_package(workspace_execution_package_id)
        if not wep:
            # Try execution package table
            from agent.db.schema import get_db
            db = await get_db()
            cur = await db.execute(
                "SELECT * FROM workspace_execution_package WHERE workspace_execution_package_id=?",
                (workspace_execution_package_id,),
            )
            row = await cur.fetchone()
            wep = dict(row) if row else None

        if not wep:
            raise HTTPException(status_code=404, detail=f"Execution package {workspace_execution_package_id!r} not found")

        product_id = wep.get("product_id", "")
        wep_mode = mode or wep.get("mode", "F2V")
        lineage = wep.get("request_lineage_payload") or {}
        if isinstance(lineage, str):
            try:
                lineage = json.loads(lineage or "{}")
            except json.JSONDecodeError:
                lineage = {}
        compiler = lineage.get("compiler") or {}
        source_mode = compiler.get("source_mode")
        # Inherit the resolved plan from the execution package so the seeded
        # handoff agrees on the same block count (workbook authority parity).
        _seed_total = compiler.get("total_duration_seconds")
        _seed_plan_kwargs: dict = (
            {
                "generation_mode": "EXTEND",
                "engine_duration_target": "GOOGLE_FLOW",
                "requested_total_duration_seconds": int(_seed_total),
            }
            if (
                compiler.get("generation_mode") == "EXTEND"
                and isinstance(_seed_total, (int, float))
                and int(_seed_total) > 8
            )
            else {}
        )

        # Preserve the WEP's RESOLVED asset slots. The execution package already
        # resolved each slot to a reviewed asset (e.g. an APPROVED 9:16 composite
        # start frame); seeding the generation package without them silently
        # re-defaults every slot to the raw product-image — which the aspect gate
        # then (correctly) blocks. Live: wep_c35fff00bc18ef8b resolved start_frame
        # -> ca_e468d188d12d4343, but the bridged wgp_7026a574a51a63c0 carried
        # product-image:* and dry-ran blocked SLOT_ASPECT_MISMATCH.
        _wep_slots = wep.get("asset_slots") or []
        if isinstance(_wep_slots, str):
            try:
                _wep_slots = json.loads(_wep_slots or "[]")
            except json.JSONDecodeError:
                _wep_slots = []
        _slot_asset: dict = {}
        for _slot in _wep_slots if isinstance(_wep_slots, list) else []:
            _ra = (_slot or {}).get("resolved_asset") or {}
            if _slot.get("slot_key") and _ra.get("asset_id"):
                _slot_asset[_slot["slot_key"]] = _ra["asset_id"]

        if wep_mode == "F2V":
            package = await create_f2v_generation_package(
                product_id=product_id,
                workspace_execution_package_id=workspace_execution_package_id,
                source_mode=source_mode,
                start_frame_asset_id=_slot_asset.get("start_frame"),
                end_frame_asset_id=_slot_asset.get("end_frame"),
                **_seed_plan_kwargs,
            )
        elif wep_mode == "I2V":
            # I2V WEP slot keys are subject/scene/style; the seeding service's
            # resolver takes reference-asset ids. subject may be the auto-seeded
            # product-image:* ref — that is NOT a creative-asset id; leave it
            # None so the resolver's own product auto-seed applies.
            def _ca_only(value: str | None) -> str | None:
                return value if value and not str(value).startswith("product-image:") else None
            package = await create_i2v_generation_package(
                product_id=product_id,
                workspace_execution_package_id=workspace_execution_package_id,
                product_reference_asset_id=_ca_only(_slot_asset.get("product_reference")),
                character_reference_asset_id=_ca_only(
                    _slot_asset.get("character_reference") or _slot_asset.get("subject")),
                scene_context_reference_asset_id=_ca_only(
                    _slot_asset.get("scene_context_reference") or _slot_asset.get("scene")),
                style_reference_asset_id=_ca_only(
                    _slot_asset.get("style_reference") or _slot_asset.get("style")),
                **_seed_plan_kwargs,
            )
        elif wep_mode == "T2V":
            package = await create_t2v_generation_package(
                product_id=product_id,
                workspace_execution_package_id=workspace_execution_package_id,
                **_seed_plan_kwargs,
            )
        elif wep_mode == "IMG":
            package = await create_img_generation_package(
                product_id=product_id,
                workspace_execution_package_id=workspace_execution_package_id,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported mode {wep_mode!r} for from-execution-package")

        return package
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/t2v")
async def create_t2v_package(request: T2VGenerationPackageRequest):
    """Create a durable T2V generation package (Prompt Handoff Bank entry)."""
    try:
        package = await create_t2v_generation_package(
            product_id=request.product_id,
            workspace_execution_package_id=request.workspace_execution_package_id,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            blocks=request.blocks,
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
            operator_notes=request.operator_notes,
        )
        return package
    except Exception as exc:
        raise _http_exc_for(exc) from exc


@router.post("/img")
async def create_img_package(request: IMGGenerationPackageRequest):
    """Create a durable IMG generation package (Prompt Handoff Bank entry)."""
    try:
        package = await create_img_generation_package(
            product_id=request.product_id,
            workspace_execution_package_id=request.workspace_execution_package_id,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            subject_asset_id=request.subject_asset_id,
            subject_preview_url=request.subject_preview_url,
            subject_download_url=request.subject_download_url,
            scene_context_asset_id=request.scene_context_asset_id,
            scene_context_preview_url=request.scene_context_preview_url,
            scene_context_download_url=request.scene_context_download_url,
            style_asset_id=request.style_asset_id,
            style_preview_url=request.style_preview_url,
            style_download_url=request.style_download_url,
            operator_notes=request.operator_notes,
        )
        return package
    except Exception as exc:
        raise _http_exc_for(exc) from exc


@router.post("/batch")
async def start_batch(request: BatchGenerationRequest):
    """Start a batch generation run. Returns immediately with batch_run_id for polling."""
    valid_modes = {"F2V", "I2V", "T2V", "IMG"}
    bad = [m for m in request.modes if m not in valid_modes]
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid modes: {bad}. Must be one of {sorted(valid_modes)}")
    if request.quantity_per_mode < 1 or request.quantity_per_mode > 100:
        raise HTTPException(status_code=400, detail="quantity_per_mode must be 1–100")
    if request.interval_seconds < 0 or request.interval_seconds > 60:
        raise HTTPException(status_code=400, detail="interval_seconds must be 0–60")

    try:
        run = await start_batch_generation(
            product_id=request.product_id,
            product_ids=request.product_ids or None,
            modes=request.modes,
            quantity_per_mode=request.quantity_per_mode,
            interval_seconds=request.interval_seconds,
            generation_mode=request.generation_mode,
            character_asset_ids=request.character_asset_ids or [],
            scene_asset_ids=request.scene_asset_ids or [],
            style_asset_ids=request.style_asset_ids or [],
            img_prompt_template=request.img_prompt_template,
        )
        return {
            "ok": True,
            "batch_run_id": run.get("batch_run_id"),
            "total_expected": run.get("total_expected"),
            "estimated_seconds": run.get("total_expected", 0) * request.interval_seconds,
            "status": run.get("status"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batch")
async def list_batch_runs(
    product_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List recent batch generation runs."""
    try:
        runs = await list_batch_generation_runs(product_id=product_id, limit=limit)
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/batch/{batch_run_id}")
async def get_batch_run(batch_run_id: str):
    """Poll batch generation run status and progress."""
    run = await get_batch_generation_run_status(batch_run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Batch run {batch_run_id!r} not found")
    return run


@router.post("/batch/{batch_run_id}/cancel")
async def cancel_batch_run(batch_run_id: str):
    """Signal a running batch to stop after the current item."""
    run = await cancel_batch_generation_run(batch_run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Batch run {batch_run_id!r} not found")
    return run


@router.post("/batch/{batch_run_id}/retry")
async def retry_batch_run(batch_run_id: str):
    """Create a new batch run retrying failed items from the given run."""
    try:
        new_run = await retry_batch_generation_run(batch_run_id)
        if not new_run:
            raise HTTPException(status_code=404, detail=f"Batch run {batch_run_id!r} not found or has no stored config")
        return new_run
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Batch Prompt Builder (prompt/production split) ──────────────────────


class BatchPromptRequest(_BaseModel):
    """One batch prompt = ONE logical mode (mode law). Prompt generation only —
    no Google Flow execution, no credits."""
    product_id: str
    logical_mode: str  # T2V | HYBRID | F2V | I2V
    quantity: int = 10
    variation_strategy: str = "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS"
    interval_seconds: int = 5
    generation_mode: str = "SINGLE"
    duration_seconds: int = 8
    target_language: str = "BM_MS"
    avatar_codes: _List[str] = []
    character_asset_ids: _List[str] = []
    scene_asset_ids: _List[str] = []
    style_asset_ids: _List[str] = []
    scene_contexts: _List[str] = []
    hook_angles: _List[str] = []
    finished_frame_asset_id: str | None = None
    # Legacy guard: old clients sending a modes list are rejected on mixes.
    modes: _List[str] | None = None


@router.post("/batch-prompts")
async def start_batch_prompts(request: BatchPromptRequest):
    """Generate a batch prompt set into the Prompt Queue (Batch Prompt Builder)."""
    from agent.services import batch_prompt_planner as _planner

    if request.modes and len({m.strip().upper() for m in request.modes if m}) > 1:
        raise HTTPException(
            status_code=422,
            detail="MIXED_MODES_FORBIDDEN: one batch prompt uses exactly one mode",
        )
    logical_mode = (request.logical_mode or "").strip().upper()
    if logical_mode not in _planner.LOGICAL_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"UNSUPPORTED_LOGICAL_MODE:{request.logical_mode} (use {'/'.join(_planner.LOGICAL_MODES)})",
        )
    if request.interval_seconds < 0 or request.interval_seconds > 60:
        raise HTTPException(status_code=400, detail="interval_seconds must be 0–60")
    try:
        run = await start_batch_prompt_run(
            product_id=request.product_id,
            logical_mode=logical_mode,
            quantity=request.quantity,
            variation_strategy=request.variation_strategy,
            interval_seconds=request.interval_seconds,
            generation_mode=request.generation_mode,
            duration_seconds=request.duration_seconds,
            target_language=request.target_language,
            avatar_codes=request.avatar_codes or None,
            character_asset_ids=request.character_asset_ids or None,
            scene_asset_ids=request.scene_asset_ids or None,
            style_asset_ids=request.style_asset_ids or None,
            scene_contexts=request.scene_contexts or None,
            hook_angles=request.hook_angles or None,
            finished_frame_asset_id=request.finished_frame_asset_id,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("MODE_CONTRACT_VIOLATION:"):
            raise HTTPException(status_code=422, detail=message)
        raise _http_exc_for(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "ok": True,
        "batch_run_id": run.get("batch_run_id"),
        "logical_mode": run.get("logical_mode"),
        "variation_strategy": run.get("variation_strategy"),
        "total_expected": run.get("total_expected"),
        "status": run.get("status"),
    }


class ApprovePackagesRequest(_BaseModel):
    package_ids: _List[str]


@router.post("/approve")
async def approve_packages_endpoint(request: ApprovePackagesRequest):
    """Approve reviewed prompt packages for production (no execution yet)."""
    from agent.services.production_queue_service import approve_packages

    if not request.package_ids:
        raise HTTPException(status_code=422, detail="package_ids is required")
    return await approve_packages(request.package_ids)


@router.get("/duration-authority")
async def duration_authority(engine: str = Query("GOOGLE_FLOW")):
    """Authoritative batch-prompt durations from the WPS workbook (ADR-008).

    The Batch Prompt Builder duration selector reads THIS list; arbitrary
    durations are rejected server-side by start_batch_prompt_run."""
    from agent.services.workspace_generation_package_service import allowed_batch_durations

    durations = allowed_batch_durations(engine=engine)
    if not durations:
        raise HTTPException(status_code=404, detail=f"NO_DURATION_AUTHORITY_FOR_ENGINE:{engine}")
    return {
        "engine": engine,
        "allowed_durations": durations,
        "source": "agent/authority/wps_blocking_authority.json",
    }


# ── Scheduled batch runs ─────────────────────────────────────────────────────


class ScheduledBatchRequest(_BaseModel):
    product_ids: _List[str]
    modes: _List[str] = ["F2V"]
    quantity_per_mode: int = 10
    interval_seconds: int = 5
    generation_mode: str = "SINGLE"
    character_asset_ids: _List[str] = []
    scene_asset_ids: _List[str] = []
    style_asset_ids: _List[str] = []
    img_prompt_template: str | None = None
    scheduled_at: str  # ISO 8601 UTC, e.g. "2026-05-25T02:00:00Z"
    label: str | None = None


@router.get("/scheduled")
async def list_scheduled_runs(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List scheduled batch runs (upcoming + recent)."""
    try:
        runs = await list_scheduled_batch_runs_service(status=status, limit=limit)
        return {"runs": runs, "count": len(runs)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scheduled")
async def create_scheduled_run(request: ScheduledBatchRequest):
    """Create a scheduled batch run to fire at a specific UTC datetime."""
    if not request.product_ids:
        raise HTTPException(status_code=400, detail="product_ids must not be empty")
    if not request.modes:
        raise HTTPException(status_code=400, detail="modes must not be empty")
    try:
        run = await create_scheduled_batch_run(
            product_ids=request.product_ids,
            modes=request.modes,
            quantity_per_mode=request.quantity_per_mode,
            interval_seconds=request.interval_seconds,
            generation_mode=request.generation_mode,
            character_asset_ids=request.character_asset_ids or None,
            scene_asset_ids=request.scene_asset_ids or None,
            style_asset_ids=request.style_asset_ids or None,
            img_prompt_template=request.img_prompt_template,
            scheduled_at=request.scheduled_at,
            label=request.label,
        )
        return run
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/scheduled/{scheduled_run_id}", status_code=200)
async def cancel_scheduled_run(scheduled_run_id: str):
    """Cancel a pending scheduled batch run."""
    run = await cancel_scheduled_batch_run(scheduled_run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Scheduled run {scheduled_run_id!r} not found")
    return run


# ── Dynamic routes MUST come last — static paths above take priority ──────────

@router.get("/{package_id}")
async def get_package(package_id: str):
    """Get a workspace generation package by ID."""
    try:
        package = await get_workspace_generation_package(package_id)
        if not package:
            raise HTTPException(status_code=404, detail=f"Package {package_id!r} not found")
        return package
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/{package_id}")
async def patch_package(package_id: str, request: WorkspaceGenerationPackagePatchRequest):
    """Patch a workspace generation package (status / operator_notes)."""
    from agent.db import crud

    try:
        existing = await get_workspace_generation_package(package_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Package {package_id!r} not found")
        kw: dict = {}
        if request.status is not None:
            allowed = {"DRAFT", "READY_MANUAL", "READY_DOM_STAGED", "BLOCKED", "ARCHIVED"}
            if request.status not in allowed:
                raise HTTPException(status_code=400, detail=f"Invalid status {request.status!r}")
            kw["status"] = request.status
        if request.operator_notes is not None:
            kw["operator_notes"] = request.operator_notes
        if kw:
            kw["updated_at"] = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            updated = await crud.update_workspace_generation_package(package_id, **kw)
            return updated
        return existing
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{package_id}", status_code=204)
async def delete_package(package_id: str):
    """Delete a workspace generation package permanently."""
    from agent.db import crud
    from agent.db.schema import get_db

    try:
        existing = await get_workspace_generation_package(package_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Package {package_id!r} not found")
        db = await get_db()
        from agent.db.schema import _db_lock
        async with _db_lock:
            await db.execute(
                "DELETE FROM workspace_generation_package WHERE workspace_generation_package_id=?",
                (package_id,),
            )
            await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
