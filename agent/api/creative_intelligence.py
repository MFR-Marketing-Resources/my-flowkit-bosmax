"""Creative Intelligence API — Round 1 (avatar) + Round 2 (scene/image prompts)
+ Round 3 (camera/video presets).

Read-first, non-generative. Exposes:
  * GET  /api/creative-intelligence/avatar-recommendation       (by product_id OR category)
  * POST /api/creative-intelligence/avatar-fit/seed             (idempotent; dry-run default)
  * GET  /api/creative-intelligence/scene-prompt-recommendation (by product_id OR category)
  * POST /api/creative-intelligence/scene-prompt/seed           (idempotent; dry-run default)
  * GET  /api/creative-intelligence/camera-preset-recommendation (by product_id/category/cluster)
  * POST /api/creative-intelligence/camera-preset/seed          (idempotent; dry-run default)

No generation, no Product Truth / product-row / Copy Set / Copy Registry / Copy
Intelligence mutation. The seeds only write the config tables ``avatar_product_fit`` /
``creative_scene_prompt`` / ``creative_camera_preset``. Scene templates keep
``[AVATAR]``/``[PRODUCT]`` placeholders unresolved; camera presets are reference-only
and are never written to product camera columns or sent to generation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent.services import creative_avatar_recommendation_service as _svc
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera

router = APIRouter(prefix="/creative-intelligence", tags=["creative-intelligence"])


@router.get("/avatar-recommendation")
async def avatar_recommendation(
    product_id: str | None = None,
    category: str | None = None,
) -> dict:
    """Recommended AI avatars for a product or a raw category. Read-only —
    resolves category -> cluster and reuses avatar_fit_service. Never mutates."""
    if product_id:
        try:
            return await _svc.recommend_avatars_for_product(product_id)
        except ValueError as exc:
            if str(exc) == "PRODUCT_NOT_FOUND":
                raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
            raise
    if category is not None:
        return await _svc.recommend_avatars_for_category(category)
    raise HTTPException(status_code=422, detail="product_id or category is required")


@router.post("/avatar-fit/seed")
async def avatar_fit_seed(dry_run: bool = True) -> dict:
    """Seed avatar_product_fit from the pool-validated crosswalk. Idempotent;
    ``dry_run`` (default true) writes nothing and returns the plan. Only writes the
    avatar_product_fit config table — no Product Truth / Copy / generation effect."""
    return await _svc.seed_avatar_product_fit(dry_run=dry_run)


@router.get("/scene-prompt-recommendation")
async def scene_prompt_recommendation(
    product_id: str | None = None,
    category: str | None = None,
) -> dict:
    """Recommended scene / image-prompt templates for a product or a raw category.
    Read-only — resolves category -> canonical cluster (Round 1 resolver) and
    returns that cluster's templates from the committed library. Placeholders
    ``[AVATAR]``/``[PRODUCT]`` stay unresolved. Never mutates, never generates."""
    if product_id:
        try:
            return await _scene.recommend_scene_prompts_for_product(product_id)
        except ValueError as exc:
            if str(exc) == "PRODUCT_NOT_FOUND":
                raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
            raise
    if category is not None:
        return await _scene.recommend_scene_prompts_for_category(category)
    raise HTTPException(status_code=422, detail="product_id or category is required")


@router.post("/scene-prompt/seed")
async def scene_prompt_seed(dry_run: bool = True) -> dict:
    """Seed creative_scene_prompt from the reconciled library. Idempotent;
    ``dry_run`` (default true) writes nothing and returns the plan. Only writes the
    creative_scene_prompt config table — no Product Truth / Copy / generation
    effect. Templates are stored with placeholders unresolved."""
    return await _scene.seed_scene_prompts(dry_run=dry_run)


@router.get("/camera-preset-recommendation")
async def camera_preset_recommendation(
    product_id: str | None = None,
    category: str | None = None,
    cluster: str | None = None,
    block: str | None = None,
    content_type: str | None = None,
) -> dict:
    """Recommended camera / video presets for a product, category, or cluster.
    Read-only — returns the universal shot/angle/movement/e-comm/named-preset
    library plus the block-content -> preset mapping (optionally narrowed by
    ``block``/``content_type``). Never mutates, never writes product camera
    columns, never generates."""
    if product_id:
        try:
            return await _camera.recommend_camera_presets_for_product(
                product_id, block=block, content_type=content_type
            )
        except ValueError as exc:
            if str(exc) == "PRODUCT_NOT_FOUND":
                raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
            raise
    if category is not None:
        return await _camera.recommend_camera_presets_for_category(
            category, block=block, content_type=content_type
        )
    if cluster is not None:
        return await _camera.recommend_camera_presets_for_cluster(
            cluster, block=block, content_type=content_type
        )
    raise HTTPException(status_code=422, detail="product_id, category, or cluster is required")


@router.post("/camera-preset/seed")
async def camera_preset_seed(dry_run: bool = True) -> dict:
    """Seed creative_camera_preset from the ingested library. Idempotent;
    ``dry_run`` (default true) writes nothing and returns the plan. Only writes the
    creative_camera_preset config table — no Product Truth / product-row / Copy /
    generation effect."""
    return await _camera.seed_camera_presets(dry_run=dry_run)
