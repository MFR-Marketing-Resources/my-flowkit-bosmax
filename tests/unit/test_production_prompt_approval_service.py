import json

import pytest

from agent.services.production_prompt_approval_service import (
    APPROVAL_PHRASE,
    STATUS_APPROVED,
    approve_production_prompt_package,
)


@pytest.mark.asyncio
async def test_production_prompt_approval_persists_audit_fields(monkeypatch):
    stored_updates = {}

    async def fake_get_product(product_id: str):
        base = {
            "id": product_id,
            "source": "MANUAL",
            "lifecycle_status": "ACTIVE",
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
        }
        base.update(stored_updates)
        return base

    async def fake_update_product(product_id: str, **kwargs):
        stored_updates.update(kwargs)
        return {"id": product_id, **stored_updates}

    async def fake_enrich(product, persist=False):
        return {
            **product,
            "product_display_name": "Bosmax Herbs 5 ML",
            "image_readiness_status": "IMAGE_CACHE_READY",
        }

    async def fake_claim_safe_package(product_id: str):
        return {
            "safe_claim_rewrite": "Bosmax Herbs 5 ML diposisikan sebagai minyak herba luaran untuk self-care lelaki yang premium dan discreet.",
        }

    async def fake_dryrun(product_id: str, mode: str):
        return {
            "status": "DRY_RUN_READY",
            "mode": mode,
            "prompt_preview": f"Clean production prompt for {mode}",
        }

    monkeypatch.setattr("agent.services.production_prompt_approval_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.production_prompt_approval_service.crud.update_product", fake_update_product)
    monkeypatch.setattr("agent.services.production_prompt_approval_service.enrich_product", fake_enrich)
    monkeypatch.setattr("agent.services.production_prompt_approval_service.get_stored_claim_safe_package", fake_claim_safe_package)
    monkeypatch.setattr("agent.services.prompt_package_dryrun_service.generate_prompt_dryrun", fake_dryrun)

    result = await approve_production_prompt_package(
        "prod-bosmax",
        approval_phrase=APPROVAL_PHRASE,
        approved_modes=["T2V", "IMG"],
        reviewer_note="Approved claim-safe BOSMAX Herbs 5 ML prompt package for production handoff.",
        confirm_no_google_flow_execution=True,
    )

    assert result["production_prompt_approval_status"] == STATUS_APPROVED
    assert result["approved_modes"] == ["T2V", "IMG"]
    assert stored_updates["production_prompt_approval_status"] == STATUS_APPROVED
    assert json.loads(stored_updates["production_prompt_approved_modes"]) == ["T2V", "IMG"]
    assert result["execution_allowed"] is False


@pytest.mark.asyncio
async def test_production_prompt_approval_requires_exact_phrase(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id}

    monkeypatch.setattr("agent.services.production_prompt_approval_service.crud.get_product", fake_get_product)

    with pytest.raises(PermissionError):
        await approve_production_prompt_package(
            "prod-bosmax",
            approval_phrase="WRONG",
            approved_modes=["T2V"],
            reviewer_note=None,
            confirm_no_google_flow_execution=True,
        )
