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


def test_generate_endpoint_includes_copy_quality_and_direct_commercial_copy(monkeypatch):
    async def fake_generate(request):
        return CopySignalGenerateResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            route="DIRECT",
            review_status="AUTO_APPROVED",
            copy_quality_status="COMMERCIAL_COPY_READY",
            text_to_video_readiness_status="READY",
            content_style_mode=request.content_style_mode,
            authority_files_found=["SCRIPT_REGISTRY_UNIFIED.yaml"],
            product_context={
                "product_scale_prompt": "EXACTLY wearable garment scale with natural two-hand drape and no enlargement.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "UGC_IPHONE_RAW",
                "ugc_camera_lock_prompt": "Raw iPhone handheld footage with subtle hand jitter.",
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
            },
            copy_signals={
                "hook": "Baju tidur nak selesa tapi tetap nampak kemas?",
                "usp_1": "Potongan longgar senang dipakai untuk rehat harian.",
                "usp_2": "Kain nampak ringan dan mudah digayakan di rumah.",
                "usp_3": "Sesuai untuk video demo sebab bentuk dan jatuhan kain jelas nampak.",
                "cta": "Pilih warna dan size yang sesuai sebelum checkout.",
                "overlay_copy": "A14 nampak selesa, kemas, dan mudah digaya.",
                "dialogue_opening": "Baju tidur nak selesa tapi tetap nampak kemas?",
                "dialogue_body": "Potongan nampak longgar dan kain jatuh elok untuk demo rumah.",
                "dialogue_cta": "Pilih warna dan size yang sesuai sebelum checkout.",
                "copy_quality_status": "COMMERCIAL_COPY_READY",
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
            "product_payload": {
                "id": "prod-001",
                "product_display_name": "A14 - Alyanaa Baju Kelawar Moden / Baju Tidur",
                "language": "Malay",
            },
            "content_style_mode": "UGC_IPHONE",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["copy_quality_status"] == "COMMERCIAL_COPY_READY"
    assert payload["text_to_video_readiness_status"] == "READY"
    assert "prompt package" not in payload["copy_signals"]["cta"].lower()
    assert "execution" not in payload["copy_signals"]["cta"].lower()
    assert payload["copy_signals"]["hook"].startswith("Baju tidur")
    assert payload["product_context"]["camera_capture_mode"] == "UGC_IPHONE_RAW"


def test_generate_endpoint_keeps_stealth_payload_review_gated(monkeypatch):
    async def fake_generate(request):
        return CopySignalGenerateResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            route="STEALTH",
            review_status="REVIEW_REQUIRED",
            copy_quality_status="REVIEW_REQUIRED",
            text_to_video_readiness_status="NEEDS_REVIEW",
            content_style_mode=request.content_style_mode,
            authority_files_found=["SCRIPT_VARIANT_LIBRARY.yaml"],
            product_context={
                "product_scale_prompt": "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "CINEMATIC_PRO_CONTROLLED",
                "ugc_camera_lock_prompt": None,
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
            },
            copy_signals={
                "stealth_silo": "health_supp_stealth_01",
                "metaphor_family": "DIALOGUE_SAFE_ROUTINE",
                "formula": "STEALTH_DIALOGUE_SAFE",
                "hook": "Bila hari terasa panjang, ramai suka cari rutin yang rasa lebih teratur.",
                "problem": "Bila mesej jualan terlalu terus terang, audiens cepat rasa menjauh.",
                "agitate": "Nada yang keras boleh buat produk sensitif nampak tidak selesa untuk ditonton.",
                "solution": "Gunakan metafora dialog selamat sambil kekalkan visual literal.",
                "usp_1": "Naratif rutin kekal lembut.",
                "usp_2": "Dialog kekal selamat tanpa claim sensitif.",
                "usp_3": "Semua mesej perlu semakan manusia.",
                "cta": "Semak naratif dialog ini dulu sebelum guna untuk output video.",
                "human_review_reason": "STEALTH_PRODUCT_REQUIRES_DIALOGUE_ONLY_REVIEW",
                "copy_quality_status": "REVIEW_REQUIRED",
            },
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
    assert payload["copy_quality_status"] == "REVIEW_REQUIRED"
    assert payload["text_to_video_readiness_status"] == "NEEDS_REVIEW"
    assert payload["visual_dialogue_isolation"]["visual_metaphor_allowed"] is False
    assert payload["visual_dialogue_isolation"]["dialogue_metaphor_allowed"] is True


def test_generate_endpoint_does_not_mark_bad_fallback_copy_commercial_ready(monkeypatch):
    async def fake_generate(request):
        return CopySignalGenerateResponse(
            scope="COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER",
            route="DIRECT",
            review_status="AUTO_APPROVED",
            copy_quality_status="FALLBACK_COPY_DRAFT",
            text_to_video_readiness_status="NEEDS_REVIEW",
            content_style_mode=request.content_style_mode,
            authority_files_found=["SCRIPT_REGISTRY_UNIFIED.yaml"],
            product_context={},
            copy_signals={
                "hook": "Mystery Gadget leads with confidence.",
                "usp_1": "Use Mystery Gadget with use steady hands.",
                "usp_2": "Keep the demo grounded in a studio setup.",
                "usp_3": "Show the product clearly before any performance implication.",
                "cta": "Review the prompt package before any execution.",
                "copy_quality_status": "FALLBACK_COPY_DRAFT",
                "warning": "COPY_QUALITY_FALLBACK_DRAFT",
            },
            claim_safety={"requires_human_review": False},
            visual_dialogue_isolation={
                "status": "PASS",
                "visual_metaphor_allowed": False,
                "dialogue_metaphor_allowed": False,
            },
            warnings=["COPY_QUALITY_FALLBACK_DRAFT"],
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
            "product_payload": {"id": "prod-003", "product_display_name": "Mystery Gadget"},
            "content_style_mode": "UGC_IPHONE",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["copy_quality_status"] == "FALLBACK_COPY_DRAFT"
    assert payload["text_to_video_readiness_status"] == "NEEDS_REVIEW"
    assert payload["copy_signals"]["warning"] == "COPY_QUALITY_FALLBACK_DRAFT"
