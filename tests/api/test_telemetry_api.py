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


def test_telemetry_requests_passes_request_type_and_mode_filters(monkeypatch):
    captured = {}

    async def fake_list(project_id=None, video_id=None, limit=50, **kwargs):
        captured["project_id"] = project_id
        captured["video_id"] = video_id
        captured["limit"] = limit
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr("agent.api.telemetry.crud.list_request_telemetry", fake_list)

    client = TestClient(_build_app())
    response = client.get(
        "/api/telemetry/requests",
        params={"limit": 60, "request_type": "MANUAL_FLOW_JOB", "mode": "F2V"},
    )

    assert response.status_code == 200
    assert captured["limit"] == 60
    assert captured["kwargs"]["request_type"] == "MANUAL_FLOW_JOB"
    assert captured["kwargs"]["mode"] == "F2V"


def test_failed_navigation_resume_stage_persists_terminal_error_code(monkeypatch):
    captured = {}

    async def fake_upsert(request_id: str, **kwargs):
        captured.update(kwargs)
        return {"request_id": request_id, **kwargs}

    async def fake_add_stage_event(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-05-26T12:00:00Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(
            stage="FAILED",
            checkpoint="NEW_PROJECT_NAVIGATION_PENDING",
            status="FAIL",
            message="ERR_FLOW_NAVIGATION_RESUME_TIMEOUT - editor URL did not load",
            fail_code="ERR_FLOW_NAVIGATION_RESUME_TIMEOUT",
            first_fail_stage="NEW_PROJECT_NAVIGATION_PENDING",
        ),
    )

    assert response.status_code == 200
    assert captured["status"] == "FAILED"
    assert captured["error_code"] == "ERR_FLOW_NAVIGATION_RESUME_TIMEOUT"
    assert captured["error_message"].startswith("ERR_FLOW_NAVIGATION_RESUME_TIMEOUT")


def test_resume_recursion_guard_stage_persists_clear_terminal_error(monkeypatch):
    captured = {}

    async def fake_upsert(request_id: str, **kwargs):
        captured.update(kwargs)
        return {"request_id": request_id, **kwargs}

    async def fake_add_stage_event(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr("agent.api.telemetry.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.telemetry.crud.add_stage_event", fake_add_stage_event)
    monkeypatch.setattr("agent.api.telemetry.crud._now", lambda: "2026-05-26T12:00:00Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/telemetry/stage",
        json=_valid_stage_payload(
            stage="FAILED",
            checkpoint="NEW_PROJECT_NAVIGATION_PENDING",
            status="FAIL",
            message="ERR_FLOW_RESUME_RECURSION_GUARD - resume attempt limit exceeded",
            fail_code="ERR_FLOW_RESUME_RECURSION_GUARD",
            first_fail_stage="NEW_PROJECT_NAVIGATION_PENDING",
        ),
    )

    assert response.status_code == 200
    assert captured["status"] == "FAILED"
    assert captured["error_code"] == "ERR_FLOW_RESUME_RECURSION_GUARD"
    assert captured["error_message"].startswith("ERR_FLOW_RESUME_RECURSION_GUARD")
