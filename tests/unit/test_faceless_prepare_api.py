"""Faceless prepare API — product-first + model/duration propagation."""
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


def _base_body(**extra):
    body = {
        "product_id": "p1",
        "hook_id": "AUTO",
        "background_id": "AUTO",
        "model": "Veo 3.1 - Lite",
        "generation_mode": "SINGLE",
        "duration_seconds": 8,
        "copy_fallback_confirmed": True,
    }
    body.update(extra)
    return body


def test_prepare_rejects_missing_product(client: TestClient) -> None:
    r = client.post("/api/faceless/prepare", json=_base_body(product_id=""))
    assert r.status_code == 422


def test_prepare_rejects_missing_model(client: TestClient) -> None:
    r = client.post(
        "/api/faceless/prepare",
        json={
            "product_id": "p1",
            "hook_id": "AUTO",
            "background_id": "AUTO",
            "model": "",
            "generation_mode": "SINGLE",
            "duration_seconds": 8,
        },
    )
    assert r.status_code == 422


def test_prepare_product_only_no_start_frame(client: TestClient) -> None:
    fake_pkg = {
        "workspace_execution_package_id": "wep-1",
        "execution_allowed": True,
        "prompt_text": "resolved environment intent in prompt",
        "prompt_fingerprint": "fp1",
        "asset_slots": [
            {
                "slot_key": "start_frame",
                "resolved_asset": {
                    "asset_id": "product-image:p1:start_frame",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_IMAGE_CACHE",
                    "media_id": "media-p1",
                    "download_url": "https://cdn.example/p1.png",
                },
            }
        ],
    }
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
        return_value=fake_pkg,
    ) as mock_create:
        r = client.post("/api/faceless/prepare", json=_base_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["generation_mode"] == "SINGLE"
    assert data["model"] == "Veo 3.1 - Lite"
    assert data["character_presence"] == "FACELESS"
    assert data["avatar_id"] is None
    assert "no visible human face" in (data.get("visual_law") or "").lower()
    hook = data["resolution"]["hook"]
    assert hook["operator_selection"] == "AUTO"
    assert hook["setting_id"] != "AUTO"
    ctx = data["scene_context_override"] or ""
    assert "AUTO (AI decided)" not in ctx
    assert "VISUAL LAW" in ctx

    kwargs = mock_create.await_args.kwargs
    assert kwargs["mode"] == "F2V"
    assert kwargs["source_mode"] == "HYBRID"
    assert kwargs["character_presence"] == "FACELESS"
    assert kwargs["avatar_id"] is None
    assert kwargs["start_frame_asset_id"] is None
    assert kwargs["model"] == "Veo 3.1 - Lite"
    assert kwargs["duration_seconds"] == 8
    assert "VISUAL LAW" in (kwargs.get("scene_context_override") or "")


def test_prepare_extend_keeps_durable_multiblock_package_lineage(
    client: TestClient,
) -> None:
    fake_pkg = {
        "workspace_execution_package_id": "wep-e",
        "execution_allowed": True,
        "prompt_text": "x",
        "asset_slots": [
            {
                "slot_key": "start_frame",
                "resolved_asset": {
                    "asset_id": "product-image:p1:start_frame",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_IMAGE_CACHE",
                    "media_id": "media-p1",
                    "download_url": "https://cdn.example/p1.png",
                },
            }
        ],
    }
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
        return_value=fake_pkg,
    ) as mock_create:
        r = client.post(
            "/api/faceless/prepare",
            json=_base_body(
                generation_mode="EXTEND",
                duration_seconds=None,
                total_duration_seconds=16,
                model="Veo 3.1 - Lite",
            ),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["durable_lifecycle"]["plan"].endswith("/video-jobs/plan")
    assert data["durable_lifecycle"]["total_duration_seconds"] == 16
    kwargs = mock_create.await_args.kwargs
    assert kwargs["duration_seconds"] == 8
    assert kwargs["generation_mode"] == "EXTEND"
    assert kwargs["requested_total_duration_seconds"] == 16
    assert kwargs["model"] == "Veo 3.1 - Lite"


def test_prepare_propagates_omni_flash_duration(client: TestClient) -> None:
    fake_pkg = {
        "workspace_execution_package_id": "wep-o",
        "execution_allowed": True,
        "prompt_text": "x",
        "asset_slots": [
            {
                "slot_key": "start_frame",
                "resolved_asset": {
                    "asset_id": "product-image:p1:start_frame",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_IMAGE_CACHE",
                    "media_id": "media-p1",
                    "download_url": "https://cdn.example/p1.png",
                },
            }
        ],
    }
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
        return_value=fake_pkg,
    ) as mock_create:
        r = client.post(
            "/api/faceless/prepare",
            json=_base_body(model="Omni Flash", duration_seconds=8),
        )
    assert r.status_code == 200, r.text
    kwargs = mock_create.await_args.kwargs
    assert kwargs["model"] == "Omni Flash"
    assert kwargs["duration_seconds"] == 8


def test_prepare_rejects_unknown_model_or_unsupported_duration(client: TestClient) -> None:
    unknown = client.post(
        "/api/faceless/prepare",
        json=_base_body(model="Not A Flow Model", duration_seconds=8),
    )
    assert unknown.status_code == 422

    unsupported = client.post(
        "/api/faceless/prepare",
        json=_base_body(model="Veo 3.1 - Lite", duration_seconds=6),
    )
    assert unsupported.status_code == 422


def test_validate_preview_no_package_write(client: TestClient) -> None:
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
    ) as mock_create:
        r = client.post(
            "/api/faceless/validate",
            json=_base_body(background_id="PHARMACY"),
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["resolution"]["background"]["setting_id"] == "PHARMACY"
    mock_create.assert_not_awaited()
