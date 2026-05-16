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
