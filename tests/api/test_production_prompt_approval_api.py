from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_production_prompt_approval_api_requires_phrase(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_approve(*args, **kwargs):
        raise PermissionError("INVALID_APPROVAL_PHRASE")

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.approve_production_prompt_package", fake_approve)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.post(
        "/api/products/prod-001/production-prompt-approval",
        json={
            "approval_phrase": "WRONG",
            "approved_modes": ["T2V", "IMG"],
            "reviewer_note": "Approved claim-safe BOSMAX Herbs 5 ML prompt package for production handoff.",
            "confirm_no_google_flow_execution": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["approval_phrase"] == "APPROVE_PRODUCTION_PROMPT_PACKAGE"


def test_production_prompt_approval_api_returns_runtime_payload(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_approve(*args, **kwargs):
        return {
            "product_id": "prod-001",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "approved_modes": ["T2V", "IMG"],
            "execution_allowed": False,
        }

    async def fake_report(product):
        return {
            "product_id": product["id"],
            "production_generation_allowed": True,
            "production_prompt_approved_modes": ["T2V", "IMG"],
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.approve_production_prompt_package", fake_approve)
    monkeypatch.setattr("agent.api.products.PromptPipelineReadinessService.get_readiness_report", fake_report)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)

    client = TestClient(_build_app())
    response = client.post(
        "/api/products/prod-001/production-prompt-approval",
        json={
            "approval_phrase": "APPROVE_PRODUCTION_PROMPT_PACKAGE",
            "approved_modes": ["T2V", "IMG"],
            "reviewer_note": "Approved claim-safe BOSMAX Herbs 5 ML prompt package for production handoff.",
            "confirm_no_google_flow_execution": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["production_prompt_approval_status"] == "PRODUCTION_PROMPT_APPROVED"
    assert response.json()["readiness_after_approval"]["production_generation_allowed"] is True
