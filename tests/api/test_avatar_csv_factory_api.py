"""API contract for the Avatar Registry CSV Factory endpoints."""
from __future__ import annotations

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
