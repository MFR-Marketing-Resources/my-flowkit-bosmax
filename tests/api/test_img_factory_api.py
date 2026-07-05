"""IMG Asset Factory v1 — API surface contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.img_factory import router
from agent.models.creative_asset import CreativeAssetRecord
from agent.models.f2v_frame_source_resolver import (
    F2VFrameSourceResolverResponse,
    F2VResolvedFrame,
)


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
    assert payload["provider_state"] == "RUNTIME_PROVEN"
    assert payload["generation_endpoint"] == "/api/flow/execute-flow-job"


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
