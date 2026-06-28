from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent.api.telemetry import router
from agent.db import crud
from agent.db.schema import get_db


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _valid_stage_payload(**overrides):
    payload = {
        "request_id": "manual_runtime_001",
        "timestamp": "2026-05-23T13:45:00Z",
        "git_sha": "flowkit-google-flow-phase1a-2026-05-23",
        "background_build_id": "flowkit-google-flow-phase1a-2026-05-23",
        "content_build_id": "flowkit-google-flow-phase1a-2026-05-23",
        "stage": "RUNTIME_HANDSHAKE_VERIFIED",
        "checkpoint": "RUNTIME_HANDSHAKE_VERIFIED",
        "status": "PASS",
        "message": "background_build_id matched content_build_id",
        "source": "extension",
        "runtime_ready": True,
        "build_match": True,
        "selector_used": "composer_dock_probe",
        "evidence_pointer": "dom://flow-editor/composer",
        "fail_code": None,
        "first_fail_stage": None,
    }
    payload.update(overrides)
    return payload


def test_telemetry_stage_rejects_na_request_id():
    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(request_id="N/A"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "REQUEST_ID_NA_REJECTED"


def test_telemetry_stage_persists_build_and_checkpoint_metadata(monkeypatch):
    captured = {}

    async def fake_upsert(request_id: str, **kwargs):
        captured["request_id"] = request_id
        captured["telemetry_kwargs"] = kwargs
        return {"request_id": request_id, **kwargs}

    async def fake_add_stage_event(request_id: str, stage: str, status: str, message=None, source="backend", **extra):
        captured["stage_event"] = {
            "request_id": request_id,
            "stage": stage,
            "status": status,
            "message": message,
            "source": source,
            "extra": extra,
        }
        return {"request_id": request_id, "stage": stage, "status": status, **extra}

    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-05-23T13:45:30Z")

    client = TestClient(_build_app())
    response = client.post("/api/telemetry/stage", json=_valid_stage_payload())

    assert response.status_code == 200
    assert captured["request_id"] == "manual_runtime_001"
    assert captured["telemetry_kwargs"]["git_sha"] == "flowkit-google-flow-phase1a-2026-05-23"
    assert captured["telemetry_kwargs"]["background_build_id"] == "flowkit-google-flow-phase1a-2026-05-23"
    assert captured["telemetry_kwargs"]["content_build_id"] == "flowkit-google-flow-phase1a-2026-05-23"
    assert captured["telemetry_kwargs"]["last_checkpoint"] == "RUNTIME_HANDSHAKE_VERIFIED"
    assert captured["telemetry_kwargs"]["runtime_ready"] == 1
    assert captured["telemetry_kwargs"]["build_match"] == 1
    assert captured["stage_event"]["extra"]["checkpoint"] == "RUNTIME_HANDSHAKE_VERIFIED"
    assert captured["stage_event"]["extra"]["selector_used"] == "composer_dock_probe"
    assert captured["stage_event"]["extra"]["evidence_pointer"] == "dom://flow-editor/composer"


def test_telemetry_stage_extracts_real_error_code_from_fail_message(monkeypatch):
    captured = {}

    async def fake_upsert(request_id: str, **kwargs):
        captured["request_id"] = request_id
        captured["telemetry_kwargs"] = kwargs
        return {"request_id": request_id, **kwargs}

    async def fake_add_stage_event(request_id: str, stage: str, status: str, message=None, source="backend", **extra):
        captured["stage_event"] = {
            "request_id": request_id,
            "stage": stage,
            "status": status,
            "message": message,
            "source": source,
            "extra": extra,
        }
        return {"request_id": request_id, "stage": stage, "status": status, **extra}

    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-05-28T05:31:55Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(
            stage="F2V_SOP_SETTINGS_PANEL_OPENED",
            checkpoint="F2V_SOP_SETTINGS_PANEL_OPENED",
            status="FAIL",
            message='ERR_F2V_SETTINGS_PANEL_NOT_OPEN detail={"target_tab_url":"https://labs.google/fx/tools/flow"}',
            fail_code=None,
        ),
    )

    assert response.status_code == 200
    assert captured["telemetry_kwargs"]["status"] == "FAILED"
    assert captured["telemetry_kwargs"]["error_message"].startswith("ERR_F2V_SETTINGS_PANEL_NOT_OPEN")
    assert captured["telemetry_kwargs"]["error_code"] == "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"


def test_telemetry_stage_syncs_gfv2psd_terminal_failure_into_base_request(monkeypatch):
    captured = {}

    class _FakeCursor:
        async def fetchone(self):
            return {"id": "gfv2psd-telemetry-fail", "type": "MANUAL_FLOW_JOB"}

    class _FakeDb:
        async def execute(self, *_args, **_kwargs):
            return _FakeCursor()

    async def fake_upsert(*_args, **_kwargs):
        return {}

    async def fake_update_request(request_id: str, **kwargs):
        captured["request_id"] = request_id
        captured["request_update"] = kwargs
        return {"id": request_id, **kwargs}

    async def fake_add_stage_event(*_args, **_kwargs):
        return {}

    async def fake_get_db():
        return _FakeDb()

    monkeypatch.setattr("agent.db.schema.get_db", fake_get_db)
    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.update_request", fake_update_request)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-06-28T08:00:00Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(
            request_id="gfv2psd-telemetry-fail",
            stage="FAILED",
            checkpoint="FAILED",
            status="FAIL",
            source="extension",
            message="GFV2_EDITOR_ENTRY_FAILED",
        ),
    )

    assert response.status_code == 200
    assert captured["request_id"] == "gfv2psd-telemetry-fail"
    assert captured["request_update"]["status"] == "FAILED"
    assert captured["request_update"]["error_message"] == "GFV2_EDITOR_ENTRY_FAILED"


def test_telemetry_stage_syncs_gfv2psd_terminal_completion_into_base_request(monkeypatch):
    captured = {}

    class _FakeCursor:
        async def fetchone(self):
            return {"id": "gfv2psd-telemetry-complete", "type": "MANUAL_FLOW_JOB"}

    class _FakeDb:
        async def execute(self, *_args, **_kwargs):
            return _FakeCursor()

    async def fake_upsert(*_args, **_kwargs):
        return {}

    async def fake_update_request(request_id: str, **kwargs):
        captured["request_id"] = request_id
        captured["request_update"] = kwargs
        return {"id": request_id, **kwargs}

    async def fake_add_stage_event(*_args, **_kwargs):
        return {}

    async def fake_get_db():
        return _FakeDb()

    monkeypatch.setattr("agent.db.schema.get_db", fake_get_db)
    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.update_request", fake_update_request)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-06-28T08:05:00Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(
            request_id="gfv2psd-telemetry-complete",
            stage="COMPLETED",
            checkpoint="COMPLETED",
            status="PASS",
            source="extension",
            message="Job completed",
        ),
    )

    assert response.status_code == 200
    assert captured["request_id"] == "gfv2psd-telemetry-complete"
    assert captured["request_update"]["status"] == "COMPLETED"
    assert captured["request_update"]["error_message"] is None


async def _insert_request(
    request_id: str,
    *,
    request_type: str,
    status: str,
    error_message: str | None = None,
):
    db = await get_db()
    now = crud._now()
    await db.execute(
        "INSERT INTO request (id, type, status, error_message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, request_type, status, error_message, now, now),
    )
    await db.commit()


async def _insert_request_telemetry(
    request_id: str,
    *,
    request_type: str = "MANUAL_FLOW_JOB",
    status: str,
    google_flow_stage: str,
    extension_stage: str,
    error_code: str | None = None,
    error_message: str | None = None,
    completed_at: str | None = None,
    failed_at: str | None = None,
):
    db = await get_db()
    await db.execute(
        """
        INSERT INTO request_telemetry (
            request_id, request_type, status, google_flow_stage, extension_stage,
            error_code, error_message, completed_at, failed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            request_type,
            status,
            google_flow_stage,
            extension_stage,
            error_code,
            error_message,
            completed_at,
            failed_at,
        ),
    )
    await db.commit()


async def _get_request_row(request_id: str) -> dict:
    db = await get_db()
    cur = await db.execute(
        "SELECT id, type, status, error_message FROM request WHERE id = ?",
        (request_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else {}


@pytest.mark.asyncio
async def test_reconcile_failed_gfv2psd_row_and_clear_active_block():
    request_id = "gfv2psd-reconcile-failed"
    await _insert_request(request_id, request_type="MANUAL_FLOW_JOB", status="PROCESSING")
    await _insert_request_telemetry(
        request_id,
        status="FAILED",
        google_flow_stage="FAILED",
        extension_stage="FAILED",
        error_code="ERR_F2V_OPTION_VIDEO_NOT_FOUND",
        error_message="ERR_F2V_OPTION_VIDEO_NOT_FOUND",
        failed_at="2026-06-28T14:30:50Z",
    )

    reconciliation = await crud.reconcile_gfv2psd_manual_request_statuses()
    request_row = await _get_request_row(request_id)

    assert reconciliation["reconciled_count"] == 1
    assert reconciliation["reconciled_rows"][0]["request_id"] == request_id
    assert request_row["status"] == "FAILED"
    assert request_row["error_message"] == "ERR_F2V_OPTION_VIDEO_NOT_FOUND"
    assert await crud.count_active_gfv2psd_manual_requests() == 0


@pytest.mark.asyncio
async def test_reconcile_completed_gfv2psd_row_and_clear_active_block():
    request_id = "gfv2psd-reconcile-completed"
    await _insert_request(
        request_id,
        request_type="MANUAL_FLOW_JOB",
        status="PROCESSING",
        error_message="old error",
    )
    await _insert_request_telemetry(
        request_id,
        status="COMPLETED",
        google_flow_stage="COMPLETED",
        extension_stage="COMPLETED",
        completed_at="2026-06-28T14:31:50Z",
    )

    reconciliation = await crud.reconcile_gfv2psd_manual_request_statuses()
    request_row = await _get_request_row(request_id)

    assert reconciliation["reconciled_count"] == 1
    assert request_row["status"] == "COMPLETED"
    assert request_row["error_message"] is None
    assert await crud.count_active_gfv2psd_manual_requests() == 0


@pytest.mark.asyncio
async def test_genuine_active_gfv2psd_row_still_blocks():
    request_id = "gfv2psd-active-real"
    await _insert_request(request_id, request_type="MANUAL_FLOW_JOB", status="PROCESSING")

    reconciliation = await crud.reconcile_gfv2psd_manual_request_statuses()
    request_row = await _get_request_row(request_id)

    assert reconciliation["reconciled_count"] == 0
    assert request_row["status"] == "PROCESSING"
    assert await crud.count_active_gfv2psd_manual_requests() == 1


@pytest.mark.asyncio
async def test_non_gfv2psd_manual_flow_row_is_not_mutated():
    request_id = "manual-not-gfv2psd"
    await _insert_request(request_id, request_type="MANUAL_FLOW_JOB", status="PROCESSING")
    await _insert_request_telemetry(
        request_id,
        status="FAILED",
        google_flow_stage="FAILED",
        extension_stage="FAILED",
        error_code="ERR_OTHER",
        error_message="ERR_OTHER",
        failed_at="2026-06-28T14:32:50Z",
    )

    reconciliation = await crud.reconcile_gfv2psd_manual_request_statuses()
    request_row = await _get_request_row(request_id)

    assert reconciliation["reconciled_count"] == 0
    assert request_row["status"] == "PROCESSING"


@pytest.mark.asyncio
async def test_non_manual_flow_row_is_not_mutated():
    request_id = "gfv2psd-worker-row"
    await _insert_request(request_id, request_type="TRUE_F2V", status="PROCESSING")
    await _insert_request_telemetry(
        request_id,
        request_type="TRUE_F2V",
        status="FAILED",
        google_flow_stage="FAILED",
        extension_stage="FAILED",
        error_code="ERR_WORKER",
        error_message="ERR_WORKER",
        failed_at="2026-06-28T14:33:50Z",
    )

    reconciliation = await crud.reconcile_gfv2psd_manual_request_statuses()
    request_row = await _get_request_row(request_id)

    assert reconciliation["reconciled_count"] == 0
    assert request_row["status"] == "PROCESSING"
