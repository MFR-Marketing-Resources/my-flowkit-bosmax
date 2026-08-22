"""Faceless prepare API — product-first + model/duration propagation."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.faceless import router as faceless_router
from agent.services import creative_lane_settings_service as cls
from agent.services import faceless_lane_service as fl


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(faceless_router, prefix="/api")
    return TestClient(app)


def _base_body(**extra):
    body = {
        "product_id": "p1",
        "staff_id": "staff_pytest_operator",
        "hook_id": "AUTO",
        "background_id": "AUTO",
        "model": "Veo 3.1 - Lite",
        "generation_mode": "SINGLE",
        "duration_seconds": 8,
        "copy_fallback_confirmed": True,
    }
    body.update(extra)
    return body


@pytest.fixture(autouse=True)
def fake_scene_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep HTTP unit tests package-free; scene authority has its own tests."""

    async def _resolve(**kwargs):
        opening = cls.resolve_opening_strategy(kwargs.get("hook_id"))
        background = cls.resolve_background(kwargs.get("background_id"))
        choreography = {
            "scene_strategy_id": "TRADITIONAL_HERBAL_OIL",
            "allowed_scene_strategy": "warm heritage tabletop",
            "allowed_action": "composed sequence",
            "scene_context": "warm heritage tabletop",
            "camera_route": "steady tabletop close-up",
            "avatar_hint": "hands only",
            "wardrobe_hint": "neutral sleeve",
            "direct_hook": "approved",
            "direct_benefit": "approved",
            "direct_cta": "approved",
            "choreography_id": "traditional_herbal_oil.v0",
            "choreography_schema_version": "scene_choreography_v2",
            "choreography_sha256": "a" * 64,
            "allowed_character_presence": ["FACELESS"],
        }
        return {
            "product": {"id": "p1", "name": "Test Oil"},
            "opening_strategy": opening,
            "background": background,
            "background_options": cls.background_options(),
            "compatible_contexts": ["warm heritage tabletop"],
            "scene_strategy": {
                "scene_strategy_id": "TRADITIONAL_HERBAL_OIL",
                "resolution_source": "test",
                "fallback_used": False,
            },
            "choreography": choreography,
        }

    monkeypatch.setattr(fl, "resolve_faceless_scene_authority", _resolve)


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
        "copy_architecture_v2": {
            "status": "READY",
            "projection": {"derived_copy": {"hook": "Approved V2 Hook"}},
        },
        "asset_slots": [
            {
                "slot_key": "start_frame",
                "resolved_asset": {
                    "asset_id": "product-visual:p1:official",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_VISUAL_OFFICIAL_SOURCE",
                    "official_visual": True,
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
    assert data["resolution"]["opening_strategy"]["setting_id"] == hook["setting_id"]
    assert data["faceless_resolution"]["opening_strategy_resolved"] == hook[
        "setting_id"
    ]
    assert data["copy_architecture_v2"]["projection"]["derived_copy"]["hook"] == (
        "Approved V2 Hook"
    )

    kwargs = mock_create.await_args.kwargs
    assert kwargs["mode"] == "F2V"
    assert kwargs["source_mode"] == "HYBRID"
    assert kwargs["character_presence"] == "FACELESS"
    assert kwargs["avatar_id"] is None
    assert kwargs["start_frame_asset_id"] is None
    assert kwargs["model"] == "Veo 3.1 - Lite"
    assert kwargs["duration_seconds"] == 8
    assert "VISUAL LAW" in (kwargs.get("scene_context_override") or "")
    assert kwargs["faceless_resolution"]["character_presence"] == "FACELESS"
    assert kwargs["faceless_resolution"]["actor_profile"]["operator_selection"] == "AUTO"
    assert kwargs["faceless_resolution"]["actor_profile"]["cue"]


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
                    "asset_id": "product-visual:p1:official",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_VISUAL_OFFICIAL_SOURCE",
                    "official_visual": True,
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
                    "asset_id": "product-visual:p1:official",
                    "asset_fingerprint": "sha256:product-p1",
                    "asset_source": "PRODUCT_VISUAL_OFFICIAL_SOURCE",
                    "official_visual": True,
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
    # This route test is about validation/resolution and must not depend on the
    # optional legacy DB shell. The production route still resolves Copy V2;
    # use an explicit maintenance-mode result here so the test remains hermetic.
    fake_copy_resolution = SimpleNamespace(v2_enabled=False)
    with (
        patch(
            "agent.api.faceless.resolve_persisted_copy_execution_binding",
            new_callable=AsyncMock,
            return_value=fake_copy_resolution,
        ),
        patch(
            "agent.api.faceless.create_workspace_execution_package",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        r = client.post(
            "/api/faceless/validate",
            json=_base_body(background_id="PHARMACY"),
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["resolution"]["background"]["setting_id"] == "PHARMACY"
    mock_create.assert_not_awaited()


def test_prepare_incompatible_background_is_blocked_before_package_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _reject(**_: object):
        raise ValueError(
            "ERR_FACELESS_BACKGROUND_INCOMPATIBLE: KITCHEN is not compatible"
        )

    monkeypatch.setattr(fl, "resolve_faceless_scene_authority", _reject)
    with patch(
        "agent.api.faceless.create_workspace_execution_package",
        new_callable=AsyncMock,
    ) as mock_create:
        response = client.post(
            "/api/faceless/prepare",
            json=_base_body(background_id="KITCHEN"),
        )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == (
        "ERR_FACELESS_BACKGROUND_INCOMPATIBLE"
    )
    mock_create.assert_not_awaited()
