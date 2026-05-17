import pytest
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.product_knowledge_service import complete_product_knowledge

def test_complete_product_knowledge_basic():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi wangi 1.2kg botol biru",
        price=12.9,
        currency="MYR",
        commission_amount=1.29,
        commission_rate="10%",
        image_url="https://example.com/detergent.jpg",
        product_url="https://example.com/detergent",
        source_url="https://example.com/source/detergent",
        image_notes="Front label visible in uploaded image.",
        product_form_factor="refill pouch",
        packaging_description="Soft blue pouch with cap",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.completion_status == "COMPLETION_READY"
    assert response.suggested_bosmax_product_family == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert response.claim_gate == "CLAIM_SAFE"
    assert "1.2kg" in response.extracted_product_facts["size_or_volume"]
    assert response.image_analysis_status == "VISION_PROVIDER_NOT_CONFIGURED"
    assert response.image_analysis_image_url == "https://example.com/detergent.jpg"
    assert response.declared_input_fields["source_url"] == "https://example.com/source/detergent"
    assert response.declared_input_fields["image_notes"] == "Front label visible in uploaded image."
    assert response.declared_input_fields["product_form_factor"] == "refill pouch"
    assert response.declared_input_fields["packaging_description"] == "Soft blue pouch with cap"

def test_complete_product_knowledge_claim_gate_review():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Whitening Serum",
        product_knowledge_text="Mencerahkan kulit dengan cepat dan berkesan.",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert "whitening" in response.claim_tokens or "mencerahkan" in response.claim_tokens

def test_complete_product_knowledge_claim_gate_blocked():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Miracle Oil",
        product_knowledge_text="Boleh menyembuhkan sakit lutut dalam 3 hari.",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.claim_gate == "CLAIM_BLOCKED"
    assert "menyembuhkan" in response.claim_tokens

def test_complete_product_knowledge_male_health_claim_gate_review():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Herbs",
        product_knowledge_text="Minyak urutan lelaki untuk tenaga batin dan bahagian intim.",
        benefits_text="Meningkatkan ketegangan dan keyakinan kelelakian.",
        package_notes="Botol kecil 5 ML dengan penitis dropper.",
        size_or_volume="5 ML",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)

    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert any(token in response.claim_tokens for token in ["tenaga batin", "bahagian intim", "ketegangan", "keyakinan kelelakian"])
    assert response.suggested_category == "Health"
    assert response.suggested_subcategory == "Supplements"
    assert response.suggested_type == "Male Health"
    assert response.suggested_bosmax_product_family == "MALE_HEALTH_SENSITIVE"
    assert response.suggested_physics_class == "SUPPLEMENT_BOTTLE"
    assert response.readiness_by_mode["IMG"].status == "IMAGE_REFERENCE_REQUIRED"

def test_complete_product_knowledge_insufficient_data():
    request = ProductKnowledgeCompleteRequest(
        product_name=None,
        product_knowledge_text=None
    )
    response = complete_product_knowledge(request)
    
    assert response.completion_status == "NEEDS_REVIEW"
    assert "PRODUCT_NAME" in response.missing_required_evidence


def test_complete_product_knowledge_tiktok_draft_fails_closed_without_fake_scrape():
    request = ProductKnowledgeCompleteRequest(
        product_name="TikTok Draft Product",
        source_lane="TIKTOKSHOP_DRAFT",
        tiktok_product_url="https://shop.tiktok.com/view/product/123",
        product_url="https://shop.tiktok.com/view/product/123",
        price=19.9,
        currency="MYR",
    )

    response = complete_product_knowledge(request)

    assert response.extraction_status == "NOT_IMPLEMENTED"
    assert "TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED" in response.missing_required_evidence
    assert "TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED" in response.warnings
