from agent.api.products import _filter_products_for_catalog
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

    filtered = _filter_products_for_catalog(items, source=None, readiness=None)

    assert [item["id"] for item in filtered] == ["real_fastmoss", "manual_prod"]


def test_catalog_test_filter_only_returns_test_products():
    items = [
        {"id": "test_prod_1", "source": "FASTMOSS", "is_test_product": True, "updated_at": "2026-05-09T10:00:00", "created_at": "2026-05-09T10:00:00"},
        {"id": "real_fastmoss", "source": "FASTMOSS", "is_test_product": False, "updated_at": "2026-05-09T09:00:00", "created_at": "2026-05-09T09:00:00"},
    ]

    filtered = _filter_products_for_catalog(items, source="TEST", readiness=None)

    assert [item["id"] for item in filtered] == ["test_prod_1"]