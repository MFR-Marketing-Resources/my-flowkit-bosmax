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
    """requested_count < 3 returns 422."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "any-id", "requested_count": 2},
    )
    assert response.status_code == 422


def test_generate_batch_rejects_count_above_max():
    """requested_count > 10 returns 422."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "any-id", "requested_count": 11},
    )
    assert response.status_code == 422


def test_generate_batch_rejects_missing_product_id():
    """product_id is required."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"requested_count": 5},
    )
    assert response.status_code == 422


def test_generate_batch_default_count_is_5():
    """Default requested_count is 5."""
    from agent.models.copy_set import AICopyAssistBatchRequest
    req = AICopyAssistBatchRequest(product_id="test-id")
    assert req.requested_count == 5


def test_generate_batch_dry_run_default_false():
    """dry_run defaults to False."""
    from agent.models.copy_set import AICopyAssistBatchRequest
    req = AICopyAssistBatchRequest(product_id="test-id")
    assert req.dry_run is False


def test_generate_batch_dedupe_threshold_validated():
    """dedupe_threshold must be >= 0 and <= 1."""
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "any-id", "requested_count": 5, "dedupe_threshold": 1.5},
    )
    assert response.status_code == 422


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
        json={"product_id": "test-id", "requested_count": 5},
    )
    assert response.status_code == 409
    body = response.json()
    assert body.get("detail", body).get("error") == "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"


def test_generate_batch_provider_error_returns_502(monkeypatch):
    """A provider error returns 502."""
    async def fake_batch(request):
        raise ai_provider.AICopyProviderError(
            ai_provider.ERR_CALL_FAILED, detail="timeout"
        )

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "requested_count": 5},
    )
    assert response.status_code == 502
    body = response.json()
    assert body.get("detail", body).get("error") == "AI_COPY_ASSIST_CALL_FAILED"


def test_generate_batch_product_not_found(monkeypatch):
    """A missing product returns 404 with PRODUCT_NOT_FOUND."""
    async def fake_batch(request):
        raise svc.CopySetError("PRODUCT_NOT_FOUND", status_code=404)

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "test-id", "requested_count": 5},
    )
    assert response.status_code == 404
    body = response.json()
    assert body.get("detail", body).get("error") == "PRODUCT_NOT_FOUND"


# ── Success paths ─────────────────────────────────────────

def test_generate_batch_success_returns_correct_shape(monkeypatch):
    """A valid batch returns 200 with batch_id, ledger, warnings, candidates."""
    async def fake_batch(request):
        return {
            "batch_id": "batch-001",
            "product_id": "prod-1",
            "requested_count": 5,
            "created_count": 3,
            "deduped_count": 2,
            "rejected_count": 0,
            "provider": {"lane": "text_assist", "configured": True},
            "candidates": [
                {
                    "copy_set_id": "cs-1", "status": "COPY_REVIEW_REQUIRED",
                    "angle": "Value", "hook": "Hook", "subhook": "", "usp_set": ["A"], "cta": "Buy",
                    "dedupe_key": "key-1", "similarity_score": 0.12, "similar_to_copy_set_id": None,
                    "uniqueness_score": 0.88, "warnings": [],
                    "created": True, "dedupe_match": False,
                    "safety": {"safe": True, "violations": []},
                },
                {
                    "copy_set_id": "cs-2", "status": "COPY_REVIEW_REQUIRED",
                    "angle": "Value2", "hook": "Hook2", "subhook": "", "usp_set": ["B"], "cta": "Buy2",
                    "dedupe_key": "key-2", "similarity_score": 0.85, "similar_to_copy_set_id": "cs-1",
                    "uniqueness_score": 0.15, "warnings": ["NEAR_DUPLICATE: 0.85 similar to cs-1"],
                    "created": True, "dedupe_match": False,
                    "safety": {"safe": True, "violations": []},
                },
            ],
            "ledger": {"batch_id": "batch-001", "source": "AI_COPY_ASSIST",
                       "requested_count": 5, "created_count": 3, "deduped_count": 2, "rejected_count": 0},
            "warnings": [{"code": "EXACT_DEDUPE_HIT", "count": 2}],
            "dry_run": False,
        }

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "prod-1", "requested_count": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"] == "batch-001"
    assert body["requested_count"] == 5
    assert body["created_count"] == 3
    assert body["deduped_count"] == 2
    assert "ledger" in body
    assert "warnings" in body
    assert len(body["candidates"]) >= 1
    # Per-candidate fields
    c = body["candidates"][0]
    assert "copy_set_id" in c
    assert "status" in c
    assert "angle" in c
    assert "hook" in c
    assert "similarity_score" in c
    assert "uniqueness_score" in c
    assert "warnings" in c


def test_generate_batch_dry_run_no_persist(monkeypatch):
    """dry_run=True returns simulated results without persistence."""
    async def fake_batch(request):
        return {
            "batch_id": "dry-batch",
            "product_id": "prod-1",
            "requested_count": 3,
            "created_count": 0,
            "deduped_count": 0,
            "rejected_count": 0,
            "provider": {"lane": "text_assist", "configured": True},
            "candidates": [
                {"copy_set_id": None, "status": "DRY_RUN", "angle": "", "hook": "",
                 "subhook": "", "usp_set": [], "cta": "", "dedupe_key": "",
                 "similarity_score": None, "similar_to_copy_set_id": None,
                 "uniqueness_score": None, "warnings": ["DRY_RUN_NO_PERSIST"],
                 "created": False, "dedupe_match": False,
                 "safety": {"safe": True, "violations": []}},
            ],
            "ledger": {"batch_id": "dry-batch", "source": "AI_COPY_ASSIST",
                       "requested_count": 3, "created_count": 0, "deduped_count": 0, "rejected_count": 0},
            "warnings": [],
            "dry_run": True,
        }

    monkeypatch.setattr(ai_svc, "generate_ai_copy_candidates_batch", fake_batch)
    response = _client().post(
        "/api/copy-sets/generate-batch",
        json={"product_id": "prod-1", "requested_count": 3, "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["created_count"] == 0
