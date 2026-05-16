import logging
from typing import Any, Dict, List, Optional

from agent.db import crud
from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationCommitRequest
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService

logger = logging.getLogger(__name__)

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
            
        # Claim Gate
        if draft.claim_gate == "CLAIM_BLOCKED":
            blocked_reasons.append("CLAIM_BLOCKED")
            
        # Identity Check (Name)
        if not draft.approval_checklist.get("normalized_name"):
            blocked_reasons.append("PRODUCT_NAME_NOT_APPROVED")

        # Human Review Fields Unresolved
        unresolved_fields = [f for f in draft.human_review_fields if not draft.approval_checklist.get(f)]
        if unresolved_fields:
            blocked_reasons.append(f"UNRESOLVED_REVIEW_FIELDS: {', '.join(unresolved_fields)}")

        if blocked_reasons:
            return {
                "commit_status": "BLOCKED",
                "write_back_performed": False,
                "blocked_reasons": blocked_reasons,
                "errors": ["COMMIT_GATE_VIOLATION"]
            }

        # 2. Build Canonical Payload
        # Only include approved fields from canonical_candidate_fields
        canonical_payload = {
            "source": "MANUAL",
            "raw_product_title": draft.declared_evidence_fields.get("product_name") or "Unnamed Owned Product",
            "product_display_name": draft.canonical_candidate_fields.get("normalized_name"),
            "product_short_name": draft.canonical_candidate_fields.get("normalized_name")[:80] if draft.canonical_candidate_fields.get("normalized_name") else "Unnamed",
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
