import pytest

from agent.services.workspace_execution_package_service import (
    create_workspace_execution_package,
    list_workspace_execution_packages,
)


@pytest.mark.asyncio
async def test_workspace_execution_package_uses_product_cached_asset(monkeypatch):
    captured = {}

    async def fake_package(product_id: str, mode: str):
        return {
            "prompt_package_snapshot_id": "pkg_123",
            "product_id": product_id,
            "product_name": "Bosmax Herbs 5 ML",
            "mode": mode,
            "production_generation_allowed": False,
            "prompt_text": "Frames prompt",
            "prompt_fingerprint": "fingerprint_123",
            "asset_slots": [
                {
                    "slot_key": "start_frame",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "USER_UPLOAD"],
                    "resolved_asset": {
                        "asset_id": "product-image:prod-001:start_frame",
                        "asset_fingerprint": "asset_fp_001",
                        "slot_key": "start_frame",
                        "asset_source": "PRODUCT_IMAGE_CACHE",
                        "label": "Product cached image",
                        "file_name": "prod-001.jpg",
                        "preview_url": "/api/products/prod-001/image",
                        "download_url": "/api/products/prod-001/image",
                        "media_id": None,
                    },
                },
                {
                    "slot_key": "end_frame",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
            ],
            "manual_fallback": {"copy_prompt_available": True, "execution_checklist": ["Copy prompt"]},
            "blockers": [],
            "source_of_truth_notes": ["Product truth remains on the product row."],
        }

    async def fake_store(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr("agent.services.workspace_execution_package_service.get_approved_product_package", fake_package)
    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.create_or_replace_workspace_execution_package", fake_store)

    result = await create_workspace_execution_package("prod-001", "F2V", 8, "9:16", "Veo 3.1 - Lite", False)

    assert result["readiness"] == "READY"
    assert result["resolved_assets"][0]["asset_source"] == "PRODUCT_IMAGE_CACHE"
    assert result["request_lineage_payload"]["prompt_package_snapshot_id"] == "pkg_123"
    assert captured["workspace_execution_package_id"].startswith("wep_")


@pytest.mark.asyncio
async def test_workspace_execution_package_history_parses_snapshot_rows(monkeypatch):
    async def fake_list(**kwargs):
        return [
            {
                "workspace_execution_package_id": "wep_123",
                "product_id": "prod-001",
                "mode": "IMG",
                "prompt_package_snapshot_id": "pkg_123",
                "prompt_fingerprint": "fp_123",
                "readiness": "READY",
                "execution_allowed": 1,
                "manual_override": 0,
                "asset_slots": '[{"slot_key":"subject"}]',
                "resolved_assets": '[{"slot_key":"subject","asset_source":"PRODUCT_IMAGE_CACHE"}]',
                "manual_fallback": '{"copy_prompt_available": true}',
                "blockers": '[]',
                "request_lineage_payload": '{"product_id":"prod-001"}',
                "source_of_truth_notes": '["note"]',
                "prompt_text": "Prompt preview",
                "created_at": "2026-05-17T00:00:00Z",
                "updated_at": "2026-05-17T00:00:00Z",
            }
        ]

    monkeypatch.setattr("agent.services.workspace_execution_package_service.crud.list_workspace_execution_packages", fake_list)

    items = await list_workspace_execution_packages(product_id="prod-001", mode="IMG")

    assert items[0]["workspace_execution_package_id"] == "wep_123"
    assert items[0]["resolved_assets"][0]["asset_source"] == "PRODUCT_IMAGE_CACHE"
    assert items[0]["prompt_preview"] == "Prompt preview"
