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


def test_execute_flow_job_materializes_i2v_refs_for_runtime_lane(monkeypatch):
    captured = {}

    class _MaterializeClient:
        connected = True

        async def execute_flow_job(self, body: dict):
            captured["body"] = body
            return {"ok": True, "request_id": body["request_id"]}

    async def fake_get_request(request_id: str):
        return {"id": request_id}

    async def fake_upsert(*args, **kwargs):
        return {}

    async def fake_stage_event(*args, **kwargs):
        return {}

    async def fake_materialize(url: str, file_name: str):
        safe_name = file_name.replace(" ", "_")
        return {
            "local_file_path": f"C:\\temp\\flowkit-upload-staging\\{safe_name}",
            "file_name": file_name,
            "mime_type": "image/png",
        }

    monkeypatch.setattr("agent.api.flow.get_flow_client", lambda: _MaterializeClient())
    monkeypatch.setattr("agent.api.flow.crud.get_request", fake_get_request)
    monkeypatch.setattr("agent.api.flow.crud.upsert_request_telemetry", fake_upsert)
    monkeypatch.setattr("agent.api.flow.crud.add_stage_event", fake_stage_event)
    monkeypatch.setattr("agent.api.flow.crud._now", lambda: "2026-07-01T00:00:00Z")
    monkeypatch.setattr("agent.api.flow._materialize_remote_url_to_staging", fake_materialize)

    client = TestClient(_build_app())
    response = client.post(
        "/api/flow/execute-flow-job",
        json={
            "request_id": "manual_i2v_001",
            "mode": "I2V",
            "lane": "WORKSPACE_FLOW_EDITOR_RUNTIME",
            "prompt": "test prompt",
            "refs": {
                "subjectAsset": {
                    "fileName": "subject.png",
                    "downloadUrl": "https://example.com/subject.png",
                },
                "sceneAsset": {
                    "fileName": "scene.png",
                    "previewUrl": "https://example.com/scene.png",
                },
                "styleAsset": {
                    "fileName": "style.png",
                    "downloadUrl": "https://example.com/style.png",
                },
            },
        },
    )

    assert response.status_code == 200
    refs = captured["body"]["refs"]
    assert refs["subjectAsset"]["localFilePath"].endswith("subject.png")
    assert refs["sceneAsset"]["localFilePath"].endswith("scene.png")
    assert refs["styleAsset"]["localFilePath"].endswith("style.png")
