"""API-level proof that both workspace routes thread the WPS chaining params
from the request model into the service layer.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_prompt_compile_route_passes_engine_duration_target(monkeypatch):
    captured = {}

    async def fake_preview(**kwargs):
        captured.update(kwargs)
        return {"final_compiled_prompt_text": "ok", "resolved_block_chain": [8, 8, 8]}

    monkeypatch.setattr(
        "agent.api.workspace_packages.compile_workspace_prompt_preview", fake_preview
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/ugc-video-prompt-compile",
        json={
            "product_id": "prod-001",
            "mode": "F2V",
            "engine_duration_target": "GOOGLE_FLOW",
            "requested_total_duration_seconds": 24,
        },
    )

    assert response.status_code == 200
    assert captured["engine_duration_target"] == "GOOGLE_FLOW"
    assert captured["requested_total_duration_seconds"] == 24
    assert response.json()["resolved_block_chain"] == [8, 8, 8]


def test_execution_package_route_passes_engine_duration_target(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"workspace_execution_package_id": "wep_1", "blockers": []}

    monkeypatch.setattr(
        "agent.api.workspace_packages.create_workspace_execution_package", fake_create
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/execution-package",
        json={
            "product_id": "prod-001",
            "mode": "F2V",
            "engine_duration_target": "GROK",
            "requested_total_duration_seconds": 16,
        },
    )

    assert response.status_code == 200
    assert captured["engine_duration_target"] == "GROK"
    assert captured["requested_total_duration_seconds"] == 16


def test_routes_default_new_params_to_none_for_old_clients(monkeypatch):
    captured = {}

    async def fake_preview(**kwargs):
        captured.update(kwargs)
        return {"final_compiled_prompt_text": "ok"}

    monkeypatch.setattr(
        "agent.api.workspace_packages.compile_workspace_prompt_preview", fake_preview
    )

    client = TestClient(_build_app())
    # Old client payload — no WPS fields.
    response = client.post(
        "/api/workspace/ugc-video-prompt-compile",
        json={"product_id": "prod-001", "mode": "F2V"},
    )

    assert response.status_code == 200
    assert captured["engine_duration_target"] is None
    assert captured["requested_total_duration_seconds"] is None
