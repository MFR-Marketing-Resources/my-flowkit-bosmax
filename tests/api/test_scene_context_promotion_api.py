"""Round 2 read-only scene context promotion API contracts."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_preview_endpoint_delegates_cluster_without_writing(monkeypatch):
    captured = {}

    def fake_preview(cluster=None):
        captured["cluster"] = cluster
        return {"dry_run": True, "candidate_count": 1, "candidates": []}

    monkeypatch.setattr(
        "agent.services.scene_context_promotion_service.preview_scene_context_promotion",
        fake_preview,
    )

    response = TestClient(_app()).get(
        "/api/creative-intelligence/scene-context-promotion/preview",
        params={"cluster": "Beauty"},
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert captured == {"cluster": "Beauty"}


def test_quarantine_endpoint_delegates_cluster(monkeypatch):
    captured = {}

    def fake_quarantine(cluster=None):
        captured["cluster"] = cluster
        return {"dry_run": True, "quarantine": []}

    monkeypatch.setattr(
        "agent.services.scene_context_promotion_service.preview_quarantine",
        fake_quarantine,
    )

    response = TestClient(_app()).get(
        "/api/creative-intelligence/scene-context-promotion/quarantine"
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert captured == {"cluster": None}
