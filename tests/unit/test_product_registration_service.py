import pytest

from agent.models.product_intelligence import ProductIntelligenceProfile
from agent.models.product_registration import ProductRegistrationEvaluateRequest
from agent.models.product_truth import ProductTruthProfile
from agent.services.product_registration_service import evaluate_product_registration


def _truth_profile(
    *,
    source_anchor_status: str = "SOURCE_ANCHOR_VERIFIED_FROM_RAW_SOURCE",
    confidence_label: str = "HIGH",
    authority_decision: str = "SOURCE_ANCHOR",
    source_category: str = "Laundry Care",
    source_subcategory: str = "Detergent",
    source_type: str = "Liquid Laundry Detergent",
    dims_display: str | None = None,
) -> ProductTruthProfile:
    profile = ProductTruthProfile(product_id="prod-001")
    profile.source_anchors.source_anchor_status = source_anchor_status
    profile.source_anchors.source_anchor_origin = "WORKBOOK_MOCK"
    profile.source_anchors.source_category = source_category
    profile.source_anchors.source_subcategory = source_subcategory
    profile.source_anchors.source_product_type = source_type
    profile.reconciliation.confidence_label = confidence_label
    profile.reconciliation.authority_decision = authority_decision
    profile.final_output_preview.final_group = "LAUNDRY_CARE"
    profile.final_output_preview.final_sub_group = "LAUNDRY_CARE"
    profile.final_output_preview.final_type_of_product = "LIQUID_LAUNDRY_DETERGENT"
    profile.final_output_preview.bosmax_product_family = "LAUNDRY_DETERGENT_LIQUID_REFILL"
    profile.final_output_preview.package_form = "bottle_or_refill_pack"
    profile.final_output_preview.physical_state = "liquid"
    profile.final_output_preview.product_scale_class = "liquid_bottle_or_refill_pack"
    if dims_display:
        profile.spec_evidence.dimension_normalized_cm.display = dims_display
    return profile


def _intelligence_profile(
    *,
    confidence: str = "HIGH",
    intelligence_status: str = "READY",
    claim_gate: str = "CLAIM_SAFE",
    taxonomy_conflict: bool = False,
    taxonomy_conflict_reason: str | None = None,
    image_status: str = "VISION_PROVIDER_NOT_CONFIGURED",
    image_provider: str = "not_configured",
    visual_confidence: str = "NOT_VERIFIED",
) -> ProductIntelligenceProfile:
    return ProductIntelligenceProfile(
        product_id="prod-001",
        source="MANUAL",
        normalized_title="sabun dobi",
        group="LAUNDRY_CARE",
        sub_group="LAUNDRY_CARE",
        type_of_product="LIQUID_LAUNDRY_DETERGENT",
        bosmax_product_family="LAUNDRY_DETERGENT_LIQUID_REFILL",
        package_form="bottle_or_refill_pack",
        physical_state="liquid",
        product_scale_class="liquid_bottle_or_refill_pack",
        handling_profile="bottle handling",
        scene_profile="utility demo",
        camera_profile="label forward",
        copy_route="DIRECT",
        claim_gate=claim_gate,
        claim_tokens=["antibacterial_claim"] if claim_gate != "CLAIM_SAFE" else [],
        copy_formula="UTILITY_DEMO",
        destination_readiness={
            "TEXT_TO_VIDEO": "READY",
            "FRAMES": "READY",
            "INGREDIENTS": "READY",
            "IMAGE": "READY",
        },
        sales_metrics={"source_status": "FOUND"},
        image_analysis={
            "status": image_status,
            "provider": image_provider,
            "detected_package": None,
            "detected_text": [],
            "visual_confidence": visual_confidence,
            "warnings": [],
        },
        confidence=confidence,
        warnings=[],
        provenance=[],
        intelligence_status=intelligence_status,
        taxonomy_conflict=taxonomy_conflict,
        taxonomy_conflict_reason=taxonomy_conflict_reason,
    )


def _physics() -> dict:
    return {
        "physics_class": "LAUNDRY_LIQUID_REFILL",
        "product_scale": "LIQUID_BOTTLE_OR_REFILL_PACK",
        "hand_object_interaction": "show bottle label and cap",
        "recommended_grip": "two-hand support",
        "section_5_product_physics_prompt": "Show bottle/refill scale with label, cap, nozzle, and pour direction visible.",
    }


@pytest.mark.asyncio
async def test_affiliate_lane_cannot_become_owned_canonical(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        ProductRegistrationEvaluateRequest(
            product_payload={
                "id": "fm-001",
                "source": "FASTMOSS",
                "raw_product_title": "3 in 1 Sabun Dobi",
                "category": "Laundry Care",
            }
        )
    )

    assert response.write_back_allowed is False
    assert response.affiliate_source_contamination_risk is True
    assert response.registration_status == "HUMAN_REVIEW_REQUIRED"
    assert response.owned_product_lane_status == "AFFILIATE_SOURCE_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_manual_input_remains_declared_evidence_not_canonical(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(
            source_anchor_status="SOURCE_ANCHOR_UNVERIFIED",
            confidence_label="LOW",
            authority_decision="KEYWORD_RULE",
        ),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(confidence="LOW", intelligence_status="NEEDS_REVIEW"),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        ProductRegistrationEvaluateRequest(
            product_payload={
                "source": "MANUAL",
                "raw_product_title": "Sabun Dobi Manual",
                "category": "Laundry Care",
                "subcategory": "Detergent",
                "type": "Liquid",
            }
        )
    )

    assert response.dry_run_only is True
    assert "category" in response.declared_evidence_fields
    assert "raw_product_title" in response.declared_evidence_fields
    assert "group" not in response.canonical_fields_allowed
    assert response.registration_status == "HUMAN_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_source_anchor_missing_requires_review(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(
            source_anchor_status="SOURCE_ANCHOR_MISSING",
            confidence_label="LOW",
            authority_decision="KEYWORD_RULE",
        ),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(confidence="MEDIUM"),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {"product_payload": {"source": "MANUAL", "raw_product_title": "Atlas Product"}}
    )

    assert "SOURCE_ANCHORED_PRODUCT_EVIDENCE" in response.required_evidence
    assert "group" in response.human_review_fields


@pytest.mark.asyncio
async def test_keyword_derived_mapping_requires_review(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(
            source_anchor_status="SOURCE_ANCHOR_KEYWORD_DERIVED",
            confidence_label="LOW",
            authority_decision="KEYWORD_RULE",
        ),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(confidence="LOW", intelligence_status="NEEDS_REVIEW"),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {"product_payload": {"source": "MANUAL", "raw_product_title": "Unknown Product"}}
    )

    assert response.registration_status == "HUMAN_REVIEW_REQUIRED"
    assert "MAPPING_V2_REVIEW_REQUIRED" in response.registration_warnings


@pytest.mark.asyncio
async def test_claim_review_blocks_canonical_claim_writeback(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(claim_gate="CLAIM_REVIEW_REQUIRED"),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {
            "product_payload": {"source": "MANUAL", "raw_product_title": "Sabun Antibakteria"},
            "manual_declared_fields": {"claim_tokens": ["antibacterial_claim"]},
        }
    )

    assert response.write_back_allowed is False
    assert response.claim_safety_requires_human_review is True
    assert "claim_tokens" in response.blocked_fields
    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_missing_image_or_ocr_proof_prevents_visual_canonicalization(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(image_status="IMAGE_MISSING"),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {
            "product_payload": {"source": "MANUAL", "raw_product_title": "Atlas Bottle"},
            "manual_declared_fields": {"package_form": "bottle"},
        }
    )

    assert "SEMANTIC_IMAGE_OR_OCR_PROOF" in response.required_evidence
    assert "package_form" in response.human_review_fields
    assert response.image_analysis_status == "IMAGE_MISSING"


@pytest.mark.asyncio
async def test_missing_verified_dimensions_blocks_exact_dimension_writeback(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(dims_display=None),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {
            "product_payload": {"source": "MANUAL", "raw_product_title": "Atlas Product"},
            "manual_declared_fields": {"length_cm": 10, "width_cm": 5},
        }
    )

    assert response.dimension_truth_status == "DIMENSIONS_NOT_VERIFIED"
    assert "length_cm" in response.blocked_fields
    assert "VERIFIED_DIMENSIONS_OR_SIZE_SPEC" in response.required_evidence
    assert response.registration_status == "BLOCK_REGISTRATION"


@pytest.mark.asyncio
async def test_dry_run_default_performs_no_db_mutation_and_explicit_write_is_rejected(monkeypatch):
    async def fail_create(*args, **kwargs):
        raise AssertionError("create_product should not be called")

    async def fail_update(*args, **kwargs):
        raise AssertionError("update_product should not be called")

    monkeypatch.setattr("agent.services.product_registration_service.crud.create_product", fail_create, raising=False)
    monkeypatch.setattr("agent.services.product_registration_service.crud.update_product", fail_update, raising=False)
    monkeypatch.setattr(
        "agent.services.product_registration_service.ProductTruthService.build_computed_profile",
        lambda payload: _truth_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_intelligence_profile",
        lambda payload: _intelligence_profile(),
    )
    monkeypatch.setattr(
        "agent.services.product_registration_service.resolve_product_physics",
        lambda product: _physics(),
    )

    response = await evaluate_product_registration(
        {
            "product_payload": {"source": "MANUAL", "raw_product_title": "Atlas Product"},
            "write_back_requested": True,
            "dry_run_only": False,
        }
    )

    assert response.write_back_allowed is False
    assert response.write_back_performed is False
    assert response.no_db_write_reason == "WRITE_BACK_NOT_ENABLED_IN_THIS_PR"
    assert "WRITE_BACK_NOT_ENABLED_IN_THIS_PR" in response.registration_errors
