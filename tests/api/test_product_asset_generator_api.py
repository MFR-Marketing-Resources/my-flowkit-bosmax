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


def test_preview_endpoint_returns_expected_shape(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="WARN",
            target_asset_intent=request.target_asset_intent,
            product_context={
                "product_id": "prod-001",
                "product_scale_prompt": "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "camera_capture_mode": "UGC_IPHONE_RAW",
                "ugc_camera_lock_prompt": "Raw iPhone handheld footage with subtle hand jitter.",
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
                "hook": "Hook",
                "usp_1": "USP 1",
                "cta": "CTA",
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
                "copy_readiness_status": "COPY_DERIVED_SUGGESTION",
                "execution_readiness_status": "DRY_RUN_ONLY",
                "persistence_truth": "NOT_PERSISTED",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "text_to_video_readiness_status": "NEEDS_REVIEW",
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
    assert payload["preview_status"] == "WARN"
    assert payload["product_context"]["product_id"] == "prod-001"
    assert payload["product_context"]["product_scale_prompt"]
    assert payload["product_context"]["camera_capture_mode"] == "UGC_IPHONE_RAW"
    assert payload["product_context"]["ugc_camera_lock_prompt"]
    assert payload["product_context"]["cinematic_camera_prompt"]
    assert payload["truth_status"]["profile_source_status"] == "EPHEMERAL_PREVIEW"
    assert payload["truth_status"]["copy_readiness_status"] == "COPY_DERIVED_SUGGESTION"
    assert payload["truth_status"]["persistence_truth"] == "NOT_PERSISTED"
    assert payload["execution_allowed"] is False
    assert payload["image_generation_allowed"] is False
    assert payload["flow_execution_allowed"] is False
    assert payload["batch_execution_allowed"] is False
    assert payload["dry_run_only"] is True


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
    assert payload["execution_allowed"] is False
    assert payload["image_generation_allowed"] is False
    assert payload["flow_execution_allowed"] is False
    assert payload["batch_execution_allowed"] is False


def test_endpoint_does_not_create_db_writes_or_queue_jobs(monkeypatch):
    called = {"preview": 0}

    async def fake_preview(request):
        called["preview"] += 1
        return ProductAssetGeneratorResponse(
            preview_status="FAIL",
            target_asset_intent=request.target_asset_intent,
            warning_summary=[],
            warnings=[],
            errors=["QUEUE_CREATION_NOT_ALLOWED_IN_ROUND_10"],
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
    body["create_queue_job"] = True

    response = client.post("/api/product-asset-generator/preview", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert called["preview"] == 1
    assert payload["errors"] == ["QUEUE_CREATION_NOT_ALLOWED_IN_ROUND_10"]


def test_endpoint_does_not_call_flow_extension_batch_or_runtime_modules(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="FAIL",
            target_asset_intent=request.target_asset_intent,
            warning_summary=[],
            warnings=[],
            errors=["FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_10"],
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
    body["execute_flow"] = True

    response = client.post("/api/product-asset-generator/preview", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["preview_status"] == "FAIL"
    assert payload["errors"] == ["FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_10"]


def test_preview_endpoint_shape_includes_scale_truth_and_camera_lock_fields(monkeypatch):
    async def fake_preview(request):
        return ProductAssetGeneratorResponse(
            preview_status="WARN",
            target_asset_intent=request.target_asset_intent,
            product_context={
                "product_id": "prod-001",
                "product_scale_prompt": "EXACTLY thin envelope size, flat paper packet scale, held naturally between fingers.",
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "scale_warning": "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED",
                "camera_capture_mode": "UGC_IPHONE_RAW",
                "ugc_camera_lock_prompt": "Raw iPhone handheld footage with subtle hand jitter.",
                "cinematic_camera_prompt": "Controlled cinematic camera with stable hero framing.",
            },
            warning_summary=["PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"],
            warnings=["PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"],
            errors=[],
            provenance={"scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"},
            truth_status={
                "scale_truth_status": "DERIVED_RELATIVE_SCALE",
                "text_to_video_readiness_status": "NEEDS_REVIEW",
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
    assert payload["product_context"]["product_scale_prompt"]
    assert payload["product_context"]["scale_truth_status"] == "DERIVED_RELATIVE_SCALE"
    assert payload["product_context"]["ugc_camera_lock_prompt"]
    assert payload["product_context"]["cinematic_camera_prompt"]
    assert payload["truth_status"]["text_to_video_readiness_status"] == "NEEDS_REVIEW"
