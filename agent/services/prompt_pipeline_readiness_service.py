from __future__ import annotations

from typing import Any
from agent.services.product_intelligence import enrich_product, IMAGE_READY_STATES
from agent.services.product_lifecycle_service import lifecycle_status
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED,
    STATUS_REVIEW_READY,
)
from agent.services.production_prompt_approval_service import (
    get_production_approved_modes,
    is_production_prompt_approved,
)

class PromptPipelineReadinessService:
    @staticmethod
    async def get_readiness_report(product: dict[str, Any]) -> dict[str, Any]:
        """Build a comprehensive readiness report for the prompt pipeline."""
        enriched = await enrich_product(product, persist=False)
        
        product_id = enriched.get("id") or enriched.get("product_id")
        name = enriched.get("raw_product_title")
        source = enriched.get("source")
        status = enriched.get("lifecycle_status")
        
        # Identity: is name/title clean?
        identity_status = "READY" if enriched.get("product_short_name") and len(enriched.get("raw_product_title", "")) > 5 else "NEEDS_REVIEW"
        
        # Taxonomy: are category/subcategory/type mapped?
        taxonomy_status = "READY" if enriched.get("category") and enriched.get("subcategory") and enriched.get("type") else "MISSING_FIELDS"
        if enriched.get("mapping_status") == "NEEDS_REVIEW":
             taxonomy_status = "NEEDS_REVIEW"
        
        claim_gate = enriched.get("claim_gate")
        claim_tokens = enriched.get("claim_tokens", [])
        claim_risk_level = enriched.get("claim_risk_level")
        claim_safe_copy_status = enriched.get("claim_safe_copy_status")
        production_prompt_approval_status = enriched.get("production_prompt_approval_status")
        production_prompt_approved_modes = get_production_approved_modes(enriched)
        production_prompt_approved = is_production_prompt_approved(enriched)
        claim_safe_copy_review_ready = claim_safe_copy_status in {STATUS_REVIEW_READY, STATUS_APPROVED}
        claim_safe_copy_required = (
            (claim_gate == "CLAIM_REVIEW_REQUIRED" or claim_gate == "CLAIM_BLOCKED")
            and not claim_safe_copy_review_ready
        )
        
        physics_class = enriched.get("physics_class")
        physics_status = enriched.get("physics_dna_status") or ("READY" if physics_class else "MISSING_FIELDS")
        
        image_status = enriched.get("image_readiness_status")
        image_reference_status = image_status
        has_image = image_status in IMAGE_READY_STATES
        
        missing_required_assets = []
        if not has_image:
            missing_required_assets.append("IMAGE_REFERENCE")
            
        # Readiness by mode
        readiness_by_mode = {}
        
        # Modes: T2V, F2V, I2V, IMG, Ingredients, Frames, ProductAssetGenerator, PromptGeneration
        
        if status == "ARCHIVED":
            readiness_by_mode = {
                mode: "BLOCKED_PRODUCT_ARCHIVED" 
                for mode in ["T2V", "F2V", "I2V", "IMG", "Ingredients", "Frames", "ProductAssetGenerator", "PromptGeneration"]
            }
        else:
            # T2V
            t2v_status = "READY"
            if production_prompt_approved and "T2V" in production_prompt_approved_modes:
                t2v_status = "PRODUCTION_READY"
            elif claim_safe_copy_required:
                t2v_status = "NEEDS_REVIEW"
            elif claim_safe_copy_review_ready and claim_gate != "CLAIM_SAFE":
                t2v_status = "DRY_RUN_READY"
            if enriched.get("bosmax_product_family") == "MALE_HEALTH_SENSITIVE" and not (
                production_prompt_approved and "T2V" in production_prompt_approved_modes
            ):
                t2v_status = "DRY_RUN_READY" if claim_safe_copy_review_ready else "NEEDS_REVIEW"
            readiness_by_mode["T2V"] = t2v_status
            
            # Image dependent modes
            img_modes = ["F2V", "I2V", "IMG", "Ingredients", "Frames"]
            for mode in img_modes:
                if not has_image:
                    readiness_by_mode[mode] = "IMAGE_REFERENCE_REQUIRED"
                elif production_prompt_approved and mode in production_prompt_approved_modes:
                    readiness_by_mode[mode] = "PRODUCTION_READY"
                elif claim_safe_copy_review_ready and claim_gate != "CLAIM_SAFE":
                    readiness_by_mode[mode] = "DRY_RUN_READY"
                elif claim_safe_copy_required:
                    readiness_by_mode[mode] = "NEEDS_REVIEW"
                else:
                    readiness_by_mode[mode] = "READY"
                    
            # ProductAssetGenerator
            if physics_status == "READY" and taxonomy_status == "READY":
                readiness_by_mode["ProductAssetGenerator"] = "READY"
            else:
                readiness_by_mode["ProductAssetGenerator"] = "NEEDS_FIELDS"
                
            # PromptGeneration
            if production_prompt_approved and {"T2V", "IMG"}.issubset(set(production_prompt_approved_modes)):
                readiness_by_mode["PromptGeneration"] = "PRODUCTION_READY"
            elif all(readiness_by_mode[m] == "READY" for m in ["T2V", "IMG", "F2V"]):
                readiness_by_mode["PromptGeneration"] = "READY"
            elif claim_safe_copy_review_ready and has_image and taxonomy_status == "READY":
                readiness_by_mode["PromptGeneration"] = "DRY_RUN_READY"
            elif any(readiness_by_mode[m] == "IMAGE_REFERENCE_REQUIRED" for m in ["IMG", "F2V"]):
                readiness_by_mode["PromptGeneration"] = "NEEDS_IMAGE"
            else:
                readiness_by_mode["PromptGeneration"] = "NEEDS_REVIEW"

        blockers = []
        if status == "ARCHIVED":
            blockers.append("PRODUCT_ARCHIVED")
        if not has_image:
            blockers.append("IMAGE_REFERENCE_MISSING")
        if claim_safe_copy_required:
            blockers.append("CLAIM_SAFE_COPY_REQUIRED")
        elif not production_prompt_approved and claim_safe_copy_review_ready and claim_gate != "CLAIM_SAFE":
            blockers.append("CLAIM_REVIEW_REQUIRED_FOR_PRODUCTION")
        if taxonomy_status != "READY":
            blockers.append("TAXONOMY_MISSING")
        if physics_status != "READY":
            blockers.append("PHYSICS_MISSING")
            
        next_required_inputs = []
        if not has_image:
            next_required_inputs.append("UPLOAD_IMAGE")
        if claim_safe_copy_required:
            next_required_inputs.append("CLAIM_SAFE_COPY_REWRITE")
        elif not production_prompt_approved and claim_safe_copy_review_ready and claim_gate != "CLAIM_SAFE":
            next_required_inputs.append("HUMAN_PRODUCTION_APPROVAL")
        if taxonomy_status != "READY":
            next_required_inputs.append("MANUAL_MAPPING_REVIEW")
            
        dry_run_preview_allowed = (
            status == "ACTIVE"
            and has_image
            and taxonomy_status == "READY"
            and claim_safe_copy_review_ready
        )
        production_generation_allowed = (
            status == "ACTIVE"
            and has_image
            and taxonomy_status == "READY"
            and (
                claim_gate == "CLAIM_SAFE"
                or {"T2V", "IMG"}.issubset(set(production_prompt_approved_modes))
                or (claim_gate != "CLAIM_SAFE" and claim_safe_copy_status == STATUS_APPROVED)
            )
        )
        safe_to_generate_prompt = production_generation_allowed
        # Special case for BOSMAX Herbs 5 ML: MALE_HEALTH_SENSITIVE requires review
        if enriched.get("bosmax_product_family") == "MALE_HEALTH_SENSITIVE" and not production_generation_allowed:
             safe_to_generate_prompt = False
             production_generation_allowed = False

        return {
            "product_id": product_id,
            "product_name": name,
            "source": source,
            "lifecycle_status": status,
            "identity_status": identity_status,
            "taxonomy_status": taxonomy_status,
            "claim_gate": claim_gate,
            "claim_tokens": claim_tokens,
            "claim_risk_level": claim_risk_level,
            "claim_safe_copy_status": claim_safe_copy_status,
            "production_prompt_approval_status": production_prompt_approval_status,
            "production_prompt_approved_modes": production_prompt_approved_modes,
            "claim_safe_copy_required": claim_safe_copy_required,
            "physics_class": physics_class,
            "physics_status": physics_status,
            "image_reference_status": image_reference_status,
            "missing_required_assets": missing_required_assets,
            "readiness_by_mode": readiness_by_mode,
            "blockers": blockers,
            "next_required_inputs": next_required_inputs,
            "dry_run_preview_allowed": dry_run_preview_allowed,
            "production_generation_allowed": production_generation_allowed,
            "safe_to_generate_prompt": safe_to_generate_prompt,
            "provenance": enriched.get("intelligence_provenance", []),
            "bosmax_product_family": enriched.get("bosmax_product_family")
        }
