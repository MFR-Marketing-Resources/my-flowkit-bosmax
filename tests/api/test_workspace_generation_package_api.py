"""API tests — workspace_generation_package endpoints."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_generation_packages import router


FAKE_PKG = {
    "workspace_generation_package_id": "wgp_test_001",
    "mode": "F2V",
    "product_id": "prod-001",
    "product_name_snapshot": "Test Product",
    "source_lane": "F2V",
    "prompt_package_snapshot_id": "pkg_001",
    "workspace_execution_package_id": None,
    "generation_mode": "SINGLE",
    "final_prompt_text": "Block 1 (ANCHOR)\nTest prompt.",
    "prompt_blocks_json": [],
    "selected_assets_json": {},
    "resolved_engine_slots_json": {},
    "resolver_output_json": {},
    "image_assets_json": {},
    "manual_handoff_json": {
        "copy_prompt_available": True,
        "final_prompt_text": "Test prompt.",
        "upload_order": ["start_frame"],
        "actions": [],
        "blockers": [],
        "warnings": [],
        "manual_fallback_ready": True,
        "dom_handoff_note": "DOM handoff not enabled in this wave.",
    },
    "dom_handoff_payload_json": {
        "mode": "F2V",
        "lineage": {},
        "prompt": {},
        "assets": {},
        "settings": {},
        "semantic_resolution": {},
        "manual_handoff": {"upload_order": ["start_frame"]},
        "readiness": {
            "manual_handoff_ready": True,
            "dom_handoff_ready": False,
            "blockers": [],
            "warnings": [],
        },
    },
    "blockers_json": [],
    "warnings_json": [],
    "status": "READY_MANUAL",
    "created_at": "2026-05-19T00:00:00Z",
    "updated_at": "2026-05-19T00:00:00Z",
}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


# ─── List packages ────────────────────────────────────────────

def test_list_packages_returns_empty_list(monkeypatch):
    async def fake_list(**kwargs):
        return []

    monkeypatch.setattr("agent.api.workspace_generation_packages.list_workspace_generation_packages", fake_list)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/generation-packages")
    assert response.status_code == 200
    data = response.json()
    assert data["packages"] == []
    assert data["count"] == 0


def test_list_packages_filters_by_mode(monkeypatch):
    captured_filter = {}

    async def fake_list(mode=None, status=None, product_id=None, batch_run_id=None, limit=50):
        captured_filter["mode"] = mode
        return [FAKE_PKG]

    monkeypatch.setattr("agent.api.workspace_generation_packages.list_workspace_generation_packages", fake_list)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/generation-packages?mode=F2V")
    assert response.status_code == 200
    assert captured_filter["mode"] == "F2V"
    assert len(response.json()["packages"]) == 1


def test_list_packages_filters_by_status(monkeypatch):
    captured_filter = {}

    async def fake_list(mode=None, status=None, product_id=None, batch_run_id=None, limit=50):
        captured_filter["status"] = status
        return []

    monkeypatch.setattr("agent.api.workspace_generation_packages.list_workspace_generation_packages", fake_list)

    client = TestClient(_build_app())
    client.get("/api/workspace/generation-packages?status=BLOCKED")
    assert captured_filter["status"] == "BLOCKED"


def test_list_packages_filters_by_product_id(monkeypatch):
    captured = {}

    async def fake_list(mode=None, status=None, product_id=None, batch_run_id=None, limit=50):
        captured["product_id"] = product_id
        return []

    monkeypatch.setattr("agent.api.workspace_generation_packages.list_workspace_generation_packages", fake_list)

    client = TestClient(_build_app())
    client.get("/api/workspace/generation-packages?product_id=prod-001")
    assert captured["product_id"] == "prod-001"


# ─── Create F2V package ───────────────────────────────────────

def test_create_f2v_package(monkeypatch):
    async def fake_create(**kwargs):
        assert kwargs["product_id"] == "prod-001"
        assert kwargs["generation_mode"] == "SINGLE"
        return {**FAKE_PKG, "mode": "F2V"}

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_f2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/f2v",
        json={"product_id": "prod-001", "generation_mode": "SINGLE"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "F2V"
    assert data["workspace_generation_package_id"] == "wgp_test_001"


def test_create_f2v_package_forwards_source_mode(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {**FAKE_PKG, "mode": "F2V", "source_lane": "HYBRID"}

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_f2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/f2v",
        json={"product_id": "prod-001", "source_mode": "HYBRID"},
    )
    assert response.status_code == 200
    assert captured["source_mode"] == "HYBRID"


def test_create_f2v_package_with_start_frame(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {**FAKE_PKG, "mode": "F2V"}

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_f2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/f2v",
        json={
            "product_id": "prod-001",
            "start_frame_asset_id": "custom_asset_001",
            "start_frame_preview_url": "/custom/preview.jpg",
            "start_frame_download_url": "/custom/download.jpg",
        },
    )
    assert response.status_code == 200
    assert captured["start_frame_asset_id"] == "custom_asset_001"


# ─── Create I2V package ───────────────────────────────────────

def test_create_i2v_package(monkeypatch):
    async def fake_create(**kwargs):
        assert kwargs["product_id"] == "prod-001"
        assert kwargs["recipe_id"] == "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
        return {**FAKE_PKG, "mode": "I2V", "source_lane": "I2V"}

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_i2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/i2v",
        json={"product_id": "prod-001"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "I2V"


# ─── Get package detail ───────────────────────────────────────

def test_get_package_detail(monkeypatch):
    async def fake_get(wgp_id):
        if wgp_id == "wgp_test_001":
            return FAKE_PKG
        return None

    monkeypatch.setattr("agent.api.workspace_generation_packages.get_workspace_generation_package", fake_get)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/generation-packages/wgp_test_001")
    assert response.status_code == 200
    assert response.json()["workspace_generation_package_id"] == "wgp_test_001"


def test_get_package_detail_not_found(monkeypatch):
    async def fake_get(wgp_id):
        return None

    monkeypatch.setattr("agent.api.workspace_generation_packages.get_workspace_generation_package", fake_get)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/generation-packages/nonexistent")
    assert response.status_code == 404


# ─── DOM readiness is false ───────────────────────────────────

def test_create_f2v_dom_readiness_false(monkeypatch):
    async def fake_create(**kwargs):
        pkg = dict(FAKE_PKG)
        pkg["dom_handoff_payload_json"] = {
            "readiness": {
                "manual_handoff_ready": True,
                "dom_handoff_ready": False,
                "blockers": [],
                "warnings": [],
            }
        }
        return pkg

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_f2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/f2v",
        json={"product_id": "prod-001"},
    )
    assert response.status_code == 200
    dom = response.json()["dom_handoff_payload_json"]
    assert dom["readiness"]["dom_handoff_ready"] is False


def test_create_i2v_dom_readiness_false(monkeypatch):
    async def fake_create(**kwargs):
        pkg = dict(FAKE_PKG)
        pkg["mode"] = "I2V"
        pkg["dom_handoff_payload_json"] = {
            "readiness": {
                "manual_handoff_ready": True,
                "dom_handoff_ready": False,
                "blockers": [],
                "warnings": [],
            }
        }
        return pkg

    monkeypatch.setattr("agent.api.workspace_generation_packages.create_i2v_generation_package", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/generation-packages/i2v",
        json={"product_id": "prod-001"},
    )
    assert response.status_code == 200
    dom = response.json()["dom_handoff_payload_json"]
    assert dom["readiness"]["dom_handoff_ready"] is False


# ─── Manual handoff payload ───────────────────────────────────

def test_f2v_manual_handoff_payload_available(monkeypatch):
    async def fake_get(wgp_id):
        return FAKE_PKG

    monkeypatch.setattr("agent.api.workspace_generation_packages.get_workspace_generation_package", fake_get)

    client = TestClient(_build_app())
    response = client.get("/api/workspace/generation-packages/wgp_test_001")
    assert response.status_code == 200
    handoff = response.json()["manual_handoff_json"]
    assert handoff["copy_prompt_available"] is True
    assert handoff["upload_order"] == ["start_frame"]
    assert "DOM handoff not enabled" in handoff["dom_handoff_note"]
