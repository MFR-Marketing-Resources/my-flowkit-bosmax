"""API contract for the Avatar Registry CSV Factory endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


_BASE = "/api/workspace/avatar-registry/csv-factory"


def test_validate_returns_report_without_staging():
    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/validate",
        content="WrongHeader\nvalue\n",
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "FAIL"
    assert any(e["code"] == "SEED_SCHEMA_MISMATCH" for e in report["errors"])


def test_validate_empty_body_rejected():
    client = TestClient(_build_app())
    response = client.post(f"{_BASE}/validate", content=b"")
    assert response.status_code == 422


def test_import_stages_batch(monkeypatch):
    captured = {}

    def fake_import(csv_bytes, source_filename=None):
        captured["csv_bytes"] = csv_bytes
        captured["source_filename"] = source_filename
        return {"staged": True, "report": {"status": "PASS"},
                "batch": {"batch_id": "acf_abc123def456"}}

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.import_seed_csv", fake_import)

    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/import?filename=candidates.csv",
        content="header\nrow\n",
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 200
    assert response.json()["batch"]["batch_id"] == "acf_abc123def456"
    assert captured["source_filename"] == "candidates.csv"


def test_import_service_error_maps_to_422(monkeypatch):
    def fake_import(csv_bytes, source_filename=None):
        raise ValueError("AVATAR_CSV_FACTORY_EMPTY_BODY")

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.import_seed_csv", fake_import)
    client = TestClient(_build_app())
    response = client.post(f"{_BASE}/import", content="x")
    assert response.status_code == 422
    assert "AVATAR_CSV_FACTORY_EMPTY_BODY" in response.json()["detail"]


def test_list_batches(monkeypatch):
    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.list_batches",
        lambda: [{"batch_id": "acf_abc123def456", "status": "REVIEW"}])
    client = TestClient(_build_app())
    response = client.get(f"{_BASE}/batches")
    assert response.status_code == 200
    assert response.json()["batches"][0]["batch_id"] == "acf_abc123def456"


def test_batch_detail_not_found_maps_to_404(monkeypatch):
    def fake_get(batch_id):
        raise KeyError(f"AVATAR_CSV_FACTORY_BATCH_NOT_FOUND:{batch_id}")

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.get_batch", fake_get)
    client = TestClient(_build_app())
    response = client.get(f"{_BASE}/batches/acf_000000000000")
    assert response.status_code == 404


def test_review_applies_decisions(monkeypatch):
    captured = {}

    def fake_review(batch_id, decisions):
        captured["batch_id"] = batch_id
        captured["decisions"] = decisions
        return {"batch_id": batch_id, "approved_rows": 1}

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.review_rows", fake_review)
    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/batches/acf_abc123def456/review",
        json={"decisions": [{"row_index": 2, "decision": "APPROVE"}]},
    )
    assert response.status_code == 200
    assert captured["decisions"] == [{"row_index": 2, "decision": "APPROVE"}]


def test_review_rejects_bad_decision_shape():
    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/batches/acf_abc123def456/review",
        json={"decisions": [{"row_index": 2, "decision": "MAYBE"}]},
    )
    assert response.status_code == 422
    response = client.post(
        f"{_BASE}/batches/acf_abc123def456/review", json={"decisions": []})
    assert response.status_code == 422


def test_review_invalid_row_approval_maps_to_422(monkeypatch):
    def fake_review(batch_id, decisions):
        raise ValueError("AVATAR_CSV_FACTORY_CANNOT_APPROVE_INVALID_ROW:2:X")

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.review_rows", fake_review)
    client = TestClient(_build_app())
    response = client.post(
        f"{_BASE}/batches/acf_abc123def456/review",
        json={"decisions": [{"row_index": 2, "decision": "APPROVE"}]},
    )
    assert response.status_code == 422


def test_export_returns_csv_attachment(monkeypatch):
    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.export_approved_csv",
        lambda batch_id: "CharacterName,Variant\nAisyah,Office 01\n")
    client = TestClient(_build_app())
    response = client.get(f"{_BASE}/batches/acf_abc123def456/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "Aisyah" in response.text


def test_sync_success_and_failure_mapping(monkeypatch):
    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.sync_approved_to_bridge",
        lambda batch_id: {"batch_id": batch_id, "synced_rows": 3,
                          "pool_rows_before": 250, "pool_rows_after": 253})
    client = TestClient(_build_app())
    response = client.post(f"{_BASE}/batches/acf_abc123def456/sync")
    assert response.status_code == 200
    assert response.json()["synced_rows"] == 3

    def fail_sync(batch_id):
        raise ValueError(f"AVATAR_CSV_FACTORY_NO_APPROVED_ROWS:{batch_id}")

    monkeypatch.setattr(
        "agent.services.avatar_csv_factory_service.sync_approved_to_bridge",
        fail_sync)
    response = client.post(f"{_BASE}/batches/acf_abc123def456/sync")
    assert response.status_code == 422


def test_avatar_registry_pool_reports_truthful_generated_and_missing_states(monkeypatch):
    monkeypatch.setattr(
        "agent.services.avatar_registry.list_pool",
        lambda: [
            {"avatar_code": "BOS_F_ALYA_01", "character_name": "Alya", "usage_tags": []},
            {"avatar_code": "BOS_F_ALYA_02", "character_name": "Alya 2", "usage_tags": []},
        ],
    )
    monkeypatch.setattr(
        "agent.services.avatar_registry._active_pool_file",
        lambda: "C:/tmp/AVATAR_POOL_NORMALIZED.csv",
    )
    monkeypatch.setattr(
        "agent.services.avatar_registry._BRIDGE_FILE",
        type("BridgeFile", (), {"exists": staticmethod(lambda: False)})(),
    )

    async def fake_index():
        return {
            "BOS_F_ALYA_01": {
                "asset_id": "ca_avatar_ok",
                "avatar_status": "GENERATED",
                "asset_lifecycle": "CANONICAL_AVATAR_ASSET",
                "integrity_status": "LOCAL_FILE_OK",
                "preview_url": "/api/creative-assets/ca_avatar_ok/preview",
            },
            "BOS_F_ALYA_02": {
                "asset_id": "ca_avatar_missing",
                "avatar_status": "MISSING_ASSET",
                "asset_lifecycle": "CANONICAL_AVATAR_ASSET",
                "integrity_status": "LOCAL_FILE_MISSING",
                "preview_url": "/api/creative-assets/ca_avatar_missing/preview",
            },
        }

    monkeypatch.setattr(
        "agent.services.creative_asset_service.list_avatar_asset_index",
        fake_index,
    )

    client = TestClient(_build_app())
    response = client.get("/api/workspace/avatar-registry/pool")

    assert response.status_code == 200
    payload = response.json()
    avatars = {row["avatar_code"]: row for row in payload["avatars"]}
    assert payload["generated_count"] == 1
    assert payload["broken_count"] == 1
    assert avatars["BOS_F_ALYA_01"]["image_generated"] is True
    assert avatars["BOS_F_ALYA_01"]["image_status"] == "GENERATED"
    assert avatars["BOS_F_ALYA_02"]["image_generated"] is False
    assert avatars["BOS_F_ALYA_02"]["image_status"] == "MISSING_ASSET"


def test_avatar_register_generated_blocks_existing_retrievable_avatar(monkeypatch, tmp_path):
    artifact_file = tmp_path / "avatar.jpg"
    artifact_file.write_bytes(b"avatar")

    async def fake_artifacts(limit=200, kind=None):
        return [
            {
                "media_id": "media_avatar_001",
                "job_id": "g_123",
                "local_path": str(artifact_file),
            }
        ]

    monkeypatch.setattr(
        "agent.services.avatar_registry.get_generation_prompt",
        lambda code: {"avatar_code": code, "character_name": "Alya", "prompt": "prompt"},
    )
    monkeypatch.setattr("agent.db.crud.list_generated_artifacts", fake_artifacts)

    async def fake_generated_index():
        return {
            "BOS_F_ALYA_01": {
                "asset_id": "ca_avatar_live",
                "avatar_status": "GENERATED",
                "retrievable": True,
            }
        }

    monkeypatch.setattr(
        "agent.api.workspace_packages._generated_avatar_asset_index",
        fake_generated_index,
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/register-generated",
        json={"avatar_code": "BOS_F_ALYA_01", "media_id": "media_avatar_001"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "AVATAR_ALREADY_REGISTERED:ca_avatar_live"


@pytest.mark.parametrize(
    ("avatar_status", "retrievable"),
    [
        ("MISSING_ASSET", False),
        ("BROKEN_LINK", False),
        ("GENERATED_METADATA_ONLY", False),
        ("NEEDS_REGENERATION", False),
    ],
)
def test_avatar_register_generated_allows_repair_for_non_retrievable_existing_asset(
    monkeypatch,
    tmp_path,
    avatar_status,
    retrievable,
):
    artifact_file = tmp_path / f"{avatar_status.lower()}.jpg"
    artifact_file.write_bytes(b"avatar")
    captured = {}
    archived = []

    async def fake_artifacts(limit=200, kind=None):
        return [
            {
                "media_id": "media_avatar_002",
                "job_id": "g_456",
                "local_path": str(artifact_file),
            }
        ]

    async def fake_create(request):
        captured["request"] = request
        return type("Record", (), {"asset_id": "ca_avatar_repaired"})()

    async def fake_archive(asset_id):
        archived.append(asset_id)
        return {"asset_id": asset_id, "status": "ARCHIVED"}

    monkeypatch.setattr(
        "agent.services.avatar_registry.get_generation_prompt",
        lambda code: {"avatar_code": code, "character_name": "Alya", "prompt": "prompt"},
    )
    monkeypatch.setattr("agent.db.crud.list_generated_artifacts", fake_artifacts)

    async def fake_generated_index():
        return {
            "BOS_F_ALYA_02": {
                "asset_id": "ca_avatar_broken",
                "avatar_status": avatar_status,
                "retrievable": retrievable,
            }
        }

    monkeypatch.setattr(
        "agent.api.workspace_packages._generated_avatar_asset_index",
        fake_generated_index,
    )
    monkeypatch.setattr(
        "agent.services.creative_asset_service.create_creative_asset",
        fake_create,
    )
    monkeypatch.setattr(
        "agent.services.creative_asset_service.archive_creative_asset",
        fake_archive,
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/register-generated",
        json={"avatar_code": "BOS_F_ALYA_02", "media_id": "media_avatar_002"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": "ca_avatar_repaired",
        "avatar_code": "BOS_F_ALYA_02",
    }
    assert archived == ["ca_avatar_broken"]
    assert captured["request"].semantic_role == "CHARACTER_REFERENCE"
    assert captured["request"].asset_lifecycle == "CANONICAL_AVATAR_ASSET"
    assert captured["request"].retention_policy == "PERSISTENT"
    assert captured["request"].is_reusable is True
    assert captured["request"].is_canonical is True
    assert captured["request"].avatar_code == "BOS_F_ALYA_02"
    assert Path(captured["request"].file_name).name == artifact_file.name
