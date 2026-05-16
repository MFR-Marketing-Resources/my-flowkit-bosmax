import pytest
from agent.services.product_intelligence_service import resolve_product_intelligence_profile
from agent.services.product_knowledge_service import complete_product_knowledge
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest

def _product(**overrides):
    payload = {
        "id": "prod-female-001",
        "source": "MANUAL",
        "raw_product_title": "Generic Product",
        "product_display_name": "Generic Product",
        "product_short_name": "Generic Product",
        "category": "Health",
        "subcategory": "Feminine Care",
        "type": "Female Health",
    }
    payload.update(overrides)
    return payload

def test_jamu_perapat_resolves_to_female_health_sensitive():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Jamu Perapat Wanita Tradisional",
            product_display_name="Jamu Perapat Wanita",
        )
    )

    assert result["bosmax_product_family"] == "FEMALE_HEALTH_SENSITIVE"
    assert result["group"] == "FEMALE_HEALTH_SENSITIVE"
    assert result["copy_route"] == "STEALTH"
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert "female_health_sensitive" in result["claim_tokens"]
    assert "perapat" in result["claim_tokens"]

def test_jamu_wanita_taxonomy_resolves_to_female_health():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Jamu Wanita Ajaib",
            category="Health",
            subcategory="Feminine Care",
            type="Female Health",
        )
    )

    assert result["bosmax_product_family"] == "FEMALE_HEALTH_SENSITIVE"
    assert result["type_of_product"] == "SENSITIVE_FEMALE_HEALTH_PRODUCT"

def test_sensitive_female_tokens_trigger_claim_review():
    tokens = ["miss v", "faraj", "vagina", "keputihan", "ketat", "anjal"]
    for token in tokens:
        result = resolve_product_intelligence_profile(
            _product(
                raw_product_title=f"Product with {token}",
            )
        )
        assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
        assert token in result["claim_tokens"]

def test_blocked_female_tokens_trigger_claim_blocked():
    blocked_tokens = ["fertility claim", "hormone claim", "infection treatment"]
    for token in blocked_tokens:
        result = resolve_product_intelligence_profile(
            _product(
                raw_product_title=f"Product with {token}",
            )
        )
        assert result["claim_gate"] == "CLAIM_BLOCKED"
        assert token in result["claim_tokens"]

def test_product_knowledge_completion_maps_female_health_correctly():
    request = ProductKnowledgeCompleteRequest(
        product_name="Jamu Perapat",
        product_knowledge_text="Jamu untuk kesegaran wanita dan merapatkan.",
        source_lane="MANUAL"
    )
    response = complete_product_knowledge(request)
    
    assert response.suggested_bosmax_product_family == "FEMALE_HEALTH_SENSITIVE"
    assert response.suggested_category == "Health"
    assert response.suggested_subcategory == "Feminine Care"
    assert response.suggested_type == "Female Health"
    assert response.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert "perapat" in response.claim_tokens

def test_male_health_regression():
    # Ensure male health still works
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Kuat Lelaki Tahan Lama",
            category="Health",
            subcategory="Supplements",
            type="Male Health",
        )
    )
    assert result["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"
    assert result["group"] == "MALE_HEALTH_SENSITIVE"

def test_bosmax_herbs_5ml_regression():
    # BOSMAX Herbs 5 ML should remain MALE_HEALTH_SENSITIVE
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Bosmax Herbs 5 ML",
            product_display_name="Bosmax Herbs 5 ML",
            category="Health",
            subcategory="Supplements",
            type="Male Health",
        )
    )
    assert result["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"
