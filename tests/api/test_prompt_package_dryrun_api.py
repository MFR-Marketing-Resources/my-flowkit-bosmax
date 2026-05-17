from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_prompt_dryrun_api_returns_clean_preview(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_generate(product_id: str, mode: str):
        return {
            "status": "DRY_RUN_READY",
            "product_id": product_id,
            "mode": mode,
            "prompt_preview": "Clean prompt preview",
            "dry_run_preview_allowed": True,
            "production_generation_allowed": False,
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.generate_prompt_dryrun", fake_generate)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-001/prompt-dryrun?mode=T2V")

    assert response.status_code == 200
    assert response.json()["status"] == "DRY_RUN_READY"


def test_prompt_dryrun_api_blocks_when_claim_safe_rewrite_missing(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_generate(product_id: str, mode: str):
        return {
            "status": "CLAIM_SAFE_COPY_REWRITE_REQUIRED",
            "product_id": product_id,
            "mode": mode,
            "errors": ["CLAIM_SAFE_COPY_REWRITE_REQUIRED"],
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.generate_prompt_dryrun", fake_generate)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-001/prompt-dryrun?mode=IMG")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "CLAIM_SAFE_COPY_REWRITE_REQUIRED"
