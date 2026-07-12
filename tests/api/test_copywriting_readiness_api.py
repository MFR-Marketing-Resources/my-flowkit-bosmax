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


def test_readiness_route_rejects_fastmoss_reference_before_service(monkeypatch):
    async def unexpected_service_call(product_id: str):
        raise AssertionError(f"reference-only id reached readiness service: {product_id}")

    monkeypatch.setattr(
        "agent.api.copywriting.get_copywriting_readiness",
        unexpected_service_call,
    )

    product_id = "fastmoss-ref:515b48d0d43fe085"
    resp = TestClient(app).get(f"/api/copywriting/readiness/{product_id}")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "REFERENCE_ONLY_PRODUCT"
    assert detail["detail"]["product_id"] == product_id
    assert detail["detail"]["conversion_instruction"] == (
        "Convert/Register this FastMoss reference before requesting copywriting readiness."
    )
