"""Deterministic poster readiness gate and repair-action contract (read-only)."""

from __future__ import annotations

from typing import Any

from agent.models.poster_readiness import (
    PosterApprovalRoute,
    PosterClaimRoute,
    PosterImageTier,
    PosterMappingRoute,
    PosterReadinessResponse,
    PosterReadinessStatus,
    PosterRepairAction,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED as CLAIM_SAFE_APPROVED,
    STATUS_REVIEW_READY as CLAIM_SAFE_REVIEW_READY,
)
from agent.services.product_intelligence import IMAGE_READY_STATES, display_name, enrich_product
from agent.services.product_lifecycle_service import lifecycle_status
from agent.services.product_truth_service import ProductTruthService
from agent.services.production_prompt_approval_service import (
    get_production_approved_modes,
    is_mode_production_approved,
    is_production_prompt_approved,
)

RESTRICTED_SAFE_POSTER_MARKER = "RESTRICTED_SAFE_POSTER"

HARD_BLOCKERS = frozenset(
    {
        "PRODUCT_ARCHIVED",
        "MISSING_RAW_TITLE",
        "MISSING_DISPLAY_NAME",
        "SEVERE_PRODUCT_TRUTH_CONTRADICTION",
        "UNSAFE_CLAIM_CANNOT_REWRITE",
        "PRODUCT_IDENTITY_CONFLICT",
    }
)

REPAIR_BLOCKERS = frozenset(
    {
        "MAPPING_MISSING",
        "MAPPING_BLOCKED",
        "MISSING_CATEGORY",
        "MISSING_SUBCAT_AND_TYPE",
        "NO_IMAGE",
        "IMG_NOT_PROD_APPROVED",
        "CLAIM_RISK_HIGH",
        "CLAIM_SAFE_COPY_REQUIRED",
        "PRODUCT_TRUTH_GAP",
    }
)

SOFT_BLOCKERS = frozenset(
    {
        "REMOTE_IMAGE_ONLY",
        "LOW_CONFIDENCE_METADATA",
        "WEAK_IMAGE_SOURCE",
    }
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _usable_remote_image_url(product: dict[str, Any]) -> bool:
    url = _norm(product.get("image_url"))
    if not url or url.upper() == "UNKNOWN":
        return False
    return True


def _has_local_image(product: dict[str, Any]) -> bool:
    return bool(_norm(product.get("local_image_path")))


def _has_any_image(product: dict[str, Any]) -> bool:
    if _has_local_image(product):
        return True
    if _usable_remote_image_url(product):
        return True
    return _norm(product.get("asset_status")).upper() == "DOWNLOADED"


def _repair_catalog() -> dict[str, list[PosterRepairAction]]:
    """Blocker code → ordered repair actions (existing endpoints where known)."""
    return {
        "MAPPING_MISSING": [
            PosterRepairAction(
                action_code="RUN_PRODUCT_MAPPING",
                label="Run Product Mapping",
                severity="P1",
                auto_executable=True,
                recommended_endpoint="POST /api/products/map",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
                notes="Also available: POST /api/products/backfill-mapping?product_id={id}",
            ),
        ],
        "MAPPING_BLOCKED": [
            PosterRepairAction(
                action_code="REVIEW_PRODUCT_MAPPING",
                label="Review Product Mapping",
                severity="P1",
                requires_human_approval=True,
                manual_review_required=True,
                recommended_endpoint="PATCH /api/products/{product_id}",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "MISSING_CATEGORY": [
            PosterRepairAction(
                action_code="FIX_PRODUCT_CATEGORY",
                label="Fix Product Category",
                severity="P1",
                recommended_endpoint="PATCH /api/products/{product_id}",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "MISSING_SUBCAT_AND_TYPE": [
            PosterRepairAction(
                action_code="FIX_PRODUCT_TAXONOMY",
                label="Fix Product Taxonomy",
                severity="P1",
                recommended_endpoint="PATCH /api/products/{product_id}",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "NO_IMAGE": [
            PosterRepairAction(
                action_code="UPLOAD_PRODUCT_IMAGE",
                label="Upload Product Image",
                severity="P1",
                recommended_endpoint="PATCH /api/products/{product_id}",
                notes="Use image_base64 / image_filename on patch payload.",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
            PosterRepairAction(
                action_code="CACHE_PRODUCT_IMAGE",
                label="Cache Remote Product Image",
                severity="P1",
                auto_executable=True,
                recommended_endpoint="POST /api/products/{product_id}/cache-image",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "IMG_NOT_PROD_APPROVED": [
            PosterRepairAction(
                action_code="RUN_IMG_PRODUCTION_APPROVAL",
                label="Run IMG Production Approval",
                severity="P1",
                requires_human_approval=True,
                recommended_endpoint="POST /api/products/{product_id}/production-prompt-approval",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
                notes="Include IMG in approved_modes after claim-safe review.",
            ),
        ],
        "CLAIM_RISK_HIGH": [
            PosterRepairAction(
                action_code="RUN_SAFE_CLAIM_CLEARANCE",
                label="Run Safe Claim Clearance",
                severity="P0",
                requires_human_approval=True,
                recommended_endpoint="GET /api/products/{product_id}/claim-safe-rewrite-preview",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
                notes="Follow with POST /api/products/{product_id}/claim-safe-rewrite-approval",
            ),
            PosterRepairAction(
                action_code="APPROVE_RESTRICTED_SAFE_POSTER_ROUTE",
                label="Approve Restricted Safe Poster Route",
                severity="P0",
                requires_human_approval=True,
                recommended_endpoint="POST /api/products/{product_id}/production-prompt-approval",
                expected_status_after_success="POSTER_READY_RESTRICTED",
                notes=(
                    f"Reviewer must record {RESTRICTED_SAFE_POSTER_MARKER} in approval note/provenance "
                    "after claim risk is lowered and claim-safe copy is approved."
                ),
            ),
        ],
        "CLAIM_SAFE_COPY_REQUIRED": [
            PosterRepairAction(
                action_code="RUN_SAFE_CLAIM_CLEARANCE",
                label="Run Safe Claim Clearance",
                severity="P0",
                requires_human_approval=True,
                recommended_endpoint="GET /api/products/{product_id}/claim-safe-rewrite-preview",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "PRODUCT_ARCHIVED": [
            PosterRepairAction(
                action_code="UNARCHIVE_OR_DUPLICATE_PRODUCT",
                label="Unarchive or Duplicate Product",
                severity="P0",
                requires_human_approval=True,
                manual_review_required=True,
                recommended_endpoint="POST /api/products/{product_id}/unarchive",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "SEVERE_PRODUCT_TRUTH_CONTRADICTION": [
            PosterRepairAction(
                action_code="HUMAN_PRODUCT_TRUTH_REVIEW",
                label="Human Product Truth Review",
                severity="P0",
                requires_human_approval=True,
                manual_review_required=True,
                recommended_endpoint="GET /api/product-truth/reconciliation-audit",
                expected_status_after_success="POSTER_BLOCKED",
            ),
        ],
        "MISSING_RAW_TITLE": [
            PosterRepairAction(
                action_code="FIX_PRODUCT_IDENTITY",
                label="Fix Product Raw Title",
                severity="P0",
                recommended_endpoint="PATCH /api/products/{product_id}",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "MISSING_DISPLAY_NAME": [
            PosterRepairAction(
                action_code="FIX_PRODUCT_DISPLAY_NAME",
                label="Fix Product Display Name",
                severity="P0",
                recommended_endpoint="PATCH /api/products/{product_id}",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
        "REMOTE_IMAGE_ONLY": [
            PosterRepairAction(
                action_code="CACHE_PRODUCT_IMAGE",
                label="Cache Remote Product Image",
                severity="P2",
                auto_executable=True,
                recommended_endpoint="POST /api/products/{product_id}/cache-image",
                expected_status_after_success="POSTER_READY",
            ),
        ],
        "PRODUCT_TRUTH_GAP": [
            PosterRepairAction(
                action_code="COMPLETE_PRODUCT_TRUTH",
                label="Complete Product Truth Fields",
                severity="P2",
                recommended_endpoint="POST /api/products/{product_id}/intelligence/review-drafts",
                expected_status_after_success="POSTER_REPAIR_REQUIRED",
            ),
        ],
    }


def _substitute_endpoints(actions: list[PosterRepairAction], product_id: str) -> list[PosterRepairAction]:
    out: list[PosterRepairAction] = []
    for action in actions:
        payload = action.model_dump()
        for key in ("recommended_endpoint", "recommended_future_endpoint", "notes"):
            val = payload.get(key)
            if isinstance(val, str):
                payload[key] = val.replace("{product_id}", product_id).replace("{id}", product_id)
        out.append(PosterRepairAction(**payload))
    return out


def _collect_repair_actions(blockers: list[str], product_id: str) -> list[PosterRepairAction]:
    catalog = _repair_catalog()
    seen: set[str] = set()
    actions: list[PosterRepairAction] = []
    for code in blockers:
        for action in catalog.get(code, []):
            if action.action_code in seen:
                continue
            seen.add(action.action_code)
            actions.append(action)
    return _substitute_endpoints(actions, product_id)


def _restricted_safe_poster_clearance_verified(product: dict[str, Any]) -> bool:
    if _norm(product.get("claim_risk_level")).upper() == "HIGH":
        return False
    claim_status = _norm(product.get("claim_safe_copy_status"))
    if claim_status not in {CLAIM_SAFE_APPROVED, CLAIM_SAFE_REVIEW_READY}:
        return False
    if not is_mode_production_approved(product, "IMG"):
        return False
    note = _norm(product.get("production_prompt_approval_note")).upper()
    prov = _norm(product.get("production_prompt_approval_provenance")).upper()
    return RESTRICTED_SAFE_POSTER_MARKER in note or RESTRICTED_SAFE_POSTER_MARKER in prov


def _severe_truth_contradiction(product: dict[str, Any]) -> bool:
    profile = ProductTruthService.build_computed_profile(product)
    flags = list(profile.reconciliation.contradiction_flags or [])
    severe_markers = {
        "FLAG_MANUAL_INPUT_CONTRADICTION_REVIEW_REQUIRED",
        "FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION",
        "FLAG_IMAGE_VS_SOURCE_PHYSICS_CONFLICT",
    }
    return any(f in severe_markers for f in flags)


def _compute_image_tier(product: dict[str, Any]) -> PosterImageTier:
    if not _has_any_image(product):
        return PosterImageTier.IMAGE_MISSING
    readiness = _norm(product.get("image_readiness_status"))
    if _has_local_image(product) or readiness in IMAGE_READY_STATES:
        return PosterImageTier.PRODUCT_HERO_POSTER_READY
    if _usable_remote_image_url(product):
        return PosterImageTier.PRODUCT_IMAGE_PROMPT_READY
    return PosterImageTier.TEXT_ONLY_POSTER_READY


def _collect_blockers(product: dict[str, Any]) -> list[str]:
    blockers: list[str] = []

    status = lifecycle_status(product)
    if status == "ARCHIVED":
        blockers.append("PRODUCT_ARCHIVED")

    raw_title = _norm(product.get("raw_product_title"))
    if not raw_title:
        blockers.append("MISSING_RAW_TITLE")

    display = _norm(product.get("product_display_name")) or display_name(
        raw_title, product.get("product_short_name")
    )
    if not display:
        blockers.append("MISSING_DISPLAY_NAME")

    if _severe_truth_contradiction(product):
        blockers.append("SEVERE_PRODUCT_TRUTH_CONTRADICTION")

    mapping_status = _norm(product.get("mapping_status")).upper()
    if mapping_status in {"", "MISSING", "UNKNOWN"}:
        blockers.append("MAPPING_MISSING")
    elif mapping_status in {"BLOCKED", "REJECTED"}:
        blockers.append("MAPPING_BLOCKED")

    if not _norm(product.get("category")):
        blockers.append("MISSING_CATEGORY")
    if not _norm(product.get("subcategory")) and not _norm(product.get("type")):
        blockers.append("MISSING_SUBCAT_AND_TYPE")

    if not _has_any_image(product):
        blockers.append("NO_IMAGE")
    elif _usable_remote_image_url(product) and not _has_local_image(product):
        blockers.append("REMOTE_IMAGE_ONLY")

    approved_modes = get_production_approved_modes(product)
    img_approved = "IMG" in approved_modes and is_production_prompt_approved(product)
    if not img_approved:
        blockers.append("IMG_NOT_PROD_APPROVED")

    risk = _norm(product.get("claim_risk_level")).upper()
    if risk == "HIGH":
        blockers.append("CLAIM_RISK_HIGH")

    claim_gate = _norm(product.get("claim_gate")).upper()
    claim_status = _norm(product.get("claim_safe_copy_status"))
    if claim_gate in {"CLAIM_REVIEW_REQUIRED", "CLAIM_BLOCKED"} and claim_status not in {
        CLAIM_SAFE_APPROVED,
        CLAIM_SAFE_REVIEW_READY,
    }:
        if "CLAIM_RISK_HIGH" not in blockers:
            blockers.append("CLAIM_SAFE_COPY_REQUIRED")

    return blockers


def _resolve_status(
    blockers: list[str],
    product: dict[str, Any],
    *,
    restricted_clearance: bool,
) -> PosterReadinessStatus:
    if any(b in HARD_BLOCKERS for b in blockers):
        return PosterReadinessStatus.POSTER_BLOCKED

    if blockers:
        repair_hits = [b for b in blockers if b in REPAIR_BLOCKERS]
        if repair_hits:
            if "CLAIM_RISK_HIGH" in repair_hits and not restricted_clearance:
                return PosterReadinessStatus.POSTER_REPAIR_REQUIRED
            if any(b for b in repair_hits if b != "REMOTE_IMAGE_ONLY"):
                return PosterReadinessStatus.POSTER_REPAIR_REQUIRED
        soft_only = all(b in SOFT_BLOCKERS for b in blockers)
        if soft_only:
            return PosterReadinessStatus.POSTER_PREVIEW_ONLY
        return PosterReadinessStatus.POSTER_PREVIEW_ONLY

    if restricted_clearance:
        return PosterReadinessStatus.POSTER_READY_RESTRICTED

    return PosterReadinessStatus.POSTER_READY


class PosterReadinessService:
    @staticmethod
    async def evaluate_product(product: dict[str, Any], *, enrich: bool = True) -> PosterReadinessResponse:
        """Read-only poster readiness evaluation. Does not persist product changes."""
        working = dict(product)
        if enrich:
            working = await enrich_product(working, persist=False)

        product_id = _norm(working.get("id") or working.get("product_id"))
        display = _norm(working.get("product_display_name")) or display_name(
            _norm(working.get("raw_product_title")),
            working.get("product_short_name"),
        )

        blockers = _collect_blockers(working)
        restricted_clearance = _restricted_safe_poster_clearance_verified(working)
        poster_status = _resolve_status(blockers, working, restricted_clearance=restricted_clearance)
        image_tier = _compute_image_tier(working)

        approved_modes = get_production_approved_modes(working)
        img_approved = is_mode_production_approved(working, "IMG")

        claim_risk = _norm(working.get("claim_risk_level")).upper() or None
        clearance_required = claim_risk == "HIGH" or _norm(working.get("claim_gate")).upper() in {
            "CLAIM_REVIEW_REQUIRED",
            "CLAIM_BLOCKED",
        }
        clearance_status = "CLEARED_RESTRICTED" if restricted_clearance else (
            "NOT_CLEARED" if clearance_required else "NOT_REQUIRED"
        )

        generation_allowed = poster_status in {
            PosterReadinessStatus.POSTER_READY,
            PosterReadinessStatus.POSTER_READY_RESTRICTED,
        }
        restricted_required = poster_status == PosterReadinessStatus.POSTER_READY_RESTRICTED
        preview_allowed = poster_status in {
            PosterReadinessStatus.POSTER_READY,
            PosterReadinessStatus.POSTER_READY_RESTRICTED,
            PosterReadinessStatus.POSTER_PREVIEW_ONLY,
            PosterReadinessStatus.POSTER_REPAIR_REQUIRED,
        }
        production_allowed = poster_status == PosterReadinessStatus.POSTER_READY

        repair_actions = _collect_repair_actions(blockers, product_id)
        if poster_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED and not repair_actions:
            repair_actions = _substitute_endpoints(
                [
                    PosterRepairAction(
                        action_code="HUMAN_POSTER_READINESS_REVIEW",
                        label="Human Poster Readiness Review",
                        severity="P1",
                        manual_review_required=True,
                    )
                ],
                product_id,
            )

        next_best = repair_actions[0].action_code if repair_actions else (
            "GENERATE_POSTER" if generation_allowed else None
        )

        notes: list[str] = []
        if poster_status == PosterReadinessStatus.POSTER_READY_RESTRICTED:
            notes.append("Restricted poster generation only: no cure/treat/heal/disease/guaranteed relief claims.")
        if "CLAIM_RISK_HIGH" in blockers and not restricted_clearance:
            notes.append("CLAIM_RISK_HIGH is not a permanent hold; run safe claim clearance then restricted route approval.")

        return PosterReadinessResponse(
            product_id=product_id,
            product_display_name=display or None,
            poster_status=poster_status,
            generation_allowed=generation_allowed,
            restricted_generation_required=restricted_required,
            preview_allowed=preview_allowed,
            production_allowed=production_allowed,
            blockers=blockers,
            repair_actions=repair_actions,
            image_tier=image_tier,
            claim_route=PosterClaimRoute(
                claim_risk_level=claim_risk,
                claim_gate=_norm(working.get("claim_gate")) or None,
                claim_safe_copy_status=_norm(working.get("claim_safe_copy_status")) or None,
                safe_claim_clearance_required=clearance_required,
                safe_claim_clearance_status=clearance_status,
                restricted_safe_poster_route_verified=restricted_clearance,
            ),
            mapping_route=PosterMappingRoute(
                mapping_status=_norm(working.get("mapping_status")) or None,
                mapping_ready=_norm(working.get("mapping_status")).upper() in {"READY", "APPROVED"},
                mapping_review_status=_norm(working.get("mapping_review_status")) or None,
            ),
            approval_route=PosterApprovalRoute(
                img_approved=img_approved,
                approved_modes=approved_modes,
                production_prompt_approval_status=_norm(working.get("production_prompt_approval_status")) or None,
            ),
            next_best_action=next_best,
            recheck_required_after_repair=poster_status != PosterReadinessStatus.POSTER_READY,
            notes=notes,
            diagnostics={
                "lifecycle_status": lifecycle_status(working),
                "has_local_image": _has_local_image(working),
                "usable_remote_image": _usable_remote_image_url(working),
                "bosmax_product_family": derive_bosmax_product_family(working).get("bosmax_product_family"),
            },
        )

    @staticmethod
    async def evaluate_product_id(product_id: str) -> PosterReadinessResponse | None:
        from agent.db import crud

        row = await crud.get_product(product_id)
        if not row:
            return None
        return await PosterReadinessService.evaluate_product(dict(row))