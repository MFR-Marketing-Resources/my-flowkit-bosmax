from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent.api import product_readiness as api
from agent.main import app
from agent.models.product_readiness import ProductReadinessEvaluateRequest
from agent.services.product_readiness_applicability_service import (
    ProductReadinessError,
)


def _request() -> ProductReadinessEvaluateRequest:
    return ProductReadinessEvaluateRequest(
        product_id="product-1",
        allowed_action_index=0,
        creative_format="UGC",
        logical_mode="T2V",
        generation_mode="SINGLE",
        model_key="veo_3_1_fast",
        duration_seconds=8,
    )


@pytest.mark.asyncio
async def test_evaluate_endpoint_delegates_only_typed_context(monkeypatch):
    expected = Mock(name="readiness-projection")
    evaluate = AsyncMock(return_value=expected)
    monkeypatch.setattr(api.readiness, "evaluate_product_readiness", evaluate)
    body = _request()

    result = await api.evaluate_product_readiness(body)

    assert result is expected
    evaluate.assert_awaited_once_with(body)


@pytest.mark.asyncio
async def test_profile_endpoint_is_read_only_registry_projection(monkeypatch):
    expected = Mock(name="profile-list")
    get_profiles = Mock(return_value=expected)
    monkeypatch.setattr(api.readiness, "get_applicability_profiles", get_profiles)

    result = await api.list_applicability_profiles()

    assert result is expected
    get_profiles.assert_called_once_with()


@pytest.mark.asyncio
async def test_api_maps_stable_structured_readiness_error(monkeypatch):
    monkeypatch.setattr(
        api.readiness,
        "evaluate_product_readiness",
        AsyncMock(
            side_effect=ProductReadinessError(
                "PRODUCT_NOT_FOUND",
                status_code=404,
                details={"product_id": "missing"},
            )
        ),
    )

    with pytest.raises(HTTPException) as error:
        await api.evaluate_product_readiness(_request())

    assert error.value.status_code == 404
    assert error.value.detail == {
        "error": "PRODUCT_NOT_FOUND",
        "message": "PRODUCT_NOT_FOUND",
        "details": {"product_id": "missing"},
    }


def test_request_forbids_client_authored_taxonomy_risk_and_evidence():
    with pytest.raises(ValidationError):
        ProductReadinessEvaluateRequest.model_validate(
            {
                **_request().model_dump(),
                "taxonomy": "client-forged",
                "risk_flags": ["client-forged"],
                "evidence_states": {"allowed_claims": "VERIFIED_VALUE"},
            }
        )


def test_router_exposes_only_bounded_read_only_profiles_and_evaluation():
    paths = {route.path for route in api.router.routes}
    methods_by_path = {
        route.path: route.methods for route in api.router.routes
    }

    assert paths == {
        "/product-readiness/applicability-profiles",
        "/product-readiness/evaluate",
    }
    assert methods_by_path["/product-readiness/applicability-profiles"] == {"GET"}
    assert methods_by_path["/product-readiness/evaluate"] == {"POST"}


def test_application_registers_product_readiness_routes():
    paths = {route.path for route in app.routes}

    assert "/api/product-readiness/applicability-profiles" in paths
    assert "/api/product-readiness/evaluate" in paths
