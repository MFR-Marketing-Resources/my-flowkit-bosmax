from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_assets import router
from agent.models.creative_asset import CreativeAssetRecord


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_creative_asset_api_lists_assets(monkeypatch):
    async def fake_list(**kwargs):
        return [
            {
                "asset_id": "ca_001",
                "semantic_role": "CHARACTER_REFERENCE",
                "display_name": "Creator A",
                "description": "UGC creator",
                "source_type": "UPLOAD",
                "storage_kind": "LOCAL_FILE",
                "preview_url": "/api/creative-assets/ca_001/preview",
                "download_url": "/api/creative-assets/ca_001/download",
                "media_id": None,
                "local_file_path": "C:/tmp/creator.png",
                "remote_source_url": None,
                "product_id": None,
                "category": None,
                "silo": None,
                "product_type": None,
                "allowed_modes": ["I2V"],
                "engine_slot_eligibility": ["scene"],
                "mode_a_metadata_handoff": None,
                "visual_dna_summary": None,
                "character_dna": None,
                "scene_context_dna": None,
                "style_mood_dna": None,
                "source_prompt_fingerprint": None,
                "source_workspace_execution_package_id": None,
                "source_prompt_package_snapshot_id": None,
                "status": "ACTIVE",
                "created_at": "2026-05-18T00:00:00Z",
                "updated_at": "2026-05-18T00:00:00Z",
            }
        ]

    monkeypatch.setattr("agent.api.creative_assets.list_creative_assets", fake_list)

    client = TestClient(_build_app())
    response = client.get("/api/creative-assets?semantic_role=CHARACTER_REFERENCE&status=ACTIVE")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["semantic_role"] == "CHARACTER_REFERENCE"


def test_creative_asset_api_archives_asset(monkeypatch):
    async def fake_archive(asset_id: str):
        return {
            "asset_id": asset_id,
            "semantic_role": "CHARACTER_REFERENCE",
            "display_name": "Creator A",
            "description": None,
            "source_type": "UPLOAD",
            "storage_kind": "LOCAL_FILE",
            "preview_url": None,
            "download_url": None,
            "media_id": None,
            "local_file_path": None,
            "remote_source_url": None,
            "product_id": None,
            "category": None,
            "silo": None,
            "product_type": None,
            "allowed_modes": ["I2V"],
            "engine_slot_eligibility": ["scene"],
            "mode_a_metadata_handoff": None,
            "visual_dna_summary": None,
            "character_dna": None,
            "scene_context_dna": None,
            "style_mood_dna": None,
            "source_prompt_fingerprint": None,
            "source_workspace_execution_package_id": None,
            "source_prompt_package_snapshot_id": None,
            "status": "ARCHIVED",
            "created_at": "2026-05-18T00:00:00Z",
            "updated_at": "2026-05-18T00:00:00Z",
        }

    monkeypatch.setattr("agent.api.creative_assets.archive_creative_asset", fake_archive)

    client = TestClient(_build_app())
    response = client.post("/api/creative-assets/ca_001/archive", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "ARCHIVED"


def test_creative_asset_post_defaults_to_pending_review(monkeypatch):
    """The direct /creative-assets POST route must default review_status to
    PENDING_REVIEW when omitted — it must NOT silently create APPROVED assets."""
    captured = {}

    async def fake_create(request):
        captured["review_status"] = request.review_status
        return CreativeAssetRecord(
            asset_id="ca_new",
            semantic_role=request.semantic_role,
            display_name=request.display_name,
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            status="ACTIVE",
            created_at="2026-05-18T00:00:00Z",
            updated_at="2026-05-18T00:00:00Z",
        )

    monkeypatch.setattr("agent.api.creative_assets.create_creative_asset", fake_create)

    client = TestClient(_build_app())
    response = client.post(
        "/api/creative-assets",
        json={"semantic_role": "STYLE_REFERENCE", "display_name": "Style A"},
    )

    assert response.status_code == 200
    assert captured["review_status"] == "PENDING_REVIEW"
    assert response.json()["review_status"] == "PENDING_REVIEW"


def test_creative_asset_library_images_endpoint_returns_diagnostics(monkeypatch):
    async def fake_library(limit=60, mode=None):
        assert limit == 25
        assert mode == "IMG"
        return {
            "items": [
                {
                    "library_key": "creative:ca_avatar_001",
                    "artifact_kind": "image",
                    "library_source": "CREATIVE_ASSET",
                    "asset_lifecycle": "CANONICAL_AVATAR_ASSET",
                    "retention_policy": "PERSISTENT",
                    "source_asset_id": "ca_avatar_001",
                    "avatar_code": "BOS_F_ALYA_01",
                    "display_name": "Alya",
                    "media_id": "media_avatar_001",
                    "created_at": "2026-07-03T00:00:00Z",
                    "preview_url": "/api/creative-assets/ca_avatar_001/preview",
                    "download_url": "/api/creative-assets/ca_avatar_001/download",
                    "expires_at": None,
                    "expires_in_hours": None,
                }
            ],
            "diagnostics": {
                "temp_image_outputs": 0,
                "reusable_image_assets": 1,
                "reusable_avatar_assets": 1,
                "broken_avatar_assets": 0,
                "purged_temp_rows": 0,
            },
        }

    monkeypatch.setattr("agent.api.creative_assets.list_image_library_items", fake_library)

    client = TestClient(_build_app())
    response = client.get("/api/creative-assets/library-images?limit=25&mode=IMG")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["artifacts"][0]["asset_lifecycle"] == "CANONICAL_AVATAR_ASSET"
    assert payload["diagnostics"]["reusable_avatar_assets"] == 1
