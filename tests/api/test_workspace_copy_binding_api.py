"""API contract tests for Copy Set binding on the workspace prompt routes
(Copy Selection & Compiler Binding Foundation V1).

Asserts that both the preview and final-package routes accept copy_set_id, thread
it to the service, and map CopyBindingError to a fail-closed HTTP response.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router
from agent.services.copy_binding_service import CopyBindingError


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_execution_package_route_forwards_copy_set_id(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"workspace_execution_package_id": "wep_1", "copy_binding": {"copy_set_id": kwargs["copy_set_id"]}}

    monkeypatch.setattr(
        "agent.api.workspace_packages.create_workspace_execution_package", fake_create
    )
    response = _client().post(
        "/api/workspace/execution-package",
        json={"product_id": "prod-1", "mode": "T2V", "copy_set_id": "cs-approved"},
    )
    assert response.status_code == 200
    assert captured["copy_set_id"] == "cs-approved"


def test_preview_route_forwards_copy_set_id(monkeypatch):
    captured = {}

    async def fake_compile(**kwargs):
        captured.update(kwargs)
        return {"final_compiled_prompt_text": "clean", "copy_binding": {"copy_set_id": kwargs["copy_set_id"]}}

    monkeypatch.setattr(
        "agent.api.workspace_packages.compile_workspace_prompt_preview", fake_compile
    )
    response = _client().post(
        "/api/workspace/ugc-video-prompt-compile",
        json={"product_id": "prod-1", "mode": "T2V", "copy_set_id": "cs-approved"},
    )
    assert response.status_code == 200
    assert captured["copy_set_id"] == "cs-approved"


def test_execution_package_route_maps_binding_error_fail_closed(monkeypatch):
    async def fake_create(**kwargs):
        raise CopyBindingError("COPY_SET_NOT_APPROVED", status_code=409, detail={"status": "DRAFT_COPY"})

    monkeypatch.setattr(
        "agent.api.workspace_packages.create_workspace_execution_package", fake_create
    )
    response = _client().post(
        "/api/workspace/execution-package",
        json={"product_id": "prod-1", "mode": "T2V", "copy_set_id": "cs-draft"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "COPY_SET_NOT_APPROVED"


def test_preview_route_maps_binding_error_fail_closed(monkeypatch):
    async def fake_compile(**kwargs):
        raise CopyBindingError("COPY_SET_PRODUCT_MISMATCH", status_code=409, detail={})

    monkeypatch.setattr(
        "agent.api.workspace_packages.compile_workspace_prompt_preview", fake_compile
    )
    response = _client().post(
        "/api/workspace/ugc-video-prompt-compile",
        json={"product_id": "prod-2", "mode": "T2V", "copy_set_id": "cs-other-product"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "COPY_SET_PRODUCT_MISMATCH"


def test_preview_route_missing_copy_set_returns_404(monkeypatch):
    async def fake_compile(**kwargs):
        raise CopyBindingError("COPY_SET_NOT_FOUND", status_code=404, detail={})

    monkeypatch.setattr(
        "agent.api.workspace_packages.compile_workspace_prompt_preview", fake_compile
    )
    response = _client().post(
        "/api/workspace/ugc-video-prompt-compile",
        json={"product_id": "prod-1", "mode": "T2V", "copy_set_id": "ghost"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "COPY_SET_NOT_FOUND"
