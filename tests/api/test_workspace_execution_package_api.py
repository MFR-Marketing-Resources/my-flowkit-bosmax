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
            "prompt_text": "Block 1 (ANCHOR)\nCompiled prompt",
            "prompt_fingerprint": "fp_123",
            "asset_slots": [],
            "resolved_assets": [],
            "readiness": "READY",
            "execution_allowed": True,
            "manual_fallback": {"copy_prompt_available": True},
            "blockers": [],
            "request_lineage_payload": {"product_id": kwargs["product_id"]},
            "source_of_truth_notes": [],
            "generation_mode": kwargs["generation_mode"],
            "camera_style": kwargs["camera_style"],
            "character_presence": kwargs["character_presence"],
        }

    monkeypatch.setattr("agent.api.workspace_packages.create_workspace_execution_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/execution-package",
        json={
            "product_id": "prod-001",
            "mode": "T2V",
            "generation_mode": "SINGLE",
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
        },
    )

    assert response.status_code == 200
    assert response.json()["workspace_execution_package_id"] == "wep_123"
    assert response.json()["generation_mode"] == "SINGLE"


def test_workspace_execution_package_api_lists_packages(monkeypatch):
    async def fake_list(**kwargs):
        return [{"workspace_execution_package_id": "wep_123", "mode": "IMG"}]

    monkeypatch.setattr("agent.api.workspace_packages.list_workspace_execution_packages", fake_list)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/execution-packages?product_id=prod-001&mode=IMG")

    assert response.status_code == 200
    assert response.json()[0]["mode"] == "IMG"


def test_workspace_package_readiness_api_returns_mode_items(monkeypatch):
    async def fake_readiness(product_id, mode):
        return {
            "product_id": product_id,
            "product_name": "Bosmax Herbs 5 ML",
            "mode": mode,
            "readiness_status": "READY",
            "blocker": None,
            "detail": "F2V package is eligible to load.",
            "checklist": [],
            "quick_actions": {
                "smart_registration_path": "/product-registration",
                "approved_packages_path": "/approved-packages",
                "products_path": "/products",
            },
        }

    monkeypatch.setattr("agent.api.workspace_packages.get_product_package_readiness", fake_readiness)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/package-readiness",
        json={"mode": "F2V", "product_ids": ["prod-001", "prod-002"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "F2V"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["readiness_status"] == "READY"
