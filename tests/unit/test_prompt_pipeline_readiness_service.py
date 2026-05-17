import pytest
from agent.services.prompt_pipeline_readiness_service import PromptPipelineReadinessService

@pytest.mark.asyncio
async def test_readiness_herbs():
    # BOSMAX Herbs 5 ML
    product = {
        "id": "38a6bacd-2427-42ca-8409-2a78c7f0520c",
        "raw_product_title": "BOSMAX Herbs 5 ML",
        "source": "MANUAL",
        "lifecycle_status": "ACTIVE",
        "category": "Health",
        "subcategory": "Supplements",
        "type": "Male Health",
        "physics_class": "SUPPLEMENT_BOTTLE"
    }
    report = await PromptPipelineReadinessService.get_readiness_report(product)
    assert report["product_id"] == "38a6bacd-2427-42ca-8409-2a78c7f0520c"
    assert report["lifecycle_status"] == "ACTIVE"
    assert report["bosmax_product_family"] == "MALE_HEALTH_SENSITIVE"
    assert report["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert report["safe_to_generate_prompt"] is False # Because MALE_HEALTH_SENSITIVE or missing image
    assert "CLAIM_SAFE_COPY_REQUIRED" in report["blockers"]

@pytest.mark.asyncio
async def test_readiness_archived():
    product = {
        "id": "cfb24f8f-a662-4a16-8bad-de77e35be510",
        "raw_product_title": "Bosmax image.jpg",
        "lifecycle_status": "ARCHIVED"
    }
    report = await PromptPipelineReadinessService.get_readiness_report(product)
    assert report["lifecycle_status"] == "ARCHIVED"
    assert report["readiness_by_mode"]["T2V"] == "BLOCKED_PRODUCT_ARCHIVED"
    assert "PRODUCT_ARCHIVED" in report["blockers"]
    assert report["safe_to_generate_prompt"] is False


@pytest.mark.asyncio
async def test_readiness_uses_image_reference_when_present():
    product = {
        "id": "prod-image-001",
        "raw_product_title": "Ready Image Product",
        "source": "MANUAL",
        "lifecycle_status": "ACTIVE",
        "category": "Household",
        "subcategory": "Laundry",
        "type": "Detergent",
        "physics_class": "LAUNDRY_LIQUID_REFILL",
        "image_url": "https://example.com/product.jpg",
    }

    report = await PromptPipelineReadinessService.get_readiness_report(product)

    assert report["image_reference_status"] in {"IMAGE_READY", "IMAGE_CACHE_READY"}
    assert "IMAGE_REFERENCE_MISSING" not in report["blockers"]


@pytest.mark.asyncio
async def test_readiness_allows_dry_run_after_claim_safe_review_ready():
    product = {
        "id": "prod-bosmax-review-ready",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "source": "MANUAL",
        "lifecycle_status": "ACTIVE",
        "category": "Health",
        "subcategory": "Supplements",
        "type": "Male Health",
        "physics_class": "SUPPLEMENT_BOTTLE",
        "image_url": "https://example.com/bosmax.jpg",
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
    }

    report = await PromptPipelineReadinessService.get_readiness_report(product)

    assert report["dry_run_preview_allowed"] is True
    assert report["production_generation_allowed"] is False
    assert report["readiness_by_mode"]["T2V"] == "DRY_RUN_READY"
    assert "CLAIM_SAFE_COPY_REQUIRED" not in report["blockers"]


@pytest.mark.asyncio
async def test_readiness_allows_production_after_explicit_prompt_approval():
    product = {
        "id": "prod-bosmax-production-approved",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "source": "MANUAL",
        "lifecycle_status": "ACTIVE",
        "category": "Health",
        "subcategory": "Supplements",
        "type": "Male Health",
        "physics_class": "SUPPLEMENT_BOTTLE",
        "image_url": "https://example.com/bosmax.jpg",
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
        "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
        "production_prompt_approved_modes": '["T2V","IMG"]',
    }

    report = await PromptPipelineReadinessService.get_readiness_report(product)

    assert report["production_generation_allowed"] is True
    assert report["readiness_by_mode"]["T2V"] == "PRODUCTION_READY"
    assert report["readiness_by_mode"]["IMG"] == "PRODUCTION_READY"
    assert report["readiness_by_mode"]["PromptGeneration"] == "PRODUCTION_READY"
    assert "CLAIM_REVIEW_REQUIRED_FOR_PRODUCTION" not in report["blockers"]
