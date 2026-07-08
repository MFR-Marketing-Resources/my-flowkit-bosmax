"""Prepare Product for Copywriting endpoint — fail-closed routing (503/502/200)."""
from fastapi.testclient import TestClient

from agent.main import app
from agent.services import ai_copy_provider_adapter as provider

_URL = "/api/products/p1/intelligence/review-drafts/prepare"


def test_prepare_router_503_when_unconfigured(monkeypatch):
    monkeypatch.setattr(provider, "is_configured", lambda: False)
    resp = TestClient(app).post(_URL)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "TEXT_ASSIST_NOT_CONFIGURED"


def test_prepare_router_happy_path(monkeypatch):
    monkeypatch.setattr(provider, "is_configured", lambda: True)

    async def fake_prepare(product_id: str):
        return {
            "review_draft_id": "d1",
            "review_status": "READY_FOR_REVIEW",
            "recommended_formula": "PAS",
        }

    monkeypatch.setattr(
        "agent.services.product_intelligence_prepare_service.prepare_product_for_copywriting",
        fake_prepare,
    )
    resp = TestClient(app).post(_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_formula"] == "PAS"
    assert body["review_status"] != "APPROVED"


def test_prepare_router_502_on_invalid_ai(monkeypatch):
    monkeypatch.setattr(provider, "is_configured", lambda: True)

    async def fake_prepare(product_id: str):
        raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID, detail="bad json")

    monkeypatch.setattr(
        "agent.services.product_intelligence_prepare_service.prepare_product_for_copywriting",
        fake_prepare,
    )
    resp = TestClient(app).post(_URL)
    assert resp.status_code == 502
