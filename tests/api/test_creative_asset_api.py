from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_assets import router


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
