"""Faceless prepare API — runtime path uses faceless_lane_service (not test-only)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.faceless import router as faceless_router


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(faceless_router, prefix="/api")
    return TestClient(app)


def test_prepare_rejects_missing_product(client: TestClient) -> None:
    r = client.post(
        "/api/faceless/prepare",
        json={
            "product_id": "",
            "start_frame_asset_id": "sf1",
            "hook_id": "AUTO",
            "background_id": "AUTO",
        },
    )
    assert r.status_code == 422
    body = r.json()
    detail = body.get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error_code") == "ERR_FACELESS_PRODUCT_REQUIRED"


def test_prepare_rejects_missing_start_frame(client: TestClient) -> None:
    r = client.post(
        "/api/faceless/prepare",
        json={
            "product_id": "p1",
            "start_frame_asset_id": "",
            "hook_id": "AUTO",
            "background_id": "AUTO",
        },
    )
    assert r.status_code == 422
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("error_code") == "ERR_FACELESS_START_FRAME_REQUIRED"


def test_prepare_resolves_auto_before_package(client: TestClient) -> None:
    fake_pkg = {
        "workspace_execution_package_id": "wep-1",
        "prompt_text": "resolved environment intent in prompt",
        "prompt_fingerprint": "fp1",
    }
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
        return_value=fake_pkg,
    ) as mock_create:
        r = client.post(
            "/api/faceless/prepare",
            json={
                "product_id": "p1",
                "start_frame_asset_id": "sf1",
                "hook_id": "AUTO",
                "background_id": "AUTO",
                "copy_fallback_confirmed": True,
            },
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    hook = data["resolution"]["hook"]
    bg = data["resolution"]["background"]
    # AUTO must not remain as engine-facing setting_id
    assert hook["operator_selection"] == "AUTO"
    assert hook["setting_id"] != "AUTO"
    assert hook["setting_id"] == "GENERAL_USP_PRODUCT"
    assert bg["operator_selection"] == "AUTO"
    assert bg["setting_id"] != "AUTO"
    ctx = data["scene_context_override"] or ""
    assert "AUTO (AI decided)" not in ctx
    assert "Auto (AI decided)" not in ctx
    # package factory received RESOLVED scene context, not raw AUTO label
    kwargs = mock_create.await_args.kwargs
    assert kwargs["mode"] == "F2V"
    assert kwargs["source_mode"] == "FRAMES"
    assert kwargs["character_presence"] == "FACELESS"
    assert kwargs["start_frame_asset_id"] == "sf1"
    assert "AUTO (AI decided)" not in (kwargs.get("scene_context_override") or "")
    assert kwargs["scene_context_override"]
    assert data["package"]["workspace_execution_package_id"] == "wep-1"


def test_validate_preview_no_package_write(client: TestClient) -> None:
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
    ) as mock_create:
        r = client.post(
            "/api/faceless/validate",
            json={
                "product_id": "p1",
                "start_frame_asset_id": "sf1",
                "hook_id": "AUTO",
                "background_id": "PHARMACY",
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["resolution"]["background"]["setting_id"] == "PHARMACY"
    mock_create.assert_not_awaited()
