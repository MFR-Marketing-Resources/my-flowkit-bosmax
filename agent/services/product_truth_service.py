from __future__ import annotations

import re
from typing import Any

from agent.models.product_truth import (
    ProductTruthProfile,
    ProductTruthProvenance,
    ProductTruthSourceAnchors,
    ProductTruthDeclaredEvidence,
    ProductTruthTextEvidence,
    ProductTruthSpecEvidence,
    ProductTruthDimensionNormalized,
    ProductTruthVisualEvidence,
    ProductTruthAnalyzedTraits,
    ProductTruthVisualTrait,
    ProductTruthCommerceEvidence,
    ProductTruthClaimEvidence,
    ProductTruthNegativeConstraints,
    ProductTruthReconciliation,
    ProductTruthFinalOutputPreview,
)
from agent.services.product_intelligence_service import (
    _resolve_sales_metrics,
    _resolve_image_analysis,
    _resolve_claim_gate,
    FAMILY_PROFILES,
    REVIEW_CLAIM_TOKENS,
    BLOCKED_CLAIM_TOKENS,
)
from agent.services.product_mapping import (
    normalize_mapping_text,
    resolve_product_mapping,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family


# Required stable Flag IDs from contract
FLAG_KEYWORD_VS_ANCHOR_TAXONOMY = "FLAG_KEYWORD_VS_ANCHOR_TAXONOMY"
FLAG_MANUAL_INPUT_CONTRADICTION_REVIEW_REQUIRED = "FLAG_MANUAL_INPUT_CONTRADICTION_REVIEW_REQUIRED"
FLAG_IMAGE_VS_SOURCE_PHYSICS_CONFLICT = "FLAG_IMAGE_VS_SOURCE_PHYSICS_CONFLICT"
FLAG_SOURCE_ANCHOR_MISSING = "FLAG_SOURCE_ANCHOR_MISSING"
FLAG_SOURCE_ANCHOR_WEAK_FILE_HINT_ONLY = "FLAG_SOURCE_ANCHOR_WEAK_FILE_HINT_ONLY"
FLAG_SOURCE_ANCHOR_COLUMN_NOT_FOUND = "FLAG_SOURCE_ANCHOR_COLUMN_NOT_FOUND"
FLAG_SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE = "FLAG_SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"
FLAG_TIKTOKSHOP_EXTRACTION_INCOMPLETE = "FLAG_TIKTOKSHOP_EXTRACTION_INCOMPLETE"
FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION = "FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION"
FLAG_NEGATIVE_CONSTRAINT_MATCHED = "FLAG_NEGATIVE_CONSTRAINT_MATCHED"
FLAG_CLAIM_REVIEW_REQUIRED = "FLAG_CLAIM_REVIEW_REQUIRED"

# Phase 2 Flags: FastMoss Taxonomy Reconciliation
FLAG_FASTMOSS_SOURCE_ANCHOR_POTENTIALLY_CONTAMINATED = "FLAG_FASTMOSS_SOURCE_ANCHOR_POTENTIALLY_CONTAMINATED"
FLAG_FASTMOSS_SOURCE_ANCHOR_KEYWORD_DERIVED = "FLAG_FASTMOSS_SOURCE_ANCHOR_KEYWORD_DERIVED"
FLAG_FASTMOSS_RAW_SOURCE_NOT_AVAILABLE = "FLAG_FASTMOSS_RAW_SOURCE_NOT_AVAILABLE"
FLAG_FASTMOSS_RAW_SOURCE_COLUMNS_MISSING = "FLAG_FASTMOSS_RAW_SOURCE_COLUMNS_MISSING"


class ProductTruthService:
    @staticmethod
    def build_computed_profile(product: dict[str, Any]) -> ProductTruthProfile:
        """
        Build a read-only computed Product Truth Profile from existing product row.
        Follows the BOSMAX Product Truth Reconciliation Contract.
        """
        product_id = str(product.get("id") or "")
        source = str(product.get("source") or "UNKNOWN").upper()
        
        # 1. Provenance
        provenance = ProductTruthProvenance(
            source_origin=source,
            commerce_mode="AFFILIATE" if source == "FASTMOSS" else "UNKNOWN",
            source_url=product.get("source_url"),
            tiktok_product_url=product.get("tiktok_product_url"),
            source_file_hint=product.get("fastmoss_source_file"),
            ingestion_timestamp=product.get("created_at"),
            builder_version="1.0.0-phase1",
        )

        # 2. Source Anchors
        source_anchors = ProductTruthService._extract_source_anchors(product, source)

        # 3. Declared Evidence (Manual Lane)
        declared = ProductTruthDeclaredEvidence()
        if source == "MANUAL":
            declared.user_category = product.get("category")
            declared.user_subcategory = product.get("subcategory")
            declared.user_product_type = product.get("type")
            declared.manual_authority_status = "DECLARED_PENDING_RECONCILIATION"

        # 4. Text Evidence
        raw_title = (
            product.get("raw_product_title")
            or product.get("product_display_name")
            or product.get("product_short_name")
            or ""
        )
        text_evidence = ProductTruthTextEvidence(
            raw_title=raw_title,
            normalized_title=normalize_mapping_text(raw_title),
            description=None, # TBD in later phases
        )

        # 5. Spec Evidence & Dimensions
        spec_evidence = ProductTruthService._extract_spec_evidence(product)

        # 6. Visual Evidence
        visual_evidence = ProductTruthService._extract_visual_evidence(product)

        # 7. Commerce Evidence
        sales_metrics, sales_provenance = _resolve_sales_metrics(product)
        commerce_evidence = ProductTruthCommerceEvidence(
            price=product.get("price"),
            currency=product.get("currency") or "MYR",
            commission_rate=product.get("commission_rate"),
            commission_amount=product.get("commission_amount"),
            sold_count=sales_metrics.sold_count,
            shop_count=sales_metrics.shop_count,
            shop_names=sales_metrics.shop_names,
        )

        # 8. Negative Constraints
        negative_constraints = ProductTruthService._calculate_negative_constraints(source_anchors)

        # 9. Reconciliation Logic (The Core of PTR)
        reconciliation = ProductTruthService._reconcile(
            source_anchors=source_anchors,
            declared=declared,
            text_evidence=text_evidence,
            visual_evidence=visual_evidence,
            negative_constraints=negative_constraints,
            product=product
        )

        # 10. Claim Evidence
        claim_evidence = ProductTruthService._extract_claim_evidence(product, reconciliation)

        # 11. Final Output Preview (What current Mapping V2 would produce)
        # We use existing services but NPTP reconciliation may override them in future phases.
        # For Phase 1, we show what THEY currently say.
        final_preview = ProductTruthService._build_final_preview(product, reconciliation, claim_evidence)

        return ProductTruthProfile(
            product_id=product_id,
            provenance=provenance,
            source_anchors=source_anchors,
            declared_evidence=declared,
            text_evidence=text_evidence,
            spec_evidence=spec_evidence,
            visual_evidence=visual_evidence,
            commerce_evidence=commerce_evidence,
            claim_evidence=claim_evidence,
            negative_constraints=negative_constraints,
            reconciliation=reconciliation,
            final_output_preview=final_preview,
        )

    @staticmethod
    def _extract_source_anchors(product: dict[str, Any], source: str) -> ProductTruthSourceAnchors:
        anchors = ProductTruthSourceAnchors()
        
        if source == "FASTMOSS":
            # In FastMoss lane, we expect category/subcategory to be preserved from workbook
            anchors.source_product_type = product.get("type")
            
            # Phase 2: Perform FastMoss Taxonomy Audit against Raw Source
            from agent.services.fastmoss_taxonomy_reconciliation_service import FastMossTaxonomyReconciliationService
            audit = FastMossTaxonomyReconciliationService.audit_fastmoss_product(product)
            
            anchors.source_anchor_status = audit["source_anchor_status"]
            anchors.source_anchor_origin = audit["source_anchor_origin"]
            
            # Enrich anchors with audit metadata
            if audit.get("raw_values"):
                # We prioritize raw values as the "True" anchors
                anchors.source_category = audit["raw_values"]["category"]
                anchors.source_subcategory = audit["raw_values"]["subcategory"]
                anchors.source_product_type = audit["raw_values"]["type"]
            else:
                anchors.source_category = product.get("category")
                anchors.source_subcategory = product.get("subcategory")
                anchors.source_product_type = product.get("type")

            # Add notes from audit
            if audit.get("notes"):
                anchors.source_anchor_notes = audit["notes"]
            
            anchors.source_anchor_columns = audit.get("discovered_columns") or []
        
        elif source == "MANUAL":
            anchors.source_anchor_origin = "MANUAL_DECLARED"
            anchors.source_anchor_status = "UNVERIFIED"
            
        return anchors

    @staticmethod
    def _extract_spec_evidence(product: dict[str, Any]) -> ProductTruthSpecEvidence:
        # Phase 1: Simple dimension extraction from title if present
        title = str(product.get("raw_product_title") or "").lower()
        
        # Look for patterns like 10cm x 5cm x 2cm or 100mm x 50mm
        # This is a basic implementation for Phase 1
        dim_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|mm)\s*[x*]\s*(\d+(?:\.\d+)?)\s*(?:cm|mm)(?:\s*[x*]\s*(\d+(?:\.\d+)?)\s*(?:cm|mm))?", title)
        
        normalized_dims = ProductTruthDimensionNormalized()
        if dim_match:
            is_mm = "mm" in title[dim_match.start():dim_match.end()]
            factor = 0.1 if is_mm else 1.0
            
            normalized_dims.length_cm = round(float(dim_match.group(1)) * factor, 2)
            normalized_dims.width_cm = round(float(dim_match.group(2)) * factor, 2)
            if dim_match.group(3):
                normalized_dims.height_cm = round(float(dim_match.group(3)) * factor, 2)
            
            parts = [str(normalized_dims.length_cm), str(normalized_dims.width_cm)]
            if normalized_dims.height_cm:
                parts.append(str(normalized_dims.height_cm))
            normalized_dims.display = " x ".join(parts) + " cm"

        return ProductTruthSpecEvidence(
            dimension_evidence=dim_match.group(0) if dim_match else None,
            dimension_normalized_cm=normalized_dims,
            spec_status="PRESENT" if dim_match else "MISSING"
        )

    @staticmethod
    def _extract_visual_evidence(product: dict[str, Any]) -> ProductTruthVisualEvidence:
        analysis = _resolve_image_analysis(product)
        
        visual = ProductTruthVisualEvidence(
            image_urls=[product.get("image_url")] if product.get("image_url") else [],
            image_analysis_status=analysis.get("status", "UNKNOWN"),
            provider=analysis.get("provider", "unknown")
        )
        
        if visual.image_analysis_status == "ANALYZED":
            traits = ProductTruthAnalyzedTraits()
            traits.package = ProductTruthVisualTrait(
                value=analysis.get("detected_package"),
                confidence=1.0 if analysis.get("visual_confidence") == "HIGH" else 0.5
            )
            traits.text = analysis.get("detected_text", [])
            visual.analyzed_traits = traits
            
        return visual

    @staticmethod
    def _calculate_negative_constraints(anchors: ProductTruthSourceAnchors) -> ProductTruthNegativeConstraints:
        constraints = ProductTruthNegativeConstraints()
        
        category = normalize_mapping_text(anchors.source_category)
        subcategory = normalize_mapping_text(anchors.source_subcategory)
        
        # Example Boundary Locks from Contract
        if category in {"baby care", "baby and maternity", "baby hygiene"}:
            constraints.category_boundary_locks.append("BABY_HYGIENE_BOUNDARY")
            constraints.forbidden_family_transitions.append("beauty_fragrance")
        
        if category in {"electronics", "electronics and gadgets"} or subcategory == "wearable device":
            constraints.category_boundary_locks.append("ELECTRONICS_BOUNDARY")
            constraints.forbidden_family_transitions.append("MALE_HEALTH_SENSITIVE")
            
        if category in {"beauty", "beauty and personal care"}:
            constraints.category_boundary_locks.append("BEAUTY_BOUNDARY")
            constraints.forbidden_family_transitions.append("HOME_TEXTILE")
            
        return constraints

    @staticmethod
    def _reconcile(
        source_anchors: ProductTruthSourceAnchors,
        declared: ProductTruthDeclaredEvidence,
        text_evidence: ProductTruthTextEvidence,
        visual_evidence: ProductTruthVisualEvidence,
        negative_constraints: ProductTruthNegativeConstraints,
        product: dict[str, Any]
    ) -> ProductTruthReconciliation:
        recon = ProductTruthReconciliation()
        source = str(product.get("source") or "").upper()
        
        # 1. Check for Missing Anchors
        if source_anchors.source_anchor_status == "MISSING":
            recon.contradiction_flags.append(FLAG_SOURCE_ANCHOR_MISSING)
        elif source_anchors.source_anchor_status == "WEAK_FILE_HINT_ONLY":
            recon.contradiction_flags.append(FLAG_SOURCE_ANCHOR_WEAK_FILE_HINT_ONLY)
        
        # FastMoss Specific Contradiction Flags
        if source == "FASTMOSS":
            if source_anchors.source_anchor_status == "SOURCE_ANCHOR_KEYWORD_DERIVED":
                recon.contradiction_flags.append(FLAG_FASTMOSS_SOURCE_ANCHOR_KEYWORD_DERIVED)
            if "POTENTIALLY_CONTAMINATED" in source_anchors.source_anchor_status:
                recon.contradiction_flags.append(FLAG_FASTMOSS_SOURCE_ANCHOR_POTENTIALLY_CONTAMINATED)
            if "RAW_SOURCE_NOT_AVAILABLE" in source_anchors.source_anchor_status:
                recon.contradiction_flags.append(FLAG_FASTMOSS_RAW_SOURCE_NOT_AVAILABLE)

        # 2. Check for Image Analysis Availability
        if visual_evidence.image_analysis_status == "VISION_PROVIDER_NOT_CONFIGURED":
            recon.contradiction_flags.append(FLAG_SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE)

        # 3. Simulate Keyword Mapping to find contradictions
        # In a real implementation, we'd run the actual keyword matcher
        current_mapping = resolve_product_mapping(product=product)
        mapped_category = normalize_mapping_text(current_mapping.get("category"))
        mapped_type = normalize_mapping_text(current_mapping.get("type"))
        
        anchor_category = normalize_mapping_text(source_anchors.source_category)
        
        # 4. Boundary Lock Violation Check
        if anchor_category:
            # If mapped family is in forbidden transitions for this anchor
            # We derive the family using the current logic to see what it WOULD be
            family_info = derive_bosmax_product_family(current_mapping)
            mapped_family = family_info.get("bosmax_product_family")
            
            if mapped_family in negative_constraints.forbidden_family_transitions:
                recon.contradiction_flags.append(FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION)
                recon.contradiction_flags.append(FLAG_KEYWORD_VS_ANCHOR_TAXONOMY)
                recon.matched_negative_constraints.append(f"FORBIDDEN_TRANSITION:{mapped_family}")

        # 5. Specific known Hallucination Patterns (Cross-check Title vs Mapping)
        title = text_evidence.normalized_title
        # Baby Wipes Hallucination (Mapped to Beauty)
        if "baby" in title and ("wipes" in title or "tisu" in title) and "beauty" in mapped_category:
             recon.contradiction_flags.append(FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION)
             recon.provenance_notes.append("Hallucination check: baby wipes mapped to beauty lane suspected.")

        # Smartwatch Hallucination (Mapped to Health)
        if "smartwatch" in title and ("health" in mapped_category or "male" in mapped_category):
             recon.contradiction_flags.append(FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION)
             recon.provenance_notes.append("Hallucination check: smartwatch mapped to health lane suspected.")

        # 6. Confidence Scoring
        # HIGH requires source anchor AND corroborating signal AND no contradictions
        has_anchor = source_anchors.source_anchor_status == "PRESENT"
        has_contradiction = len(recon.contradiction_flags) > 0
        
        if has_contradiction:
            recon.confidence_label = "NEEDS_REVIEW"
            recon.confidence_score = 0.2
        elif not has_anchor:
            recon.confidence_label = "LOW"
            recon.confidence_score = 0.4
        else:
            # Anchor exists and no contradictions
            recon.confidence_label = "MEDIUM"
            recon.confidence_score = 0.7
            # In Phase 1 we don't have enough corroboration logic to reach HIGH safely
            # as per contract: "A single weak keyword match must never produce HIGH."
            
        recon.authority_decision = "SOURCE_ANCHOR" if has_anchor else "KEYWORD_RULE"
        if has_contradiction:
            recon.authority_decision = "RECONCILIATION_FAILED"
            
        return recon

    @staticmethod
    def _extract_claim_evidence(product: dict[str, Any], recon: ProductTruthReconciliation) -> ProductTruthClaimEvidence:
        # Use existing claim gate logic
        mapping = resolve_product_mapping(product=product)
        family_info = derive_bosmax_product_family(mapping)
        family = family_info.get("bosmax_product_family")
        
        status, tokens, warnings = _resolve_claim_gate(product, family, mapping.get("copy_route", "UNKNOWN"))
        
        claim = ProductTruthClaimEvidence(
            claim_tokens=tokens,
            claim_sources=["title", "description"] if tokens else [],
            claim_gate_preview=status
        )
        
        if status == "CLAIM_REVIEW_REQUIRED":
            recon.contradiction_flags.append(FLAG_CLAIM_REVIEW_REQUIRED)
            
        return claim

    @staticmethod
    def _build_final_preview(
        product: dict[str, Any], 
        recon: ProductTruthReconciliation,
        claim: ProductTruthClaimEvidence
    ) -> ProductTruthFinalOutputPreview:
        # This shows what the system CURRENTLY thinks, but with PTR metadata
        mapping = resolve_product_mapping(product=product)
        family_info = derive_bosmax_product_family(mapping)
        family = family_info.get("bosmax_product_family")
        profile = FAMILY_PROFILES.get(family, FAMILY_PROFILES["UNKNOWN_REVIEW_REQUIRED"])
        
        return ProductTruthFinalOutputPreview(
            final_group=profile.get("group"),
            final_sub_group=profile.get("sub_group"),
            final_type_of_product=profile.get("type_of_product"),
            bosmax_product_family=family,
            package_form=profile.get("package_form"),
            physical_state=profile.get("physical_state"),
            product_scale_class=profile.get("product_scale_class"),
            copy_route=profile.get("copy_route", "UNKNOWN"),
            claim_gate=claim.claim_gate_preview
        )
