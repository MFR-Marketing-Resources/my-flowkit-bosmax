import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router as product_intelligence_router
from agent.services import product_intelligence_snapshot_service as svc
from agent.db import crud


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(product_intelligence_router, prefix="/api")
    return TestClient(app)


def test_snapshot_provenance_404_when_snapshot_missing():
    response = _client().get("/api/product-intelligence/snapshots/missing/provenance")
    assert response.status_code == 404
    assert response.json()["detail"] == "SNAPSHOT_NOT_FOUND"


def test_snapshot_provenance_returns_empty_items_when_none_exist():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Empty Provenance",
            source="MANUAL",
            product_display_name="Bosmax Empty Provenance",
            product_short_name="Bosmax Empty Provenance",
        )
    )
    snapshot = asyncio.run(
        svc.create_snapshot(
            product_id=product["id"],
            version=1,
            status="APPROVED",
            approved_at="2026-07-05T12:00:00Z",
        )
    )

    response = _client().get(
        f"/api/product-intelligence/snapshots/{snapshot.snapshot_id}/provenance"
    )
    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": snapshot.snapshot_id,
        "product_id": product["id"],
        "items": [],
    }


def test_snapshot_provenance_returns_filtered_items():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Provenance API",
            source="MANUAL",
            product_display_name="Bosmax Provenance API",
            product_short_name="Bosmax Provenance API",
        )
    )
    snapshot = asyncio.run(
        svc.create_snapshot(
            product_id=product["id"],
            version=1,
            status="APPROVED",
            approved_at="2026-07-05T12:00:00Z",
        )
    )
    asyncio.run(
        svc.create_field_provenance(
            snapshot_id=snapshot.snapshot_id,
            product_id=product["id"],
            field_name="benefits_json",
            source_type="MANUAL_DECLARED",
            evidence_kind="TEXT",
            extraction_method="OPERATOR_INPUT",
            verification_status="REVIEWED_APPROVED",
            normalized_value='["portable"]',
        )
    )
    asyncio.run(
        svc.create_field_provenance(
            snapshot_id=snapshot.snapshot_id,
            product_id=product["id"],
            field_name="usage_text",
            source_type="MANUAL_DECLARED",
            evidence_kind="TEXT",
            extraction_method="OPERATOR_INPUT",
            verification_status="REVIEWED_APPROVED",
            normalized_value="Apply externally",
        )
    )

    response = _client().get(
        f"/api/product-intelligence/snapshots/{snapshot.snapshot_id}/provenance?field_name=benefits_json"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot_id"] == snapshot.snapshot_id
    assert payload["product_id"] == product["id"]
    assert len(payload["items"]) == 1
    assert payload["items"][0]["field_name"] == "benefits_json"
