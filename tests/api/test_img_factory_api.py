"""IMG Asset Factory v1 — API surface contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.img_factory import router
from agent.models.creative_asset import CreativeAssetRecord
from agent.models.f2v_frame_source_resolver import (
    F2VFrameSourceResolverResponse,
    F2VResolvedFrame,
)
from agent.models.img_asset_factory import ImgFastlanePromptPreviewResponse


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_lanes_endpoint_returns_seven_lanes():
    client = TestClient(_build_app())
    response = client.get("/api/img-factory/lanes")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 7
    lane_ids = {item["lane_id"] for item in payload["items"]}
    assert "PRODUCT_POSTER" in lane_ids
    poster = next(i for i in payload["items"] if i["lane_id"] == "PRODUCT_POSTER")
    assert poster["default_contains_rendered_text"] is True
    assert poster["default_approved_for_video_support"] is False


def test_provider_status_is_honest():
    client = TestClient(_build_app())
    response = client.get("/api/img-factory/provider-status")
    assert response.status_code == 200
    payload = response.json()
    # Must NOT over-claim RUNTIME_PROVEN — generation runtime is external and not
    # re-verified in this PR.
    assert payload["provider_state"] == "SAVE_TO_LIBRARY_READY_GENERATION_RUNTIME_EXTERNAL"
    assert payload["generation_endpoint"] == "/api/flow/execute-flow-job"


def test_fastlane_presets_endpoint_returns_required_presets():
    client = TestClient(_build_app())
    response = client.get("/api/img-factory/fastlane-presets")
    assert response.status_code == 200
    payload = response.json()
    preset_ids = {item["preset_id"] for item in payload["items"]}
    assert {
        "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF",
        "BOSMAX_SERUM_AVATAR_PRODUCT_2REF",
        "MWCB_WG40_AVATAR_BOTTLE",
        "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
        "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
    }.issubset(preset_ids)


def test_fastlane_preview_endpoint_returns_compiled_prompt(monkeypatch):
    async def fake_compile(request):
        return ImgFastlanePromptPreviewResponse(
            preset_id=request.preset_id,
            route=request.route,
            ingredient_role=request.ingredient_role,
            lane_id="AVATAR_PRODUCT_COMPOSITE",
            prompt_text="compiled prompt",
            display_name_suggestion="Bosmax Herbs 5 ML - Hero",
            blockers=[],
            warnings=[],
            output_spec="Vertical TikTok 9:16 commercial image.",
            negative_rules=["No drift."],
            reference_map=["Ref 1 = avatar identity lock"],
        )

    monkeypatch.setattr("agent.api.img_factory.compile_img_fastlane_prompt_preview", fake_compile)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/fastlane-preview",
        json={
            "preset_id": "BOSMAX_SERUM_AVATAR_PRODUCT_2REF",
            "route": "FRAMES",
            "product_id": "prod-bosmax",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["prompt_text"] == "compiled prompt"
    assert payload["lane_id"] == "AVATAR_PRODUCT_COMPOSITE"


def test_fastlane_preview_endpoint_maps_value_error_to_400(monkeypatch):
    async def fake_compile(request):
        raise ValueError("UNKNOWN_FASTLANE_PRESET")

    monkeypatch.setattr("agent.api.img_factory.compile_img_fastlane_prompt_preview", fake_compile)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/fastlane-preview",
        json={
            "preset_id": "UNKNOWN",
            "route": "FRAMES",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "UNKNOWN_FASTLANE_PRESET"


def test_fastlane_preview_invalid_creative_mode_is_controlled_4xx(monkeypatch):
    from agent.services.creative_direction_service import CreativeDirectionError

    async def fake_compile(request):
        raise CreativeDirectionError("UNSUPPORTED_CREATIVE_MODE")

    monkeypatch.setattr("agent.api.img_factory.compile_img_fastlane_prompt_preview", fake_compile)
    response = TestClient(_build_app()).post(
        "/api/img-factory/fastlane-preview",
        json={"preset_id": "UNKNOWN", "route": "FRAMES", "creative_mode": "UNSAFE_MODE"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "UNSUPPORTED_CREATIVE_MODE"


def test_save_multiple_sources_returns_400(monkeypatch):
    async def fake_save(request):
        raise ValueError("MULTIPLE_OUTPUT_SOURCES_NOT_ALLOWED")

    monkeypatch.setattr("agent.api.img_factory.save_img_output_to_library", fake_save)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/save",
        json={
            "lane_id": "AVATAR_REFERENCE",
            "display_name": "x",
            "generated_artifact_media_id": "m1",
            "image_base64": "aGVsbG8=",
        },
    )
    assert response.status_code == 400
    assert "MULTIPLE_OUTPUT_SOURCES_NOT_ALLOWED" in response.json()["detail"]


def test_save_product_not_found_returns_404(monkeypatch):
    async def fake_save(request):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr("agent.api.img_factory.save_img_output_to_library", fake_save)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/save",
        json={
            "lane_id": "PRODUCT_ONLY_HERO",
            "display_name": "x",
            "image_base64": "aGVsbG8=",
            "product_id": "nope",
        },
    )
    assert response.status_code == 404
    assert "PRODUCT_NOT_FOUND" in response.json()["detail"]


def test_save_endpoint_persists(monkeypatch):
    async def fake_save(request):
        return CreativeAssetRecord(
            asset_id="ca_saved",
            semantic_role="CHARACTER_REFERENCE",
            display_name=request.display_name,
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            allowed_modes=["I2V"],
            engine_slot_eligibility=["scene"],
            generation_recipe_id="AVATAR_REFERENCE",
            review_status="APPROVED",
            status="ACTIVE",
            created_at="2026-05-18T00:00:00Z",
            updated_at="2026-05-18T00:00:00Z",
        )

    monkeypatch.setattr("agent.api.img_factory.save_img_output_to_library", fake_save)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/save",
        json={
            "lane_id": "AVATAR_REFERENCE",
            "display_name": "Avatar A",
            "image_base64": "aGVsbG8=",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "ca_saved"
    assert payload["generation_recipe_id"] == "AVATAR_REFERENCE"


def test_save_unknown_lane_returns_400(monkeypatch):
    async def fake_save(request):
        raise ValueError("UNSUPPORTED_IMG_LANE")

    monkeypatch.setattr("agent.api.img_factory.save_img_output_to_library", fake_save)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/save",
        json={"lane_id": "NOPE", "display_name": "x", "image_base64": "aGVsbG8="},
    )
    assert response.status_code == 400
    assert "UNSUPPORTED_IMG_LANE" in response.json()["detail"]


def test_save_missing_artifact_returns_404(monkeypatch):
    async def fake_save(request):
        raise ValueError("GENERATED_ARTIFACT_NOT_FOUND")

    monkeypatch.setattr("agent.api.img_factory.save_img_output_to_library", fake_save)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/save",
        json={
            "lane_id": "PRODUCT_ONLY_HERO",
            "display_name": "x",
            "generated_artifact_media_id": "missing",
            "product_id": "p1",
        },
    )
    assert response.status_code == 404


def test_f2v_frame_sources_endpoint(monkeypatch):
    async def fake_resolve(request):
        return F2VFrameSourceResolverResponse(
            start_frame=F2VResolvedFrame(
                slot_key="start_frame",
                source_kind="COMPOSITE_FRAME_REFERENCE",
                asset_id="ca_comp",
            ),
            resolved_frames=[
                F2VResolvedFrame(
                    slot_key="start_frame",
                    source_kind="COMPOSITE_FRAME_REFERENCE",
                    asset_id="ca_comp",
                )
            ],
            warnings=["END_FRAME_OPTIONAL_NOT_SELECTED"],
            blockers=[],
        )

    monkeypatch.setattr("agent.api.img_factory.resolve_f2v_frame_sources", fake_resolve)
    client = TestClient(_build_app())
    response = client.post(
        "/api/img-factory/f2v-frame-sources",
        json={"start_frame_asset_id": "ca_comp"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "F2V"
    assert payload["start_frame"]["source_kind"] == "COMPOSITE_FRAME_REFERENCE"
