import pytest
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.product_knowledge_service import complete_product_knowledge

def test_complete_product_knowledge_basic():
    request = ProductKnowledgeCompleteRequest(
        product_name="Bosmax Liquid Detergent",
        product_knowledge_text="Sabun dobi wangi 1.2kg botol biru",
        price=12.9,
        commission_rate="10%",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.completion_status == "COMPLETION_READY"
    assert response.suggested_bosmax_product_family == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert response.claim_gate == "CLAIM_SAFE"
    assert "1.2kg" in response.extracted_product_facts["size_or_volume"]

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
