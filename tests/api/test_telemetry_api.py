from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.telemetry import router


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
