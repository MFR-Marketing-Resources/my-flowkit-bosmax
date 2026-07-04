from agent.api.products import _filter_products_for_catalog
from agent.services.product_catalog_audit import CANONICAL_FATIMA_PRODUCT_ID, build_cleanup_plan, build_mapping_summary
from agent.services.product_intelligence import enrich_product


async def test_enrich_product_marks_test_rows_and_local_cache_missing():
    enriched = await enrich_product(
        {
            "id": "test_prod_deadbeef",
            "source": "FASTMOSS",
            "raw_product_title": "Test Product",
            "product_short_name": "Test Product",
            "local_image_path": "test.jpg",
            "asset_status": "DOWNLOADED",
        }
    )

    assert enriched["is_test_product"] is True
    assert enriched["catalog_label"] == "TEST"
    assert enriched["image_readiness_status"] == "LOCAL_CACHE_MISSING"
    assert enriched["rendered_img_src"] == "/api/products/test_prod_deadbeef/image"
    assert enriched["image_http_status"] == 404


async def test_enrich_product_normalizes_baby_wipes_price_commission_and_taxonomy():
    enriched = await enrich_product(
        {
            "id": "baby_wipes_1",
            "source": "FASTMOSS",
            "raw_product_title": "Baby Wipes Newborn Wet Tissue Tisue Basah Non-alcohol Paraben-free Fragrance-free Babies Wipe Tisu Basah Bayi",
            "product_short_name": "Baby Wipes Newborn Wet",
            "price": 8.360000000000001,
            "currency": "MYR",
            "commission_rate": "6%",
            "commission_amount": None,
            "asset_status": "DOWNLOADED",
        }
    )

    assert enriched["category"] == "Baby Care"
    assert enriched["subcategory"] == "Diapering / Baby Wipes / Wet Wipes"
    assert enriched["type"] == "Baby Wipes"
    assert enriched["price"] == 8.36
    assert enriched["commission_amount"] == 0.5
    assert enriched["product_type_id"] == "BABY_WIPES"
    assert enriched["copywriting_angle"] == "Trust-led baby hygiene and gentle newborn care"


def test_catalog_default_hides_test_products_and_prioritizes_ready_fastmoss():
    items = [
        {
            "id": "test_prod_1",
            "source": "FASTMOSS",
            "product_short_name": "Test Product",
            "is_test_product": True,
            "prompt_readiness_status": None,
            "image_readiness_status": "LOCAL_CACHE_MISSING",
            "updated_at": "2026-05-09T10:00:00",
            "created_at": "2026-05-09T10:00:00",
        },
        {
            "id": "real_fastmoss",
            "source": "FASTMOSS",
            "product_short_name": "Sumikko",
            "is_test_product": False,
            "prompt_readiness_status": "READY",
            "image_readiness_status": "IMAGE_CACHE_READY",
            "updated_at": "2026-05-09T09:00:00",
            "created_at": "2026-05-09T09:00:00",
        },
        {
            "id": "manual_prod",
            "source": "MANUAL",
            "product_short_name": "Manual Product",
            "is_test_product": False,
            "prompt_readiness_status": "READY",
            "image_readiness_status": "IMAGE_READY",
            "updated_at": "2026-05-09T11:00:00",
            "created_at": "2026-05-09T11:00:00",
        },
    ]

    filtered = _filter_products_for_catalog(
        items, query=None, source=None, source_lane=None, readiness=None
    )

    assert [item["id"] for item in filtered] == ["real_fastmoss", "manual_prod"]


def test_catalog_test_filter_only_returns_test_products():
    items = [
        {"id": "test_prod_1", "source": "FASTMOSS", "is_test_product": True, "updated_at": "2026-05-09T10:00:00", "created_at": "2026-05-09T10:00:00"},
        {"id": "real_fastmoss", "source": "FASTMOSS", "is_test_product": False, "updated_at": "2026-05-09T09:00:00", "created_at": "2026-05-09T09:00:00"},
    ]

    filtered = _filter_products_for_catalog(
        items, query=None, source="TEST", source_lane=None, readiness=None
    )

    assert [item["id"] for item in filtered] == ["test_prod_1"]


def test_cleanup_plan_classifies_leaked_fixtures_and_noncanonical_fatima_rows():
    plan = build_cleanup_plan(
        [
            {
                "id": "test_prod_1",
                "source": "FASTMOSS",
                "product_short_name": "Test Product",
                "raw_product_title": "Test Product",
                "mapping_status": None,
                "created_at": "2026-05-10T05:47:17Z",
                "updated_at": "2026-05-10T05:47:17Z",
            },
            {
                "id": CANONICAL_FATIMA_PRODUCT_ID,
                "source": "FASTMOSS",
                "product_short_name": "FATIMA INSTANT SARUNG SYRIA",
                "raw_product_title": "FATIMA INSTANT SARUNG SYRIA ~ HQ MOSCREPE PREMIUM ~ IRONLESS & STRETCHABLE HIJAB UNTUK WANITA MUSLIMAH BAHAN ELASTIK SESUAI KESELAMAN DAN GAYA",
                "mapping_status": "READY",
                "created_at": "2026-05-09T08:51:59Z",
                "updated_at": "2026-05-10T05:44:27Z",
            },
            {
                "id": "duplicate-fatima",
                "source": "FASTMOSS",
                "product_short_name": "FATIMA INSTANT SARUNG SYRIA",
                "raw_product_title": "FATIMA INSTANT SARUNG SYRIA ~ HQ MOSCREPE PREMIUM",
                "mapping_status": None,
                "created_at": "2026-05-10T05:47:17Z",
                "updated_at": "2026-05-10T05:47:17Z",
            },
        ]
    )

    assert plan["null_mapping_status_before"] == 2
    assert plan["test_fixture_rows_found"] == 1
    assert plan["stale_duplicate_rows_found"] == 1
    assert {row["id"] for row in plan["rows_to_delete"]} == {"test_prod_1", "duplicate-fatima"}


def test_mapping_summary_groups_blocked_products_by_missing_fields_and_source():
    raw_products = [
        {
            "id": "blocked_1",
            "source": "FASTMOSS",
            "mapping_status": "BLOCKED",
            "created_at": "2026-05-10T05:00:00Z",
            "updated_at": "2026-05-10T05:00:00Z",
        },
        {
            "id": "ready_1",
            "source": "MANUAL",
            "mapping_status": "READY",
            "created_at": "2026-05-10T05:00:00Z",
            "updated_at": "2026-05-10T05:00:00Z",
        },
    ]
    enriched_products = [
        {
            "id": "blocked_1",
            "source": "FASTMOSS",
            "product_short_name": "Blocked Product",
            "raw_product_title": "Blocked Product",
            "category": "UNMAPPED",
            "subcategory": "UNMAPPED",
            "type": None,
            "mapping_source": "fallback",
            "mapping_status": "BLOCKED",
            "mapping_missing_fields": ["category", "trigger_id"],
            "image_readiness_status": "IMAGE_URL_MISSING",
            "updated_at": "2026-05-10T05:00:00Z",
        },
        {
            "id": "ready_1",
            "source": "MANUAL",
            "product_short_name": "Ready Product",
            "raw_product_title": "Ready Product",
            "category": "Fashion",
            "subcategory": "Muslim Fashion",
            "type": "Instant Sarung",
            "mapping_source": "rule",
            "mapping_status": "READY",
            "mapping_missing_fields": [],
            "image_readiness_status": "IMAGE_READY",
            "updated_at": "2026-05-10T05:00:00Z",
        },
    ]

    summary = build_mapping_summary(raw_products, enriched_products, sample_limit=10)

    assert summary["total_products"] == 2
    assert summary["ready"] == 1
    assert summary["blocked"] == 1
    assert summary["blocked_by_source"] == {"FASTMOSS": 1}
    assert summary["blocked_by_missing_field"] == {"category": 1, "trigger_id": 1}
    assert summary["blocked_by_mapping_source"] == {"fallback": 1}
    assert summary["sample_blocked_products"][0]["id"] == "blocked_1"