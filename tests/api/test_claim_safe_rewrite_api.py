from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_claim_safe_preview_api(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_preview(product_id: str):
        return {
            "product_id": product_id,
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_PREVIEW_ONLY",
            "approval_required": True,
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.preview_claim_safe_rewrite", fake_preview)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-001/claim-safe-rewrite-preview")

    assert response.status_code == 200
    assert response.json()["approval_required"] is True


def test_claim_safe_approval_api_requires_phrase(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_approve(product_id: str, confirmation_phrase: str, approval_note: str | None = None):
        raise PermissionError("INVALID_APPROVAL_PHRASE")

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.approve_claim_safe_rewrite", fake_approve)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.post(
        "/api/products/prod-001/claim-safe-rewrite-approval",
        json={"confirmation_phrase": "WRONG"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["approval_phrase"] == "APPROVE_CLAIM_SAFE_COPY_REVIEW"


def test_get_product_refreshes_stale_claim_safe_payload(monkeypatch):
    stored_product = {
        "id": "prod-legacy",
        "lifecycle_status": "ACTIVE",
        "claim_safe_copy_payload": '{"legacy":true}',
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
    }

    async def fake_get_product(product_id: str):
        return dict(stored_product)

    async def fake_refresh(product_id: str):
        return {
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
            "safe_claim_rewrite": "Saya sendiri guna produk ni - memang jadi rutin harian saya.",
        }

    async def fake_enrich(product, persist=False):
        updated = dict(product)
        updated["claim_safe_copy_payload"] = '{"safe_claim_rewrite":"Saya sendiri guna produk ni - memang jadi rutin harian saya."}'
        return updated

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.refresh_claim_safe_package_if_stale", fake_refresh)
    monkeypatch.setattr("agent.api.products.enrich_product", fake_enrich)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-legacy")

    assert response.status_code == 200
    assert "Saya sendiri guna produk ni" in response.json()["claim_safe_copy_payload"]
