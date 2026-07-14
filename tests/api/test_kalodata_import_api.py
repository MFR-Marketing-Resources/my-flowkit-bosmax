"""Kalodata import API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.kalodata_import import router
from agent.models.kalodata_import import KalodataImportReport


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_import_endpoint_returns_report(monkeypatch):
    captured = {}

    def fake_import(source_path, existing_tids=None):
        captured["source_path"] = source_path
        captured["existing_tids"] = existing_tids
        return KalodataImportReport(
            source_path=str(source_path), parsed_merged=4, parsed_hub=3,
            staged=3, skipped_duplicate_in_file=1, product_id_from_url=2,
            price_ranges_parsed=1, hub_matched=1, hub_unmatched_rows=[99],
            staged_catalog_path="x.json", staged_hub_path="y.json",
        )

    monkeypatch.setattr(
        "agent.services.kalodata_import_service.import_workbook", fake_import
    )
    async def fake_tids():
        return {"tid-existing"}
    monkeypatch.setattr(
        "agent.services.kalodata_import_service.collect_system_tids", fake_tids
    )
    client = TestClient(_build_app())
    response = client.post("/api/kalodata/import", json={"source_path": "C:/tmp/kalo.xlsx"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["staged"] == 3
    assert payload["hub_matched"] == 1
    assert captured["source_path"] == "C:/tmp/kalo.xlsx"


def test_import_endpoint_uses_default_path(monkeypatch):
    captured = {}

    def fake_import(source_path, existing_tids=None):
        captured["source_path"] = source_path
        captured["existing_tids"] = existing_tids
        return KalodataImportReport(source_path=str(source_path))

    monkeypatch.setattr(
        "agent.services.kalodata_import_service.import_workbook", fake_import
    )
    async def fake_tids():
        return {"tid-existing"}
    monkeypatch.setattr(
        "agent.services.kalodata_import_service.collect_system_tids", fake_tids
    )
    client = TestClient(_build_app())
    response = client.post("/api/kalodata/import", json={})
    assert response.status_code == 200
    assert "Kalodata-BONUS 300 DATA PRODUK.xlsx" in captured["source_path"]


def test_import_endpoint_404_on_missing_workbook(monkeypatch):
    def fake_import(source_path, existing_tids=None):
        raise FileNotFoundError(source_path)

    monkeypatch.setattr(
        "agent.services.kalodata_import_service.import_workbook", fake_import
    )
    async def fake_tids():
        return {"tid-existing"}
    monkeypatch.setattr(
        "agent.services.kalodata_import_service.collect_system_tids", fake_tids
    )
    client = TestClient(_build_app())
    response = client.post("/api/kalodata/import", json={"source_path": "C:/no.xlsx"})
    assert response.status_code == 404
    assert "WORKBOOK_NOT_FOUND" in response.text


def test_copy_intelligence_dry_run_requires_explicit_source_path():
    client = TestClient(_build_app())
    response = client.post("/api/kalodata/copy-intelligence/dry-run", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "SOURCE_PATH_REQUIRED"


def test_apply_hub_enrichment_delegates(monkeypatch):
    captured = {}

    async def fake_apply(reference_ids=None):
        captured["reference_ids"] = reference_ids
        return {"total": 2, "recomputed": 2, "skipped": 0, "failed": 0, "results": []}

    monkeypatch.setattr(
        "agent.services.kalodata_import_service.apply_hub_enrichment", fake_apply
    )
    client = TestClient(_build_app())
    response = client.post(
        "/api/kalodata/apply-hub-enrichment",
        json={"reference_ids": ["fastmoss-ref:abc123"]},
    )
    assert response.status_code == 200
    assert response.json()["recomputed"] == 2
    assert captured["reference_ids"] == ["fastmoss-ref:abc123"]


def test_hub_gaps_shape(monkeypatch):
    async def fake_gaps():
        return {"items": [], "totals": {"staged": 0, "fully_enriched": 0, "with_any_gap": 0}}

    monkeypatch.setattr("agent.services.kalodata_import_service.hub_gaps", fake_gaps)
    client = TestClient(_build_app())
    response = client.get("/api/kalodata/hub-gaps")
    assert response.status_code == 200
    assert response.json()["totals"]["staged"] == 0


def test_cache_images_bounds():
    client = TestClient(_build_app())
    assert client.post("/api/kalodata/cache-images", json={"product_ids": []}).status_code == 422
    assert (
        client.post(
            "/api/kalodata/cache-images",
            json={"product_ids": [f"p{i}" for i in range(26)]},
        ).status_code
        == 422
    )


def test_cache_images_sequential_with_results(monkeypatch):
    calls: list[str] = []

    async def fake_cache(product_id):
        calls.append(product_id)
        if product_id == "bad":
            return {"status": "failed", "detail": "404", "image_asset_status": "FAILED"}
        return {"status": "success", "local_image_path": f"/img/{product_id}.jpg",
                "image_asset_status": "READY"}

    monkeypatch.setattr("agent.api.products.cache_product_image", fake_cache)
    # retries should not sleep the suite
    import agent.api.kalodata_import as api_mod

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(api_mod.asyncio, "sleep", no_sleep)

    client = TestClient(_build_app())
    response = client.post(
        "/api/kalodata/cache-images", json={"product_ids": ["p1", "bad", "p2"]}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["cached"] == 2
    assert payload["failed"] == 1
    # 'bad' retried 3 times, successes once each
    assert calls.count("bad") == 3
    assert calls.count("p1") == calls.count("p2") == 1
