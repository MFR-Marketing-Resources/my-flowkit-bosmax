"""Kalodata staged import — parser/normalizer/staging contract tests."""
import json

import pytest

from agent.services import kalodata_import_service as svc
from agent.services.fastmoss_product_reference_service import (
    FASTMOSS_REFERENCE_ID_PREFIX,
)


# ── normalizers ──────────────────────────────────────────────────────────────
def test_tiktok_id_recovered_from_url_patterns():
    assert svc.extract_tiktok_product_id(
        "https://shop-my.tiktok.com/pdp/1731147231842430988?src=x", None
    ) == ("1731147231842430988", "URL")
    assert svc.extract_tiktok_product_id(
        "https://shop.tiktok.com/view/product/1729674255001688097", 1.72e18
    ) == ("1729674255001688097", "URL")


def test_tiktok_id_float_cell_beyond_precision_is_low_confidence():
    # 19-digit ids exceed float64's 53-bit mantissa — unrecoverable from a cell.
    assert svc.extract_tiktok_product_id(None, 1.73114723184243e18) == (None, "LOW")


def test_tiktok_id_small_integral_cell_accepted():
    assert svc.extract_tiktok_product_id(None, 123456.0) == ("123456", "CELL")
    assert svc.extract_tiktok_product_id(None, "1731147231842430988") == (
        "1731147231842430988",
        "CELL",
    )
    assert svc.extract_tiktok_product_id(None, None) == (None, "NONE")


def test_price_range_parses_midpoint_min_max():
    mid, low, high, raw, is_range = svc.parse_price("RM6.12  - 19.01")
    assert (mid, low, high, is_range) == (12.57, 6.12, 19.01, True)
    assert raw.startswith("RM6.12")


def test_price_single_and_numeric():
    assert svc.parse_price("RM45.90")[:3] == (45.9, 45.9, 45.9)
    assert svc.parse_price(26.5)[:3] == (26.5, 26.5, 26.5)
    assert svc.parse_price(None) == (None, None, None, None, False)


def test_excel_serial_and_datetime_dates():
    assert svc.excel_date_to_iso(45765) == "2025-04-18"
    from datetime import datetime

    assert svc.excel_date_to_iso(datetime(2025, 7, 18)) == "2025-07-18"
    assert svc.excel_date_to_iso("2025-04-18") == "2025-04-18"
    assert svc.excel_date_to_iso(None) is None


# ── workbook fixture ─────────────────────────────────────────────────────────
def _build_workbook(path):
    import openpyxl

    wb = openpyxl.Workbook()
    merged = wb.active
    merged.title = svc.MERGED_SHEET
    merged.append([
        "No", "Sumber", "Product Name", "Image URL", "Category", "Price (RM)",
        "Launch Date", "Product Rating", "Item Sold / Total Sales",
        "Avg Unit Price (RM)", "Commission Rate", "Creator Number",
        "Creator Conversion/Sales Rate", "TikTok URL", "Product ID", "Source URL 1",
    ])
    merged.append([
        1, "KALODATA", "Pengedap Vakum Mudah Alih", "https://img/1.jpg",
        "Home Supplies > Home Organizers > Storage", "RM26.50", 45765, 4.5, 3448,
        123.99, 0.05, 57, 0.7719,
        "https://shop-my.tiktok.com/pdp/1731147231842430988",
        1.73114723184243e18, "https://kalodata/1",
    ])
    merged.append([
        2, "FASTMOSS", "Jalur Pemutih Gigi", "https://img/2.jpg",
        "Beauty & Personal Care > Oral", "RM6.12 - 19.01", 45856, 4.5, 6335,
        47.54, 0.1, 120, 0.8333,
        "https://shop.tiktok.com/view/product/1731684607938880001",
        None, "https://kalodata/2",
    ])
    # duplicate of row 1 (same name+urls → same reference id)
    merged.append([
        3, "KALODATA", "Pengedap Vakum Mudah Alih", "https://img/1.jpg",
        "Home Supplies", "RM26.50", 45765, 4.5, 3448, 123.99, 0.05, 57, 0.7719,
        "https://shop-my.tiktok.com/pdp/1731147231842430988",
        None, "https://kalodata/1",
    ])
    # no image, no urls
    merged.append([
        4, "KALODATA", "Produk Tanpa Gambar", None, "Food", "RM9.90",
        None, None, None, None, None, None, None, None, None, None,
    ])

    hub = wb.create_sheet(svc.HUB_SHEET)
    hub.append([
        "No", "Product ID", "Product Name", "Product Type", "Category",
        "Price (RM)", "Image URL", "Target Avatar", "Pain Point",
        "Emotion/Trigger", "Dream Outcome", "Key Ingredient/Feature",
        "Main Benefit", "Secondary Benefit", "USP", "Hook Type",
    ])
    hub.append([
        1, None, "Pengedap Vakum Mudah Alih", "Home", "Home Supplies", "RM26.50",
        "https://img/1.jpg", "Ibu rumah yang kemas", "Makanan cepat basi",
        "Geram bila bazir", "Dapur tersusun", "Vacuum seal technology",
        "Makanan tahan lebih lama", "Jimat ruang", "Seal kedap udara", "Problem-Solution",
    ])
    hub.append([  # empty enrichment row → skipped
        2, None, "Jalur Pemutih Gigi", None, None, None, None,
        None, None, None, None, None, None, None, None, None,
    ])
    hub.append([  # unmatched product name
        99, None, "Produk Tidak Wujud", None, None, None, None,
        "Avatar X", None, None, None, None, None, None, None, None,
    ])
    wb.save(path)


@pytest.fixture()
def staged_env(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "OPERATOR_PACK_DIR", tmp_path)
    workbook_path = tmp_path / "kalodata_sample.xlsx"
    _build_workbook(workbook_path)
    return workbook_path


# ── import_workbook ──────────────────────────────────────────────────────────
def test_import_workbook_stages_records_and_hub(staged_env, tmp_path):
    report = svc.import_workbook(staged_env)
    assert report.parsed_merged == 4
    assert report.staged == 3  # duplicate collapsed
    assert report.skipped_duplicate_in_file == 1
    assert report.product_id_from_url == 2
    assert report.price_ranges_parsed == 1
    assert report.hub_matched == 1
    assert 99 in report.hub_unmatched_rows

    catalog = json.loads((tmp_path / svc.STAGED_CATALOG_FILENAME).read_text(encoding="utf-8"))
    assert len(catalog) == 3
    first = catalog[0]
    assert first["id"].startswith(FASTMOSS_REFERENCE_ID_PREFIX)
    assert first["source"] == "KALODATA"
    assert first["reference_only"] is True
    assert first["price"] == 26.5
    assert first["currency"] == "MYR"
    assert first["kalodata_meta"]["tiktok_product_id"] == "1731147231842430988"
    assert first["kalodata_meta"]["launch_date"] == "2025-04-18"

    hub = json.loads((tmp_path / svc.STAGED_HUB_FILENAME).read_text(encoding="utf-8"))
    assert len(hub) == 1
    (ref_id, item), = hub.items()
    assert ref_id == first["id"]
    assert item["target_customer_text"] == "Ibu rumah yang kemas"
    assert "Vacuum seal technology" == item["ingredients_text"]
    assert "Makanan tahan lebih lama" in item["benefits_text"]
    assert "Seal kedap udara" in item["benefits_text"]
    assert "Pain point: Makanan cepat basi" in item["product_knowledge_text"]
    assert "Hook type: Problem-Solution" in item["product_knowledge_text"]
    assert item["price"] == 26.5


def test_import_workbook_is_idempotent(staged_env):
    first = svc.import_workbook(staged_env)
    second = svc.import_workbook(staged_env)
    assert first.staged == second.staged == 3
    assert svc.load_staged_catalog() == svc.load_staged_catalog()


def test_import_workbook_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "OPERATOR_PACK_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.import_workbook(tmp_path / "nope.xlsx")


def test_loaders_fail_closed_on_corrupt_files(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "OPERATOR_PACK_DIR", tmp_path)
    (tmp_path / svc.STAGED_CATALOG_FILENAME).write_text("{not json", encoding="utf-8")
    (tmp_path / svc.STAGED_HUB_FILENAME).write_text("[]", encoding="utf-8")
    assert svc.load_staged_catalog() == []
    assert svc.load_hub_enrichment() == {}


# ── reference-catalog union ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reference_union_includes_staged_records(staged_env, monkeypatch):
    from agent.services import fastmoss_product_reference_service as ref_svc

    svc.import_workbook(staged_env)

    async def fake_enrich(record, persist=False):
        return dict(record)

    monkeypatch.setattr(ref_svc, "enrich_product", fake_enrich)
    monkeypatch.setattr(ref_svc, "_REFERENCE_CACHE_SIGNATURE", None)
    monkeypatch.setattr(ref_svc, "_REFERENCE_CACHE_ITEMS", [])
    monkeypatch.setattr(ref_svc, "_REFERENCE_CACHE_LOADED_LIMIT", 0)

    items = await ref_svc.list_fastmoss_reference_products(limit=2000)
    kalodata_items = [i for i in items if i.get("source_label") == "Kalodata Reference"]
    assert len(kalodata_items) == 3
    assert all(i["id"].startswith(FASTMOSS_REFERENCE_ID_PREFIX) for i in kalodata_items)
    assert all(i["reference_only"] for i in kalodata_items)

    # cache invalidates when the staged file changes (re-import)
    svc.import_workbook(staged_env)
    items_again = await ref_svc.list_fastmoss_reference_products(limit=2000)
    assert len([i for i in items_again if i.get("source_label") == "Kalodata Reference"]) == 3


@pytest.mark.asyncio
async def test_apply_hub_enrichment_delegates_to_import_enrichment(staged_env, monkeypatch):
    svc.import_workbook(staged_env)
    captured: dict = {}

    async def fake_import_enrichment(items):
        captured["items"] = items
        return {"total": len(items), "recomputed": len(items), "skipped": 0,
                "failed": 0, "results": []}

    import agent.services.fastmoss_bulk_promotion_service as bulk
    monkeypatch.setattr(bulk, "import_enrichment", fake_import_enrichment)

    result = await svc.apply_hub_enrichment()
    assert result["total"] == 1
    item = captured["items"][0]
    assert item["reference_id"].startswith(FASTMOSS_REFERENCE_ID_PREFIX)
    # exact import_enrichment field names only
    assert set(item.keys()) <= {
        "reference_id", "price", "benefits_text", "usage_text",
        "target_customer_text", "ingredients_text", "warnings_text",
        "product_knowledge_text",
    }
