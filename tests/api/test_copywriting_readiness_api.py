"""GET /api/copywriting/readiness/{product_id} — route wiring + fail-closed 404."""
from fastapi.testclient import TestClient

from agent.main import app

_URL = "/api/copywriting/readiness/p1"


def test_readiness_route_200(monkeypatch):
    async def fake(product_id: str):
        return {
            "product_id": product_id,
            "product_intelligence_status": "APPROVED_SNAPSHOT_AVAILABLE",
            "has_approved_snapshot": True,
            "ready_for_generation": True,
            "recommended_next_action": "READY",
        }

    monkeypatch.setattr("agent.api.copywriting.get_copywriting_readiness", fake)
    resp = TestClient(app).get(_URL)
    assert resp.status_code == 200
    assert resp.json()["ready_for_generation"] is True


def test_readiness_route_404(monkeypatch):
    from agent.services.copy_set_service import CopySetError

    async def fake(product_id: str):
        raise CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": product_id})

    monkeypatch.setattr("agent.api.copywriting.get_copywriting_readiness", fake)
    resp = TestClient(app).get("/api/copywriting/readiness/missing")
    assert resp.status_code == 404
