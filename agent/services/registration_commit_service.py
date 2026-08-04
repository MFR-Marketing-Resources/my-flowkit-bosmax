import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from agent.db import crud
from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationCommitRequest
)
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomyReviewRequest,
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
    product_strategy_fingerprint,
    review_product_strategy_taxonomy,
    validate_product_strategy_assignment,
)
from agent.utils.paths import product_image_path

logger = logging.getLogger(__name__)


def _build_owned_raw_title(draft: RegistrationReviewDraft) -> str:
    base_name = (
        draft.declared_evidence_fields.get("product_name")
        or draft.canonical_candidate_fields.get("normalized_name")
        or "Unnamed Owned Product"
    )
    size = str(
        draft.declared_evidence_fields.get("size_or_volume")
        or draft.canonical_candidate_fields.get("size_or_volume")
        or ""
    ).strip()
    if size and size.lower() not in str(base_name).lower():
        return f"{base_name} {size}".strip()
    return str(base_name)


async def _find_manual_duplicate(draft: RegistrationReviewDraft) -> dict[str, Any] | None:
    candidate_names = [
        str(draft.canonical_candidate_fields.get("normalized_name") or "").strip(),
        str(draft.declared_evidence_fields.get("product_name") or "").strip(),
        _build_owned_raw_title(draft),
    ]
    checked_names = [name for name in candidate_names if name]
    for source in ("MANUAL", "IMPORTED"):
        for name in checked_names:
            matches = await crud.list_products(source=source, query=name, limit=50)
            lowered = name.lower()
            for row in matches:
                row_names = {
                    str(row.get("raw_product_title") or "").lower(),
                    str(row.get("product_display_name") or "").lower(),
                    str(row.get("product_short_name") or "").lower(),
                }
                if lowered in row_names:
                    return row
    return None


def _is_canonical_duplicate_blocker(row: dict) -> bool:
    """Return True if this product row represents owned canonical truth that blocks promotion.

    Raw source=FASTMOSS reference-catalog rows are the inputs being promoted — they must
    NOT block the commit. Only block on rows that are confirmed canonical product truth:
      - source=MANUAL (user-owned)
      - source=IMPORTED (canonical import)
      - source=FASTMOSS with mapping_source=FASTMOSS_PROMOTED (already committed via this pipeline)
      - any row with fastmoss_reference_id set (already promoted and committed)

    Mirrors the policy applied in fastmoss_bulk_promotion_service._detect_queue_duplicate().
    """
    src = str(row.get("source") or "")
    mapping_src = str(row.get("mapping_source") or "")
    fastmoss_ref = str(row.get("fastmoss_reference_id") or "")
    if src == "FASTMOSS" and not mapping_src and not fastmoss_ref:
        return False
    return True


async def _find_fastmoss_promoted_duplicate(draft) -> dict | None:
    candidate_names = [
        str(draft.canonical_candidate_fields.get("normalized_name") or "").strip(),
        str(draft.declared_evidence_fields.get("product_name") or "").strip(),
        _build_owned_raw_title(draft),
    ]
    checked_names = [n for n in candidate_names if n]
    tiktok_url = str(draft.declared_evidence_fields.get("tiktok_product_url") or "").strip()
    for name in checked_names:
        matches = await crud.list_products(query=name, limit=50)
        lowered = name.lower()
        for row in matches:
            if not _is_canonical_duplicate_blocker(row):
                continue
            row_names = {
                str(row.get("raw_product_title") or "").lower(),
                str(row.get("product_display_name") or "").lower(),
                str(row.get("product_short_name") or "").lower(),
            }
            if lowered in row_names:
                return row
            if tiktok_url and tiktok_url == str(row.get("tiktok_product_url") or "").strip():
                return row
    return None


async def _manual_taxonomy_validation_error(
    draft: RegistrationReviewDraft,
) -> str | None:
    taxonomy = draft.strategy_taxonomy
    if not taxonomy or taxonomy.authority_source != "MANUAL_OVERRIDE":
        return None
    if not (taxonomy.reviewer_id or "").strip() or not (
        taxonomy.reviewer_note or ""
    ).strip():
        return "TAXONOMY_REVIEWER_EVIDENCE_REQUIRED"
    try:
        await validate_product_strategy_assignment(
            cluster=taxonomy.cluster,
            product_type_group=taxonomy.product_type_group,
            matched_scene_strategy_id=taxonomy.matched_scene_strategy_id,
            scene_coverage_status=taxonomy.scene_coverage_status,
            review_status=taxonomy.review_status,
        )
    except ProductStrategyTaxonomyError as exc:
        return str(exc)
    return None


async def _promote_intelligence_or_compensate(
    product: dict[str, Any],
    draft: RegistrationReviewDraft,
    *,
    lane: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """B-08A-02. Returns (promotion_receipt, failure_response); exactly one is not None.

    Before this, BOTH commit lanes wrote identity / taxonomy / physics / commerce only.
    Approved Product Knowledge was discarded, and invisibly so: `excluded_fields` lists
    candidates the operator did NOT approve, so an approved field with no canonical
    mapping appeared nowhere at all.

    Compensation, not a transaction: `crud.create_product` has already committed by the
    time promotion runs, and the two writes cannot share one SQLite transaction through
    the existing service seam. So a promotion failure DELETES the product and reports the
    exact stage — a canonical product must never survive without its promised
    intelligence record.
    """
    from agent.services.registration_intelligence_promotion_service import (
        promote_registration_to_intelligence,
    )

    try:
        receipt = await promote_registration_to_intelligence(product["id"], draft)
        return receipt, None
    except Exception as promotion_error:  # noqa: BLE001 - compensating path
        logger.error(
            "Intelligence promotion failed (%s) for %s: %s",
            lane, product["id"], promotion_error,
        )
        compensated = True
        try:
            await crud.delete_product(product["id"])
        except Exception as rollback_error:  # noqa: BLE001
            compensated = False
            logger.error(
                "Compensation delete failed for %s: %s", product["id"], rollback_error,
            )
        return None, {
            "commit_status": "FAILED",
            "write_back_performed": False,
            "failed_stage": "PRODUCT_INTELLIGENCE_PROMOTION",
            "compensated": compensated,
            "committed_product_id": None if compensated else product["id"],
            "errors": [f"INTELLIGENCE_PROMOTION_FAILED: {promotion_error}"],
        }


async def _materialize_manual_taxonomy(
    product: dict[str, Any],
    draft: RegistrationReviewDraft,
) -> dict[str, Any] | None:
    taxonomy = draft.strategy_taxonomy
    if not taxonomy or taxonomy.authority_source != "MANUAL_OVERRIDE":
        return None
    reviewed = await review_product_strategy_taxonomy(
        str(product["id"]),
        ProductStrategyTaxonomyReviewRequest(
            expected_product_fingerprint=product_strategy_fingerprint(product),
            cluster=taxonomy.cluster,
            product_type_group=taxonomy.product_type_group,
            matched_scene_strategy_id=taxonomy.matched_scene_strategy_id,
            scene_coverage_status=taxonomy.scene_coverage_status,
            review_status=taxonomy.review_status,
            reviewer_id=str(taxonomy.reviewer_id or ""),
            reviewer_note=str(taxonomy.reviewer_note or ""),
        ),
    )
    return reviewed.model_dump(mode="json")


class RegistrationCommitService:
    @staticmethod
    async def commit_fastmoss_promoted_draft(request) -> dict:
        """Commit path for FASTMOSS_PROMOTED lane. Uses PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH phrase."""
        draft = RegistrationDraftStorageService.get_draft(request.draft_id)
        if not draft:
            return {"commit_status": "BLOCKED", "write_back_performed": False, "errors": ["DRAFT_NOT_FOUND"]}

        blocked_reasons = []
        if request.user_confirmation_phrase != "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH":
            blocked_reasons.append("INVALID_CONFIRMATION_PHRASE_FOR_FASTMOSS_PROMOTED")
        if not request.write_back_confirmed:
            blocked_reasons.append("WRITE_BACK_NOT_CONFIRMED")
        if draft.source_lane != "FASTMOSS_PROMOTED":
            blocked_reasons.append("SOURCE_LANE_MUST_BE_FASTMOSS_PROMOTED")
        if draft.claim_gate == "CLAIM_BLOCKED":
            blocked_reasons.append("CLAIM_BLOCKED")
        if draft.claim_risk_level != "LOW":
            blocked_reasons.append(
                f"CLAIM_RISK_NOT_ELIGIBLE_FOR_FASTMOSS_PROMOTED_COMMIT:{draft.claim_risk_level or 'UNKNOWN'}"
            )
        if draft.image_asset_status == "IMAGE_REFERENCE_MISSING":
            blocked_reasons.append("IMAGE_MISSING_BLOCKS_FASTMOSS_PROMOTED_COMMIT")
        if not draft.declared_evidence_fields.get("product_name"):
            blocked_reasons.append("PRODUCT_NAME_REQUIRED")
        if draft.missing_required_evidence:
            blocked_reasons.append(f"MISSING_REQUIRED_EVIDENCE:{','.join(draft.missing_required_evidence)}")
        taxonomy_error = await _manual_taxonomy_validation_error(draft)
        if taxonomy_error:
            blocked_reasons.append(
                f"INVALID_PRODUCT_STRATEGY_TAXONOMY:{taxonomy_error}"
            )
        if blocked_reasons:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "blocked_reasons": blocked_reasons,
                "errors": ["COMMIT_GATE_VIOLATION"],
            }

        dup = await _find_fastmoss_promoted_duplicate(draft)
        if dup:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "blocked_reasons": [f"DUPLICATE_PRODUCT_CANDIDATE:{dup['id']}"],
                "errors": ["COMMIT_GATE_VIOLATION"],
            }

        raw_title = _build_owned_raw_title(draft)
        display = draft.canonical_candidate_fields.get("normalized_name") or raw_title
        payload = {
            "source": "MANUAL",
            "raw_product_title": raw_title,
            "product_display_name": display,
            "product_short_name": (display or "Unnamed")[:80],
            "source_url": (
                draft.declared_evidence_fields.get("source_url")
                or draft.declared_evidence_fields.get("tiktok_product_url")
            ),
            "tiktok_product_url": draft.declared_evidence_fields.get("tiktok_product_url"),
            "image_url": draft.declared_evidence_fields.get("image_url"),
            "category": draft.canonical_candidate_fields.get("category"),
            "subcategory": draft.canonical_candidate_fields.get("subcategory"),
            "type": draft.canonical_candidate_fields.get("type"),
            "silo": draft.canonical_candidate_fields.get("silo"),
            "claim_risk_level": draft.claim_risk_level,
            "bosmax_product_family": draft.system_inferred_fields.get("bosmax_product_family"),
            "price": draft.declared_evidence_fields.get("price"),
            "currency": draft.declared_evidence_fields.get("currency"),
            "commission_amount": draft.declared_evidence_fields.get("commission_amount"),
            "commission_rate": draft.declared_evidence_fields.get("commission_rate"),
            "commission": draft.declared_evidence_fields.get("commission_rate"),
            "mapping_source": "FASTMOSS_PROMOTED",
            "mapping_review_status": "REVIEWED_FASTMOSS_PROMOTED_COMMIT",
            "mapping_status": "APPROVED",
            "fastmoss_reference_id": draft.fastmoss_reference_id,
        }
        try:
            product = await crud.create_product(**payload)
            local_path = str(draft.declared_evidence_fields.get("local_image_path") or "").strip()
            if local_path:
                import shutil as _shutil
                from agent.utils.paths import product_image_path as _pip
                src = Path(local_path)
                if src.exists():
                    ext = src.suffix.lstrip(".").lower() or "jpg"
                    dest = _pip(product["id"], ext=ext)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _shutil.copyfile(src, dest)
                    await crud.update_product(product["id"], local_image_path=str(dest),
                                              asset_status="DOWNLOADED", image_asset_status="DOWNLOADED")
            materialized_taxonomy = await _materialize_manual_taxonomy(
                product,
                draft,
            )
            promotion, failure = await _promote_intelligence_or_compensate(
                product, draft, lane="FASTMOSS_PROMOTED",
            )
            if failure:
                return failure
            draft.write_back_performed = True
            draft.write_back_status = "COMMITTED"
            draft.review_status = "COMMITTED"
            RegistrationDraftStorageService.save_draft(draft)
            return {
                "commit_status": "COMMITTED",
                "write_back_performed": True,
                "committed_product_id": product["id"],
                "committed_fields": list(payload.keys()),
                "strategy_taxonomy": materialized_taxonomy,
                "product_intelligence": promotion,
                "intelligence_draft_id": (promotion or {}).get("intelligence_draft_id"),
                "provenance": ["registration_commit_service:fastmoss_promoted:v1"],
            }
        except Exception as e:
            logger.error("FASTMOSS_PROMOTED commit failed: %s", e)
            return {"commit_status": "FAILED", "write_back_performed": False, "errors": [str(e)]}

    @staticmethod
    async def commit_draft(request: RegistrationCommitRequest) -> Dict[str, Any]:
        """
        Final authority gate for owned product registration.
        Performs the actual write-back to the product table.
        """
        draft = RegistrationDraftStorageService.get_draft(request.draft_id)
        if not draft:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "errors": ["DRAFT_NOT_FOUND"]
            }

        # 1. Validation Gates
        blocked_reasons = []
        
        # Confirmation Phrase
        if request.user_confirmation_phrase != "REGISTER_OWNED_PRODUCT":
            blocked_reasons.append("INVALID_CONFIRMATION_PHRASE")
            
        # Write back confirmation checkbox
        if not request.write_back_confirmed:
            blocked_reasons.append("WRITE_BACK_NOT_CONFIRMED")

        # Source Lane Authority
        if draft.source_lane == "AFFILIATE_CONTAMINATED":
            blocked_reasons.append("AFFILIATE_LANE_CONTAMINATION_BLOCKED")
        if draft.source_lane in {
            "FASTMOSS_REFERENCE",
            "FASTMOSS",
            "TIKTOKSHOP_DRAFT",
            "TIKTOKSHOP",
            "UNKNOWN_REVIEW_REQUIRED",
        }:
            blocked_reasons.append("SOURCE_LANE_NOT_ALLOWED_FOR_OWNED_COMMIT")

        if draft.draft_freshness_status != "FRESH":
            blocked_reasons.append("DRAFT_RECOMPUTE_REQUIRED")
        if draft.recompute_required_reasons:
            blocked_reasons.append(
                "AUTHORITY_RECOMPUTE_REQUIRED: "
                + ", ".join(draft.recompute_required_reasons)
            )
        if draft.evidence_quality_status == "REVIEW_REQUIRED":
            blocked_reasons.append(
                "EVIDENCE_QUALITY_REVIEW_REQUIRED: "
                + ", ".join(draft.evidence_quality_issues)
            )
        if draft.consistency_status == "BLOCKED_REVIEW_REQUIRED":
            blocked_reasons.append(
                "CONSISTENCY_REVIEW_REQUIRED: "
                + ", ".join(draft.consistency_issues)
            )

        if not draft.last_recomputed_at:
            blocked_reasons.append("DRAFT_RECOMPUTE_REQUIRED")

        def _parse_timestamp(value: str | None) -> datetime | None:
            if not value:
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return None

        evidence_edit_at = _parse_timestamp(draft.last_evidence_edit_at)
        recomputed_at = _parse_timestamp(draft.last_recomputed_at)
        if evidence_edit_at and recomputed_at and evidence_edit_at > recomputed_at:
            blocked_reasons.append("DRAFT_RECOMPUTE_REQUIRED")
            
        # Claim Gate
        if draft.claim_gate == "CLAIM_BLOCKED":
            blocked_reasons.append("CLAIM_BLOCKED")
            
        # Identity Check (Name)
        if not draft.approval_checklist.get("normalized_name"):
            blocked_reasons.append("PRODUCT_NAME_NOT_APPROVED")

        # Human Review Fields Unresolved
        # Only check fields that are actually candidates (virtual fields like 'physics_profile' are skipped)
        unresolved_fields = [
            field
            for field in draft.human_review_fields
            if field in draft.approval_checklist and not draft.approval_checklist.get(field)
        ]
        if unresolved_fields:
            blocked_reasons.append(f"UNRESOLVED_REVIEW_FIELDS: {', '.join(unresolved_fields)}")

        if draft.missing_required_evidence:
            blocked_reasons.append(
                f"MISSING_REQUIRED_EVIDENCE: {', '.join(draft.missing_required_evidence)}"
            )
        taxonomy_error = await _manual_taxonomy_validation_error(draft)
        if taxonomy_error:
            blocked_reasons.append(
                f"INVALID_PRODUCT_STRATEGY_TAXONOMY:{taxonomy_error}"
            )

        if blocked_reasons:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "blocked_reasons": blocked_reasons,
                "errors": ["COMMIT_GATE_VIOLATION"]
            }

        duplicate = await _find_manual_duplicate(draft)
        if duplicate:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "blocked_reasons": [f"DUPLICATE_OWNED_PRODUCT_CANDIDATE:{duplicate['id']}"],
                "errors": ["COMMIT_GATE_VIOLATION"],
            }

        # 2. Build Canonical Payload
        raw_product_title = _build_owned_raw_title(draft)
        # Only include approved fields from canonical_candidate_fields
        canonical_payload = {
            "source": "MANUAL",
            "raw_product_title": raw_product_title,
            "product_display_name": draft.canonical_candidate_fields.get("normalized_name"),
            "product_short_name": draft.canonical_candidate_fields.get("normalized_name")[:80] if draft.canonical_candidate_fields.get("normalized_name") else "Unnamed",
            "source_url": draft.declared_evidence_fields.get("source_url") or draft.declared_evidence_fields.get("product_url") or draft.declared_evidence_fields.get("tiktok_product_url") or draft.declared_evidence_fields.get("tiktok_shop_url"),
            "category": draft.canonical_candidate_fields.get("category"),
            "subcategory": draft.canonical_candidate_fields.get("subcategory"),
            "type": draft.canonical_candidate_fields.get("type"),
            "silo": draft.canonical_candidate_fields.get("silo"),
            "trigger_id": draft.canonical_candidate_fields.get("trigger_id"),
            "formula": draft.canonical_candidate_fields.get("copy_formula"),
            "claim_risk_level": draft.claim_risk_level,
            "bosmax_product_family": draft.system_inferred_fields.get("bosmax_product_family"),
            "physics_class": draft.canonical_candidate_fields.get("physics_class"),
            "product_scale": draft.canonical_candidate_fields.get("product_scale_class"),
            "recommended_grip": draft.canonical_candidate_fields.get("recommended_grip"),
            "section_5_product_physics_prompt": draft.canonical_candidate_fields.get("section_5_product_physics_prompt"),
            "price": draft.declared_evidence_fields.get("price"),
            "currency": draft.declared_evidence_fields.get("currency"),
            "commission_amount": draft.declared_evidence_fields.get("commission_amount"),
            "commission_rate": draft.declared_evidence_fields.get("commission_rate"),
            "commission": draft.declared_evidence_fields.get("commission_rate"),
            "image_url": draft.declared_evidence_fields.get("image_url"),
            "tiktok_product_url": draft.declared_evidence_fields.get("tiktok_product_url") or draft.declared_evidence_fields.get("tiktok_shop_url"),
            "mapping_status": "APPROVED",
            "mapping_review_status": "REVIEWED_OWNED_COMMIT",
        }
        
        # Filter payload: only include fields that were explicitly approved in the draft
        # (Though most of these are essential for the canonical record)
        final_fields = {}
        for k, v in canonical_payload.items():
            # For taxonomy/physics, we check the corresponding candidate field approval
            candidate_map = {
                "product_display_name": "normalized_name",
                "category": "category",
                "subcategory": "subcategory",
                "type": "type",
                "silo": "silo",
                "trigger_id": "trigger_id",
                "formula": "copy_formula",
                "physics_class": "physics_class",
                "product_scale": "product_scale_class",
                "recommended_grip": "recommended_grip",
                "section_5_product_physics_prompt": "section_5_product_physics_prompt",
            }
            if k in candidate_map:
                if draft.approval_checklist.get(candidate_map[k]):
                    final_fields[k] = v
            else:
                final_fields[k] = v

        # 3. Execute Write-Back
        try:
            product = await crud.create_product(
                **final_fields
            )
            local_image_path = str(draft.declared_evidence_fields.get("local_image_path") or "").strip()
            if local_image_path:
                source_path = Path(local_image_path)
                if source_path.exists():
                    ext = source_path.suffix.lstrip(".").lower() or "jpg"
                    dest = product_image_path(product["id"], ext=ext)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_path, dest)
                    await crud.update_product(
                        product["id"],
                        local_image_path=str(dest),
                        asset_status="DOWNLOADED",
                        image_asset_status="DOWNLOADED",
                    )
            materialized_taxonomy = await _materialize_manual_taxonomy(
                product,
                draft,
            )
            promotion, failure = await _promote_intelligence_or_compensate(
                product, draft, lane="MANUAL_OWNED",
            )
            if failure:
                return failure

            # Update Draft Status
            draft.write_back_performed = True
            draft.write_back_status = "COMMITTED"
            draft.review_status = "COMMITTED"
            RegistrationDraftStorageService.save_draft(draft)
            
            return {
                "commit_status": "COMMITTED",
                "write_back_performed": True,
                "committed_product_id": product["id"],
                "committed_fields": list(final_fields.keys()),
                # Candidates the operator did NOT approve. This alone hid B-08A-02: an
                # APPROVED field with no canonical mapping appeared in neither list. The
                # promotion receipt below now accounts for those explicitly.
                "excluded_fields": [f for f in draft.canonical_candidate_fields.keys() if not draft.approval_checklist.get(f)],
                "strategy_taxonomy": materialized_taxonomy,
                "product_intelligence": promotion,
                "intelligence_draft_id": (promotion or {}).get("intelligence_draft_id"),
                "intelligence_dropped_fields": (promotion or {}).get("dropped_fields", []),
                "provenance": ["registration_commit_service:v1"]
            }
        except Exception as e:
            logger.error(f"Commit failed: {e}")
            return {
                "commit_status": "FAILED",
                "write_back_performed": False,
                "errors": [str(e)]
            }
