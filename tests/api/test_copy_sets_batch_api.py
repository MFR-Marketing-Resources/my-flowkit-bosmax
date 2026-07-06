"""API tests for POST /api/copy-sets/generate-batch — Phase 2 batch candidate generation."""
import pytest
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


# ── Validation ─────────────────────────────────────────────

def test_generate_batch_rejects_count_below_min():
    """candidate_count < 3 returns 422."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "any-id", "candidate_count": 2},
    )
    assert response.status_code == 422


def test_generate_batch_rejects_count_above_max():
    """candidate_count > 10 returns 422."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "any-id", "candidate_count": 11},
    )
    assert response.status_code == 422


def test_generate_batch_rejects_missing_product_id():
    """product_id is required."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"candidate_count": 5},
    )
    assert response.status_code == 422


def test_generate_batch_default_count_is_5():
    """Default candidate_count is 5."""
    from agent.models.copy_set import AICopyAssistBatchRequest
    req = AICopyAssistBatchRequest(product_id="test-id")
    assert req.candidate_count == 5


# ── Provider-not-configured (fail-closed) ───────────────────

def test_generate_batch_fails_when_provider_not_configured(monkeypatch):
    """Without a configured text_assist provider, returns 409."""
    async def fake_batch(request):
        raise ai_provider.AICopyProviderNotConfigured(
            ai_provider.ERR_NOT_CONFIGURED
        )

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "candidate_count": 5},
    )
    assert response.status_code == 409
    body = response.json(); assert body.get("detail", body).get("error") == "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"


def test_generate_batch_provider_error_returns_502(monkeypatch):
    """A provider error returns 502."""
    async def fake_batch(request):
        raise ai_provider.AICopyProviderError(
            ai_provider.ERR_CALL_FAILED, detail="timeout"
        )

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "candidate_count": 5},
    )
    assert response.status_code == 502
    body = response.json(); assert body.get("detail", body).get("error") == "AI_COPY_ASSIST_CALL_FAILED"


def test_generate_batch_product_not_found(monkeypatch):
    """A missing product returns 404 with PRODUCT_NOT_FOUND."""
    async def fake_batch(request):
        raise svc.CopySetError("PRODUCT_NOT_FOUND", status_code=404)

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "candidate_count": 5},
    )
    assert response.status_code == 404
    body = response.json(); assert body.get("detail", body).get("error") == "PRODUCT_NOT_FOUND"


def test_generate_batch_success(monkeypatch):
    """A valid batch returns 200 with summary."""
    async def fake_batch(request):
        return {
            "provider": {"lane": "text_assist", "configured": True},
            "candidates": [
                {"copy_set": {"copy_set_id": "cs-1"}, "created": True, "dedupe_match": False},
                {"copy_set": {"copy_set_id": "cs-2"}, "created": True, "dedupe_match": False},
            ],
            "summary": {"requested": 5, "created": 2, "deduped_existing": 3, "rejected_safety": 0},
        }

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "candidate_count": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["requested"] == 5
    assert body["summary"]["created"] == 2
    assert len(body["candidates"]) == 2
