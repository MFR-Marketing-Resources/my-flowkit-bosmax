import pytest

from agent.services.prompt_package_dryrun_service import generate_prompt_dryrun


@pytest.mark.asyncio
async def test_prompt_dryrun_requires_claim_safe_package(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "raw_product_title": "Bosmax Herbs 5 ML"}

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "product_display_name": "Bosmax Herbs 5 ML",
            "image_readiness_status": "IMAGE_CACHE_READY",
            "section_5_product_physics_prompt": "Keep bottle scale realistic.",
        }

    async def fake_package(product_id: str):
        return None

    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.get_stored_claim_safe_package", fake_package)

    result = await generate_prompt_dryrun("prod-001", "T2V")

    assert result["status"] == "CLAIM_SAFE_COPY_REWRITE_REQUIRED"


@pytest.mark.asyncio
async def test_prompt_dryrun_generates_clean_t2v_and_img_previews(monkeypatch):
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
            "product_display_name": "Bosmax Herbs 5 ML",
            "image_readiness_status": "IMAGE_CACHE_READY",
            "section_5_product_physics_prompt": "Keep bottle scale realistic and label visible.",
        }

    async def fake_package(product_id: str):
        return {
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
            "safe_claim_rewrite": "Bosmax Herbs 5 ML diposisikan sebagai minyak herba luaran untuk self-care lelaki yang premium dan discreet.",
            "safe_hook_angles": ["Rutin penjagaan diri lelaki yang premium dan discreet."],
            "safe_cta_angles": ["Lihat rutin penjagaan diri lelaki yang lebih premium dan discreet."],
        }

    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.get_stored_claim_safe_package", fake_package)

    t2v = await generate_prompt_dryrun("prod-001", "T2V")
    img = await generate_prompt_dryrun("prod-001", "IMG")

    assert t2v["status"] == "DRY_RUN_READY"
    assert "ubat kuat" not in t2v["prompt_preview"].casefold()
    assert "Bosmax Herbs 5 ML" in t2v["prompt_preview"]
    assert img["status"] == "DRY_RUN_READY"
    assert "No explicit adult cues" in img["prompt_preview"]
