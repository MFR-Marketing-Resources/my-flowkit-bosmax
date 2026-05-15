from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_get_product_intelligence_by_id(monkeypatch):
    async def fake_get(product_id: str):
        assert product_id == "prod-001"
        return {
            "product_id": "prod-001",
            "group": "LAUNDRY_CARE",
            "bosmax_product_family": "LAUNDRY_DETERGENT_LIQUID_REFILL",
            "copy_route": "DIRECT",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.get_product_intelligence_by_id",
        fake_get,
    )
    client = TestClient(_build_app())

    response = client.get("/api/product-intelligence/prod-001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["group"] == "LAUNDRY_CARE"
    assert payload["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"


def test_post_product_intelligence_resolve(monkeypatch):
    async def fake_resolve(request):
        assert request.product_payload["raw_product_title"] == "Atlas Lip Balm Original"
        return {
            "product_id": "inline-prod",
            "group": "BEAUTY_AND_PERSONAL_CARE",
            "bosmax_product_family": "BEAUTY_PERSONAL_CARE",
            "copy_route": "DIRECT",
            "claim_gate": "CLAIM_SAFE",
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.resolve_product_intelligence_request",
        fake_resolve,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/product-intelligence/resolve",
        json={
            "product_payload": {
                "id": "inline-prod",
                "raw_product_title": "Atlas Lip Balm Original",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["group"] == "BEAUTY_AND_PERSONAL_CARE"
    assert payload["claim_gate"] == "CLAIM_SAFE"


def test_get_product_intelligence_summary(monkeypatch):
    async def fake_summary():
        return {
            "total_products": 317,
            "products_by_source": {"FASTMOSS": 299, "MANUAL": 18},
            "group_distribution": {"LAUNDRY_CARE": 12},
            "copy_route_distribution": {"DIRECT": 290},
            "claim_gate_distribution": {"CLAIM_SAFE": 250, "CLAIM_REVIEW_REQUIRED": 67},
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.get_product_intelligence_summary",
        fake_summary,
    )
    client = TestClient(_build_app())

    response = client.get("/api/product-intelligence/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_products"] == 317
    assert payload["group_distribution"]["LAUNDRY_CARE"] == 12


def test_post_product_intelligence_backfill_preview(monkeypatch):
    async def fake_preview():
        return {
            "total_products": 317,
            "resolved": 299,
            "high_confidence": 200,
            "medium_confidence": 80,
            "low_confidence": 37,
            "needs_review": 37,
            "taxonomy_conflicts": 12,
            "group_distribution": {"FASHION_AND_APPAREL": 50},
            "copy_route_distribution": {"DIRECT": 280},
            "claim_gate_distribution": {"CLAIM_SAFE": 240, "CLAIM_REVIEW_REQUIRED": 77},
            "sample_failures": [],
            "sample_conflicts": [],
            "write_back_status": "READ_ONLY_NO_DB_WRITES",
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.get_product_intelligence_backfill_preview",
        fake_preview,
    )
    client = TestClient(_build_app())

    response = client.post("/api/product-intelligence/backfill-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved"] == 299
    assert payload["write_back_status"] == "READ_ONLY_NO_DB_WRITES"
