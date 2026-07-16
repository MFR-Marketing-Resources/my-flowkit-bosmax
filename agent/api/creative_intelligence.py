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
from pydantic import BaseModel

from agent.services import creative_avatar_recommendation_service as _svc
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera
from agent.services import creative_setup_service as _setup
from agent.services import creative_handoff_service as _handoff

router = APIRouter(prefix="/creative-intelligence", tags=["creative-intelligence"])


class CreativeSelectionSaveRequest(BaseModel):
    product_id: str
    selected_avatar_code: str | None = None
    selected_scene_template_id: str | None = None
    selected_camera_preset_code: str | None = None
    selected_block_purpose: str | None = None
    selected_content_type: str | None = None
    notes: str | None = None


class CreativeSelectionReviewRequest(BaseModel):
    product_id: str
    action: str  # APPROVE | REJECT
    reviewer_note: str | None = None


# Round 4/5 service error code -> HTTP status.
_SETUP_ERROR_STATUS = {
    "PRODUCT_NOT_FOUND": 404,
    "SELECTION_NOT_FOUND": 404,
    "INVALID_AVATAR_CODE": 422,
    "INVALID_SCENE_TEMPLATE_ID": 422,
    "INVALID_CAMERA_PRESET_CODE": 422,
    "INVALID_ACTION": 422,
    "NOT_IN_DRAFT": 409,
    "SELECTION_NOT_APPROVED": 409,  # Round 5: DRAFT/REJECTED cannot hand off
}


def _raise_setup_error(exc: ValueError):
    code = str(exc)
    status = _SETUP_ERROR_STATUS.get(code)
    if status:
        raise HTTPException(status_code=status, detail=code) from exc
    raise exc


@router.get("/registry-coverage")
async def registry_coverage() -> dict:
    """READ-ONLY coverage/usage lens for the Avatar + Scene authority pools.

    Aggregates the existing config tables (``avatar_product_fit`` /
    ``creative_scene_prompt`` / ``creative_camera_preset``) and the CSV-bridge
    pools against the canonical cluster list, so the Avatar/Scene Registry pages
    can show what is covered vs thin/missing. Reads only — never seeds, mutates,
    or calls a provider. Powers the Phase A registry coverage cards.
    """
    from agent.db import crud
    from agent.services import avatar_fit_service, avatar_registry, scene_context_registry

    canonical = _svc.canonical_clusters()

    # Avatar authority pool (CSV bridge) + product-fit coverage (R1).
    avatar_pool = avatar_registry.list_pool()
    fits = await crud.list_avatar_product_fits(limit=2000)
    fit_categories = {str(f.get("product_category") or "") for f in fits}
    avatar_covered = [
        c for c in canonical
        if avatar_fit_service.normalise_category(c) in fit_categories
    ]
    avatar_missing = [c for c in canonical if c not in avatar_covered]

    # Scene authority pool (CSV bridge) + scene-prompt coverage (R2).
    scene_pool = scene_context_registry.list_pool()
    prompts = await crud.list_creative_scene_prompts(limit=2000)
    prompt_clusters = {str(p.get("cluster") or "") for p in prompts}
    scene_covered = [c for c in canonical if c in prompt_clusters]
    scene_missing = [c for c in canonical if c not in prompt_clusters]

    presets = await crud.list_creative_camera_presets(limit=2000)
    block_groups = sorted(
        {str(p.get("block_group") or "") for p in presets if p.get("block_group")}
    )

    return {
        "canonical_clusters": canonical,
        "cluster_total": len(canonical),
        "product_total": await crud.count_products(),
        "avatar": {
            "pool_total": len(avatar_pool),
            "bridge_active": avatar_registry._BRIDGE_FILE.exists(),
            "fit_total": len(fits),
            "distinct_avatars_in_fit": len(
                {str(f.get("avatar_code") or "") for f in fits}
            ),
            "clusters_covered": avatar_covered,
            "clusters_missing": avatar_missing,
        },
        "scene": {
            "pool_total": len(scene_pool),
            "bridge_active": scene_context_registry._BRIDGE_FILE.exists(),
            "prompt_total": len(prompts),
            "clusters_covered": scene_covered,
            "clusters_missing": scene_missing,
        },
        "camera": {
            "preset_total": len(presets),
            "block_groups": block_groups,
        },
        "used_by": {
            "avatar": [
                "Avatar Recommendation (R1)",
                "Creative Setup (R4)",
                "Creative Handoff (R5)",
                "prompt compiler",
            ],
            "scene": [
                "Scene reference (IMG Fastlane / I2V scene-style)",
                "prompt compiler",
            ],
        },
    }


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


# --- Round 4: unified creative setup + saved selection (review-gated) ---


@router.get("/creative-setup")
async def creative_setup(product_id: str | None = None) -> dict:
    """Unified read-only creative setup for a product: recommended avatars +
    scene templates + camera presets, plus the saved selection (if any). Never
    mutates, never generates."""
    if not product_id:
        raise HTTPException(status_code=422, detail="product_id is required")
    try:
        return await _setup.resolve_creative_setup(product_id)
    except ValueError as exc:
        _raise_setup_error(exc)


@router.get("/creative-selection")
async def creative_selection_get(product_id: str | None = None) -> dict:
    """Return the product's saved creative selection (or ``{selection: null}``)."""
    if not product_id:
        raise HTTPException(status_code=422, detail="product_id is required")
    return {"product_id": product_id, "selection": await _setup.get_creative_selection(product_id)}


@router.post("/creative-selection")
async def creative_selection_save(req: CreativeSelectionSaveRequest) -> dict:
    """Create/update a product's creative selection (avatar + scene + camera),
    validated against the live pool/libraries. Starts review-gated at DRAFT.
    Only writes the creative_product_selection config table — no product-row /
    Product Truth / Copy / generation effect."""
    try:
        return await _setup.save_creative_selection(
            req.product_id,
            selected_avatar_code=req.selected_avatar_code,
            selected_scene_template_id=req.selected_scene_template_id,
            selected_camera_preset_code=req.selected_camera_preset_code,
            selected_block_purpose=req.selected_block_purpose,
            selected_content_type=req.selected_content_type,
            notes=req.notes,
        )
    except ValueError as exc:
        _raise_setup_error(exc)


@router.post("/creative-selection/review")
async def creative_selection_review(req: CreativeSelectionReviewRequest) -> dict:
    """Transition a DRAFT selection to APPROVED or REJECTED. Fail-closed on
    missing selection (404) or non-DRAFT status (409). No generation effect."""
    try:
        return await _setup.review_creative_selection(
            req.product_id, req.action, req.reviewer_note
        )
    except ValueError as exc:
        _raise_setup_error(exc)


# --- Round 5: gated generation handoff PREVIEW (APPROVED-only, read-only) ---


@router.get("/creative-handoff")
async def creative_handoff(product_id: str | None = None) -> dict:
    """Prepare a read-only generation handoff PREVIEW from an APPROVED creative
    selection. Resolves [AVATAR]/[PRODUCT] at this boundary only and returns a
    payload labelled auto_generated=False / requires_confirmation=True. Fail-closed:
    404 missing product/selection, 409 non-APPROVED (DRAFT/REJECTED), 422 invalid id.
    NEVER generates, enqueues, burns credits, or writes anything."""
    if not product_id:
        raise HTTPException(status_code=422, detail="product_id is required")
    try:
        return await _handoff.prepare_generation_handoff(product_id)
    except ValueError as exc:
        _raise_setup_error(exc)
