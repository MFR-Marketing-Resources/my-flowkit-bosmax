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
