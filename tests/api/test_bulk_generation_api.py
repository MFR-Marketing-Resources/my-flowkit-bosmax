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