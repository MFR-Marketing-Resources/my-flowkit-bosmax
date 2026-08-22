"""HTTP authority boundary tests for active staff attribution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from agent.api.flow import router as flow_router
from agent.api.staff_identity import router as staff_router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(flow_router, prefix="/api")
    app.include_router(staff_router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_staff_profile_http_registry_preserves_history() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post(
            "/api/staff/profiles",
            json={"display_name": "HTTP Operator"},
        )
        assert created_response.status_code == 201
        created = created_response.json()
        staff_id = created["staff_id"]

        renamed_response = await client.patch(
            f"/api/staff/profiles/{staff_id}",
            json={"display_name": "HTTP Operator Renamed"},
        )
        assert renamed_response.status_code == 200
        assert renamed_response.json()["staff_id"] == staff_id
        assert renamed_response.json()["display_name"] == "HTTP Operator Renamed"

        inactive_response = await client.patch(
            f"/api/staff/profiles/{staff_id}",
            json={"active": False},
        )
        assert inactive_response.status_code == 200
        assert inactive_response.json()["active"] is False

        resolve_response = await client.get(f"/api/staff/resolve/{staff_id}")
        assert resolve_response.status_code == 409
        assert resolve_response.json()["detail"]["error"] == "STAFF_IDENTITY_INACTIVE"

        active_profiles = await client.get(
            "/api/staff/profiles",
            params={"include_inactive": "false"},
        )
        assert staff_id not in {row["staff_id"] for row in active_profiles.json()["profiles"]}

        all_profiles = await client.get(
            "/api/staff/profiles",
            params={"include_inactive": "true"},
        )
        historical = next(
            row for row in all_profiles.json()["profiles"] if row["staff_id"] == staff_id
        )
        assert historical["display_name"] == "HTTP Operator Renamed"
        assert historical["active"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("recipe", "mode", "source_mode", "visual_lane_id"),
    [
        ("HYBRID", "F2V", "HYBRID", None),
        ("FACELESS", "F2V", "FACELESS", None),
        ("MONTAGE", "F2V", "MONTAGE", None),
        ("POSTER_BUILDER", "IMG", None, "POSTER_BUILDER"),
    ],
)
async def test_active_recipe_generate_requires_staff_before_provider(
    monkeypatch,
    recipe: str,
    mode: str,
    source_mode: str | None,
    visual_lane_id: str | None,
) -> None:
    provider = AsyncMock(side_effect=AssertionError("provider boundary must not be reached"))
    monkeypatch.setattr("agent.services.make_video.start_generate", provider)
    payload = {
        "mode": mode,
        "prompt": "provider-ready prompt",
        "production_recipe": recipe,
        "staff_id": None,
    }
    if source_mode:
        payload["source_mode"] = source_mode
    if visual_lane_id:
        payload["visual_lane_id"] = visual_lane_id

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/flow/generate", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "STAFF_IDENTITY_REQUIRED"
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_staff_is_rejected_at_generate_boundary(monkeypatch) -> None:
    from agent.services import staff_identity_service as staff

    profile = await staff.create_staff_profile("Inactive HTTP Operator")
    await staff.update_staff_profile(profile["staff_id"], active=False)
    provider = AsyncMock(side_effect=AssertionError("provider boundary must not be reached"))
    monkeypatch.setattr("agent.services.make_video.start_generate", provider)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/flow/generate",
            json={
                "mode": "F2V",
                "prompt": "provider-ready prompt",
                "production_recipe": "HYBRID",
                "staff_id": profile["staff_id"],
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STAFF_IDENTITY_INACTIVE"
    provider.assert_not_awaited()
