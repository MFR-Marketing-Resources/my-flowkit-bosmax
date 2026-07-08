"""API contract for bulk generation orchestrator."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.bulk_generation import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


_BASE = "/api/bulk-generation"


def test_create_avatar_bulk_maps_validation_error(monkeypatch):
    async def fake_create(*_args, **_kwargs):
        raise ValueError("NO_ELIGIBLE_AVATARS")

    monkeypatch.setattr(
        "agent.services.bulk_generation_service.create_avatar_image_bulk_run",
        fake_create,
    )
    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/avatar-images",
        json={"avatar_codes": ["X"]},
    )
    assert response.status_code == 422
    assert "NO_ELIGIBLE_AVATARS" in response.json()["detail"]


def test_get_bulk_run_not_found(monkeypatch):
    async def fake_detail(_id):
        return None

    monkeypatch.setattr(
        "agent.services.bulk_generation_service.get_bulk_run_detail",
        fake_detail,
    )
    client = TestClient(_build_app())
    response = client.get(f"{_BASE}/missing-id")
    assert response.status_code == 404


def test_list_runs_not_shadowed_by_id_route(monkeypatch):
    async def fake_list(limit=20):
        return [{"bulk_run_id": "abc", "status": "PENDING"}]

    monkeypatch.setattr("agent.db.crud.list_bulk_generation_runs", fake_list)
    client = TestClient(_build_app())
    response = client.get(f"{_BASE}/runs")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["runs"][0]["bulk_run_id"] == "abc"


def test_retry_failed_endpoint(monkeypatch):
    async def fake_retry(bulk_run_id):
        return {"bulk_run_id": bulk_run_id, "retried": 2, "status": "PENDING"}

    monkeypatch.setattr(
        "agent.services.bulk_generation_service.retry_failed_bulk_run",
        fake_retry,
    )
    client = TestClient(_build_app())
    response = client.post(f"{_BASE}/run-xyz/retry-failed")
    assert response.status_code == 200
    assert response.json()["retried"] == 2


def test_start_requires_confirm_credit(monkeypatch):
    async def fake_start(bulk_run_id, *, confirm_credit_burn=False, dry_run=False):
        if not confirm_credit_burn:
            return {"dry_run": True, "confirm_credit_burn_required": True}
        return {"status": "RUNNING"}

    monkeypatch.setattr(
        "agent.services.bulk_generation_service.start_bulk_run",
        fake_start,
    )
    client = TestClient(_build_app())
    response = client.post(f"{_BASE}/run-1/start", json={"confirm_credit_burn": False})
    assert response.status_code == 200
    assert response.json()["dry_run"] is True