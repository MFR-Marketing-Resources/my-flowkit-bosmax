"""HTTP proof for the Copy Register V2 cross-product review queue."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_bulk import router
from agent.services import copy_register_review_queue_service as service


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_review_queue_get_forwards_filters_and_is_provider_free(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_list_review_queue(**kwargs):
        captured.update(kwargs)
        return {
            "items": [],
            "total": 0,
            "filters": kwargs,
            "provider_calls": 0,
            "credit_spend": 0,
            "activation_mutations": 0,
        }

    monkeypatch.setattr(service, "list_review_queue", fake_list_review_queue)
    response = _client().get(
        "/api/copy-register/v2/bulk/review-queue"
        "?only_claim_safe=true&product_id=product-001"
    )

    assert response.status_code == 200
    assert captured == {"only_claim_safe": True, "product_id": "product-001"}
    assert response.json()["provider_calls"] == 0
    assert response.json()["activation_mutations"] == 0


def test_review_queue_approve_returns_per_item_results(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_batch_approve(blueprint_ids, **kwargs):
        captured["blueprint_ids"] = blueprint_ids
        captured.update(kwargs)
        return {
            "results": [
                {
                    "blueprint_id": "bp-001",
                    "status": "APPROVED",
                    "production_status": "PRODUCTION_VALID",
                }
            ],
            "approved_count": 1,
            "failed_count": 0,
            "automatic_approval": False,
            "activation_mutations": 0,
            "provider_calls": 0,
            "credit_spend": 0,
        }

    monkeypatch.setattr(service, "batch_approve_drafts", fake_batch_approve)
    response = _client().post(
        "/api/copy-register/v2/bulk/review-queue/approve",
        json={
            "blueprint_ids": ["bp-001"],
            "reviewer": "human-reviewer",
            "rationale": "Five gates reviewed against current Product Truth.",
            "readiness_proof": {
                "readiness_validated": True,
                "provenance_validated": True,
                "safety_validated": True,
                "bridge_validated": True,
                "duration_validated": True,
            },
            "confirmation_phrase": "APPROVE_COPY_DRAFTS_BATCH",
        },
    )

    assert response.status_code == 200
    assert captured["blueprint_ids"] == ["bp-001"]
    assert captured["reviewer"] == "human-reviewer"
    assert response.json()["results"][0]["production_status"] == "PRODUCTION_VALID"
    assert response.json()["automatic_approval"] is False


def test_review_queue_approve_maps_invalid_attestation_to_422(monkeypatch):
    async def reject_batch(*_args, **_kwargs):
        raise service.CopyRegisterReviewQueueError(
            "INVALID_CONFIRMATION_PHRASE",
            "The exact batch approval confirmation phrase is required.",
        )

    monkeypatch.setattr(service, "batch_approve_drafts", reject_batch)
    response = _client().post(
        "/api/copy-register/v2/bulk/review-queue/approve",
        json={
            "blueprint_ids": ["bp-001"],
            "reviewer": "human-reviewer",
            "rationale": "Rationale",
            "readiness_proof": {
                "readiness_validated": True,
                "provenance_validated": True,
                "safety_validated": True,
                "bridge_validated": True,
                "duration_validated": True,
            },
            "confirmation_phrase": "WRONG",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "INVALID_CONFIRMATION_PHRASE"


def test_activation_candidates_get_forwards_read_only_projection(monkeypatch):
    async def fake_list_activation_candidates():
        return {
            "items": [
                {
                    "blueprint_id": "bp-001",
                    "status": "PRODUCTION_VALID",
                    "activatable": True,
                    "current_authority_state": "NONE",
                    "required_lane_count": 8,
                }
            ],
            "total": 1,
            "max_batch_size": 50,
            "provider_calls": 0,
            "credit_spend": 0,
            "activation_mutations": 0,
        }

    monkeypatch.setattr(service, "list_activation_candidates", fake_list_activation_candidates)
    response = _client().get("/api/copy-register/v2/bulk/activation-candidates")

    assert response.status_code == 200
    assert response.json()["items"][0]["activatable"] is True
    assert response.json()["max_batch_size"] == 50
    assert response.json()["provider_calls"] == 0
    assert response.json()["credit_spend"] == 0
    assert response.json()["activation_mutations"] == 0


def test_activation_batch_post_forwards_owner_attestation_and_returns_per_item_results(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_batch_activate(blueprint_ids, **kwargs):
        captured["blueprint_ids"] = blueprint_ids
        captured.update(kwargs)
        return {
            "results": [
                {
                    "blueprint_id": "bp-001",
                    "status": "ACTIVATED",
                    "activated": True,
                    "idempotent": False,
                    "lane_count": 8,
                    "error_code": None,
                }
            ],
            "activated_count": 1,
            "idempotent_count": 0,
            "failed_count": 0,
            "activation_mutations": 1,
            "bound_lane_count": 8,
            "automatic_approval": False,
            "provider_calls": 0,
            "credit_spend": 0,
        }

    monkeypatch.setattr(service, "batch_activate", fake_batch_activate)
    response = _client().post(
        "/api/copy-register/v2/bulk/activate",
        json={
            "blueprint_ids": ["bp-001"],
            "confirmation_phrase": "ACTIVATE_COPY_AUTHORITY_BATCH",
            "owner_authorization": True,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "blueprint_ids": ["bp-001"],
        "confirmation_phrase": "ACTIVATE_COPY_AUTHORITY_BATCH",
        "owner_authorization": True,
    }
    assert response.json()["results"][0]["status"] == "ACTIVATED"
    assert response.json()["bound_lane_count"] == 8
    assert response.json()["provider_calls"] == 0
    assert response.json()["credit_spend"] == 0


def test_activation_batch_maps_owner_gate_to_422(monkeypatch):
    async def reject_batch(*_args, **_kwargs):
        raise service.CopyRegisterReviewQueueError(
            "OWNER_AUTHORIZATION_REQUIRED",
            "Explicit owner authorization is required for copy authority activation.",
        )

    monkeypatch.setattr(service, "batch_activate", reject_batch)
    response = _client().post(
        "/api/copy-register/v2/bulk/activate",
        json={
            "blueprint_ids": ["bp-001"],
            "confirmation_phrase": "ACTIVATE_COPY_AUTHORITY_BATCH",
            "owner_authorization": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "OWNER_AUTHORIZATION_REQUIRED"
