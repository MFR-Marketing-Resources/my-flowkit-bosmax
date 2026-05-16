from __future__ import annotations

from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from agent.api.fastmoss_import import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _xlsx_bytes(headers: list[str], rows: list[list[object]], sheet_name: str) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_fastmoss_import_batch_accepts_all_ten_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_import_service.FASTMOSS_IMPORTS_DIR", tmp_path)
    monkeypatch.setattr("agent.services.fastmoss_import_service.LATEST_BATCH_POINTER", tmp_path / "latest.json")

    client = TestClient(_build_app())
    files = {
        "creator_search": ("Creator_Search.xlsx", _xlsx_bytes(["Creator Name"], [["Alya"]], "Creator Search"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "export_ad_list": ("Export Ad List.xlsx", _xlsx_bytes(["Product Name", "Orders"], [["Atlas", 5]], "Export Ad List"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "export_advertiser_list": ("Export Advertiser List.xlsx", _xlsx_bytes(["Shop Name", "Total Sales Volume"], [["Atlas Shop", 900]], "Export Advertiser List"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "shop_list": ("Shop List.xlsx", _xlsx_bytes(["Shop Name", "Shop Total Units Sold"], [["Atlas Shop", 9911]], "Shop List"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "sales_rank": ("Sales Rank.xlsx", _xlsx_bytes(["Product Name", "Shop Name", "Total Units Sold", "Shop Total Units Sold"], [["Atlas", "Atlas Shop", 50, 9911]], "Product Sales Rank"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "new_products_ranking": ("New_Products_Ranking.xlsx", _xlsx_bytes(["Product Name", "Shop", "Units Sold"], [["Atlas", "Atlas Shop", 20]], "New Products Ranking"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "product_search_data": ("Product Search Data.xlsx", _xlsx_bytes(["Product Name", "Store Name", "Total Sales Volume"], [["Atlas", "Atlas Shop", 1200]], "Product Search Data"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "product_search_sales_rank": ("Product_Search_Sales_Rank.xlsx", _xlsx_bytes(["Product Name", "Shop", "Units Sold"], [["Atlas", "Atlas Shop", 20]], "Product Search Sales Rank"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "most_promoted_products_rank": ("TT_Most_Promoted_Products_Rank.xlsx", _xlsx_bytes(["Product Name", "Shop Name", "Total Units Sold"], [["Atlas", "Atlas Shop", 40]], "Most Promoted Products"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "video_product_list": ("Video_Product_List.xlsx", _xlsx_bytes(["Product Title", "Video Total Units Sold", "Video Units Sold"], [["Atlas", 70, 33]], "Video Product List"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }

    response = client.post("/api/fastmoss/import-batch", files=files)
    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded_files"] == 10
    assert len(payload["recognized_file_types"]) == 10
    assert payload["missing_expected_file_types"] == []
    assert payload["latest_reference_only"] is True
    assert payload["growth_analytics_enabled"] is False
    assert payload["write_back_status"] == "READ_ONLY_IMPORT_PREVIEW"


def test_fastmoss_import_batch_latest_endpoint_returns_saved_report(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_import_service.FASTMOSS_IMPORTS_DIR", tmp_path)
    monkeypatch.setattr("agent.services.fastmoss_import_service.LATEST_BATCH_POINTER", tmp_path / "latest.json")

    client = TestClient(_build_app())
    response = client.post(
        "/api/fastmoss/import-batch",
        files={
            "sales_rank": (
                "Sales Rank.xlsx",
                _xlsx_bytes(
                    ["Product Name", "Shop Name", "Total Units Sold"],
                    [["Atlas", "Atlas Shop", 50]],
                    "Product Sales Rank",
                ),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]

    latest = client.get("/api/fastmoss/import-batch/latest")
    assert latest.status_code == 200
    assert latest.json()["batch_id"] == batch_id

    specific = client.get(f"/api/fastmoss/import-batch/{batch_id}")
    assert specific.status_code == 200
    assert specific.json()["batch_id"] == batch_id
