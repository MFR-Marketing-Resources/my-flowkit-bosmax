"""P6 typed API and stable error-contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agent.api import creative_production as api
from agent.models.creative_production import (
    CreativePoolSelection,
    DryRunRequest,
    PlanActionRequest,
    ProductionPlanCreateRequest,
    StartPlanRequest,
)
from agent.services.creative_production_plan_service import CreativeProductionError


def _create_body() -> ProductionPlanCreateRequest:
    return ProductionPlanCreateRequest(
        request_id="api-create-request-0001",
        operator_id="api-owner",
        name="API plan",
        product_ids=["product-1"],
        target_video_count=1,
        model_keys=["Veo 3.1 - Lite"],
        duration_seconds=[8],
        pools=CreativePoolSelection(
            copy_set_ids=["copy-1"],
        ),
    )


@pytest.mark.asyncio
async def test_create_plan_api_uses_typed_service_contract(monkeypatch):
    create = AsyncMock(return_value={"plan_id": "p6plan-api", "status": "DRAFT"})
    monkeypatch.setattr(api.plans, "create_plan", create)
    result = await api.create_plan(_create_body())
    assert result["plan_id"] == "p6plan-api"
    create.assert_awaited_once()
    assert isinstance(create.await_args.args[0], ProductionPlanCreateRequest)


@pytest.mark.asyncio
async def test_api_returns_stable_structured_error(monkeypatch):
    monkeypatch.setattr(
        api.plans,
        "run_capacity_preflight",
        AsyncMock(
            side_effect=CreativeProductionError(
                "UNIQUE_CAPACITY_SHORTFALL",
                "Capacity is insufficient.",
                status_code=409,
                details={"shortfall": 3},
            )
        ),
    )
    body = PlanActionRequest(
        request_id="api-preflight-request-0001",
        operator_id="api-owner",
    )
    with pytest.raises(HTTPException) as error:
        await api.preflight_plan("p6plan-api", body)
    assert error.value.status_code == 409
    assert error.value.detail == {
        "error": "UNIQUE_CAPACITY_SHORTFALL",
        "message": "Capacity is insufficient.",
        "details": {"shortfall": 3},
    }


@pytest.mark.asyncio
async def test_dry_run_and_live_start_are_distinct_api_actions(monkeypatch):
    dry = AsyncMock(return_value={"credit_spend": 0})
    start = AsyncMock(return_value={"status": "PROVIDER_JOB_KNOWN"})
    monkeypatch.setattr(api.scheduler, "dry_run_plan", dry)
    monkeypatch.setattr(api.scheduler, "start_plan", start)
    dry_body = DryRunRequest(
        request_id="api-dry-request-0001",
        operator_id="owner",
    )
    live_body = StartPlanRequest(
        request_id="api-live-request-0001",
        operator_id="owner",
        live=True,
        credit_confirmation="AUTHORIZE_P6_LIVE_CREDIT_SPEND",
    )
    assert (await api.dry_run_plan("plan", dry_body))["credit_spend"] == 0
    assert (await api.start_plan("plan", live_body))["status"] == (
        "PROVIDER_JOB_KNOWN"
    )
    dry.assert_awaited_once_with("plan", dry_body)
    start.assert_awaited_once_with("plan", live_body)


@pytest.mark.asyncio
async def test_control_and_retry_endpoints_preserve_request_identity(monkeypatch):
    control = AsyncMock(return_value={"status": "PAUSED"})
    retry = AsyncMock(return_value={"replacement_attempt": {"attempt_id": "a2"}})
    monkeypatch.setattr(api.scheduler, "control_plan", control)
    monkeypatch.setattr(api.scheduler, "retry_attempt", retry)
    body = PlanActionRequest(
        request_id="api-control-request-0001",
        operator_id="owner",
    )
    await api.pause_plan("plan", body)
    await api.retry_attempt("attempt", body)
    control.assert_awaited_once_with("plan", "PAUSE", body)
    retry.assert_awaited_once_with("attempt", body)


@pytest.mark.asyncio
async def test_lane_api_exposes_runtime_live_certification_truth(monkeypatch):
    list_lanes = AsyncMock(return_value=[{"lane_id": "video"}])
    monkeypatch.setattr(api.scheduler, "list_lanes", list_lanes)
    monkeypatch.setattr(
        api.scheduler,
        "live_execution_certified",
        lambda: True,
    )
    result = await api.list_lanes()
    assert result == {
        "lanes": [{"lane_id": "video"}],
        "live_execution_certified": True,
    }
    list_lanes.assert_awaited_once()


def test_router_exposes_complete_operator_control_plane():
    method_paths = {
        (method, route.path)
        for route in api.router.routes
        for method in route.methods
    }
    expected = {
        ("GET", "/creative-production/cohort-authority"),
        ("POST", "/creative-production/pool-authority"),
        ("POST", "/creative-production/plans"),
        ("PATCH", "/creative-production/plans/{plan_id}"),
        ("GET", "/creative-production/plans/{plan_id}"),
        ("POST", "/creative-production/plans/{plan_id}/preflight"),
        ("POST", "/creative-production/plans/{plan_id}/content-matrix"),
        ("POST", "/creative-production/plans/{plan_id}/compile"),
        ("POST", "/creative-production/plans/{plan_id}/approve"),
        ("POST", "/creative-production/plans/{plan_id}/waves"),
        ("POST", "/creative-production/plans/{plan_id}/dry-run"),
        ("POST", "/creative-production/plans/{plan_id}/start"),
        ("POST", "/creative-production/plans/{plan_id}/pause"),
        ("POST", "/creative-production/plans/{plan_id}/resume"),
        ("POST", "/creative-production/plans/{plan_id}/cancel"),
        ("GET", "/creative-production/lanes"),
        ("POST", "/creative-production/attempts/{attempt_id}/reconcile"),
        ("POST", "/creative-production/attempts/{attempt_id}/retry"),
        ("POST", "/creative-production/items/{item_id}/qa"),
    }
    assert expected <= method_paths
