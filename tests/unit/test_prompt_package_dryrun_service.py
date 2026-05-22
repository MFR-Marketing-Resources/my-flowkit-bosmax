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
    assert img["image_prompt"] == img["prompt_preview"]
    assert img["metadata_handoff"]["image_prompt_metadata_isolated"] is True
    assert img["overlay_spec"]["render_text_inside_image"] is False
    assert img["export_spec"]["color_profile"] == "sRGB"
    assert "safe_zone" not in img["image_prompt"]
    assert "metadata_handoff_contract" not in img["image_prompt"]
    assert "50mm" in img["image_prompt"] or "100mm" in img["image_prompt"]


@pytest.mark.asyncio
async def test_prompt_dryrun_reports_production_ready_after_approval(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "local_image_path": r"C:\tmp\bosmax.jpg",
            "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
            "production_prompt_approved_modes": '["T2V","IMG"]',
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

    result = await generate_prompt_dryrun("prod-001", "T2V")

    assert result["status"] == "PRODUCTION_READY"
    assert result["production_generation_allowed"] is True


@pytest.mark.asyncio
async def test_prompt_dryrun_builds_real_estate_img_contract(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Mont Kiara Luxury Condo Interior",
            "product_display_name": "Mont Kiara Luxury Condo Interior",
            "image_url": "https://cdn.example.com/condo.jpg",
        }

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "image_readiness_status": "IMAGE_READY",
        }

    async def fake_package(product_id: str):
        return {
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
            "safe_claim_rewrite": "Luxury condo hero render with premium Malaysian urban positioning.",
            "safe_hook_angles": ["Luxury city residence visual."],
            "safe_cta_angles": ["Book a viewing today."],
        }

    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.get_stored_claim_safe_package", fake_package)

    result = await generate_prompt_dryrun("prop-001", "IMG")

    assert result["mode"] == "IMG"
    assert result["route"] == "REAL_ESTATE_LISTING"
    assert result["metadata_handoff"]["camera_profile"]["focal_length"] == "24mm lens"
    assert result["export_spec"]["recommended_aspect_ratio"] == "4:5"
    assert "vertical line correction" in result["image_prompt"].casefold()
