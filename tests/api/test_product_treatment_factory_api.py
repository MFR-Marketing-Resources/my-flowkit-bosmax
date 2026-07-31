import pytest
from fastapi import HTTPException

from agent.api import product_treatment_factory as api
from agent.main import app
from agent.models.product_treatment_factory import (
    CreateFactoryPlanRequest,
    FactoryPlanControlRequest,
    FactoryPlanProjection,
    FactoryProductContext,
    PrepareFactoryPlanRequest,
)


def _plan(status: str = "SCANNED") -> FactoryPlanProjection:
    return FactoryPlanProjection(
        plan_id="ptfp_api",
        plan_identity_sha256="a" * 64,
        cohort_sha256="b" * 64,
        context_sha256="c" * 64,
        status=status,
        product_count=1,
        request={"products": [{"product_id": "product-api"}]},
        authority_versions={"factory_version": "test-v1"},
        readiness_summary={"SATISFIED": 10},
        capacity_summary={"p6_ready_product_count": 1},
        failure_count=0,
        provider_calls_enabled=False,
        media_generation_enabled=False,
        created_by="api-test",
        created_at="2026-07-31T00:00:00Z",
        updated_at="2026-07-31T00:00:00Z",
        tasks=[],
    )


def _create_request() -> CreateFactoryPlanRequest:
    return CreateFactoryPlanRequest(
        products=[
            FactoryProductContext(
                product_id="product-api",
                format="PGC",
                logical_mode="HYBRID",
                generation_mode="SINGLE",
                model_key="veo_3_1_fast",
                duration_seconds=8,
            )
        ],
        created_by="api-test",
    )


@pytest.mark.asyncio
async def test_api_routes_delegate_to_factory_service(monkeypatch):
    calls: list[str] = []

    async def create_plan(_body):
        calls.append("create")
        return _plan()

    async def list_plans(*, status, limit):
        assert status == "SCANNED"
        assert limit == 25
        calls.append("list")
        return [_plan()]

    async def get_plan(plan_id):
        assert plan_id == "ptfp_api"
        calls.append("get")
        return _plan()

    async def prepare_plan(plan_id, _body):
        assert plan_id == "ptfp_api"
        calls.append("prepare")
        return _plan("COMPLETED_WITH_BLOCKERS")

    async def pause_plan(plan_id, _body):
        assert plan_id == "ptfp_api"
        calls.append("pause")
        return _plan("PAUSED")

    async def resume_plan(plan_id, _body):
        assert plan_id == "ptfp_api"
        calls.append("resume")
        return _plan("SCANNED")

    monkeypatch.setattr(api.factory, "create_plan", create_plan)
    monkeypatch.setattr(api.factory, "list_plans", list_plans)
    monkeypatch.setattr(api.factory, "get_plan", get_plan)
    monkeypatch.setattr(api.factory, "prepare_plan", prepare_plan)
    monkeypatch.setattr(api.factory, "pause_plan", pause_plan)
    monkeypatch.setattr(api.factory, "resume_plan", resume_plan)

    assert (await api.create_factory_plan(_create_request())).plan_id == "ptfp_api"
    listed = await api.list_factory_plans(status="SCANNED", limit=25)
    assert [plan.plan_id for plan in listed.plans] == ["ptfp_api"]
    assert (await api.get_factory_plan("ptfp_api")).plan_id == "ptfp_api"
    assert (
        await api.prepare_factory_plan(
            "ptfp_api",
            PrepareFactoryPlanRequest(actor_id="api-test"),
        )
    ).status == "COMPLETED_WITH_BLOCKERS"
    control = FactoryPlanControlRequest(actor_id="api-test", reason="governed")
    assert (await api.pause_factory_plan("ptfp_api", control)).status == "PAUSED"
    assert (await api.resume_factory_plan("ptfp_api", control)).status == "SCANNED"
    assert calls == ["create", "list", "get", "prepare", "pause", "resume"]


@pytest.mark.asyncio
async def test_api_preserves_structured_fail_closed_error(monkeypatch):
    async def create_plan(_body):
        raise api.factory.ProductTreatmentFactoryError(
            "FACTORY_COHORT_EMPTY",
            status_code=422,
            details={"cohort": "empty"},
        )

    monkeypatch.setattr(api.factory, "create_plan", create_plan)

    with pytest.raises(HTTPException) as captured:
        await api.create_factory_plan(_create_request())

    assert captured.value.status_code == 422
    assert captured.value.detail == {
        "error": "FACTORY_COHORT_EMPTY",
        "message": "FACTORY_COHORT_EMPTY",
        "details": {"cohort": "empty"},
    }


def test_application_registers_exact_factory_routes():
    routes = {
        route.path
        for route in app.routes
        if route.path.startswith("/api/product-treatment-factory")
    }
    assert routes == {
        "/api/product-treatment-factory/plans",
        "/api/product-treatment-factory/plans/{plan_id}",
        "/api/product-treatment-factory/plans/{plan_id}/prepare",
        "/api/product-treatment-factory/plans/{plan_id}/pause",
        "/api/product-treatment-factory/plans/{plan_id}/resume",
    }
