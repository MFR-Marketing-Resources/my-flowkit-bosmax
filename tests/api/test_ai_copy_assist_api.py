"""API contract tests for the AI Copy Assist route (candidate Copy Set).

Asserts the HTTP surface + fail-closed error mapping. Service behavior is covered
in tests/unit/test_ai_copy_assist_service.py. The service is mocked here.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_sets import router
from agent.services import ai_copy_assist_service as ai_svc
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_set_service as svc


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _candidate(**over):
    base = {
        "copy_set": {
            "copy_set_id": "cs-ai-1",
            "product_id": "prod-1",
            "status": "COPY_REVIEW_REQUIRED",
            "source": "AI_COPY_ASSIST",
            "hook": "Nak kulit segar?",
        },
        "created": True,
        "dedupe_match": False,
        "safety": {"safe": True, "violations": []},
        "warnings": [],
    }
    base.update(over)
    return base


def test_ai_assist_returns_review_required_candidate(monkeypatch):
    async def fake(request):
        return {
            "provider": {"lane": "text_assist", "configured": True, "provider_id": "qwen"},
            "candidates": [_candidate()],
        }

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidate", fake)
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "prod-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["copy_set"]["status"] == "COPY_REVIEW_REQUIRED"
    assert body["candidates"][0]["copy_set"]["status"] != "COPY_APPROVED"


def test_ai_assist_provider_not_configured_returns_409(monkeypatch):
    async def fake(request):
        raise ai_provider.AICopyProviderNotConfigured(ai_provider.ERR_NOT_CONFIGURED)

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidate", fake)
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "prod-1"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"


def test_ai_assist_invalid_response_returns_502(monkeypatch):
    async def fake(request):
        raise ai_provider.AICopyProviderError(ai_provider.ERR_RESPONSE_INVALID, detail="bad json")

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidate", fake)
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "prod-1"})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "AI_COPY_ASSIST_RESPONSE_INVALID"


def test_ai_assist_product_not_found_returns_404(monkeypatch):
    async def fake(request):
        raise svc.CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": "x"})

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidate", fake)
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "x"})
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


def test_ai_assist_candidate_count_validation():
    # candidate_count is bounded 1..3 by the request model.
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "p", "candidate_count": 9})
    assert r.status_code == 422  # pydantic validation, service never called
