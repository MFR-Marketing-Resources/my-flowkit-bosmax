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
            "sales_metrics_source": "LATEST_FASTMOSS_IMPORT_BATCH",
            "sales_metrics_batch_id": "batch-001",
            "sold_count_metric_scope": "PRODUCT",
            "sold_count_truth_status": "VERIFIED_PRODUCT_LEVEL",
            "product_sold_count": 88,
            "image_analysis": {
                "status": "VISION_PROVIDER_NOT_CONFIGURED",
                "provider": "not_configured",
                "detected_package": None,
                "detected_text": [],
                "visual_confidence": "NOT_VERIFIED",
                "warnings": ["SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"],
            },
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
    assert payload["sales_metrics_source"] == "LATEST_FASTMOSS_IMPORT_BATCH"
    assert payload["product_sold_count"] == 88
    assert payload["image_analysis"]["status"] == "VISION_PROVIDER_NOT_CONFIGURED"


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


# ── AI Fill Missing route ────────────────────────────────────────────────────
def test_ai_fill_missing_route_returns_result(monkeypatch):
    captured = {}

    async def fake_fill(draft_id, *, selected_fields=None):
        captured["draft_id"] = draft_id
        captured["selected_fields"] = selected_fields
        return {
            "draft_id": draft_id, "product_id": "prod-1", "review_status": "NEEDS_REVISION",
            "provider": "deepseek", "model": "deepseek-chat", "prompt_version": "product_intel_ai_fill_v1",
            "generated_at": "2026-07-15T00:00:00Z", "targeted_fields": ["benefits_json"],
            "proposed": [{"field": "benefits_json", "status": "INFERENCE", "confidence": 0.6,
                          "rationale": "category", "previous_value": None, "proposed_value": ["Cold drinks"]}],
            "unresolved": [], "provider_configured": True,
        }

    monkeypatch.setattr(
        "agent.api.product_intelligence.ai_fill_missing_review_draft", fake_fill
    )
    client = TestClient(_build_app())
    response = client.post(
        "/api/product-intelligence/review-drafts/draft-1/ai-fill-missing",
        json={"selected_fields": ["benefits_json"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deepseek"
    assert body["review_status"] == "NEEDS_REVISION"
    assert body["proposed"][0]["field"] == "benefits_json"
    assert captured == {"draft_id": "draft-1", "selected_fields": ["benefits_json"]}


def test_ai_fill_missing_route_maps_errors(monkeypatch):
    from agent.services import ai_copy_provider_adapter as prov

    async def not_configured(draft_id, *, selected_fields=None):
        raise prov.AICopyProviderNotConfigured(prov.ERR_NOT_CONFIGURED)

    monkeypatch.setattr(
        "agent.api.product_intelligence.ai_fill_missing_review_draft", not_configured
    )
    client = TestClient(_build_app())
    r1 = client.post("/api/product-intelligence/review-drafts/draft-1/ai-fill-missing", json={})
    assert r1.status_code == 409
    assert r1.json()["detail"]["error"] == prov.ERR_NOT_CONFIGURED

    async def provider_error(draft_id, *, selected_fields=None):
        raise prov.AICopyProviderError(prov.ERR_CALL_FAILED, detail="boom")

    monkeypatch.setattr(
        "agent.api.product_intelligence.ai_fill_missing_review_draft", provider_error
    )
    r2 = client.post("/api/product-intelligence/review-drafts/draft-1/ai-fill-missing", json={})
    assert r2.status_code == 502
    assert r2.json()["detail"]["error"] == prov.ERR_CALL_FAILED

    async def not_found(draft_id, *, selected_fields=None):
        raise ValueError("DRAFT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.api.product_intelligence.ai_fill_missing_review_draft", not_found
    )
    r3 = client.post("/api/product-intelligence/review-drafts/draft-1/ai-fill-missing", json={})
    assert r3.status_code == 404
