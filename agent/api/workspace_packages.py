from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.services.prompt_compiler_runtime_config_service import (
    get_runtime_config,
)
from agent.services.workspace_execution_package_service import (
    compile_workspace_prompt_preview,
    create_workspace_execution_package,
    list_workspace_execution_packages,
)
from agent.services.i2v_semantic_slot_resolver_service import (
    resolve_i2v_semantic_slots,
)
from agent.models.i2v_semantic_slot_resolver import (
    I2VSemanticSlotResolverRequest,
)
from agent.services.approved_product_package_service import (
    get_product_package_readiness,
    normalize_mode,
)


router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspacePromptBlockRequest(BaseModel):
    block_index: int
    duration_seconds: int


class WorkspaceExecutionPackageRequest(BaseModel):
    product_id: str
    mode: str
    duration_seconds: int = 8
    aspect_ratio: str = "9:16"
    model: str = ""
    manual_override: bool = False
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = True
    dialogue_enabled: bool = True
    recipe_id: str = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
    product_reference_asset_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_context_reference_asset_id: str | None = None
    style_reference_asset_id: str | None = None
    blocks: list[WorkspacePromptBlockRequest] = Field(default_factory=list)
    # WPS Blocking Template enforcement (optional; engine VENDOR, distinct from
    # `mode`). When set, the compiler resolves the deterministic block chain.
    engine_duration_target: str | None = None
    requested_total_duration_seconds: int | None = None


class WorkspacePromptCompileRequest(BaseModel):
    product_id: str
    mode: str
    duration_seconds: int = 8
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = True
    dialogue_enabled: bool = True
    blocks: list[WorkspacePromptBlockRequest] = Field(default_factory=list)
    # WPS Blocking Template enforcement (optional; engine VENDOR, distinct from
    # `mode`). When set, the compiler resolves the deterministic block chain.
    engine_duration_target: str | None = None
    requested_total_duration_seconds: int | None = None


class WorkspacePackageReadinessRequest(BaseModel):
    mode: str
    product_ids: list[str]


@router.post("/execution-package")
async def post_workspace_execution_package(request: WorkspaceExecutionPackageRequest):
    try:
        return await create_workspace_execution_package(
            product_id=request.product_id,
            mode=request.mode,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            model=request.model,
            manual_override=request.manual_override,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            recipe_id=request.recipe_id,
            product_reference_asset_id=request.product_reference_asset_id,
            character_reference_asset_id=request.character_reference_asset_id,
            scene_context_reference_asset_id=request.scene_context_reference_asset_id,
            style_reference_asset_id=request.style_reference_asset_id,
            blocks=[block.model_dump() for block in request.blocks],
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/execution-packages")
async def get_workspace_execution_packages(
    product_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    return await list_workspace_execution_packages(product_id=product_id, mode=mode, limit=limit)


@router.post("/package-readiness")
async def post_workspace_package_readiness(
    request: WorkspacePackageReadinessRequest,
):
    normalized_mode = normalize_mode(request.mode)
    items = []
    for product_id in request.product_ids:
        items.append(await get_product_package_readiness(product_id, normalized_mode))
    return {
        "mode": normalized_mode,
        "items": items,
    }


@router.get("/prompt-compiler-config")
async def get_workspace_prompt_compiler_config():
    return get_runtime_config()


@router.post("/ugc-video-prompt-compile")
async def post_workspace_prompt_compile(request: WorkspacePromptCompileRequest):
    try:
        return await compile_workspace_prompt_preview(
            product_id=request.product_id,
            mode=request.mode,
            duration_seconds=request.duration_seconds,
            generation_mode=request.generation_mode,
            target_language=request.target_language,
            camera_style=request.camera_style,
            character_presence=request.character_presence,
            creator_persona=request.creator_persona,
            overlay_enabled=request.overlay_enabled,
            dialogue_enabled=request.dialogue_enabled,
            blocks=[block.model_dump() for block in request.blocks],
            engine_duration_target=request.engine_duration_target,
            requested_total_duration_seconds=request.requested_total_duration_seconds,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/i2v/resolve-slots")
async def post_i2v_semantic_slot_resolver(
    request: I2VSemanticSlotResolverRequest,
):
    try:
        return await resolve_i2v_semantic_slots(request=request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message in {"PRODUCT_NOT_FOUND", "CREATIVE_ASSET_NOT_FOUND"} else 409
        raise HTTPException(status_code=status_code, detail=message) from exc
