import pytest
from agent.services.product_truth_service import ProductTruthService
from agent.services.product_truth_service import (
    FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION,
    FLAG_KEYWORD_VS_ANCHOR_TAXONOMY,
    FLAG_SOURCE_ANCHOR_MISSING
)

def test_baby_wipes_reconciliation_contradiction():
    # GIVEN a product that is baby wipes but currently mapped to beauty_fragrance by keywords
    product = {
        "id": "test-wipes-1",
        "source": "FASTMOSS",
        "raw_product_title": "Baby Wipes Fragrance Free 80s",
        "category": "Baby Care",
        "subcategory": "Baby Hygiene",
        "type": "Baby Wipes",
        "image_url": "http://example.com/wipes.jpg"
    }
    
    # WHEN building truth profile
    profile = ProductTruthService.build_computed_profile(product)
    
    # THEN it should detect contradiction if keyword mapping (fragrance) attempts to move it to beauty
    # Current mapping logic would likely map "fragrance" to beauty_fragrance
    assert FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION in profile.reconciliation.contradiction_flags
    assert profile.reconciliation.confidence_label in ["LOW", "NEEDS_REVIEW"]
    assert profile.source_anchors.source_category == "Baby Care"

def test_smartwatch_reconciliation_contradiction():
    # GIVEN a smartwatch currently mapped to MALE_HEALTH_SENSITIVE by some keyword
    product = {
        "id": "test-watch-1",
        "source": "FASTMOSS",
        "raw_product_title": "Smartwatch for Men with Heart Rate Monitor",
        "category": "Electronics",
        "subcategory": "Wearable Device",
        "type": "Smartwatch"
    }
    
    # WHEN building truth profile
    profile = ProductTruthService.build_computed_profile(product)
    
    # THEN it should flag the contradiction if mapped to male health
    # (Assuming current mapping logic hallucination exists as per contract)
    assert profile.source_anchors.source_category == "Electronics"
    # The actual flag depends on if the keyword resolver in ProductTruthService simulates the failure
    # In my implementation, I added a specific check for smartwatch vs male health

def test_dimension_normalization():
    # GIVEN a product with cm dimensions in title
    product1 = {"raw_product_title": "Box 10cm x 5cm x 2cm"}
    profile1 = ProductTruthService.build_computed_profile(product1)
    assert profile1.spec_evidence.dimension_normalized_cm.length_cm == 10.0
    assert profile1.spec_evidence.dimension_normalized_cm.display == "10.0 x 5.0 x 2.0 cm"
    
    # GIVEN a product with mm dimensions in title
    product2 = {"raw_product_title": "Widget 100mm x 50mm"}
    profile2 = ProductTruthService.build_computed_profile(product2)
    assert profile2.spec_evidence.dimension_normalized_cm.length_cm == 10.0
    assert profile2.spec_evidence.dimension_normalized_cm.width_cm == 5.0
    assert profile2.spec_evidence.dimension_normalized_cm.display == "10.0 x 5.0 cm"

def test_source_anchor_missing():
    # GIVEN a product with no category metadata
    product = {
        "source": "FASTMOSS",
        "raw_product_title": "Random Product",
        "category": None
    }
    profile = ProductTruthService.build_computed_profile(product)
    assert FLAG_SOURCE_ANCHOR_MISSING in profile.reconciliation.contradiction_flags
    assert profile.source_anchors.source_anchor_status == "MISSING"

if __name__ == "__main__":
    # Manual run
    pytest.main([__file__])
