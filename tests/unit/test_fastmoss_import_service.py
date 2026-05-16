from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook
from starlette.datastructures import UploadFile

from agent.services.fastmoss_import_service import (
    FILE_TYPE_CONFIGS,
    LATEST_BATCH_POINTER,
    classify_sales_metric_column,
    detect_fastmoss_file_type,
    import_fastmoss_batch,
)


def _xlsx_bytes(headers: list[str], rows: list[list[object]], sheet_name: str = "Sheet1") -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _upload(name: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(payload))


@pytest.mark.asyncio
async def test_import_batch_accepts_partial_set_and_reports_missing_types(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_import_service.FASTMOSS_IMPORTS_DIR", tmp_path)
    monkeypatch.setattr("agent.services.fastmoss_import_service.LATEST_BATCH_POINTER", tmp_path / "latest.json")

    sales_rank = _upload(
        "FastMoss Sales Rank.xlsx",
        _xlsx_bytes(
            ["Product Name", "Shop Name", "Total Units Sold", "Shop Total Units Sold", "Orders"],
            [["Atlas Bottle", "Atlas Shop", 125, 9911, 92]],
            sheet_name="Product Sales Rank",
        ),
    )
    video_product_list = _upload(
        "Video_Product_List.xlsx",
        _xlsx_bytes(
            ["Product Title", "Video Total Units Sold", "Video Units Sold"],
            [["Atlas Bottle", 55, 21]],
            sheet_name="Video Product List",
        ),
    )

    report = await import_fastmoss_batch(
        {
            "creator_search": None,
            "export_ad_list": None,
            "export_advertiser_list": None,
            "shop_list": None,
            "sales_rank": sales_rank,
            "new_products_ranking": None,
            "product_search_data": None,
            "product_search_sales_rank": None,
            "most_promoted_products_rank": None,
            "video_product_list": video_product_list,
        }
    )

    assert report["uploaded_files"] == 2
    assert report["latest_reference_only"] is True
    assert report["growth_analytics_enabled"] is False
    assert report["write_back_status"] == "READ_ONLY_IMPORT_PREVIEW"
    assert "SALES_RANK" in report["recognized_file_types"]
    assert "VIDEO_PRODUCT_LIST" in report["recognized_file_types"]
    assert "CREATOR_SEARCH" in report["missing_expected_file_types"]
    assert report["row_counts_by_file_type"]["SALES_RANK"] == 1
    assert Path(report["raw_file_storage_path"]).exists()
    assert (tmp_path / report["batch_id"] / "report.json").exists()
    assert (tmp_path / "latest.json").exists()


def test_detect_fastmoss_file_type_supports_field_key_and_filename_pattern():
    detected, mode = detect_fastmoss_file_type(
        upload_field_key="sales_rank",
        filename="whatever.xlsx",
        headers=[],
        sheet_names=[],
    )
    assert detected == "SALES_RANK"
    assert mode == "field_key"

    detected, mode = detect_fastmoss_file_type(
        upload_field_key=None,
        filename="TT_Most_Promoted_Products_Rank_20260416_020903.xlsx",
        headers=[],
        sheet_names=[],
    )
    assert detected == "MOST_PROMOTED_PRODUCTS_RANK"
    assert mode == "filename_pattern"


def test_classify_sales_metric_column_separates_product_shop_and_unknown():
    product_metric = classify_sales_metric_column("SALES_RANK", "Total Units Sold")
    shop_metric = classify_sales_metric_column("SALES_RANK", "Shop Total Units Sold")
    unknown_metric = classify_sales_metric_column("PRODUCT_SEARCH_DATA", "7-Day Sales Volume")

    assert product_metric is not None
    assert product_metric.metric_scope == "PRODUCT"
    assert product_metric.truth_status == "VERIFIED_PRODUCT_LEVEL"

    assert shop_metric is not None
    assert shop_metric.metric_scope == "SHOP"
    assert shop_metric.truth_status == "SHOP_LEVEL_AGGREGATE"
    assert shop_metric.warning == "SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES"

    assert unknown_metric is not None
    assert unknown_metric.metric_scope == "UNKNOWN"
    assert unknown_metric.truth_status == "NOT_VERIFIED"


@pytest.mark.asyncio
async def test_ambiguous_or_shop_metrics_are_not_promoted_to_product_sold_count(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_import_service.FASTMOSS_IMPORTS_DIR", tmp_path)
    monkeypatch.setattr("agent.services.fastmoss_import_service.LATEST_BATCH_POINTER", tmp_path / "latest.json")

    payload = _upload(
        "Shop_List.xlsx",
        _xlsx_bytes(
            ["Shop Name", "Shop Total Units Sold", "Total Sales Volume"],
            [["Atlas Shop", 74561117, 999999]],
            sheet_name="Shop List",
        ),
    )
    report = await import_fastmoss_batch(
        {key: (payload if key == "shop_list" else None) for key in FILE_TYPE_CONFIGS}
    )

    metrics = report["sales_metric_scope_report"]
    assert any(metric["metric_name"] == "shop_total_sold_count" and metric["metric_scope"] == "SHOP" for metric in metrics)
    assert not any(metric["metric_name"] == "product_sold_count" and metric["metric_scope"] == "SHOP" for metric in metrics)
