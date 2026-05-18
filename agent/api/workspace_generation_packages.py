"""API router for workspace_generation_package (Prompt Handoff Bank)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from agent.models.workspace_generation_package import (
    F2VGenerationPackageRequest,
    I2VGenerationPackageRequest,
    WorkspaceGenerationPackagePatchRequest,
)
from agent.services.workspace_generation_package_service import (
    create_f2v_generation_package,
    create_i2v_generation_package,
    get_workspace_generation_package,
    list_workspace_generation_packages,
)

router = APIRouter(prefix="/workspace/generation-packages", tags=["workspace-generation-packages"])


@router.get("")
async def list_packages(
    mode: str | None = Query(None),
    status: str | None = Query(None),
    product_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List saved workspace generation packages with optional filters."""
    try:
        packages = await list_workspace_generation_packages(
            mode=mode, status=status, product_id=product_id, limit=limit
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
            blocks=request.blocks,
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
        raise HTTPException(status_code=500, detail=str(exc))


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
            overlay_enabled=overlay_enabled if (overlay_enabled := request.overlay_enabled) is not None else True,
            dialogue_enabled=request.dialogue_enabled,
            product_reference_asset_id=request.product_reference_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
            style_reference_asset_id=request.style_reference_asset_id,
            operator_notes=request.operator_notes,
        )
        return package
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
    """Patch a workspace generation package (status only — no DOM execution)."""
    from agent.db import crud

    try:
        existing = await get_workspace_generation_package(package_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Package {package_id!r} not found")
        kw: dict = {}
        if request.status is not None:
            allowed = {"DRAFT", "READY_MANUAL", "READY_DOM_STAGED", "BLOCKED"}
            if request.status not in allowed:
                raise HTTPException(status_code=400, detail=f"Invalid status {request.status!r}")
            kw["status"] = request.status
        if kw:
            updated = await crud.update_workspace_generation_package(package_id, **kw)
            return updated
        return existing
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/from-execution-package")
async def create_from_execution_package(
    workspace_execution_package_id: str = Query(...),
    mode: str = Query("F2V"),
):
    """Convenience: look up an execution package and seed a generation package from it."""
    from agent.db import crud as _crud
    import json

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

        if wep_mode == "F2V":
            package = await create_f2v_generation_package(
                product_id=product_id,
                workspace_execution_package_id=workspace_execution_package_id,
            )
        elif wep_mode == "I2V":
            package = await create_i2v_generation_package(
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
