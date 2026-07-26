"""Round 3 owner-review HTTP contract tests."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router
from agent.services import scene_context_promotion_review_service as review_svc


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.mark.parametrize(
    ("code", "status"),
    (
        ("PRODUCT_NOT_FOUND", 404),
        ("STALE_CANDIDATE_FINGERPRINT", 409),
        ("PRODUCT_CLUSTER_REVIEW_REQUIRED", 422),
        ("UNKNOWN_SOURCE_TEMPLATE", 422),
        ("PRODUCT_TEMPLATE_MISMATCH", 422),
        ("CANDIDATE_QUARANTINED", 422),
        ("CANDIDATE_NOT_CURRENTLY_PROMOTABLE", 422),
        ("INVALID_REVIEW_DECISION", 422),
        ("INVALID_REVIEW_BATCH", 422),
    ),
)
def test_review_error_codes_have_explicit_http_status(monkeypatch, code, status):
    async def fail(*_args, **_kwargs):
        raise review_svc.ReviewError(code)

    monkeypatch.setattr(review_svc, "record_reviews", fail)
    response = TestClient(_app()).post(
        "/api/creative-intelligence/scene-context-promotion/review",
        json={
            "reviewed_via_product_id": "p1",
            "source_template_id": "SCN-BEAUTY-01",
            "candidate_fingerprint": "fp",
            "decision": "PENDING",
        },
    )

    assert response.status_code == status
    assert response.json()["detail"] == code


def test_bulk_review_uses_single_outer_product_authority_and_typed_items(monkeypatch):
    captured = {}

    async def record(product_id, items):
        captured["product_id"] = product_id
        captured["items"] = items
        return {"dry_run": True, "registry_mutations": 0}

    monkeypatch.setattr(review_svc, "record_reviews", record)
    response = TestClient(_app()).post(
        "/api/creative-intelligence/scene-context-promotion/review/bulk",
        json={
            "reviewed_via_product_id": "p1",
            "items": [{
                "source_template_id": "SCN-BEAUTY-01",
                "candidate_fingerprint": "fp",
                "decision": "PENDING",
                "reviewer_note": "owner review",
            }],
        },
    )

    assert response.status_code == 200
    assert captured == {
        "product_id": "p1",
        "items": [{
            "source_template_id": "SCN-BEAUTY-01",
            "candidate_fingerprint": "fp",
            "decision": "PENDING",
            "reviewer_note": "owner review",
        }],
    }
