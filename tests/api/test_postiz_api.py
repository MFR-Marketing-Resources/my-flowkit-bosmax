"""API contracts for /api/postiz (route functions called directly, mocked
Postiz network layer — no real Postiz instance, no real providers)."""
import json

import pytest
from fastapi import HTTPException

from agent.api import postiz as postiz_api
from agent.db import crud
from agent.services import postiz_client as pz

_UUID = "550e8400-e29b-41d4-a716-446655440000"

_CHANNELS = [
    {"id": "tt-1", "provider": "tiktok", "name": "TikTok Acct A",
     "picture": None, "disabled": False, "refresh_needed": False, "profile": "a"},
    {"id": "tt-2", "provider": "tiktok", "name": "TikTok Acct B",
     "picture": None, "disabled": False, "refresh_needed": False, "profile": "b"},
    {"id": "fb-1", "provider": "facebook", "name": "FB Page",
     "picture": None, "disabled": False, "refresh_needed": False, "profile": "c"},
]


def _enable(monkeypatch):
    monkeypatch.setenv("POSTIZ_ENABLED", "true")
    monkeypatch.setenv("POSTIZ_BASE_URL", "http://localhost:5000")
    monkeypatch.setenv("POSTIZ_API_KEY", "test-key")
    monkeypatch.setenv("POSTIZ_UPLOAD_MODE", "file")
    monkeypatch.setenv("POSTIZ_DEFAULT_POST_TYPE", "draft")


async def _seed_artifact(tmp_path, kind="image", ext=".jpg", media_id=_UUID):
    f = tmp_path / f"{media_id}{ext}"
    f.write_bytes(b"fake-media-bytes")
    await crud.insert_generated_artifact(
        media_id, job_id="g_test", mode="IMG", artifact_kind=kind,
        local_path=str(f), size_mb=0.1,
    )
    return f


async def _expect_http(coro, status, needle=None):
    with pytest.raises(HTTPException) as exc_info:
        await coro
    assert exc_info.value.status_code == status, exc_info.value.detail
    if needle:
        assert needle.lower() in str(exc_info.value.detail).lower()


# ── Flag off: everything fails closed, nothing else changes ───────────────


async def test_health_reports_disabled_without_leaking_anything(monkeypatch):
    monkeypatch.delenv("POSTIZ_ENABLED", raising=False)
    monkeypatch.setenv("POSTIZ_API_KEY", "should-not-appear")
    result = await postiz_api.health()
    assert result["ok"] is False
    assert "POSTIZ_DISABLED" in result["problems"]
    assert "should-not-appear" not in str(result)


async def test_integrations_and_publish_fail_closed_when_disabled(monkeypatch):
    monkeypatch.setenv("POSTIZ_ENABLED", "false")
    await _expect_http(postiz_api.integrations(), 503, "postiz_disabled")
    body = postiz_api.PublishRequest(artifact_media_id=_UUID, integration_ids=["tt-1"])
    await _expect_http(postiz_api.publish(body), 503, "postiz_disabled")


# ── Channels ──────────────────────────────────────────────────────────────


async def test_list_integrations_supports_multiple_same_provider(monkeypatch):
    _enable(monkeypatch)

    async def fake_list():
        return list(_CHANNELS)

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    result = await postiz_api.integrations()
    assert result["count"] == 3
    tiktoks = [c for c in result["integrations"] if c["provider"] == "tiktok"]
    assert len(tiktoks) == 2  # multi-account per provider is first-class


# ── Publish flow (mocked Postiz) ──────────────────────────────────────────


async def test_publish_uploads_artifact_and_creates_draft(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)
    calls = {"upload": [], "post": []}

    async def fake_list():
        return list(_CHANNELS)

    async def fake_upload(path):
        calls["upload"].append(path)
        return {"id": "pz-media-1", "path": "/uploads/pz-media-1.jpg"}

    async def fake_create(payload):
        calls["post"].append(payload)
        return {"id": "pz-post-group-1", "status": "created"}

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    monkeypatch.setattr(pz, "upload_file", fake_upload)
    monkeypatch.setattr(pz, "create_post", fake_create)

    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID,
        integration_ids=["tt-1", "tt-2"],  # two TikTok accounts at once
        content="BOSMAX draft",
    )
    result = await postiz_api.publish(body)
    assert result["ok"] is True
    assert result["post_type"] == "draft"  # safe default from env
    assert result["postiz_media"]["id"] == "pz-media-1"
    assert len(calls["upload"]) == 1 and calls["upload"][0].endswith(".jpg")
    payload = calls["post"][0]
    assert payload["type"] == "draft"
    assert [p["integration"]["id"] for p in payload["posts"]] == ["tt-1", "tt-2"]
    assert payload["posts"][0]["settings"]["privacy_level"] == "SELF_ONLY"

    # Audit trail persisted with Postiz ids.
    records = await crud.list_postiz_publish_records()
    rec = next(r for r in records if r["artifact_media_id"] == _UUID)
    assert rec["status"] == "POST_CREATED"
    assert rec["postiz_media_id"] == "pz-media-1"
    assert json.loads(rec["integration_ids_json"]) == ["tt-1", "tt-2"]


async def test_publish_dry_run_builds_payload_without_uploading(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)
    touched = []

    async def fake_list():
        return list(_CHANNELS)

    async def boom(*a, **k):
        touched.append(True)
        raise AssertionError("must not be called in dry run")

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    monkeypatch.setattr(pz, "upload_file", boom)
    monkeypatch.setattr(pz, "create_post", boom)

    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID, integration_ids=["fb-1"], dry_run=True,
    )
    result = await postiz_api.publish(body)
    assert result["dry_run"] is True
    assert result["payload"]["posts"][0]["integration"]["id"] == "fb-1"
    assert not touched


async def test_publish_rejects_unknown_integration_ids(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)

    async def fake_list():
        return list(_CHANNELS)

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID, integration_ids=["ghost-channel"],
    )
    await _expect_http(postiz_api.publish(body), 422, "unknown_integration_ids")


async def test_publish_404_when_artifact_missing(monkeypatch):
    _enable(monkeypatch)
    body = postiz_api.PublishRequest(
        artifact_media_id="00000000-0000-0000-0000-000000000000",
        integration_ids=["tt-1"],
    )
    await _expect_http(postiz_api.publish(body), 404, "artifact_not_found")


async def test_publish_schedule_requires_datetime(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)
    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID, integration_ids=["tt-1"], post_type="schedule",
    )
    await _expect_http(postiz_api.publish(body), 422, "schedule_at_required")


async def test_publish_url_mode_without_public_base_is_blocked(monkeypatch, tmp_path):
    _enable(monkeypatch)
    monkeypatch.setenv("POSTIZ_UPLOAD_MODE", "url")
    monkeypatch.delenv("POSTIZ_PUBLIC_MEDIA_BASE_URL", raising=False)
    await _seed_artifact(tmp_path)
    body = postiz_api.PublishRequest(artifact_media_id=_UUID, integration_ids=["tt-1"])
    await _expect_http(postiz_api.publish(body), 422, "media_not_publicly_reachable")


async def test_publish_failure_is_recorded_in_audit_trail(monkeypatch, tmp_path):
    _enable(monkeypatch)
    fail_uuid = "660e8400-e29b-41d4-a716-446655440111"
    await _seed_artifact(tmp_path, media_id=fail_uuid)

    async def fake_list():
        return list(_CHANNELS)

    async def failing_upload(path):
        raise pz.PostizApiError(401, "invalid api key")

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    monkeypatch.setattr(pz, "upload_file", failing_upload)
    body = postiz_api.PublishRequest(artifact_media_id=fail_uuid, integration_ids=["tt-1"])
    await _expect_http(postiz_api.publish(body), 401)
    records = await crud.list_postiz_publish_records()
    rec = next(r for r in records if r["artifact_media_id"] == fail_uuid)
    assert rec["status"] == "FAILED"
    assert "401" in (rec["error"] or "")


# ── Templates endpoint ────────────────────────────────────────────────────


async def test_provider_templates_endpoint_surfaces_warnings():
    result = await postiz_api.templates()
    assert "tiktok" in result["templates"]
    assert any("audit" in w.lower() for w in result["warnings"]["tiktok"])


async def test_publish_schedule_rejects_non_iso_datetime(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)
    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID, integration_ids=["tt-1"],
        post_type="schedule", schedule_at="tomorrow at noon",
    )
    await _expect_http(postiz_api.publish(body), 422, "invalid_schedule_at")


async def test_publish_schedule_accepts_iso_z_datetime_in_dry_run(monkeypatch, tmp_path):
    _enable(monkeypatch)
    await _seed_artifact(tmp_path)

    async def fake_list():
        return list(_CHANNELS)

    monkeypatch.setattr(pz, "list_integrations", fake_list)
    body = postiz_api.PublishRequest(
        artifact_media_id=_UUID, integration_ids=["tt-1"],
        post_type="schedule", schedule_at="2026-08-01T10:00:00Z", dry_run=True,
    )
    result = await postiz_api.publish(body)
    assert result["payload"]["date"] == "2026-08-01T10:00:00Z"
