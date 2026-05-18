import pytest

from agent.services.approved_product_package_service import get_approved_product_package


def _scan_clean(*args, **kwargs):
    return {
        "unsafe_claim_terms_found": False,
        "metadata_leak_found": False,
        "placeholder_found": False,
    }


@pytest.mark.asyncio
async def test_remote_image_only_product_uses_direct_preview_url(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Glad2Glow Body Serum",
            "product_display_name": "Glad2Glow Body Serum",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "production_prompt_approved_modes": '["T2V","IMG"]',
            "local_image_path": None,
            "image_url": "https://cdn.example.com/glad2glow.webp",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "lifecycle_status": "ACTIVE",
            "image_readiness_status": "IMAGE_READY",
        }

    async def fake_claim_safe(product_id: str):
        return {
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
            "safe_claim_rewrite": "Safe rewrite",
            "safe_hook_angles": ["Safe hook"],
            "safe_cta_angles": ["Safe CTA"],
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])
    monkeypatch.setattr("agent.services.approved_product_package_service.scan_prompt_text", _scan_clean)

    result = await get_approved_product_package("prod-remote", "F2V")
    start = next(slot for slot in result["asset_slots"] if slot["slot_key"] == "start_frame")

    assert start["default_source"] == "PRODUCT_IMAGE_URL"
    assert start["resolved_asset"]["preview_url"] == "https://cdn.example.com/glad2glow.webp"
    assert start["resolved_asset"]["download_url"] == "https://cdn.example.com/glad2glow.webp"
    assert start["resolved_asset"]["preview_url"] != "/api/products/prod-remote/image"


@pytest.mark.asyncio
async def test_local_cache_product_uses_local_image_endpoint(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "production_prompt_approved_modes": '["T2V","IMG"]',
            "local_image_path": r"C:\tmp\bosmax.jpg",
            "image_url": "https://cdn.example.com/bosmax.webp",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "lifecycle_status": "ACTIVE",
            "image_readiness_status": "IMAGE_CACHE_READY",
        }

    async def fake_claim_safe(product_id: str):
        return {
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
            "safe_claim_rewrite": "Safe rewrite",
            "safe_hook_angles": ["Safe hook"],
            "safe_cta_angles": ["Safe CTA"],
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])
    monkeypatch.setattr("agent.services.approved_product_package_service.scan_prompt_text", _scan_clean)

    result = await get_approved_product_package("prod-local", "F2V")
    start = next(slot for slot in result["asset_slots"] if slot["slot_key"] == "start_frame")

    assert start["default_source"] == "PRODUCT_IMAGE_CACHE"
    assert start["resolved_asset"]["preview_url"] == "/api/products/prod-local/image"
    assert start["resolved_asset"]["preview_renderable_status"] == "RENDERABLE"
