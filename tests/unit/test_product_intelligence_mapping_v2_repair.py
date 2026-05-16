import pytest
from agent.services.product_intelligence_service import resolve_product_intelligence_profile

def test_v2_baby_wipes_guardrail():
    # Baby wipes should not be beauty_fragrance
    payload = {
        "id": "test_wipes",
        "raw_product_title": "Baby Wipes Newborn Wet Tissue Tisue Basah Fragrance-free",
        "category": "Baby Care",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "BABY_WIPES"
    # Even if it matches keywords, it should be LOW if no anchor corroborated it (mocked missing anchor)
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_lipmatte_guardrail():
    # Lipmatte should not be HOME_TEXTILE
    payload = {
        "id": "test_lipmatte",
        "raw_product_title": "CUBRE MI LIPMATTE FULL LOCK EDITION",
        "category": "Beauty",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "BEAUTY_PERSONAL_CARE"
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_makeup_powder_guardrail():
    # Makeup powder should not be HOME_TEXTILE
    payload = {
        "id": "test_powder",
        "raw_product_title": "KAXIER Powder Two Way Cake Pressed Powder",
        "category": "Beauty",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "BEAUTY_PERSONAL_CARE"
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_smartwatch_guardrail():
    # Smartwatch should not be MALE_HEALTH_SENSITIVE
    payload = {
        "id": "test_watch",
        "raw_product_title": "Smartwatch Men Waterproof Health Monitor",
        "category": "Electronics",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "electronics_wearable"
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_fashion_male_health_guardrail():
    # Fashion/underwear should not be MALE_HEALTH_SENSITIVE automatically
    payload = {
        "id": "test_undies",
        "raw_product_title": "3 helai Set seluar dalam fesyen untuk lelaki",
        "category": "Fashion",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "fashion_apparel"
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_true_male_health_sensitive():
    # Real sensitive products should still be mapped
    payload = {
        "id": "test_sensitive",
        "raw_product_title": "Minyak Lintah Tradisi Gunung Tahan Lama Lelaki",
        "category": "Health",
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"

def test_v2_single_weak_keyword_not_high():
    # Single keyword match should not be HIGH
    payload = {
        "id": "test_weak",
        "raw_product_title": "Something Sabun", # Sabun matches BEAUTY_PERSONAL_CARE
        "category": None,
        "source": "MANUAL"
    }
    profile = resolve_product_intelligence_profile(payload)
    assert profile["confidence"] in ["LOW", "MEDIUM"]

def test_v2_source_anchor_contradiction_downgrade():
    # If Truth reports a boundary violation, confidence must be LOW
    payload = {
        "id": "test_contradiction",
        "raw_product_title": "Baby Wipes",
        "category": "Fashion", # This should trigger a contradiction in reconciliation
        "source": "FASTMOSS"
    }
    profile = resolve_product_intelligence_profile(payload)
    # Reconciliation will see Baby Wipes (Baby) vs Fashion (Taxonomy)
    # It should flag a boundary lock violation or contradiction
    assert profile["confidence"] == "LOW"
    assert "MAPPING_RECONCILIATION_CONTRADICTION" in profile["warnings"]
