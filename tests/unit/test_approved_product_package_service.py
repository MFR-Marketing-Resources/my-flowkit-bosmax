import pytest

from agent.services.approved_product_package_service import (
    get_approved_product_package,
    get_product_package_readiness,
)


def _scan_clean(*args, **kwargs):
    return {
        "unsafe_claim_terms_found": False,
        "metadata_leak_found": False,
        "placeholder_found": False,
    }


@pytest.mark.asyncio
async def test_approved_product_package_returns_t2v_package(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "production_prompt_approved_modes": '["T2V","IMG"]',
            "local_image_path": r"C:\tmp\bosmax.jpg",
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
            "safe_claim_rewrite": "Bosmax Herbs 5 ML diposisikan sebagai minyak herba luaran untuk rutin self-care lelaki yang premium dan discreet.",
            "safe_hook_angles": ["Discreet masculine wellness positioning only."],
            "safe_cta_angles": ["Lihat rutin penjagaan diri lelaki yang lebih premium dan discreet."],
        }

    async def fake_dryrun(product_id: str, mode: str):
        return {
            "status": "PRODUCTION_READY",
            "prompt_preview": "Approved premium self-care video prompt.",
            "warnings": [],
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.generate_prompt_dryrun", fake_dryrun)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])
    monkeypatch.setattr("agent.services.approved_product_package_service.scan_prompt_text", _scan_clean)

    result = await get_approved_product_package("prod-001", "T2V")

    assert result["mode"] == "T2V"
    assert result["production_generation_allowed"] is True
    assert result["prompt_text"] == "Approved premium self-care video prompt."
    assert result["prompt_fingerprint"]
    assert result["blockers"] == []


@pytest.mark.asyncio
async def test_approved_product_package_returns_f2v_with_cached_start_frame(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "production_prompt_approved_modes": '["T2V","IMG"]',
            "local_image_path": r"C:\tmp\bosmax.jpg",
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
            "safe_claim_rewrite": "Bosmax Herbs 5 ML diposisikan sebagai minyak herba luaran untuk rutin self-care lelaki yang premium dan discreet.",
            "safe_hook_angles": ["Discreet masculine wellness positioning only."],
            "safe_cta_angles": ["Lihat rutin penjagaan diri lelaki yang lebih premium dan discreet."],
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])
    monkeypatch.setattr("agent.services.approved_product_package_service.scan_prompt_text", _scan_clean)

    result = await get_approved_product_package("prod-001", "F2V")

    start_frame = next(slot for slot in result["asset_slots"] if slot["slot_key"] == "start_frame")
    end_frame = next(slot for slot in result["asset_slots"] if slot["slot_key"] == "end_frame")

    assert result["mode"] == "F2V"
    assert result["production_generation_allowed"] is False
    assert result["blockers"] == []
    assert start_frame["default_source"] == "PRODUCT_IMAGE_CACHE"
    assert start_frame["resolved_asset"]["asset_source"] == "PRODUCT_IMAGE_CACHE"
    assert start_frame["resolved_asset"]["preview_url"] == "/api/products/prod-001/image"
    assert start_frame["resolved_asset"]["preview_renderable_status"] == "RENDERABLE"
    assert end_frame["required"] is False


@pytest.mark.asyncio
async def test_approved_product_package_returns_f2v_with_remote_image_preview(monkeypatch):
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
            "safe_claim_rewrite": "Safe body serum rewrite",
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

    start_frame = next(slot for slot in result["asset_slots"] if slot["slot_key"] == "start_frame")

    assert start_frame["default_source"] == "PRODUCT_IMAGE_URL"
    assert start_frame["resolved_asset"]["asset_source"] == "PRODUCT_IMAGE_URL"
    assert start_frame["resolved_asset"]["preview_url"] == "https://cdn.example.com/glad2glow.webp"
    assert start_frame["resolved_asset"]["download_url"] == "https://cdn.example.com/glad2glow.webp"
    assert start_frame["resolved_asset"]["preview_renderable_status"] == "REMOTE_URL_DIRECT"
    assert start_frame["resolved_asset"]["local_image_path_present"] is False
    assert start_frame["resolved_asset"]["remote_image_url_present"] is True


@pytest.mark.asyncio
async def test_approved_product_package_blocks_archived_product(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Archived Product",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "lifecycle_status": "ARCHIVED",
            "image_readiness_status": "IMAGE_CACHE_READY",
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)

    with pytest.raises(ValueError, match="PRODUCT_ARCHIVED"):
        await get_approved_product_package("prod-archived", "T2V")


@pytest.mark.asyncio
async def test_approved_product_package_blocks_when_production_approval_missing(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "local_image_path": r"C:\tmp\bosmax.jpg",
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
            "safe_cta_angles": ["Safe cta"],
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: False)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: [])

    with pytest.raises(ValueError, match="PRODUCTION_APPROVAL_REQUIRED"):
        await get_approved_product_package("prod-001", "T2V")


@pytest.mark.asyncio
async def test_product_package_readiness_reports_claim_safe_blocker(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "BeFocusPro+",
            "product_display_name": "BeFocusPro+",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "lifecycle_status": "ACTIVE",
            "image_readiness_status": "IMAGE_CACHE_READY",
        }

    async def fake_claim_safe(product_id: str):
        return None

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])

    result = await get_product_package_readiness("prod-unready", "F2V")

    assert result["readiness_status"] == "CLAIM_SAFE_PACKAGE_NOT_READY"
    assert result["blocker"] == "CLAIM_SAFE_PACKAGE_NOT_READY"
    assert result["checklist"][0]["label"] == "Claim-safe package"
    assert result["checklist"][0]["ready"] is False


@pytest.mark.asyncio
async def test_product_package_readiness_reports_ready_f2v(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
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
        }

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_stored_claim_safe_package", fake_claim_safe)
    monkeypatch.setattr("agent.services.approved_product_package_service.is_production_prompt_approved", lambda product: True)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_production_approved_modes", lambda product: ["T2V", "IMG"])

    result = await get_product_package_readiness("prod-ready", "F2V")

    assert result["readiness_status"] == "READY"
    assert result["blocker"] is None
    assert all(entry["ready"] is True for entry in result["checklist"])
