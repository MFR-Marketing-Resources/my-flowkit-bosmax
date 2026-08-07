"""Creative Intelligence API — avatar, scene-prompt, scene-suitability, and camera
recommendation layers.

Read-first, non-generative. Exposes:
  * GET  /api/creative-intelligence/avatar-recommendation       (by product_id OR category)
  * POST /api/creative-intelligence/avatar-fit/seed             (idempotent; dry-run default)
  * GET  /api/creative-intelligence/scene-prompt-recommendation (by product_id OR category)
  * POST /api/creative-intelligence/scene-prompt/seed           (idempotent; dry-run default)
  * GET  /api/creative-intelligence/scene-suitability/category  (by category)
  * GET  /api/creative-intelligence/scene-suitability/product/{product_id}
  * GET  /api/creative-intelligence/scene-strategy-scouting
  * GET/POST /api/creative-intelligence/product-strategy-type-registry
  * POST /api/creative-intelligence/product-strategy-type-registry/seed
  * POST /api/creative-intelligence/product-strategy-taxonomy/backfill
  * GET  /api/creative-intelligence/camera-preset-recommendation (by product_id/category/cluster)
  * POST /api/creative-intelligence/camera-preset/seed          (idempotent; dry-run default)

No generation, no Product Truth / product-row / Copy Set / Copy Registry / Copy
Intelligence mutation. The seeds only write the config tables ``avatar_product_fit`` /
``creative_scene_prompt`` / ``creative_camera_preset``; the explicitly confirmed
taxonomy backfill writes only ``product_strategy_taxonomy``. Scene templates keep
``[AVATAR]``/``[PRODUCT]`` placeholders unresolved; camera presets are reference-only
and are never written to product camera columns or sent to generation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomyBackfillRequest,
    ProductStrategyTaxonomyBackfillResponse,
    ProductStrategyTypeRegistrationRequest,
    ProductStrategyTypeRegistryEntry,
    ProductStrategyTypeRegistryListResponse,
    ProductStrategyTypeRegistrySeedRequest,
    ProductStrategyTypeRegistrySeedResponse,
)
from agent.services import creative_avatar_recommendation_service as _svc
from agent.services import creative_scene_prompt_service as _scene
from agent.services import product_strategy_scouting_service as _strategy_scouting
from agent.services import product_scene_suitability_service as _scene_suitability
from agent.services import scene_context_promotion_service as _scene_promotion
from agent.services import scene_context_promotion_review_service as _scene_review
from agent.services import scene_context_promotion_activation_service as _scene_activation
from agent.services import creative_camera_preset_service as _camera
from agent.services import creative_setup_service as _setup
from agent.services import creative_recipe_service as _recipe
from agent.services import creative_handoff_service as _handoff
from agent.services import product_strategy_taxonomy_service as _strategy_taxonomy

router = APIRouter(prefix="/creative-intelligence", tags=["creative-intelligence"])


class CreativeSelectionSaveRequest(BaseModel):
    product_id: str
    # Singular fields kept for backward compatibility (treated as a one-item list).
    selected_avatar_code: str | None = None
    selected_scene_template_id: str | None = None
    selected_camera_preset_code: str | None = None
    # Multi-select: the FULL chosen set. When present these win; the first of each
    # becomes the backward-compatible primary.
    selected_avatar_codes: list[str] | None = None
    selected_scene_template_ids: list[str] | None = None
    selected_camera_preset_codes: list[str] | None = None
    selected_block_purpose: str | None = None
    selected_content_type: str | None = None
    notes: str | None = None


class CreativeSelectionBulkAutoSetupRequest(BaseModel):
    """Bulk auto-fill each eligible product from its top-scored recommendation."""
    product_ids: list[str] | None = None
    approve: bool = True
    dry_run: bool = True
    limit: int | None = None


class CreativeSelectionAvatarPatchRequest(BaseModel):
    """Avatar-only partial update. Other selection fields are preserved server-side."""
    product_id: str
    selected_avatar_code: str
    notes_append: str | None = None


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
    "PRODUCT_CATEGORY_REVIEW_REQUIRED": 409,  # D1: fail-closed, no auto-plan/save
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
    live_avatar_codes = {
        str(avatar.get("avatar_code") or "").strip()
        for avatar in avatar_pool
        if avatar.get("avatar_code")
    }
    valid_fits = [
        fit for fit in fits
        if str(fit.get("avatar_code") or "").strip() in live_avatar_codes
    ]
    fit_categories = {str(f.get("product_category") or "") for f in valid_fits}
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
            "fit_total": len(valid_fits),
            "distinct_avatars_in_fit": len(
                {str(f.get("avatar_code") or "") for f in valid_fits}
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


@router.get("/registry-reconciliation")
async def registry_reconciliation() -> dict:
    """READ-ONLY item-level reconciliation of the Avatar + Scene authority pools
    against the Creative Intelligence tables.

    Surfaces which pool entries are MAPPED (avatar pool code present in
    ``avatar_product_fit``), REFERENCED (by a saved ``creative_product_selection``),
    or UNMAPPED review candidates. Never mutates, seeds, archives, or deletes.
    ``REVIEW_CANDIDATE`` items are informational only — NEVER flagged as delete-safe.
    """
    from agent.db import crud
    from agent.services import avatar_registry, scene_context_registry

    # Avatar pool <-> product-fit: same AvatarCode id space, so mapping is exact.
    avatar_pool = {
        str(a.get("avatar_code") or "").strip()
        for a in avatar_registry.list_pool()
        if a.get("avatar_code")
    }
    fits = await crud.list_avatar_product_fits(limit=5000)
    fit_codes = {str(f.get("avatar_code") or "").strip() for f in fits if f.get("avatar_code")}
    avatar_mapped = sorted(avatar_pool & fit_codes)
    avatar_unmapped = sorted(avatar_pool - fit_codes)

    # Scene pool + scene-prompt templates: SEPARATE id spaces (SceneCode vs
    # template_id) — no row-level link exists, so do not invent one.
    scene_pool = {
        str(s.get("scene_code") or "").strip()
        for s in scene_context_registry.list_pool()
        if s.get("scene_code")
    }
    prompts = await crud.list_creative_scene_prompts(limit=5000)
    prompt_ids = {str(p.get("template_id") or "").strip() for p in prompts if p.get("template_id")}

    # Saved selections (usually empty at this stage). No bulk list crud exists, so
    # read-only direct query — never written.
    db = await crud.get_db()
    cur = await db.execute(
        "SELECT selected_avatar_code, selected_scene_template_id, status "
        "FROM creative_product_selection"
    )
    sel_rows = [dict(r) for r in await cur.fetchall()]
    sel_avatar = {
        str(r.get("selected_avatar_code") or "").strip()
        for r in sel_rows if r.get("selected_avatar_code")
    }
    sel_scene = {
        str(r.get("selected_scene_template_id") or "").strip()
        for r in sel_rows if r.get("selected_scene_template_id")
    }
    avatar_referenced = sorted(avatar_pool & sel_avatar)
    scene_referenced = sorted(prompt_ids & sel_scene)

    return {
        "avatar": {
            "pool_total": len(avatar_pool),
            "mapped_to_fit": len(avatar_mapped),
            "referenced_by_selection": len(avatar_referenced),
            "unmapped": len(avatar_unmapped),
            "review_candidate_count": len(avatar_unmapped),
            "review_candidate_sample": avatar_unmapped[:10],
            "mapping_basis": (
                "avatar_product_fit.avatar_code matched against the avatar authority "
                "pool (AvatarCode) — same id space, exact. Review candidates are pool "
                "avatars not yet in the product-fit crosswalk or a saved selection; "
                "some may still be referenced by generated library assets. Informational "
                "only — NOT a deletion signal."
            ),
        },
        "scene": {
            "pool_total": len(scene_pool),
            "prompt_template_total": len(prompt_ids),
            "referenced_by_selection": len(scene_referenced),
            "pool_to_prompt_mapping": "NOT_DIRECTLY_MAPPED",
            "review_candidate_count": len(scene_pool),
            "review_candidate_sample": sorted(scene_pool)[:10],
            "mapping_basis": (
                "Scene pool plates (SceneCode) and scene-prompt templates (template_id) "
                "use separate id spaces; no row-level link exists yet — not invented. "
                "Scene plates also feed the IMG/I2V reference lane + compiler, whose "
                "usage is not tracked in this lens. Review candidates are a review "
                "prompt, NOT an unused/deletion signal."
            ),
        },
        "selection": {
            "total": len(sel_rows),
            "distinct_avatar_codes": sorted(sel_avatar),
            "distinct_scene_template_ids": sorted(sel_scene),
        },
        "disclaimer": (
            "REVIEW_CANDIDATE items are pool entries not yet referenced by product-fit "
            "or saved selections. This lens is READ-ONLY and informational — nothing "
            "here is flagged for deletion or archival."
        ),
    }


@router.get("/registry-cleanup-plan")
async def registry_cleanup_plan() -> dict:
    """READ-ONLY DRY-RUN archive/delete PLANNING report for the Avatar + Scene
    authority pools.

    Classifies each pool entry — KEEP_ACTIVE / BLOCKED_REFERENCED /
    REVIEW_CANDIDATE / BLOCKED_UNKNOWN_MAPPING / FUTURE_ARCHIVE_ELIGIBLE — with the
    dependency evidence and the evidence still required before any future action.

    Mutates NOTHING: no delete, archive, reseed, or write of any kind — only reads.
    Nothing is ever labelled 'safe to delete now'; FUTURE_ARCHIVE_ELIGIBLE
    additionally requires explicit owner approval before any real action.
    """
    from agent.db import crud
    from agent.services import avatar_registry, scene_context_registry

    pool = avatar_registry.list_pool()
    fits = await crud.list_avatar_product_fits(limit=5000)
    fit_codes = {str(f.get("avatar_code") or "").strip() for f in fits if f.get("avatar_code")}
    scene_pool = scene_context_registry.list_pool()

    # Read-only reads of downstream references (no bulk-list crud exists).
    db = await crud.get_db()
    sel_cur = await db.execute(
        "SELECT selected_avatar_code FROM creative_product_selection"
    )
    sel_avatar = {
        str(dict(r).get("selected_avatar_code") or "").strip()
        for r in await sel_cur.fetchall()
    }
    sel_avatar.discard("")
    asset_cur = await db.execute(
        "SELECT DISTINCT avatar_code FROM creative_asset "
        "WHERE avatar_code IS NOT NULL AND avatar_code <> ''"
    )
    asset_avatar = {str(r[0]).strip() for r in await asset_cur.fetchall() if r[0]}

    _CLASSES = (
        "KEEP_ACTIVE", "BLOCKED_REFERENCED", "REVIEW_CANDIDATE",
        "BLOCKED_UNKNOWN_MAPPING", "FUTURE_ARCHIVE_ELIGIBLE",
    )

    # --- Avatar classification (per pool AvatarCode) ---
    avatar_counts = {k: 0 for k in _CLASSES}
    avatar_samples: list[dict] = []
    for a in pool:
        code = str(a.get("avatar_code") or "").strip()
        if not code:
            continue
        in_fit = code in fit_codes
        sel_ref = 1 if code in sel_avatar else 0
        asset_ref = 1 if code in asset_avatar else 0
        if in_fit:
            cls = "KEEP_ACTIVE"
            reason = "Mapped in avatar_product_fit — actively used by R1 avatar recommendation."
            req = "None — actively used; not an archive candidate."
        elif sel_ref or asset_ref:
            cls = "BLOCKED_REFERENCED"
            reason = "Referenced by a saved creative selection and/or a generated library asset."
            req = "Clear all selection + asset references, then re-run this plan to confirm zero references."
        else:
            cls = "REVIEW_CANDIDATE"
            reason = (
                "Not in the product-fit crosswalk and not referenced by a selection/asset "
                "— thin, but NOT provably unused: resolve_presenter can still pick any pool "
                "member as a deterministic fallback at generation time."
            )
            req = (
                "Prove no resolve_presenter/seed path can select it, + owner approval. "
                "Not archive-eligible on current evidence."
            )
        avatar_counts[cls] += 1
        if cls != "KEEP_ACTIVE" and len(avatar_samples) < 10:
            avatar_samples.append({
                "id": code,
                "name": str(a.get("character_name") or ""),
                "classification": cls,
                "reason": reason,
                "product_fit_refs": 1 if in_fit else 0,
                "selection_refs": sel_ref,
                "asset_refs": asset_ref,
                "required_evidence": req,
            })

    # --- Scene classification (per pool SceneCode) ---
    scene_counts = {k: 0 for k in _CLASSES}
    scene_samples: list[dict] = []
    _scene_reason = (
        "Scene pool plates (SceneCode) use a separate id space from scene-prompt "
        "templates and saved selections, and feed the compiler + IMG/I2V reference "
        "lane whose usage is not tracked in these tables. A safe dependency "
        "determination is not possible from current data."
    )
    _scene_req = (
        "Add scene-plate usage tracking in the compiler/IMG-I2V lane, prove zero "
        "references, + owner approval before any real action."
    )
    for s in scene_pool:
        code = str(s.get("scene_code") or "").strip()
        if not code:
            continue
        scene_counts["BLOCKED_UNKNOWN_MAPPING"] += 1
        if len(scene_samples) < 10:
            scene_samples.append({
                "id": code,
                "name": str(s.get("scene_name") or ""),
                "classification": "BLOCKED_UNKNOWN_MAPPING",
                "reason": _scene_reason,
                "scene_prompt_refs": None,
                "selection_refs": 0,
                "required_evidence": _scene_req,
            })

    future_eligible = (
        avatar_counts["FUTURE_ARCHIVE_ELIGIBLE"]
        + scene_counts["FUTURE_ARCHIVE_ELIGIBLE"]
    )
    return {
        "dry_run": True,
        "mutations": 0,
        "future_archive_eligible_total": future_eligible,
        "owner_approval_required": True,
        "notice": (
            "READ-ONLY DRY-RUN. No records are archived or deleted from this planning "
            "report. FUTURE_ARCHIVE_ELIGIBLE requires zero references, fully-known "
            "mapping, AND explicit owner approval before any real action."
        ),
        "classification_legend": {
            "KEEP_ACTIVE": "Actively mapped/used in R1-R5 coverage.",
            "BLOCKED_REFERENCED": "Referenced by saved selections, prompts, assets, or product-fit — cannot archive.",
            "BLOCKED_UNKNOWN_MAPPING": "Current data does not support a safe dependency determination.",
            "REVIEW_CANDIDATE": "Unmapped/thin but not proven safe.",
            "FUTURE_ARCHIVE_ELIGIBLE": "All known references zero AND mapping fully known — even then owner approval is required before any real action.",
        },
        "avatar": {
            "total": len(pool),
            "classification_counts": avatar_counts,
            "candidates_sample": avatar_samples,
        },
        "scene": {
            "total": len(scene_pool),
            "classification_counts": scene_counts,
            "candidates_sample": scene_samples,
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


@router.get("/product-cluster-audit")
async def product_cluster_audit() -> dict:
    """Read-only product inventory grouped by avatar-planning cluster.

    Blank product categories remain review-required instead of falling back to a
    visual cluster. This endpoint never mutates product, avatar, or generation
    state and is intended to drive pool planning before avatar creation.
    """
    return await _svc.audit_product_cluster_coverage()


@router.get("/scene-strategy-scouting")
async def scene_strategy_scouting() -> dict:
    """Return a read-only cluster/type coverage queue for Scene Strategy work."""

    return await _strategy_scouting.get_product_strategy_scouting_report()


@router.get(
    "/product-strategy-type-registry",
    response_model=ProductStrategyTypeRegistryListResponse,
)
async def product_strategy_type_registry(
    cluster: str | None = None,
) -> ProductStrategyTypeRegistryListResponse:
    """Read the official cluster -> product-type registration layer."""

    return await _strategy_taxonomy.list_product_strategy_type_registry(cluster)


@router.post(
    "/product-strategy-type-registry",
    response_model=ProductStrategyTypeRegistryEntry,
)
async def product_strategy_type_register(
    request: ProductStrategyTypeRegistrationRequest,
) -> ProductStrategyTypeRegistryEntry:
    """Register one reviewed type under an existing strategy cluster."""

    try:
        return await _strategy_taxonomy.register_product_strategy_type(request)
    except _strategy_taxonomy.ProductStrategyTaxonomyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/product-strategy-type-registry/seed",
    response_model=ProductStrategyTypeRegistrySeedResponse,
)
async def product_strategy_type_registry_seed(
    request: ProductStrategyTypeRegistrySeedRequest,
) -> ProductStrategyTypeRegistrySeedResponse:
    """Preview by default; seed config only with the exact confirmation token."""

    try:
        return await _strategy_taxonomy.seed_product_strategy_type_registry(
            request
        )
    except _strategy_taxonomy.ProductStrategyTaxonomyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/product-strategy-taxonomy/backfill",
    response_model=ProductStrategyTaxonomyBackfillResponse,
)
async def product_strategy_taxonomy_backfill(
    request: ProductStrategyTaxonomyBackfillRequest,
) -> ProductStrategyTaxonomyBackfillResponse:
    """Preview by default; apply only with the exact confirmation token."""

    try:
        return await _strategy_taxonomy.run_product_strategy_taxonomy_backfill(
            request
        )
    except _strategy_taxonomy.ProductStrategyTaxonomyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/scene-suitability/category")
async def scene_suitability_by_category(category: str | None = None) -> dict:
    """Read-only suitability recommendations for a raw product category.

    The returned workbook templates remain preview-only with ``[AVATAR]`` and
    ``[PRODUCT]`` unresolved; this route never promotes a template to the
    background scene registry or invokes generation.
    """
    if category is None:
        raise HTTPException(status_code=422, detail="category is required")
    return await _scene_suitability.recommend_scene_suitability_for_category(category)


@router.get("/scene-suitability/product/{product_id}")
async def scene_suitability_by_product(product_id: str) -> dict:
    """Read-only suitability recommendations for a registered product."""
    try:
        return await _scene_suitability.recommend_scene_suitability_for_product(product_id)
    except ValueError as exc:
        if str(exc) == "PRODUCT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND") from exc
        raise


@router.get("/scene-context-promotion/preview")
async def scene_context_promotion_preview(cluster: str | None = None) -> dict:
    """Read-only Round 2 candidate preview; never syncs the scene registry."""
    return _scene_promotion.preview_scene_context_promotion(cluster)


@router.get("/scene-context-promotion/quarantine")
async def scene_context_promotion_quarantine(cluster: str | None = None) -> dict:
    """Read-only fail-closed ledger for unsuitable source templates."""
    return _scene_promotion.preview_quarantine(cluster)


class ScenePromotionReviewRequest(BaseModel):
    source_template_id: str
    candidate_fingerprint: str
    decision: str
    reviewer_note: str | None = None
    reviewed_via_product_id: str


def _scene_review_error(exc: _scene_review.ReviewError) -> HTTPException:
    code = str(exc)
    return HTTPException(404 if code == "PRODUCT_NOT_FOUND" else 409 if code == "STALE_CANDIDATE_FINGERPRINT" else 422, code)


@router.get("/scene-context-promotion/review/product/{product_id}")
async def scene_context_promotion_product_review(product_id: str) -> dict:
    try:
        return await _scene_review.product_review(product_id)
    except _scene_review.ReviewError as exc:
        raise _scene_review_error(exc) from exc


@router.post("/scene-context-promotion/review")
async def scene_context_promotion_review(request: ScenePromotionReviewRequest) -> dict:
    try:
        return await _scene_review.record_reviews(request.reviewed_via_product_id, [request.model_dump()])
    except _scene_review.ReviewError as exc:
        raise _scene_review_error(exc) from exc


class ScenePromotionReviewItem(BaseModel):
    source_template_id: str
    candidate_fingerprint: str
    decision: str
    reviewer_note: str | None = None


class ScenePromotionBulkReviewRequest(BaseModel):
    reviewed_via_product_id: str
    items: list[ScenePromotionReviewItem]


@router.post("/scene-context-promotion/review/bulk")
async def scene_context_promotion_bulk_review(request: ScenePromotionBulkReviewRequest) -> dict:
    try:
        return await _scene_review.record_reviews(request.reviewed_via_product_id, [item.model_dump() for item in request.items])
    except _scene_review.ReviewError as exc:
        raise _scene_review_error(exc) from exc


class ScenePromotionActivationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_template_id: str
    candidate_fingerprint: str


class ScenePromotionActivationRequest(ScenePromotionActivationItem):
    model_config = ConfigDict(extra="forbid")
    reviewed_via_product_id: str
    confirmation: str
    activated_by: str
    activation_note: str | None = None


class ScenePromotionBulkActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_via_product_id: str
    items: list[ScenePromotionActivationItem]
    confirmation: str
    activated_by: str
    activation_note: str | None = None


def _scene_activation_error(exc: _scene_activation.ActivationError) -> HTTPException:
    code = str(exc)
    if code in {"PRODUCT_NOT_FOUND", "UNKNOWN_SOURCE_TEMPLATE"}:
        return HTTPException(404, code)
    if code in {"STALE_CANDIDATE_FINGERPRINT", "SCENE_ALREADY_ACTIVE", "SCENE_DUPLICATE"}:
        return HTTPException(409, code)
    return HTTPException(422, code)


@router.get("/scene-context-promotion/activation/product/{product_id}")
async def scene_context_promotion_activation_eligibility(product_id: str) -> dict:
    try:
        return await _scene_activation.activation_eligibility(product_id)
    except _scene_activation.ActivationError as exc:
        raise _scene_activation_error(exc) from exc


@router.post("/scene-context-promotion/activation")
async def scene_context_promotion_activation(request: ScenePromotionActivationRequest) -> dict:
    try:
        result = await _scene_activation.activate(
            request.reviewed_via_product_id,
            [{"source_template_id": request.source_template_id, "candidate_fingerprint": request.candidate_fingerprint}],
            request.confirmation, request.activated_by, request.activation_note,
        )
        return result["items"][0]
    except _scene_activation.ActivationError as exc:
        raise _scene_activation_error(exc) from exc


@router.post("/scene-context-promotion/activation/bulk")
async def scene_context_promotion_bulk_activation(request: ScenePromotionBulkActivationRequest) -> dict:
    try:
        return await _scene_activation.activate(
            request.reviewed_via_product_id, [item.model_dump() for item in request.items],
            request.confirmation, request.activated_by, request.activation_note,
        )
    except _scene_activation.ActivationError as exc:
        raise _scene_activation_error(exc) from exc


@router.get("/scene-context-promotion/activation/history")
async def scene_context_promotion_activation_history(
    product_id: str | None = None, source_template_id: str | None = None, limit: int = 100,
) -> dict:
    return await _scene_activation.activation_history(product_id, source_template_id, limit)


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


@router.get("/creative-recipes")
async def creative_recipes(product_id: str | None = None) -> dict:
    """Coherent (avatar x scene -> camera-derived) recipes for a product. The camera
    FOLLOWS the scene (via the scene->variation->camera bridge), so every recipe is
    shot-coherent. Returns the full pool (mass rotation) + a capped, arc-spread
    `recommended_pretick` (the manual smart-suggest default). Deterministic, read-only,
    never generates."""
    if not product_id:
        raise HTTPException(status_code=422, detail="product_id is required")
    try:
        return await _recipe.generate_product_recipes(product_id)
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
            selected_avatar_codes=req.selected_avatar_codes,
            selected_scene_template_ids=req.selected_scene_template_ids,
            selected_camera_preset_codes=req.selected_camera_preset_codes,
            selected_block_purpose=req.selected_block_purpose,
            selected_content_type=req.selected_content_type,
            notes=req.notes,
        )
    except ValueError as exc:
        _raise_setup_error(exc)


@router.post("/creative-selection/bulk-auto-setup")
async def creative_selection_bulk_auto_setup(
    req: CreativeSelectionBulkAutoSetupRequest,
) -> dict:
    """Auto-fill every eligible product's creative selection from its top-scored
    recommendation (avatar #1 + scene #1 + camera #1), optionally APPROVING it.
    Idempotent (already-APPROVED left alone) and fail-closed (review-required /
    no-recommendation skipped). ``dry_run`` defaults true — nothing writes until
    an explicit ``dry_run: false``. Planning only; no generation effect."""
    return await _setup.bulk_auto_setup(
        product_ids=req.product_ids,
        approve=req.approve,
        dry_run=req.dry_run,
        limit=req.limit,
    )


@router.patch("/creative-selection/avatar")
async def creative_selection_avatar_patch(req: CreativeSelectionAvatarPatchRequest) -> dict:
    """Avatar-only partial update: preserves scene/camera/block/content/notes,
    rebuilds preview from the merged selection, and returns status to DRAFT.
    Only writes creative_product_selection — no product-row / generation effect."""
    try:
        return await _setup.update_creative_selection_avatar(
            req.product_id,
            selected_avatar_code=req.selected_avatar_code,
            notes_append=req.notes_append,
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
