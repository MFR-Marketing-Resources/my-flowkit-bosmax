from copy import deepcopy

from agent.services.all_product_mapping_audit_service import (
    build_all_product_mapping_audit,
)


def _raw_product(**overrides):
    payload = {
        "id": "prod-001",
        "source": "FASTMOSS",
        "raw_product_title": "Atlas Product",
        "product_display_name": "Atlas Product",
        "product_short_name": "Atlas Product",
        "category": "General Goods",
        "subcategory": "Unknown",
        "type": "Unknown",
        "image_readiness_status": "IMAGE_READY",
    }
    payload.update(overrides)
    return payload


def _profile(raw_product: dict, **overrides):
    payload = {
        "product_id": raw_product["id"],
        "normalized_title": raw_product["raw_product_title"],
        "group": "FASHION_AND_APPAREL",
        "sub_group": "GENERAL_APPAREL",
        "type_of_product": "APPAREL",
        "bosmax_product_family": "fashion_apparel",
        "copy_route": "DIRECT",
        "claim_gate": "CLAIM_SAFE",
        "confidence": "MEDIUM",
        "taxonomy_conflict": False,
        "intelligence_status": "READY",
        "sales_metrics": {"source_status": "FOUND"},
        "image_analysis": {"status": "VISION_PROVIDER_NOT_CONFIGURED"},
    }
    payload.update(overrides)
    return payload


def test_all_product_mapping_audit_returns_required_fields_and_does_not_mutate_input():
    raw_products = [
        _raw_product(id="prod-001", source="FASTMOSS", raw_product_title="Atlas Lip Serum", category="Beauty & Personal Care"),
        _raw_product(id="prod-002", source="MANUAL", raw_product_title="Atlas Baby Wipes", category="Baby Care"),
    ]
    resolved_profiles = [
        _profile(raw_products[0], group="HOUSEHOLD_CARE", bosmax_product_family="HOME_TEXTILE", confidence="HIGH"),
        _profile(raw_products[1], group="BEAUTY_AND_PERSONAL_CARE", bosmax_product_family="beauty_fragrance", confidence="HIGH"),
    ]
    snapshot = deepcopy(raw_products)

    audit = build_all_product_mapping_audit(raw_products, resolved_profiles, sample_limit=10)

    assert audit["total_products"] == 2
    assert audit["source_distribution"] == {"FASTMOSS": 1, "MANUAL": 1}
    assert "image_readiness_distribution" in audit
    assert "image_analysis_status_distribution" in audit
    assert "group_distribution" in audit
    assert "sub_group_distribution" in audit
    assert "type_of_product_distribution" in audit
    assert "bosmax_family_distribution" in audit
    assert "copy_route_distribution" in audit
    assert "claim_gate_distribution" in audit
    assert "intelligence_confidence_distribution" in audit
    assert audit["write_back_status"] == "READ_ONLY_NO_DB_WRITES"
    assert raw_products == snapshot


def test_beauty_to_household_textile_high_confidence_is_flagged_suspicious():
    raw_product = _raw_product(
        id="beauty-001",
        raw_product_title="Atlas Lip Serum Glass Bottle",
        category="Beauty & Personal Care",
        subcategory="Skincare",
        type="Serum",
    )

    audit = build_all_product_mapping_audit(
        [raw_product],
        [_profile(raw_product, group="HOUSEHOLD_CARE", bosmax_product_family="HOME_TEXTILE", confidence="HIGH")],
    )

    assert audit["suspicious_high_confidence_count"] == 1
    assert "BEAUTY_EVIDENCE_CONTRADICTS_HOUSEHOLD_OR_HOME_TEXTILE_MAPPING" in audit["examples"][0]["reason"]


def test_baby_wipes_to_fragrance_family_is_flagged_suspicious():
    raw_product = _raw_product(
        id="baby-001",
        raw_product_title="Atlas Baby Wipes Aloe Vera",
        category="Baby Care",
        subcategory="Wipes",
        type="Baby Wipes",
    )

    audit = build_all_product_mapping_audit(
        [raw_product],
        [_profile(raw_product, group="BEAUTY_AND_PERSONAL_CARE", bosmax_product_family="beauty_fragrance", confidence="HIGH")],
    )

    assert "BABY_WIPES_EVIDENCE_CONTRADICTS_FRAGRANCE_FAMILY" in audit["examples"][0]["reason"]


def test_fashion_and_electronics_to_male_health_sensitive_are_flagged_without_sensitive_evidence():
    fashion_raw = _raw_product(
        id="fashion-001",
        raw_product_title="Seluar Cargo Lelaki Streetwear",
        category="Fashion",
        subcategory="Pants",
        type="Cargo Pants",
    )
    electronics_raw = _raw_product(
        id="home-001",
        raw_product_title="Kipas Portable Mini Fan Rechargeable",
        category="Household Appliances",
        subcategory="Fan",
        type="Portable Fan",
    )

    audit = build_all_product_mapping_audit(
        [fashion_raw, electronics_raw],
        [
            _profile(fashion_raw, group="MALE_HEALTH_SENSITIVE", bosmax_product_family="MALE_HEALTH_SENSITIVE", confidence="HIGH"),
            _profile(electronics_raw, group="MALE_HEALTH_SENSITIVE", bosmax_product_family="MALE_HEALTH_SENSITIVE", confidence="MEDIUM"),
        ],
    )

    reasons = [example["reason"] for example in audit["examples"]]
    assert any("FASHION_EVIDENCE_CONTRADICTS_MALE_HEALTH_SENSITIVE_MAPPING" in reason for reason in reasons)
    assert any("HOME_OR_ELECTRONICS_EVIDENCE_CONTRADICTS_MALE_HEALTH_SENSITIVE_MAPPING" in reason for reason in reasons)


def test_image_analysis_unavailable_is_counted_truthfully_without_fake_semantic_detection():
    raw_product = _raw_product(
        id="image-001",
        raw_product_title="Atlas Storage Rack",
        category="Home Organization",
        subcategory="Storage",
        type="Rack",
        image_readiness_status="IMAGE_URL_MISSING",
    )

    audit = build_all_product_mapping_audit(
        [raw_product],
        [
            _profile(
                raw_product,
                image_analysis={"status": "VISION_PROVIDER_NOT_CONFIGURED"},
                sales_metrics={"source_status": "NOT_FOUND"},
                confidence="LOW",
                intelligence_status="NEEDS_REVIEW",
                group="UNKNOWN_REVIEW_REQUIRED",
                bosmax_product_family="UNKNOWN_REVIEW_REQUIRED",
            )
        ],
    )

    assert audit["image_analysis_status_distribution"]["VISION_PROVIDER_NOT_CONFIGURED"] == 1
    assert audit["semantic_unavailable_count"] == 1
    assert audit["missing_sales_metrics_count"] == 1
    assert audit["low_confidence_count"] == 1
