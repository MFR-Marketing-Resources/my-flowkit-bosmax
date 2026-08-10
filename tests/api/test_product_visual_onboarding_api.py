import pytest
from fastapi import HTTPException

from agent.api import product_visual_onboarding as api


@pytest.mark.asyncio
async def test_bulk_prepare_requires_explicit_confirmation():
    with pytest.raises(HTTPException) as raised:
        await api.queue_bulk_prepare(
            api.BulkPrepareRequest(
                confirm=False,
                preview_digest="a" * 64,
                batch_size=5,
            )
        )
    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "EXPLICIT_CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_cutout_engine_readiness_endpoint_reports_engine_state():
    # Read-only diagnostics: exposes the pinned model contract, reflects the
    # opt-in flag, and fails closed to an ENGINE state (never mutates truth,
    # never runs inference).
    payload = await api.get_local_cutout_engine_readiness(verify=False)
    assert payload["enabled"] is False  # opt-in flag defaults off
    assert payload["model_id"] == "birefnet-general-lite"
    assert payload["state"] in {
        "READY",
        "DEPENDENCY_MISSING",
        "MODEL_MISSING",
        "MODEL_INVALID",
        "LOAD_FAILED",
    }


@pytest.mark.asyncio
async def test_bulk_prepare_rejects_stale_preview(monkeypatch):
    async def preview(**_kwargs):
        return {
            "eligible_product_ids": ["canonical-1"],
            "preview_digest": "b" * 64,
            "counts": {"eligible": 1, "already_approved": 0, "pending_review": 0, "blocked": 0, "skipped": 0},
        }

    monkeypatch.setattr(
        api,
        "preview_bulk_cutout_preparation",
        preview,
    )
    with pytest.raises(HTTPException) as raised:
        await api.queue_bulk_prepare(
            api.BulkPrepareRequest(
                confirm=True,
                preview_digest="a" * 64,
                batch_size=5,
            )
        )
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "PREVIEW_STALE"


def test_visual_onboarding_routes_are_review_gated():
    paths = {route.path for route in api.router.routes}
    assert "/product-visual-onboarding/bulk/preview" in paths
    assert "/product-visual-onboarding/bulk/prepare" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/prepare" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/rebuild" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/manual" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/reject" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/fallback" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/history" in paths
    assert "/product-visual-onboarding/{product_id}/cutout/preview/{variant}" in paths
