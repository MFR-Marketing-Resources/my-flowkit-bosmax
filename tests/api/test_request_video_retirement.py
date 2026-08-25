"""Containment tests for retired generic paid-video request entrypoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api import requests as requests_api
from agent.api import smoke as smoke_api


RETIREMENT_CODE = "LEGACY_VIDEO_REQUEST_RETIRED_USE_DURABLE_VIDEO_JOB"
RETIRED_VIDEO_TYPES = (
    "GENERATE_VIDEO",
    "REGENERATE_VIDEO",
    "GENERATE_VIDEO_REFS",
    "TRUE_F2V",
    "UPSCALE_VIDEO",
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(requests_api.router, prefix="/api")
    app.include_router(smoke_api.router)
    return TestClient(app)


def _video_body(req_type: str) -> dict:
    body = {"type": req_type}
    if req_type != "TRUE_F2V":
        body.update({
            "scene_id": "scene-001",
            "project_id": "project-001",
            "video_id": "video-001",
        })
    return body


@pytest.mark.parametrize("req_type", RETIRED_VIDEO_TYPES)
def test_single_video_request_returns_410_before_crud(req_type):
    with patch.object(requests_api.crud, "list_requests", new_callable=AsyncMock) as list_requests, \
         patch.object(requests_api.crud, "update_video", new_callable=AsyncMock) as update_video, \
         patch.object(requests_api.crud, "create_request", new_callable=AsyncMock) as create_request:
        response = _client().post("/api/requests", json=_video_body(req_type))

    assert response.status_code == 410
    assert response.json() == {"detail": RETIREMENT_CODE}
    list_requests.assert_not_awaited()
    update_video.assert_not_awaited()
    create_request.assert_not_awaited()


def test_mixed_batch_returns_410_before_any_mutation():
    payload = {
        "requests": [
            {
                "type": "GENERATE_IMAGE",
                "orientation": "VERTICAL",
                "scene_id": "scene-001",
                "project_id": "project-001",
                "video_id": "video-001",
            },
            {
                "type": "GENERATE_VIDEO",
                "scene_id": "scene-002",
                "project_id": "project-001",
                "video_id": "video-001",
            },
            {
                "type": "GENERATE_CHARACTER_IMAGE",
                "character_id": "character-001",
                "project_id": "project-001",
            },
        ]
    }
    with patch.object(requests_api.crud, "update_video", new_callable=AsyncMock) as update_video, \
         patch.object(requests_api.crud, "list_requests", new_callable=AsyncMock) as list_requests, \
         patch.object(requests_api.crud, "create_request", new_callable=AsyncMock) as create_request:
        response = _client().post("/api/requests/batch", json=payload)

    assert response.status_code == 410
    assert response.json() == {"detail": RETIREMENT_CODE}
    update_video.assert_not_awaited()
    list_requests.assert_not_awaited()
    create_request.assert_not_awaited()


class _NoEventBusAccess:
    @property
    def extension_connected(self):
        raise AssertionError("retired smoke route touched extension state")

    @property
    def extension_state(self):
        raise AssertionError("retired smoke route touched extension state")


class _NoCrudAccess:
    def __getattr__(self, name):
        raise AssertionError(f"retired smoke route touched crud.{name}")


def test_true_f2v_smoke_returns_410_before_extension_or_crud():
    with patch.object(smoke_api, "event_bus", _NoEventBusAccess()), \
         patch.object(smoke_api, "crud", _NoCrudAccess()):
        response = _client().post("/api/smoke/true-f2v")

    assert response.status_code == 410
    assert response.json() == {"detail": RETIREMENT_CODE}


@pytest.mark.parametrize(
    ("req_type", "body", "expected_type"),
    (
        (
            "GENERATE_IMAGE",
            {
                "type": "GENERATE_IMAGE",
                "scene_id": "scene-001",
                "project_id": "project-001",
                "video_id": "video-001",
            },
            "GENERATE_IMAGE",
        ),
        (
            "GENERATE_CHARACTER_IMAGE",
            {
                "type": "GENERATE_CHARACTER_IMAGE",
                "character_id": "character-001",
                "project_id": "project-001",
            },
            "GENERATE_CHARACTER_IMAGE",
        ),
    ),
)
def test_image_and_character_requests_remain_available(req_type, body, expected_type):
    created = {
        "id": f"request-{req_type.lower()}",
        "type": expected_type,
        "project_id": "project-001",
        "scene_id": body.get("scene_id"),
        "video_id": body.get("video_id"),
        "character_id": body.get("character_id"),
        "status": "PENDING",
    }
    with patch.object(
        requests_api.crud,
        "list_requests",
        new=AsyncMock(return_value=[]),
    ) as list_requests, patch.object(
        requests_api.crud,
        "create_request",
        new=AsyncMock(return_value=created),
    ) as create_request, patch.object(
        requests_api.crud,
        "update_video",
        new_callable=AsyncMock,
    ) as update_video:
        response = _client().post("/api/requests", json=body)

    assert response.status_code == 200
    assert response.json()["type"] == expected_type
    if req_type == "GENERATE_IMAGE":
        list_requests.assert_awaited_once()
    else:
        list_requests.assert_not_awaited()
    create_request.assert_awaited_once()
    update_video.assert_not_awaited()
