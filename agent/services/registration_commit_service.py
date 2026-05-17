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
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
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

class RegistrationCommitService:
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
                "excluded_fields": [f for f in draft.canonical_candidate_fields.keys() if not draft.approval_checklist.get(f)],
                "provenance": ["registration_commit_service:v1"]
            }
        except Exception as e:
            logger.error(f"Commit failed: {e}")
            return {
                "commit_status": "FAILED",
                "write_back_performed": False,
                "errors": [str(e)]
            }
