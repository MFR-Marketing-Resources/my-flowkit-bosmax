import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router as product_intelligence_router
from agent.api.products import router as products_router
from agent.services import product_intelligence_snapshot_service as svc
from agent.db import crud


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    app.include_router(product_intelligence_router, prefix="/api")
    return TestClient(app)


def test_get_product_intelligence_404_when_product_missing():
    response = _client().get("/api/products/missing/intelligence")
    assert response.status_code == 404
    assert response.json()["detail"] == "PRODUCT_NOT_FOUND"


def test_get_product_intelligence_returns_empty_state_for_existing_product_without_snapshot():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Empty Intelligence",
            source="MANUAL",
            product_display_name="Bosmax Empty Intelligence",
            product_short_name="Bosmax Empty Intelligence",
        )
    )

    response = _client().get(f"/api/products/{product['id']}/intelligence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == product["id"]
    assert payload["latest_snapshot"] is None
    assert payload["status"] == "NO_APPROVED_SNAPSHOT"
    assert payload["provenance_summary"]["total_snapshots"] == 0


def test_get_product_intelligence_and_snapshot_list_return_structured_json_fields():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Approved Snapshot",
            source="MANUAL",
            product_display_name="Bosmax Approved Snapshot",
            product_short_name="Bosmax Approved Snapshot",
        )
    )
    snapshot = asyncio.run(
        svc.create_snapshot(
            product_id=product["id"],
            version=1,
            status="APPROVED",
            benefits_json=["portable", "clean"],
            source_urls_json={"source_url": "https://example.com/source"},
            image_evidence_json={"image_url": "https://example.com/image.jpg"},
            claim_tokens_json=["safe"],
            approved_at="2026-07-05T12:00:00Z",
            created_by="operator",
        )
    )

    latest_response = _client().get(f"/api/products/{product['id']}/intelligence")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["status"] == "APPROVED_SNAPSHOT_AVAILABLE"
    assert latest_payload["latest_snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert latest_payload["latest_snapshot"]["benefits_json"] == ["portable", "clean"]
    assert latest_payload["latest_snapshot"]["source_urls_json"] == {
        "source_url": "https://example.com/source"
    }
    assert latest_payload["latest_snapshot"]["image_evidence_json"] == {
        "image_url": "https://example.com/image.jpg"
    }
    assert latest_payload["latest_snapshot"]["claim_tokens_json"] == ["safe"]

    list_response = _client().get(f"/api/products/{product['id']}/intelligence/snapshots")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["product_id"] == product["id"]
    assert len(list_payload["items"]) == 1
    assert list_payload["items"][0]["snapshot_id"] == snapshot.snapshot_id
    assert list_payload["items"][0]["benefits_json"] == ["portable", "clean"]


def test_get_product_intelligence_snapshot_list_returns_empty_items_for_existing_product():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Snapshot List Empty",
            source="MANUAL",
            product_display_name="Bosmax Snapshot List Empty",
            product_short_name="Bosmax Snapshot List Empty",
        )
    )

    response = _client().get(f"/api/products/{product['id']}/intelligence/snapshots")
    assert response.status_code == 200
    assert response.json() == {"product_id": product["id"], "items": []}


def test_get_product_intelligence_snapshot_list_rejects_invalid_status():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Snapshot Invalid Status",
            source="MANUAL",
            product_display_name="Bosmax Snapshot Invalid Status",
            product_short_name="Bosmax Snapshot Invalid Status",
        )
    )

    response = _client().get(
        f"/api/products/{product['id']}/intelligence/snapshots?status=NOT_A_REAL_STATUS"
    )

    assert response.status_code == 422
