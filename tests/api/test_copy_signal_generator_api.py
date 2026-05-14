from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_signals import router
from agent.models.copy_signal_generator import (
    CopySignalGenerateResponse,
    CopySignalRoutesResponse,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_routes_endpoint_returns_authority_and_supported_modes(monkeypatch):
    monkeypatch.setattr(
        "agent.api.copy_signals.get_copy_signal_routes_summary",
        lambda: CopySignalRoutesResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            routes=["DIRECT", "STEALTH", "REVIEW_REQUIRED"],
            content_style_modes=["UGC_IPHONE", "CINEMATIC_PRO"],
            authority_files_found=["SCRIPT_REGISTRY_UNIFIED.yaml"],
            authority_files_missing=[],
        ),
    )
    client = TestClient(_build_app())

    response = client.get("/api/copy-signals/routes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["routes"] == ["DIRECT", "STEALTH", "REVIEW_REQUIRED"]
    assert payload["content_style_modes"] == ["UGC_IPHONE", "CINEMATIC_PRO"]


def test_generate_endpoint_includes_scale_and_camera_lock_fields(monkeypatch):
    async def fake_generate(request):
        return CopySignalGenerateResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            route="DIRECT",
            review_status="AUTO_APPROVED",
            content_style_mode=request.content_style_mode,
            authority_files_found=["SCRIPT_REGISTRY_UNIFIED.yaml"],
            product_context={
                "product_scale_prompt": "EXACTLY lip balm size, fit into fingers naturally.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "UGC_IPHONE_RAW",
                "ugc_camera_lock_prompt": "Raw iPhone handheld footage with subtle hand jitter.",
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
            },
            copy_signals={
                "hook": "Hook",
                "usp_1": "USP 1",
                "usp_2": "USP 2",
                "usp_3": "USP 3",
                "cta": "CTA",
            },
            claim_safety={"requires_human_review": False},
            visual_dialogue_isolation={
                "status": "PASS",
                "visual_metaphor_allowed": False,
                "dialogue_metaphor_allowed": False,
            },
            warnings=[],
            provenance={"scope": "COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER"},
        )

    monkeypatch.setattr(
        "agent.api.copy_signals.generate_copy_signal_response",
        fake_generate,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/copy-signals/generate",
        json={
            "product_payload": {"id": "prod-001", "product_display_name": "Atlas Lip Balm"},
            "content_style_mode": "UGC_IPHONE",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_context"]["product_scale_prompt"]
    assert payload["product_context"]["scale_truth_status"] == "DERIVED_RELATIVE_SCALE"
    assert payload["product_context"]["camera_capture_mode"] == "UGC_IPHONE_RAW"
    assert payload["product_context"]["ugc_camera_lock_prompt"]
    assert payload["product_context"]["cinematic_camera_prompt"]


def test_generate_endpoint_supports_cinematic_and_stealth_review_shape(monkeypatch):
    async def fake_generate(request):
        return CopySignalGenerateResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            route="STEALTH",
            review_status="REVIEW_REQUIRED",
            content_style_mode=request.content_style_mode,
            authority_files_found=["SCRIPT_VARIANT_LIBRARY.yaml"],
            product_context={
                "product_scale_prompt": "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "CINEMATIC_PRO_CONTROLLED",
                "ugc_camera_lock_prompt": None,
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
            },
            copy_signals={"hook": "Stealth hook", "usp_1": "USP", "usp_2": "USP", "usp_3": "USP", "cta": "CTA"},
            claim_safety={"requires_human_review": True},
            visual_dialogue_isolation={
                "status": "ENFORCED",
                "visual_metaphor_allowed": False,
                "dialogue_metaphor_allowed": True,
            },
            warnings=["COPY_ROUTE_REVIEW_REQUIRED"],
            provenance={"scope": "COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER"},
        )

    monkeypatch.setattr(
        "agent.api.copy_signals.generate_copy_signal_response",
        fake_generate,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/copy-signals/generate",
        json={
            "product_payload": {"id": "prod-002", "product_display_name": "Stealth Bottle"},
            "content_style_mode": "CINEMATIC_PRO",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "STEALTH"
    assert payload["review_status"] == "REVIEW_REQUIRED"
    assert payload["product_context"]["camera_capture_mode"] == "CINEMATIC_PRO_CONTROLLED"
    assert payload["product_context"]["cinematic_camera_prompt"]
    assert payload["visual_dialogue_isolation"]["dialogue_metaphor_allowed"] is True