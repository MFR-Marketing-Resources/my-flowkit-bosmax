from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api import creative_intelligence as api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    return TestClient(app)


def test_activation_endpoint_requires_explicit_confirmation(monkeypatch):
    async def activate(*_args):
        raise api._scene_activation.ActivationError("ACTIVATION_CONFIRMATION_REQUIRED")

    monkeypatch.setattr(api._scene_activation, "activate", activate)
    response = _client().post("/api/creative-intelligence/scene-context-promotion/activation", json={
        "reviewed_via_product_id": "p1", "source_template_id": "template", "candidate_fingerprint": "fp",
        "confirmation": "wrong", "activated_by": "owner",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "ACTIVATION_CONFIRMATION_REQUIRED"


def test_activation_endpoint_returns_server_result_without_paths_or_prompt(monkeypatch):
    async def activate(*_args):
        return {"items": [{
            "activation_id": "a1", "source_template_id": "template", "candidate_fingerprint": "fp",
            "product_id": "p1", "cluster": "Beauty", "scene_code": "SCN_BEAUTY", "scene_name": "Beauty",
            "activation_status": "ACTIVE_IN_REGISTRY", "generation_status": "NOT_GENERATED", "idempotent": False,
            "registry_scene_count": 21, "registry_mutations": 1, "provider_calls": 0, "generation_jobs": 0, "credits_used": 0,
        }]}

    monkeypatch.setattr(api._scene_activation, "activate", activate)
    response = _client().post("/api/creative-intelligence/scene-context-promotion/activation", json={
        "reviewed_via_product_id": "p1", "source_template_id": "template", "candidate_fingerprint": "fp",
        "confirmation": "PROMOTE_TO_ACTIVE_REGISTRY", "activated_by": "owner",
    })
    assert response.status_code == 200
    assert "PromptV1" not in response.text and "bridge_path" not in response.text
    assert response.json()["generation_status"] == "NOT_GENERATED"


def test_activation_error_status_mapping(monkeypatch):
    async def activate(*_args):
        raise api._scene_activation.ActivationError("STALE_CANDIDATE_FINGERPRINT")

    monkeypatch.setattr(api._scene_activation, "activate", activate)
    response = _client().post("/api/creative-intelligence/scene-context-promotion/activation", json={
        "reviewed_via_product_id": "p1", "source_template_id": "template", "candidate_fingerprint": "fp",
        "confirmation": "PROMOTE_TO_ACTIVE_REGISTRY", "activated_by": "owner",
    })
    assert response.status_code == 409


def test_eligibility_and_history_contracts(monkeypatch):
    async def eligibility(_product):
        return {"product_id": "p1", "cluster": "Beauty", "candidate_count": 0, "registry_mutations": 0, "candidates": []}

    async def history(*_args):
        return {"count": 0, "events": [], "registry_mutations": 0, "provider_calls": 0, "generation_jobs": 0, "credits_used": 0}

    monkeypatch.setattr(api._scene_activation, "activation_eligibility", eligibility)
    monkeypatch.setattr(api._scene_activation, "activation_history", history)
    client = _client()
    assert client.get("/api/creative-intelligence/scene-context-promotion/activation/product/p1").status_code == 200
    assert client.get("/api/creative-intelligence/scene-context-promotion/activation/history?product_id=p1").json()["events"] == []
