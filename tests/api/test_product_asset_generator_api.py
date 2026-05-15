from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_asset_generator import router
from agent.models.product_asset_generator import ProductAssetGeneratorResponse


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _request_body() -> dict:
    return {
        "product_payload": {
            "id": "prod-001",
            "product_display_name": "Atlas Bottle",
            "raw_product_title": "Atlas Bottle Original",
        },
        "target_asset_intent": "CHARACTER_CONCEPT",
        "dry_run_only": True,
    }


def test_preview_endpoint_includes_copy_quality_status(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="WARN",
            target_asset_intent=request.target_asset_intent,
            product_context={
                "product_id": "prod-001",
                "group": "BEAUTY_AND_PERSONAL_CARE",
                "sub_group": "PERSONAL_CARE",
                "type_of_product": "BEAUTY_PERSONAL_CARE_PRODUCT",
                "claim_gate": "CLAIM_SAFE",
                "product_scale_prompt": "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "UGC_IPHONE_RAW",
                "ugc_camera_lock_prompt": "Raw iPhone handheld footage with subtle hand jitter.",
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
                "hook": "Nak nampak kemas tanpa routine yang leceh?",
                "usp_1": "Mudah ditunjuk dalam demo close-up.",
                "usp_2": "Saiz produk sesuai untuk genggaman tangan.",
                "usp_3": "Sesuai untuk routine harian tanpa claim berlebihan.",
                "cta": "Check pilihan produk dan cuba ikut keperluan kau.",
                "copy_quality_status": "COMMERCIAL_COPY_READY",
                "copy_route": "DIRECT",
                "copy_review_status": "AUTO_APPROVED",
            },
            derived_asset_suggestions=[{"asset_role": "SUBJECT_CHARACTER"}],
            prompt_suggestions=[{"suggestion_type": "character_concept_card"}],
            required_assets=[{"asset_role": "SUBJECT_CHARACTER"}],
            missing_assets=[{"asset_role": "SUBJECT_CHARACTER_IMAGE"}],
            handling_notes=["Derived handling guidance."],
            physics_notes=["Derived physics guidance."],
            scene_notes=["Derived scene guidance."],
            camera_notes=["Derived camera guidance."],
            warning_summary=["PREVIEW_ONLY_NOT_GENERATED_ASSET"],
            warnings=["PREVIEW_ONLY_NOT_GENERATED_ASSET"],
            errors=[],
            provenance={"scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"},
            truth_status={
                "overall_source_status": "DERIVED_FROM_PRODUCT_DATA",
                "profile_source_status": "EPHEMERAL_PREVIEW",
                "group": "BEAUTY_AND_PERSONAL_CARE",
                "sub_group": "PERSONAL_CARE",
                "type_of_product": "BEAUTY_PERSONAL_CARE_PRODUCT",
                "claim_gate": "CLAIM_SAFE",
                "copy_quality_status": "COMMERCIAL_COPY_READY",
                "copy_readiness_status": "COPY_READY",
                "execution_readiness_status": "DRY_RUN_ONLY",
                "persistence_truth": "NOT_PERSISTED",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "text_to_video_readiness_status": "READY",
            },
            dry_run_only=True,
            execution_allowed=False,
            image_generation_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
        )

    monkeypatch.setattr(
        "agent.api.product_asset_generator.generate_product_asset_preview",
        fake_preview,
    )
    client = TestClient(_build_app())

    response = client.post("/api/product-asset-generator/preview", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["truth_status"]["copy_quality_status"] == "COMMERCIAL_COPY_READY"
    assert payload["truth_status"]["text_to_video_readiness_status"] == "READY"
    assert payload["truth_status"]["claim_gate"] == "CLAIM_SAFE"
    assert payload["product_context"]["copy_quality_status"] == "COMMERCIAL_COPY_READY"


def test_preview_endpoint_keeps_fallback_draft_text_to_video_in_needs_review(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="WARN",
            target_asset_intent=request.target_asset_intent,
            product_context={
                "product_id": "prod-002",
                "hook": "Mystery Gadget leads with confidence.",
                "usp_1": "Use Mystery Gadget with use steady hands.",
                "cta": "Review the prompt package before any execution.",
                "copy_quality_status": "FALLBACK_COPY_DRAFT",
                "copy_route": "DIRECT",
                "copy_review_status": "AUTO_APPROVED",
            },
            derived_asset_suggestions=[],
            prompt_suggestions=[],
            required_assets=[],
            missing_assets=[],
            handling_notes=[],
            physics_notes=[],
            scene_notes=[],
            camera_notes=[],
            warning_summary=["COPY_QUALITY_FALLBACK_DRAFT"],
            warnings=["COPY_QUALITY_FALLBACK_DRAFT"],
            errors=[],
            provenance={"scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"},
            truth_status={
                "profile_source_status": "EPHEMERAL_PREVIEW",
                "copy_quality_status": "FALLBACK_COPY_DRAFT",
                "copy_readiness_status": "COPY_DERIVED_SUGGESTION",
                "text_to_video_readiness_status": "NEEDS_REVIEW",
                "execution_readiness_status": "DRY_RUN_ONLY",
                "persistence_truth": "NOT_PERSISTED",
            },
            dry_run_only=True,
            execution_allowed=False,
            image_generation_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
        )

    monkeypatch.setattr(
        "agent.api.product_asset_generator.generate_product_asset_preview",
        fake_preview,
    )
    client = TestClient(_build_app())

    response = client.post("/api/product-asset-generator/preview", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["truth_status"]["copy_quality_status"] == "FALLBACK_COPY_DRAFT"
    assert payload["truth_status"]["text_to_video_readiness_status"] == "NEEDS_REVIEW"


def test_preview_endpoint_keeps_review_gated_stealth_output_not_ready(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="WARN",
            target_asset_intent=request.target_asset_intent,
            product_context={
                "product_id": "prod-003",
                "copy_quality_status": "REVIEW_REQUIRED",
                "copy_route": "STEALTH",
                "copy_review_status": "REVIEW_REQUIRED",
                "dialogue_opening": "Bila hari terasa panjang, ramai suka cari rutin yang rasa lebih teratur.",
                "dialogue_body": "Dialog kekal selamat tanpa claim sensitif.",
                "dialogue_cta": "Semak naratif dialog ini dulu sebelum guna untuk output video.",
            },
            derived_asset_suggestions=[],
            prompt_suggestions=[],
            required_assets=[],
            missing_assets=[],
            handling_notes=[],
            physics_notes=[],
            scene_notes=[],
            camera_notes=[],
            warning_summary=["COPY_ROUTE_REVIEW_REQUIRED"],
            warnings=["COPY_ROUTE_REVIEW_REQUIRED"],
            errors=[],
            provenance={"scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"},
            truth_status={
                "profile_source_status": "EPHEMERAL_PREVIEW",
                "copy_quality_status": "REVIEW_REQUIRED",
                "copy_readiness_status": "COPY_DERIVED_SUGGESTION",
                "text_to_video_readiness_status": "NEEDS_REVIEW",
                "execution_readiness_status": "DRY_RUN_ONLY",
                "persistence_truth": "NOT_PERSISTED",
            },
            dry_run_only=True,
            execution_allowed=False,
            image_generation_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
        )

    monkeypatch.setattr(
        "agent.api.product_asset_generator.generate_product_asset_preview",
        fake_preview,
    )
    client = TestClient(_build_app())

    response = client.post("/api/product-asset-generator/preview", json=_request_body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["truth_status"]["copy_quality_status"] == "REVIEW_REQUIRED"
    assert payload["truth_status"]["text_to_video_readiness_status"] != "READY"


def test_dry_run_only_false_returns_fail_payload(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="FAIL",
            target_asset_intent=request.target_asset_intent,
            warning_summary=[],
            warnings=[],
            errors=["DRY_RUN_ONLY_FALSE_NOT_ALLOWED"],
            provenance={"scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"},
            truth_status={},
            dry_run_only=True,
            execution_allowed=False,
            image_generation_allowed=False,
            flow_execution_allowed=False,
            batch_execution_allowed=False,
        )

    monkeypatch.setattr(
        "agent.api.product_asset_generator.generate_product_asset_preview",
        fake_preview,
    )
    client = TestClient(_build_app())
    body = _request_body()
    body["dry_run_only"] = False

    response = client.post("/api/product-asset-generator/preview", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_status"] == "FAIL"
    assert payload["errors"] == ["DRY_RUN_ONLY_FALSE_NOT_ALLOWED"]
