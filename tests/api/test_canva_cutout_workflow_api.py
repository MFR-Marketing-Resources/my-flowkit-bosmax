import pytest
from fastapi import HTTPException

from agent.api import product_visual_onboarding as api


def test_canva_routes_and_explicit_state_machine_surface_exist():
    paths = {route.path for route in api.router.routes}
    assert "/product-visual-onboarding/{product_id}/canva" in paths
    assert "/product-visual-onboarding/{product_id}/canva/start" in paths
    assert "/product-visual-onboarding/{product_id}/canva/preflight" in paths
    assert "/product-visual-onboarding/{product_id}/canva/complete" in paths
    assert "/product-visual-onboarding/canva/bulk/preview" in paths
    assert "/product-visual-onboarding/canva/bulk/prepare" in paths
    assert "/product-visual-onboarding/canva/bulk/runs/{run_id}/pause" in paths
    assert "/product-visual-onboarding/canva/bulk/runs/{run_id}/resume" in paths
    assert "/product-visual-onboarding/canva/bulk/runs/{run_id}/cancel" in paths


@pytest.mark.asyncio
async def test_canva_bulk_prepare_requires_explicit_confirmation():
    with pytest.raises(HTTPException) as raised:
        await api.prepare_canva_bulk(
            api.CanvaBulkPrepareRequest(
                confirm=False,
                preview_digest="a" * 64,
            )
        )
    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "EXPLICIT_CONFIRMATION_REQUIRED"


def test_canva_preflight_model_forbids_secrets_as_unknown_fields():
    with pytest.raises(ValueError):
        api.CanvaPreflightRequest.model_validate({"cookie": "never-store-this"})


def test_canva_stage_model_requires_method_for_operator_progress():
    request = api.CanvaStageRequest(stage="OPENING_CANVA", canva_method="MAGIC_GRAB")
    assert request.stage == "OPENING_CANVA"
    assert request.canva_method == "MAGIC_GRAB"
