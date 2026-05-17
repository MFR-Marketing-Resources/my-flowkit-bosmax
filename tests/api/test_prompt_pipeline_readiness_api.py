import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app

@pytest.mark.asyncio
async def test_api_readiness_herbs():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8100/api") as client:
        resp = await client.get("/products/38a6bacd-2427-42ca-8409-2a78c7f0520c/prompt-readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_id"] == "38a6bacd-2427-42ca-8409-2a78c7f0520c"
        assert data["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"

@pytest.mark.asyncio
async def test_api_readiness_archived():
    async def fake_lookup(product_id: str):
        return {"id": product_id, "lifecycle_status": "ARCHIVED", "raw_product_title": "Archived Product"}

    async def fake_report(product):
        return {
            "product_id": product["id"],
            "lifecycle_status": "ARCHIVED",
            "blockers": ["PRODUCT_ARCHIVED"],
            "readiness_by_mode": {"T2V": "BLOCKED_PRODUCT_ARCHIVED"},
        }

    from agent.api import products as products_api

    client = TestClient(_build_app())
    from pytest import MonkeyPatch
    monkeypatch = MonkeyPatch()
    monkeypatch.setattr(products_api, "_find_product_by_lookup", fake_lookup)
    monkeypatch.setattr(products_api.PromptPipelineReadinessService, "get_readiness_report", fake_report)
    try:
        resp = client.get("/api/products/archived-prod/prompt-readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lifecycle_status"] == "ARCHIVED"
        assert "PRODUCT_ARCHIVED" in data["blockers"]
    finally:
        monkeypatch.undo()
