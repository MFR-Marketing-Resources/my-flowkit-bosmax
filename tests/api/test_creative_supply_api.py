from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agent.api import creative_supply as api


@pytest.mark.asyncio
async def test_list_route_returns_summary_read_model(monkeypatch):
    summary = {
        "runs": [
            {
                "run_id": "csr-p7-r1",
                "mission_id": "BOSMAX-P7-R1",
                "roster_sha256": "a" * 64,
                "cohort_sha256": "b" * 64,
                "state": "COMPLETED",
                "provider_budget_max": 120,
                "provider_calls_used": 79,
                "reviewer_id": "codex-p7-reviewer",
                "pause_reason": None,
                "last_error": None,
                "created_at": "2026-07-30T00:00:00Z",
                "updated_at": "2026-07-30T01:00:00Z",
            }
        ]
    }
    list_runs = AsyncMock(return_value=summary)
    monkeypatch.setattr(api.service, "list_runs", list_runs)

    assert await api.list_runs() == summary
    list_runs.assert_awaited_once_with()


def _create_body() -> api.CreateRunRequest:
    roster = [
        api.RosterItem(
            product_id=f"product-{index}",
            product_name=f"Product {index}",
            rank=index,
            role="HERO" if index <= 2 else "TOP10",
            selection_basis="frozen commercial signal",
        )
        for index in range(1, 11)
    ]
    angles = []
    for index in range(1, 11):
        for angle_index in range(1, 5 if index <= 2 else 3):
            angles.append(
                api.AnglePlanItem(
                    product_id=f"product-{index}",
                    angle_key=f"p{index}-angle-{angle_index}",
                    angle_label=f"Angle {angle_index}",
                )
            )
    return api.CreateRunRequest(
        mission_id="BOSMAX-P7-API",
        roster=roster,
        angle_plan=angles,
        target_policy=api.TargetPolicy(
            HERO=api.RoleTargetPolicy(
                components=api.ComponentTargets(HOOK=6, SUBHOOK=4, USP_SET=3, CTA=3),
                minimum_capacity=500,
            ),
            TOP10=api.RoleTargetPolicy(
                components=api.ComponentTargets(HOOK=5, SUBHOOK=3, USP_SET=2, CTA=2),
                minimum_capacity=100,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_create_run_forwards_schema_bound_authority(monkeypatch):
    create = AsyncMock(return_value={"run": {"run_id": "csr-api"}})
    monkeypatch.setattr(api.service, "create_run", create)
    result = await api.create_run(_create_body())
    assert result["run"]["run_id"] == "csr-api"
    assert create.await_args.kwargs["provider_budget_max"] == 120
    assert len(create.await_args.kwargs["roster"]) == 10
    assert len(create.await_args.kwargs["angle_plan"]) == 24
    assert (
        create.await_args.kwargs["target_policy"]["TOP10"]["components"]["HOOK"]
        == 5
    )


@pytest.mark.asyncio
async def test_service_error_is_exposed_as_fail_closed_http_detail(monkeypatch):
    monkeypatch.setattr(
        api.service,
        "step",
        AsyncMock(
            side_effect=api.service.CreativeSupplyError(
                "PROVIDER_BUDGET_EXHAUSTED",
                "No calls remain.",
                status_code=409,
                details={"remaining": 0},
            )
        ),
    )
    with pytest.raises(HTTPException) as raised:
        await api.execute_step("csr-api")
    assert raised.value.status_code == 409
    assert raised.value.detail["error"] == "PROVIDER_BUDGET_EXHAUSTED"
    assert raised.value.detail["details"] == {"remaining": 0}


@pytest.mark.asyncio
async def test_review_route_preserves_content_hash_reasons_and_reviewer(monkeypatch):
    review = AsyncMock(return_value={"event": {"event_id": "event-api"}})
    monkeypatch.setattr(api.service, "review_component", review)
    body = api.ReviewRequest(
        task_id="cst-api",
        component_id="component-api",
        decision="APPROVED",
        reviewed_content_sha256="a" * 64,
        reasons=["Product Truth grounded and claim-safe."],
        reviewer_id="codex-p7-reviewer",
    )
    result = await api.review_component("csr-api", body)
    assert result["event"]["event_id"] == "event-api"
    review.assert_awaited_once_with(
        run_id="csr-api",
        task_id="cst-api",
        component_id="component-api",
        decision="APPROVED",
        reviewed_content_sha256="a" * 64,
        reasons=["Product Truth grounded and claim-safe."],
        reviewer_id="codex-p7-reviewer",
    )


@pytest.mark.asyncio
async def test_retry_route_rejects_task_from_another_run(monkeypatch):
    monkeypatch.setattr(
        api.service,
        "retry_transient",
        AsyncMock(return_value={"run": {"run_id": "csr-other"}}),
    )
    with pytest.raises(HTTPException) as raised:
        await api.retry_task("csr-api", "cst-api")
    assert raised.value.status_code == 409
    assert raised.value.detail["error"] == "TASK_RUN_MISMATCH"


@pytest.mark.asyncio
async def test_manual_remediation_route_forwards_zero_provider_review_payload(monkeypatch):
    register = AsyncMock(
        return_value={"task": {"task_id": "cst-manual", "state": "REVIEW_REQUIRED"}}
    )
    monkeypatch.setattr(api.service, "register_manual_remediation", register)
    request = api.ManualRemediationRequest(
        product_id="product-3",
        angle_key="angle-1",
        component_type="USP_SET",
        contents=[["Microfiber lembut", "Potongan panjang"]],
        authored_by="codex-p7-reviewer",
    )

    result = await api.register_manual_remediation("csr-api", request)

    assert result["task"]["state"] == "REVIEW_REQUIRED"
    assert register.await_args.kwargs == {
        "run_id": "csr-api",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "USP_SET",
        "contents": [["Microfiber lembut", "Potongan panjang"]],
        "authored_by": "codex-p7-reviewer",
    }


@pytest.mark.asyncio
async def test_anchor_upload_route_preserves_exact_zero_credit_confirmation(
    monkeypatch,
):
    upload = AsyncMock(
        return_value={
            "asset_id": "asset-anchor",
            "media_id": "00000000-0000-4000-8000-000000000006",
            "credit_spend": 0,
        }
    )
    monkeypatch.setattr(
        api.service, "upload_product_only_f2v_anchor_916", upload
    )

    result = await api.upload_product_only_anchor(
        "csr-api",
        "asset-anchor",
        api.AnchorUploadRequest(
            confirmation=api.service.P7_ANCHOR_UPLOAD_CONFIRMATION
        ),
    )

    assert result["credit_spend"] == 0
    upload.assert_awaited_once_with(
        run_id="csr-api",
        asset_id="asset-anchor",
        confirmation=api.service.P7_ANCHOR_UPLOAD_CONFIRMATION,
    )
