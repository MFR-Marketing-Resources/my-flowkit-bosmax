import pytest

from agent.services.product_intelligence import enrich_product
from agent.services.product_intelligence_service import (
    _resolve_sales_metrics,
    get_product_intelligence_backfill_preview,
    inject_product_intelligence_fields,
    resolve_product_intelligence_profile,
)


def _product(**overrides):
    payload = {
        "id": "prod-001",
        "source": "FASTMOSS",
        "raw_product_title": "Atlas Product",
        "product_display_name": "Atlas Product",
        "product_short_name": "Atlas Product",
        "category": "General Goods",
        "subcategory": "Unknown",
        "type": "Unknown",
        "copywriting_angle": "",
        "image_url": "https://example.com/product.jpg",
        "local_image_path": "",
    }
    payload.update(overrides)
    return payload


def test_detergent_resolves_to_laundry_care_direct_and_claim_review_when_antibacterial_token_exists():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Sabun Dobi Liquid Detergen Antibakteria Isi Ulang 5KG",
            product_display_name="Sabun Dobi Liquid Detergen Antibakteria",
            product_short_name="Sabun Dobi Liquid",
            category="Home Supplies",
            subcategory="Home Care Supplies",
            type="Household Cleaners",
        )
    )

    assert result["group"] == "LAUNDRY_CARE"
    assert result["sub_group"] == "LAUNDRY_CARE"
    assert result["type_of_product"] == "LIQUID_LAUNDRY_DETERGENT"
    assert result["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert result["copy_route"] == "DIRECT"
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert "antibakteria" in result["claim_tokens"]
    assert result["physical_state"] == "liquid"
    assert "fold" not in result["handling_profile"]
    assert "roll" not in result["handling_profile"]
    assert "fluff" not in result["handling_profile"]
    assert "textile" not in result["handling_profile"]


def test_detergent_does_not_use_stealth_route():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="3 in 1 Sabun Dobi Liquid Refill 5L",
            category="Home Supplies",
            subcategory="Home Care Supplies",
            type="Household Cleaners",
        )
    )

    assert result["copy_route"] == "DIRECT"
    assert result["claim_gate"] in {"CLAIM_SAFE", "CLAIM_REVIEW_REQUIRED"}


def test_apparel_resolves_to_fashion_and_textile_handling():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="A14 Alyanaa Baju Kelawar Moden Baju Tidur",
            category="Womenswear & Underwear",
            subcategory="Women's Sleepwear & Loungewear",
            type="Nightdresses",
        )
    )

    assert result["group"] == "FASHION_AND_APPAREL"
    assert result["physical_state"] == "textile"
    assert result["handling_profile"] == "drape_seam_shoulder_hanger_visibility"


def test_envelope_packet_resolves_to_paper_flat_packet_scale():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Sampul Duit Raya Premium Envelope Pack",
            category="Stationery",
            subcategory="Envelope",
            type="Money Packet",
        )
    )

    assert result["group"] == "STATIONERY_AND_GIFTING"
    assert result["physical_state"] == "paper"
    assert result["package_form"] == "flat_packet"
    assert result["product_scale_class"] == "small_flat_packet"


def test_beauty_small_item_resolves_to_small_product_handling():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Atlas Lip Balm Original",
            category="Beauty & Personal Care",
            subcategory="Skincare",
            type="Lip Balm",
        )
    )

    assert result["group"] == "BEAUTY_AND_PERSONAL_CARE"
    assert result["package_form"] == "small_bottle_tube_or_compact"
    assert result["product_scale_class"] == "small_handheld"


def test_sensitive_male_health_routes_to_stealth_and_claim_review():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Kuat Lelaki Tahan Lama Capsule",
            category="Health",
            subcategory="Supplements",
            type="Male Health",
        )
    )

    assert result["group"] == "MALE_HEALTH_SENSITIVE"
    assert result["copy_route"] == "STEALTH"
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"


def test_manual_male_health_taxonomy_without_explicit_title_still_resolves_sensitive_family():
    result = resolve_product_intelligence_profile(
        _product(
            source="MANUAL",
            raw_product_title="Bosmax Herbs 5 ML",
            product_display_name="Bosmax Herbs 5 ML",
            product_short_name="Bosmax Herbs 5 ML",
            category="Health",
            subcategory="Supplements",
            type="Male Health",
            image_url="",
        )
    )

    assert result["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert "male_health_sensitive" in result["claim_tokens"]
    assert "IMAGE_REFERENCE_REQUIRED" in result["warnings"]


def test_claim_sensitive_supplement_routes_review_required_not_stealth():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Vitamin Detox Supplement Whitening",
            category="Health",
            subcategory="Supplements",
            type="Wellness Supplements",
        )
    )

    assert result["group"] == "HEALTH_AND_WELLNESS"
    assert result["copy_route"] == "REVIEW_REQUIRED"
    assert result["claim_gate"] == "CLAIM_REVIEW_REQUIRED"


def test_baby_taxonomy_conflict_does_not_override_detergent_title_evidence():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Sabun Dobi Liquid Laundry Refill Pack 2KG",
            category="Baby & Maternity",
            subcategory="Baby Care & Health",
            type="Laundry Detergent",
        )
    )

    assert result["group"] == "LAUNDRY_CARE"
    assert result["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"
    assert result["taxonomy_conflict"] is True


def test_stale_legacy_mapping_fields_do_not_override_apparel_title_evidence():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Myawan Bra Plus-Size Wireless Bra",
            product_display_name="Myawan Bra Plus-Size Wireless Bra",
            product_short_name="Myawan Bra",
            category="Womenswear & Underwear",
            subcategory="Women's Underwear",
            type="Bras",
            product_type="UNIVERSAL",
            copywriting_angle="Utility-led laundry cleanliness, refill value, and pakaian wangi framing",
            product_type_id="HOUSEHOLD_LAUNDRY_DETERGENT",
        )
    )

    assert result["group"] == "FASHION_AND_APPAREL"
    assert result["bosmax_product_family"] in {"fashion_apparel", "APPAREL_SLEEPWEAR"}
    assert result["physical_state"] == "textile"
    assert result["type_of_product"] != "LIQUID_LAUNDRY_DETERGENT"


def test_unknown_product_returns_low_confidence_and_needs_review():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="XJ-8841 Multi Purpose Item",
            category="",
            subcategory="",
            type="",
            image_url="",
        )
    )

    assert result["group"] == "UNKNOWN_REVIEW_REQUIRED"
    assert result["confidence"] == "LOW"
    assert result["intelligence_status"] == "NEEDS_REVIEW"


def test_semantic_image_warning_appears_when_provider_unavailable():
    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Atlas Lip Balm Original",
            image_url="https://example.com/product.jpg",
            local_image_path="",
        )
    )

    assert result["image_analysis"]["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert "SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE" in result["warnings"]


def test_high_confidence_provider_result_can_influence_package_form(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_intelligence_service.analyze_product_image_payload",
        lambda product: {
            "status": "ANALYZED",
            "image_url": product.get("image_url"),
            "local_image_path": product.get("local_image_path"),
            "detected_package": "packet",
            "detected_text": ["Sampul Premium"],
            "detected_brand": None,
            "detected_size_text": None,
            "detected_form_factor": "flat_packet",
            "visual_confidence": "HIGH",
            "evidence": ["provider:mock"],
            "warnings": [],
            "provider": "mock_provider",
            "metadata": {},
        },
    )

    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Mystery Product",
            category="",
            subcategory="",
            type="",
            image_url="https://example.com/product.jpg",
        )
    )

    assert result["package_form"] == "flat_packet"


def test_low_confidence_provider_result_does_not_override_package_form(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_intelligence_service.analyze_product_image_payload",
        lambda product: {
            "status": "ANALYZED",
            "image_url": product.get("image_url"),
            "local_image_path": product.get("local_image_path"),
            "detected_package": "packet",
            "detected_text": ["Sampul Premium"],
            "detected_brand": None,
            "detected_size_text": None,
            "detected_form_factor": "flat_packet",
            "visual_confidence": "LOW",
            "evidence": ["provider:mock"],
            "warnings": [],
            "provider": "mock_provider",
            "metadata": {},
        },
    )

    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Mystery Product",
            category="",
            subcategory="",
            type="",
            image_url="https://example.com/product.jpg",
        )
    )

    assert result["package_form"] == "unknown"


def test_title_vs_image_conflict_triggers_review_warning(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_intelligence_service.analyze_product_image_payload",
        lambda product: {
            "status": "ANALYZED",
            "image_url": product.get("image_url"),
            "local_image_path": product.get("local_image_path"),
            "detected_package": "garment",
            "detected_text": ["Baju"],
            "detected_brand": None,
            "detected_size_text": None,
            "detected_form_factor": "garment",
            "visual_confidence": "HIGH",
            "evidence": ["provider:mock"],
            "warnings": [],
            "provider": "mock_provider",
            "metadata": {},
        },
    )

    result = resolve_product_intelligence_profile(
        _product(
            raw_product_title="Sabun Dobi Liquid Refill 5KG",
            category="Home Supplies",
            subcategory="Home Care Supplies",
            type="Household Cleaners",
            image_url="https://example.com/product.jpg",
        )
    )

    assert "IMAGE_TITLE_CONFLICT_REVIEW_REQUIRED" in result["warnings"]


@pytest.mark.asyncio
async def test_backfill_preview_returns_distribution_counts_and_does_not_write_db(monkeypatch):
    rows = [
        _product(
            id="prod-laundry",
            raw_product_title="Sabun Dobi Liquid Detergen",
            category="Home Supplies",
            subcategory="Home Care Supplies",
            type="Household Cleaners",
        ),
        _product(
            id="prod-apparel",
            raw_product_title="Baju Tidur Moden",
            category="Womenswear & Underwear",
            subcategory="Women's Sleepwear & Loungewear",
            type="Nightdresses",
        ),
    ]

    async def fake_list_products(*args, **kwargs):
        return rows

    async def fail_update(*args, **kwargs):
        raise AssertionError("backfill preview must not write to DB")

    monkeypatch.setattr("agent.services.product_intelligence_service.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.services.product_intelligence_service.crud.update_product", fail_update)

    result = await get_product_intelligence_backfill_preview()

    assert result["total_products"] == 2
    assert result["resolved"] == 2
    assert result["group_distribution"]["LAUNDRY_CARE"] == 1
    assert result["group_distribution"]["FASHION_AND_APPAREL"] == 1
    assert result["write_back_status"] == "READ_ONLY_NO_DB_WRITES"


def test_latest_import_batch_metrics_are_preferred_over_legacy(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_intelligence_service._latest_sales_metrics_index",
        lambda: {
            "source": "LATEST_FASTMOSS_IMPORT_BATCH",
            "batch_id": "batch-latest",
            "records": [],
            "by_name": {
                "atlas product": [
                    {
                        "file_type_id": "PRODUCT_SEARCH_SALES_RANK",
                        "names": ["Atlas Product"],
                        "shop_names": ["Atlas Shop"],
                        "metric_values": [
                            {
                                "metric_name": "product_sold_count",
                                "source_column": "Total Units Sold",
                                "metric_scope": "PRODUCT",
                                "truth_status": "VERIFIED_PRODUCT_LEVEL",
                                "warning": None,
                                "value": 88,
                            }
                        ],
                    }
                ]
            },
            "by_source_url": {},
            "by_tiktok_url": {},
        },
    )
    monkeypatch.setattr(
        "agent.services.product_intelligence_service._sales_metrics_index",
        lambda: {
            "source": "LEGACY_COMBINED_WORKBOOK",
            "batch_id": None,
            "records": [],
            "by_name": {
                "atlas product": [
                    {
                        "sheet": "Product Sales Rank",
                        "file_type_id": "Product Sales Rank",
                        "names": ["Atlas Product"],
                        "shop_names": ["Atlas Shop"],
                        "metric_values": [
                            {
                                "metric_name": "product_sold_count",
                                "source_column": "Total Units Sold",
                                "metric_scope": "PRODUCT",
                                "truth_status": "VERIFIED_PRODUCT_LEVEL",
                                "warning": None,
                                "value": 12,
                            }
                        ],
                    }
                ]
            },
            "by_source_url": {},
            "by_tiktok_url": {},
        },
    )

    metrics, _ = _resolve_sales_metrics(_product())

    assert metrics.sales_metrics_source == "LATEST_FASTMOSS_IMPORT_BATCH"
    assert metrics.sales_metrics_batch_id == "batch-latest"
    assert metrics.product_sold_count == 88
    assert metrics.sold_count == 88
    assert metrics.sold_count_truth_status == "VERIFIED_PRODUCT_LEVEL"


def test_legacy_combined_workbook_fallback_still_works_when_latest_missing(monkeypatch):
    monkeypatch.setattr("agent.services.product_intelligence_service._latest_sales_metrics_index", lambda: None)
    monkeypatch.setattr(
        "agent.services.product_intelligence_service._sales_metrics_index",
        lambda: {
            "source": "LEGACY_COMBINED_WORKBOOK",
            "batch_id": None,
            "records": [],
            "by_name": {
                "atlas product": [
                    {
                        "sheet": "Most Promoted Products",
                        "file_type_id": "Most Promoted Products",
                        "names": ["Atlas Product"],
                        "shop_names": ["Atlas Shop"],
                        "metric_values": [
                            {
                                "metric_name": "shop_total_sold_count",
                                "source_column": "Shop Units Sold",
                                "metric_scope": "SHOP",
                                "truth_status": "SHOP_LEVEL_AGGREGATE",
                                "warning": "SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES",
                                "value": 74561117,
                            }
                        ],
                    }
                ]
            },
            "by_source_url": {},
            "by_tiktok_url": {},
        },
    )

    metrics, _ = _resolve_sales_metrics(_product())

    assert metrics.sales_metrics_source == "LEGACY_COMBINED_WORKBOOK"
    assert metrics.product_sold_count is None
    assert metrics.sold_count is None
    assert metrics.shop_total_sold_count == 74561117
    assert metrics.sold_count_metric_scope == "SHOP"
    assert metrics.sold_count_truth_status == "SHOP_LEVEL_AGGREGATE"
    assert "SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES" in metrics.sales_metric_warnings


def test_unknown_sales_metric_does_not_become_product_sold_count(monkeypatch):
    monkeypatch.setattr("agent.services.product_intelligence_service._latest_sales_metrics_index", lambda: None)
    monkeypatch.setattr(
        "agent.services.product_intelligence_service._sales_metrics_index",
        lambda: {
            "source": "LEGACY_COMBINED_WORKBOOK",
            "batch_id": None,
            "records": [],
            "by_name": {
                "atlas product": [
                    {
                        "sheet": "Product Search Data",
                        "file_type_id": "Product Search Data",
                        "names": ["Atlas Product"],
                        "shop_names": ["Atlas Shop"],
                        "metric_values": [
                            {
                                "metric_name": "total_sales_volume",
                                "source_column": "Total Sales Volume",
                                "metric_scope": "UNKNOWN",
                                "truth_status": "NOT_VERIFIED",
                                "warning": "SALES_METRIC_SCOPE_NOT_VERIFIED",
                                "value": 1200,
                            }
                        ],
                    }
                ]
            },
            "by_source_url": {},
            "by_tiktok_url": {},
        },
    )

    metrics, _ = _resolve_sales_metrics(_product())

    assert metrics.product_sold_count is None
    assert metrics.sold_count is None
    assert metrics.shop_total_sold_count is None
    assert metrics.sold_count_metric_scope == "UNKNOWN"
    assert metrics.sold_count_truth_status == "NOT_VERIFIED"
    assert "SALES_METRIC_SCOPE_NOT_VERIFIED" in metrics.sales_metric_warnings


def test_inject_product_intelligence_fields_exposes_sales_metric_truth_fields(monkeypatch):
    monkeypatch.setattr("agent.services.product_intelligence_service._latest_sales_metrics_index", lambda: None)
    monkeypatch.setattr(
        "agent.services.product_intelligence_service._sales_metrics_index",
        lambda: {
            "source": "LEGACY_COMBINED_WORKBOOK",
            "batch_id": None,
            "records": [],
            "by_name": {
                "atlas product": [
                    {
                        "sheet": "Most Promoted Products",
                        "file_type_id": "Most Promoted Products",
                        "names": ["Atlas Product"],
                        "shop_names": ["Atlas Shop"],
                        "metric_values": [
                            {
                                "metric_name": "shop_total_sold_count",
                                "source_column": "Shop Units Sold",
                                "metric_scope": "SHOP",
                                "truth_status": "SHOP_LEVEL_AGGREGATE",
                                "warning": "SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES",
                                "value": 74561117,
                            }
                        ],
                    }
                ]
            },
            "by_source_url": {},
            "by_tiktok_url": {},
        },
    )

    profile = resolve_product_intelligence_profile(_product())
    enriched = inject_product_intelligence_fields(_product(), profile)

    assert enriched["sales_metrics_source"] == "LEGACY_COMBINED_WORKBOOK"
    assert enriched["sold_count"] is None
    assert enriched["product_sold_count"] is None
    assert enriched["shop_total_sold_count"] == 74561117
    assert enriched["sold_count_metric_scope"] == "SHOP"
    assert enriched["sold_count_truth_status"] == "SHOP_LEVEL_AGGREGATE"


async def test_archived_product_fail_closes_mode_readiness_and_preflight():
    enriched = await enrich_product(
        _product(
            lifecycle_status="ARCHIVED",
            image_url="https://example.com/product.jpg",
        )
    )

    assert enriched["lifecycle_status"] == "ARCHIVED"
    assert enriched["mode_readiness"]["Text to Video"]["status"] == "PRODUCT_ARCHIVED"
    assert enriched["mode_readiness"]["Images"]["status"] == "PRODUCT_ARCHIVED"
    assert enriched["preflight"]["blocking_reason"] == "PRODUCT_ARCHIVED"
    assert enriched["preflight"]["safe_to_generate_prompt"] is False
