import pytest
from unittest.mock import patch
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
        "raw_product_title": "Baby Wipes Fragrance Free 80s Perfume",
        "category": "Baby Care",
        "subcategory": "Baby Hygiene",
        "type": "Baby Wipes",
        "product_display_name": "Baby Wipes Fragrance Free 80s Perfume",
        "product_short_name": "Baby Wipes"
    }
    
    # Mock the FastMoss audit to return a positive anchor match
    mock_audit = {
        "source_anchor_status": "PRESENT",
        "source_anchor_origin": "WORKBOOK_MOCK",
        "reconciliation_status": "MATCHES_RAW_SOURCE",
        "discovered_columns": ["Category", "Sub Category"],
        "notes": [],
        "raw_source_available": True,
        "raw_values": {
            "category": "Baby Care",
            "subcategory": "Baby Hygiene",
            "type": "Baby Wipes"
        }
    }
    
    with patch("agent.services.fastmoss_taxonomy_reconciliation_service.FastMossTaxonomyReconciliationService.audit_fastmoss_product", return_value=mock_audit):
        profile = ProductTruthService.build_computed_profile(product)
        assert FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION in profile.reconciliation.contradiction_flags
        assert profile.reconciliation.confidence_label == "NEEDS_REVIEW"

def test_smartwatch_reconciliation_contradiction():
    # GIVEN a smartwatch currently mapped to Health by some keyword
    product = {
        "id": "test-watch-1",
        "source": "FASTMOSS",
        "raw_product_title": "Smartwatch Male Health", # This triggers Health category mapping
        "category": "Electronics",
        "subcategory": "Wearables",
        "type": "Smartwatch",
        "product_display_name": "Smartwatch Male Health",
        "product_short_name": "Smartwatch"
    }
    
    # Mock the FastMoss audit to return a positive anchor match
    mock_audit = {
        "source_anchor_status": "PRESENT",
        "source_anchor_origin": "WORKBOOK_MOCK",
        "reconciliation_status": "MATCHES_RAW_SOURCE",
        "discovered_columns": ["Category", "Sub Category"],
        "notes": [],
        "raw_source_available": True,
        "raw_values": {
            "category": "Electronics",
            "subcategory": "Wearables",
            "type": "Smartwatch"
        }
    }
    
    with patch("agent.services.fastmoss_taxonomy_reconciliation_service.FastMossTaxonomyReconciliationService.audit_fastmoss_product", return_value=mock_audit):
        profile = ProductTruthService.build_computed_profile(product)
        assert FLAG_CATEGORY_BOUNDARY_LOCK_VIOLATION in profile.reconciliation.contradiction_flags

def test_dimension_normalization():
    product1 = {"raw_product_title": "Box 10cm x 5cm x 2cm"}
    profile1 = ProductTruthService.build_computed_profile(product1)
    assert profile1.spec_evidence.dimension_normalized_cm.length_cm == 10.0
    
    product2 = {"raw_product_title": "Widget 100mm x 50mm"}
    profile2 = ProductTruthService.build_computed_profile(product2)
    assert profile2.spec_evidence.dimension_normalized_cm.length_cm == 10.0

def test_source_anchor_missing():
    product = {
        "source": "FASTMOSS",
        "raw_product_title": "Random Product",
        "category": None
    }
    
    mock_audit = {
        "source_anchor_status": "SOURCE_ANCHOR_MISSING",
        "source_anchor_origin": "NONE",
        "reconciliation_status": "RAW_SOURCE_NOT_AVAILABLE",
        "discovered_columns": [],
        "notes": [],
        "raw_source_available": False,
        "raw_values": None
    }
    
    with patch("agent.services.fastmoss_taxonomy_reconciliation_service.FastMossTaxonomyReconciliationService.audit_fastmoss_product", return_value=mock_audit):
        profile = ProductTruthService.build_computed_profile(product)
        assert FLAG_SOURCE_ANCHOR_MISSING in profile.reconciliation.contradiction_flags

if __name__ == "__main__":
    pytest.main([__file__])
