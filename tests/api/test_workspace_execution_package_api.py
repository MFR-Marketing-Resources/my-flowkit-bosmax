from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_workspace_execution_package_api_creates_package(monkeypatch):
    async def fake_create(**kwargs):
        return {
            "workspace_execution_package_id": "wep_123",
            "product_id": kwargs["product_id"],
            "mode": kwargs["mode"],
            "prompt_text": "Prompt",
            "prompt_fingerprint": "fp_123",
            "asset_slots": [],
            "resolved_assets": [],
            "readiness": "READY",
            "execution_allowed": True,
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "request_lineage_payload": {"product_id": kwargs["product_id"]},
            "source_of_truth_notes": [],
        }

    monkeypatch.setattr("agent.api.workspace_packages.create_workspace_execution_package", fake_create)

    client = TestClient(_build_app())
    response = client.post("/api/workspace/execution-package", json={"product_id": "prod-001", "mode": "T2V"})

    assert response.status_code == 200
    assert response.json()["workspace_execution_package_id"] == "wep_123"


def test_workspace_execution_package_api_lists_packages(monkeypatch):
    async def fake_list(**kwargs):
        return [{"workspace_execution_package_id": "wep_123", "mode": "IMG"}]

    monkeypatch.setattr("agent.api.workspace_packages.list_workspace_execution_packages", fake_list)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/execution-packages?product_id=prod-001&mode=IMG")

    assert response.status_code == 200
    assert response.json()[0]["mode"] == "IMG"
