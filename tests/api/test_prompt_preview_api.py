from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.prompt_preview import router
from agent.models.prompt_preview import PromptPreviewResponse


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _request_body() -> dict:
    return {
        "source_route": "PRODUCT_DRIVEN_AUTO",
        "destination_mode": "IMAGE",
        "output_type": "IMAGE_PROMPT",
        "product_payload": {"id": "prod-001", "product_display_name": "Atlas Bottle"},
        "asset_bindings": [],
        "dry_run_only": True,
    }


def test_api_endpoint_returns_expected_response_shape(monkeypatch):
    async def fake_pipeline(request):
        return PromptPreviewResponse(
            preview_status="WARN",
            source_route="PRODUCT_DRIVEN_AUTO",
            destination_mode="IMAGE",
            output_type="IMAGE_PROMPT",
            planner_output={"planning_status": "WARN"},
            adapter_output={"adapter_status": "WARN"},
            composer_output={"composer_status": "WARN", "prompt_text": "Offline prompt text."},
            temporal_output={},
            warnings=["PREVIEW_IS_OFFLINE_ONLY_NOT_FLOW_EXECUTION_READY"],
            errors=[],
            provenance={"scope": "ROUND_7_API_PREVIEW_LAYER_ONLY"},
            execution_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
            dry_run_only=True,
        )

    monkeypatch.setattr("agent.api.prompt_preview.run_prompt_preview_pipeline", fake_pipeline)
    client = TestClient(_build_app())

    response = client.post("/api/prompt-preview/offline", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_status"] == "WARN"
    assert payload["planner_output"]["planning_status"] == "WARN"
    assert payload["adapter_output"]["adapter_status"] == "WARN"
    assert payload["composer_output"]["composer_status"] == "WARN"
    assert payload["execution_allowed"] is False
    assert payload["flow_execution_allowed"] is False
    assert payload["batch_execution_allowed"] is False
    assert payload["dry_run_only"] is True


def test_api_endpoint_does_not_trigger_flow_dom_batch_or_runtime_execution(monkeypatch):
    calls = {"pipeline": 0}

    async def fake_pipeline(request):
        calls["pipeline"] += 1
        return PromptPreviewResponse(
            preview_status="FAIL",
            source_route=request.source_route,
            destination_mode=request.destination_mode,
            output_type=request.output_type,
            warnings=[],
            errors=["DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_7"],
            provenance={"scope": "ROUND_7_API_PREVIEW_LAYER_ONLY"},
            execution_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
            dry_run_only=True,
        )

    monkeypatch.setattr("agent.api.prompt_preview.run_prompt_preview_pipeline", fake_pipeline)
    client = TestClient(_build_app())
    body = _request_body()
    body["execute_dom"] = True

    response = client.post("/api/prompt-preview/offline", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert calls["pipeline"] == 1
    assert payload["preview_status"] == "FAIL"
    assert payload["errors"] == ["DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_7"]
    assert payload["execution_allowed"] is False
    assert payload["flow_execution_allowed"] is False
    assert payload["batch_execution_allowed"] is False
