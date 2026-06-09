import json
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.flow import router


class _FakeClient:
    connected = True

    async def execute_flow_job(self, body: dict):
        return {"ok": True, "request_id": body["request_id"]}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_execute_flow_job_persists_request_lineage(monkeypatch):
    captured = {}

    async def fake_get_request(request_id: str):
        return {"id": request_id}

    async def fake_upsert(request_id: str, **kwargs):
        captured["request_id"] = request_id
        captured["kwargs"] = kwargs
        return {"request_id": request_id, **kwargs}

    async def fake_stage_event(*args, **kwargs):
        return {}

    monkeypatch.setattr("agent.api.flow.get_flow_client", lambda: _FakeClient())
    monkeypatch.setattr("agent.api.flow.crud.get_request", fake_get_request)
    monkeypatch.setattr("agent.api.flow.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.flow.crud.add_stage_event", fake_stage_event)
    monkeypatch.setattr("agent.api.flow.crud._now", lambda: "2026-05-17T00:00:00Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/flow/execute-flow-job",
        json={
            "request_id": "manual_lineage_001",
            "mode": "F2V",
            "product_id": "prod-001",
            "prompt_package_snapshot_id": "pkg_001",
            "workspace_execution_package_id": "wep_001",
            "prompt_fingerprint": "fp_001",
            "asset_fingerprints": ["asset_001"],
            "request_lineage_payload": {"product_id": "prod-001", "mode": "F2V"},
        },
    )

    assert response.status_code == 200
    assert captured["request_id"] == "manual_lineage_001"
    assert captured["kwargs"]["product_id"] == "prod-001"
    assert captured["kwargs"]["prompt_package_snapshot_id"] == "pkg_001"
    assert captured["kwargs"]["workspace_execution_package_id"] == "wep_001"


class _FailingClient:
    connected = True

    async def execute_flow_job(self, body: dict):
        return {"ok": False, "error": "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"}


def test_execute_flow_job_failure_persists_snapshot_visible_report(monkeypatch):
    captured = {
        "telemetry": [],
        "request_updates": [],
        "stage_events": [],
    }

    async def fake_get_request(request_id: str):
        return {"id": request_id}

    async def fake_upsert(request_id: str, **kwargs):
        captured["telemetry"].append({"request_id": request_id, **kwargs})
        return {"request_id": request_id, **kwargs}

    async def fake_update_request(request_id: str, **kwargs):
        captured["request_updates"].append({"request_id": request_id, **kwargs})
        return {"id": request_id, **kwargs}

    async def fake_stage_event(request_id: str, stage: str, status: str, message=None, source="backend", **extra):
        captured["stage_events"].append(
            {
                "request_id": request_id,
                "stage": stage,
                "status": status,
                "message": message,
                "source": source,
                "extra": extra,
            }
        )
        return {}

    async def fake_stage_history(request_id: str):
        return [
            {
                "stage": "F2V_SOP_TARGET_TAB_RESOLVED",
                "status": "PASS",
                "source": "extension",
                "message": '{"selected_tab":{"url":"https://labs.google/fx/tools/flow"},"candidate_tabs":[{"url":"https://labs.google/fx/tools/flow"}]}',
            },
            {
                "stage": "F2V_SOP_SETTINGS_OPENER_SCAN",
                "status": "PASS",
                "source": "extension",
                "message": '{"target_tab_url":"https://labs.google/fx/tools/flow","document_title":"Flow","composer_present":false,"prompt_field_present":false,"candidate_settings_launchers_found":12,"attempted_strategies":["model_chip"]}',
            },
            {
                "stage": "F2V_SOP_SETTINGS_PANEL_OPENED",
                "status": "FAIL",
                "source": "extension",
                "message": 'ERR_F2V_SETTINGS_PANEL_NOT_OPEN detail={"reason":"no_settings_launcher_found","target_tab_url":"https://labs.google/fx/tools/flow","document_title":"Flow","visible_button_texts":["New project"],"visible_aria_labels":["Go to banner 1"],"composer_present":false,"prompt_field_present":false,"candidate_settings_launchers_found":[{"text":"New project"}],"attempted_strategies":[{"strategy":"model_chip","reason":"no_candidates"}]}',
            },
        ]

    monkeypatch.setattr("agent.api.flow.get_flow_client", lambda: _FailingClient())
    monkeypatch.setattr("agent.api.flow.crud.get_request", fake_get_request)
    monkeypatch.setattr("agent.api.flow.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.flow.crud.update_request", fake_update_request)
    monkeypatch.setattr("agent.api.flow.crud.add_stage_event", fake_stage_event)
    monkeypatch.setattr("agent.api.flow.crud.get_stage_history", fake_stage_history)
    monkeypatch.setattr("agent.api.flow.crud._now", lambda: "2026-05-28T05:31:55Z")

    client = TestClient(_build_app())
    response = client.post(
        "/api/flow/execute-flow-job",
        json={
            "request_id": "manual_failure_001",
            "mode": "F2V",
            "product_id": "prod-001",
            "prompt_package_snapshot_id": "pkg_001",
            "workspace_execution_package_id": "wep_001",
            "prompt_fingerprint": "fp_001",
            "asset_fingerprints": ["asset_001"],
            "request_lineage_payload": {"product_id": "prod-001", "mode": "F2V"},
        },
    )

    assert response.status_code == 502
    latest_telemetry = captured["telemetry"][-1]
    assert latest_telemetry["status"] == "FAILED"
    assert latest_telemetry["error_code"] == "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"
    assert latest_telemetry["error_message"] == "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"

    request_update = captured["request_updates"][-1]
    assert request_update["status"] == "FAILED"
    assert request_update["error_message"] == "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"
    report = json.loads(request_update["automation_report"])
    assert report["error_code"] == "ERR_F2V_SETTINGS_PANEL_NOT_OPEN"
    assert report["target_tab_url"] == "https://labs.google/fx/tools/flow"
    assert report["candidate_tabs"] == [{"url": "https://labs.google/fx/tools/flow"}]
    assert report["document_title"] == "Flow"
    assert report["visible_button_texts"] == ["New project"]
    assert report["visible_aria_labels"] == ["Go to banner 1"]
    assert report["composer_present"] is False
    assert report["prompt_field_present"] is False
