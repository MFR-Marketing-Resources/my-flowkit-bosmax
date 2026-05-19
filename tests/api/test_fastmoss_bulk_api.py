"""
Tests for /api/fastmoss-bulk endpoints.
Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue: #92
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.fastmoss_bulk import router

_SVC = "agent.api.fastmoss_bulk._svc"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client():
    return TestClient(_build_app())


# ---------------------------------------------------------------------------
# GET /fastmoss-bulk/queue
# ---------------------------------------------------------------------------


def test_list_queue_default_params(client, monkeypatch):
    mock = AsyncMock(return_value={"items": [], "total": 0, "page": 1, "page_size": 50})
    monkeypatch.setattr(f"{_SVC}.list_bulk_queue", mock)
    r = client.get("/fastmoss-bulk/queue")
    assert r.status_code == 200
    mock.assert_awaited_once_with(
        promotion_status=None,
        claim_risk_level=None,
        image_readiness=None,
        category=None,
        q=None,
        page=1,
        page_size=50,
    )


def test_list_queue_with_filters(client, monkeypatch):
    mock = AsyncMock(return_value={"items": [], "total": 0, "page": 1, "page_size": 10})
    monkeypatch.setattr(f"{_SVC}.list_bulk_queue", mock)
    r = client.get(
        "/fastmoss-bulk/queue?promotion_status=READY_FOR_APPROVAL&claim_risk_level=LOW"
        "&image_readiness=IMAGE_PRESENT&category=Beauty&q=serum&page=2&page_size=10"
    )
    assert r.status_code == 200
    mock.assert_awaited_once_with(
        promotion_status="READY_FOR_APPROVAL",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        category="Beauty",
        q="serum",
        page=2,
        page_size=10,
    )


def test_list_queue_page_size_clamped(client, monkeypatch):
    monkeypatch.setattr(f"{_SVC}.list_bulk_queue", AsyncMock(return_value={}))
    r = client.get("/fastmoss-bulk/queue?page_size=999")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /fastmoss-bulk/queue/stats
# ---------------------------------------------------------------------------


def test_get_queue_stats(client, monkeypatch):
    expected = {"total": 42, "by_status": {"PENDING_DRAFT": 10}, "by_risk": {"LOW": 32}}
    monkeypatch.setattr(f"{_SVC}.get_queue_stats", AsyncMock(return_value=expected))
    r = client.get("/fastmoss-bulk/queue/stats")
    assert r.status_code == 200
    assert r.json() == expected


# ---------------------------------------------------------------------------
# POST /fastmoss-bulk/queue/sync
# ---------------------------------------------------------------------------


def test_sync_queue_no_body(client, monkeypatch):
    mock = AsyncMock(return_value={"synced": 10, "skipped": 0, "errors": []})
    monkeypatch.setattr(f"{_SVC}.sync_bulk_queue", mock)
    r = client.post("/fastmoss-bulk/queue/sync")
    assert r.status_code == 200
    mock.assert_awaited_once_with(batch_id=None)


def test_sync_queue_empty_catalog_200_shape(client, monkeypatch):
    """POST /queue/sync returns 200 with zero counts when catalog is empty."""
    mock = AsyncMock(return_value={
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "total_refs_loaded": 0,
        "synced_at": "2026-05-19T00:00:00Z",
    })
    monkeypatch.setattr(f"{_SVC}.sync_bulk_queue", mock)
    r = client.post("/fastmoss-bulk/queue/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] == 0
    assert body["total_refs_loaded"] == 0
    assert "synced_at" in body


def test_sync_queue_with_batch_id(client, monkeypatch):
    mock = AsyncMock(return_value={"synced": 5, "skipped": 2, "errors": []})
    monkeypatch.setattr(f"{_SVC}.sync_bulk_queue", mock)
    r = client.post("/fastmoss-bulk/queue/sync", json={"batch_id": "batch-abc-123"})
    assert r.status_code == 200
    mock.assert_awaited_once_with(batch_id="batch-abc-123")


# ---------------------------------------------------------------------------
# POST /fastmoss-bulk/queue/{reference_id}/create-draft
# ---------------------------------------------------------------------------


def test_create_draft_success(client, monkeypatch):
    payload = {"draft_id": "draft-xyz", "promotion_status": "READY_FOR_APPROVAL"}
    monkeypatch.setattr(f"{_SVC}.create_draft_from_reference", AsyncMock(return_value=payload))
    r = client.post("/fastmoss-bulk/queue/ref-001/create-draft")
    assert r.status_code == 200
    assert r.json()["draft_id"] == "draft-xyz"


def test_create_draft_not_in_queue(client, monkeypatch):
    monkeypatch.setattr(
        f"{_SVC}.create_draft_from_reference",
        AsyncMock(return_value={"error": "REFERENCE_NOT_IN_QUEUE"}),
    )
    r = client.post("/fastmoss-bulk/queue/nonexistent/create-draft")
    assert r.status_code == 404
    assert "REFERENCE_NOT_IN_QUEUE" in r.json()["detail"]


# ---------------------------------------------------------------------------
# POST /fastmoss-bulk/queue/bulk-create-drafts
# ---------------------------------------------------------------------------


def test_bulk_create_drafts_success(client, monkeypatch):
    result = {
        "results": [
            {"reference_id": "ref-1", "status": "DRAFT_CREATED", "draft_id": "d1"},
            {"reference_id": "ref-2", "status": "DRAFT_CREATED", "draft_id": "d2"},
        ]
    }
    monkeypatch.setattr(f"{_SVC}.bulk_create_drafts", AsyncMock(return_value=result))
    r = client.post("/fastmoss-bulk/queue/bulk-create-drafts", json={"reference_ids": ["ref-1", "ref-2"]})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2


def test_bulk_create_drafts_empty_list_rejected(client, monkeypatch):
    monkeypatch.setattr(f"{_SVC}.bulk_create_drafts", AsyncMock(return_value={}))
    r = client.post("/fastmoss-bulk/queue/bulk-create-drafts", json={"reference_ids": []})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /fastmoss-bulk/queue/bulk-approve-drafts
# ---------------------------------------------------------------------------


def test_bulk_approve_drafts_correct_phrase(client, monkeypatch):
    result = {
        "commit_status": "OK",
        "approved": ["ref-1"],
        "skipped": [],
        "errors": [],
    }
    monkeypatch.setattr(f"{_SVC}.bulk_approve_drafts", AsyncMock(return_value=result))
    r = client.post(
        "/fastmoss-bulk/queue/bulk-approve-drafts",
        json={
            "reference_ids": ["ref-1"],
            "confirmation_phrase": "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
        },
    )
    assert r.status_code == 200
    assert r.json()["commit_status"] == "OK"


def test_bulk_approve_drafts_wrong_phrase_returns_403(client, monkeypatch):
    monkeypatch.setattr(
        f"{_SVC}.bulk_approve_drafts",
        AsyncMock(
            return_value={
                "commit_status": "BLOCKED",
                "error": "INVALID_CONFIRMATION_PHRASE",
            }
        ),
    )
    r = client.post(
        "/fastmoss-bulk/queue/bulk-approve-drafts",
        json={
            "reference_ids": ["ref-1"],
            "confirmation_phrase": "WRONG_PHRASE",
        },
    )
    assert r.status_code == 403
    assert "INVALID_CONFIRMATION_PHRASE" in r.json()["detail"]


def test_bulk_approve_drafts_empty_list_rejected(client, monkeypatch):
    monkeypatch.setattr(f"{_SVC}.bulk_approve_drafts", AsyncMock(return_value={}))
    r = client.post(
        "/fastmoss-bulk/queue/bulk-approve-drafts",
        json={"reference_ids": [], "confirmation_phrase": "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /fastmoss-bulk/queue/{reference_id}/status
# ---------------------------------------------------------------------------


def test_update_queue_row_status_success(client, monkeypatch):
    monkeypatch.setattr(
        f"{_SVC}.update_queue_row_status",
        AsyncMock(return_value={"reference_id": "ref-1", "promotion_status": "REJECTED"}),
    )
    r = client.patch("/fastmoss-bulk/queue/ref-1/status", json={"promotion_status": "REJECTED"})
    assert r.status_code == 200
    assert r.json()["promotion_status"] == "REJECTED"


def test_update_queue_row_status_not_found(client, monkeypatch):
    monkeypatch.setattr(
        f"{_SVC}.update_queue_row_status",
        AsyncMock(return_value={"error": "NOT_IN_QUEUE"}),
    )
    r = client.patch("/fastmoss-bulk/queue/ghost/status", json={"promotion_status": "REJECTED"})
    assert r.status_code == 404


def test_update_queue_row_status_invalid_transition(client, monkeypatch):
    monkeypatch.setattr(
        f"{_SVC}.update_queue_row_status",
        AsyncMock(return_value={"error": "INVALID_STATUS_TRANSITION"}),
    )
    r = client.patch("/fastmoss-bulk/queue/ref-1/status", json={"promotion_status": "INVALID_X"})
    assert r.status_code == 422
