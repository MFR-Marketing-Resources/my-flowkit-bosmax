from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from agent.services import creative_supply_factory_service as service


def _policy() -> dict:
    return {
        "HERO": {
            "components": {"HOOK": 6, "SUBHOOK": 4, "USP_SET": 3, "CTA": 3},
            "minimum_capacity": 500,
        },
        "TOP10": {
            "components": {"HOOK": 5, "SUBHOOK": 3, "USP_SET": 2, "CTA": 2},
            "minimum_capacity": 100,
        },
    }


def _roster() -> list[dict]:
    return [
        {
            "product_id": f"product-{index}",
            "product_name": f"Product {index}",
            "rank": index,
            "role": "HERO" if index <= 2 else "TOP10",
        }
        for index in range(1, 11)
    ]


def _angles() -> list[dict]:
    items = []
    for index in range(1, 11):
        count = 4 if index <= 2 else 2
        for angle_index in range(1, count + 1):
            items.append(
                {
                    "product_id": f"product-{index}",
                    "angle_key": f"p{index}-angle-{angle_index}",
                    "angle_label": f"Angle {angle_index}",
                }
            )
    return items


def _hero_components(product_id: str) -> list[dict]:
    items = []
    for angle_index in range(1, 5):
        angle_key = f"{product_id.removeprefix('product-')}"
        angle_key = f"p{angle_key}-angle-{angle_index}"
        for component_type, count in (
            ("HOOK", 6),
            ("SUBHOOK", 4),
            ("USP_SET", 3),
            ("CTA", 3),
        ):
            for item_index in range(count):
                items.append(
                    {
                        "component_id": f"{product_id}-{angle_index}-{component_type}-{item_index}",
                        "angle_key": angle_key,
                        "component_type": component_type,
                        "status": "COMPONENT_APPROVED",
                        "archived": 0,
                    }
                )
    return items


@pytest.mark.asyncio
async def test_create_run_plans_only_measured_top10_deficits(monkeypatch):
    monkeypatch.setattr(service, "_validate_scope", AsyncMock(return_value={
        item["product_id"]: [
            angle for angle in _angles() if angle["product_id"] == item["product_id"]
        ]
        for item in _roster()
    }))
    monkeypatch.setattr(
        service.supply_db,
        "create_run",
        AsyncMock(return_value={"run_id": "csr-test"}),
    )
    create_task = AsyncMock(return_value={})
    monkeypatch.setattr(service.supply_db, "create_task", create_task)
    monkeypatch.setattr(
        service.crud,
        "list_copy_components_for_product",
        AsyncMock(
            side_effect=lambda product_id: (
                _hero_components(product_id) if product_id in {"product-1", "product-2"} else []
            )
        ),
    )
    monkeypatch.setattr(service.crud, "update_copy_component", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service,
        "status",
        AsyncMock(return_value={"run": {"run_id": "csr-test"}}),
    )

    result = await service.create_run(
        mission_id="BOSMAX-P7-TEST",
        roster=_roster(),
        angle_plan=_angles(),
        target_policy=_policy(),
        provider_budget_max=120,
    )

    assert result["run"]["run_id"] == "csr-test"
    assert create_task.await_count == 96
    author_calls = [
        call.kwargs
        for call in create_task.await_args_list
        if call.kwargs.get("task_kind", "AUTHOR_DEFICIT") == "AUTHOR_DEFICIT"
    ]
    legacy_audits = [
        call.kwargs
        for call in create_task.await_args_list
        if call.kwargs.get("task_kind") == "LEGACY_AUDIT"
    ]
    assert len(author_calls) == 64
    assert len(legacy_audits) == 32
    assert all(call["requested_count"] == 0 for call in legacy_audits)
    hook_calls = [
        call for call in author_calls if call["component_type"] == "HOOK"
    ]
    assert hook_calls
    assert all(call["requested_count"] == 5 for call in hook_calls)


@pytest.mark.asyncio
async def test_step_records_exactly_one_provider_call_and_requires_review(monkeypatch):
    run = {
        "run_id": "csr-test",
        "state": "RUNNING",
        "provider_calls_used": 0,
        "provider_budget_max": 120,
    }
    task = {
        "task_id": "cst-test",
        "run_id": "csr-test",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "HOOK",
        "target_approved_count": 5,
        "attempt_count": 1,
        "provider_call_count": 0,
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service.supply_db, "claim_next_pending_task", AsyncMock(return_value=task))
    monkeypatch.setattr(service.supply_db, "update_run", AsyncMock(return_value=run))
    update_task = AsyncMock(return_value=task)
    monkeypatch.setattr(service.supply_db, "update_task", update_task)
    increment = AsyncMock(return_value=run)
    monkeypatch.setattr(service.supply_db, "increment_provider_calls", increment)
    monkeypatch.setattr(service.crud, "list_copy_components_for_product", AsyncMock(return_value=[]))
    receipts = iter(
        [
            {"request_count_since_process_start": 4, "last_call": None},
            {
                "request_count_since_process_start": 5,
                "last_call": {"provider_id": "deepseek", "model": "configured"},
            },
        ]
    )
    monkeypatch.setattr(service.ai_provider, "provider_call_receipt", lambda: next(receipts))
    monkeypatch.setattr(
        service.author_service,
        "author_components",
        AsyncMock(
            return_value={
                "created_count": 2,
                "deduped_count": 0,
                "rejected_count": 0,
                "items": [{"component_id": "component-1"}, {"component_id": "component-2"}],
                "warnings": ["PROVIDER_RETURNED_FEWER:2/5"],
            }
        ),
    )
    monkeypatch.setattr(service, "status", AsyncMock(return_value={"ok": True}))

    assert await service.step("csr-test") == {"ok": True}
    increment.assert_awaited_once_with("csr-test", 1)
    final_update = update_task.await_args_list[-1].kwargs
    assert final_update["state"] == "REVIEW_REQUIRED"
    assert "component-1" in final_update["result_json"]
    assert "PROVIDER_RETURNED_FEWER" in final_update["result_json"]


@pytest.mark.asyncio
async def test_step_never_auto_retries_a_transient_failure(monkeypatch):
    run = {
        "run_id": "csr-test",
        "state": "RUNNING",
        "provider_calls_used": 0,
        "provider_budget_max": 120,
    }
    task = {
        "task_id": "cst-test",
        "run_id": "csr-test",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "HOOK",
        "target_approved_count": 5,
        "attempt_count": 1,
        "provider_call_count": 0,
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service.supply_db, "claim_next_pending_task", AsyncMock(return_value=task))
    monkeypatch.setattr(service.supply_db, "update_run", AsyncMock(return_value=run))
    update_task = AsyncMock(return_value=task)
    monkeypatch.setattr(service.supply_db, "update_task", update_task)
    monkeypatch.setattr(service.supply_db, "increment_provider_calls", AsyncMock(return_value=run))
    monkeypatch.setattr(service.crud, "list_copy_components_for_product", AsyncMock(return_value=[]))
    receipts = iter(
        [
            {"request_count_since_process_start": 8, "last_call": None},
            {"request_count_since_process_start": 9, "last_call": {"http_status": 503}},
        ]
    )
    monkeypatch.setattr(service.ai_provider, "provider_call_receipt", lambda: next(receipts))
    author = AsyncMock(
        side_effect=service.ai_provider.AICopyProviderError(
            service.ai_provider.ERR_CALL_FAILED,
            "temporary unavailable",
            http_status=503,
        )
    )
    monkeypatch.setattr(service.author_service, "author_components", author)
    monkeypatch.setattr(service, "status", AsyncMock(return_value={"ok": True}))

    await service.step("csr-test")
    assert author.await_count == 1
    final_update = update_task.await_args_list[-1].kwargs
    assert final_update["state"] == "RETRY_ELIGIBLE"
    assert final_update["transient_failure_proven"] == 1


@pytest.mark.asyncio
async def test_explicit_retry_requires_transient_evidence_and_one_attempt(monkeypatch):
    monkeypatch.setattr(
        service.supply_db,
        "get_task",
        AsyncMock(
            return_value={
                "task_id": "cst-test",
                "run_id": "csr-test",
                "state": "RETRY_ELIGIBLE",
                "transient_failure_proven": 1,
                "attempt_count": 1,
            }
        ),
    )
    update = AsyncMock(return_value={})
    monkeypatch.setattr(service.supply_db, "update_task", update)
    monkeypatch.setattr(service, "status", AsyncMock(return_value={"ok": True}))
    assert await service.retry_transient("cst-test") == {"ok": True}
    update.assert_awaited_once_with("cst-test", state="PENDING")


@pytest.mark.asyncio
async def test_interrupted_running_task_is_conservatively_charged_and_replaced(monkeypatch):
    task = {
        "task_id": "cst-interrupted",
        "run_id": "csr-test",
        "state": "RUNNING",
        "provider_call_count": 0,
    }
    run = {
        "run_id": "csr-test",
        "provider_calls_used": 1,
        "provider_budget_max": 120,
    }
    monkeypatch.setattr(service.supply_db, "get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    increment = AsyncMock(return_value=run)
    update_task = AsyncMock(return_value=task)
    monkeypatch.setattr(service.supply_db, "increment_provider_calls", increment)
    monkeypatch.setattr(service.supply_db, "update_task", update_task)
    monkeypatch.setattr(service.supply_db, "update_run", AsyncMock(return_value=run))
    replacement = AsyncMock()
    monkeypatch.setattr(service, "_create_deficit_round_if_needed", replacement)
    monkeypatch.setattr(service, "status", AsyncMock(return_value={"ok": True}))

    assert await service.reconcile_interrupted_running_task(
        "cst-interrupted", "worker process terminated"
    ) == {"ok": True}
    increment.assert_awaited_once_with("csr-test", 1)
    assert update_task.await_args.kwargs["state"] == "COMPLETED"
    assert "conservative_billable_count" in update_task.await_args.kwargs[
        "provider_receipt_json"
    ]
    replacement.assert_awaited_once_with("cst-interrupted")


@pytest.mark.asyncio
async def test_review_is_content_hash_bound_and_reasoned(monkeypatch):
    component = {
        "component_id": "component-1",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "HOOK",
        "content": "Masih susah kekalkan rutin harian?",
        "provenance_json": '{"lane":"text_assist"}',
    }
    run = {"run_id": "csr-test", "reviewer_id": service.DEFAULT_REVIEWER_ID}
    task = {
        "task_id": "cst-test",
        "run_id": "csr-test",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "HOOK",
        "result": {"component_ids": ["component-1"]},
        "provider_receipt": {"last_call": {"provider_id": "deepseek"}},
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service.supply_db, "get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(service.crud, "get_copy_component", AsyncMock(return_value=component))
    record = AsyncMock(return_value={"event_id": "event-1"})
    monkeypatch.setattr(service.supply_db, "record_review_and_update_component", record)
    monkeypatch.setattr(service, "_finalize_review_task_if_ready", AsyncMock())
    monkeypatch.setattr(service, "status", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(
        service,
        "scan_copy_safety",
        lambda *_args, **_kwargs: {"safe": True, "violations": []},
    )

    with pytest.raises(service.CreativeSupplyError, match="current component content"):
        await service.review_component(
            run_id="csr-test",
            task_id="cst-test",
            component_id="component-1",
            decision="APPROVED",
            reviewed_content_sha256="0" * 64,
            reasons=["safe"],
            reviewer_id=service.DEFAULT_REVIEWER_ID,
        )

    result = await service.review_component(
        run_id="csr-test",
        task_id="cst-test",
        component_id="component-1",
        decision="APPROVED",
        reviewed_content_sha256=service.content_sha256(component),
        reasons=[
            "Product-specific; correct angle and HOOK type; Product Truth grounded; claim-safe BM; distinct."
        ],
        reviewer_id=service.DEFAULT_REVIEWER_ID,
    )
    assert result["event"]["event_id"] == "event-1"
    assert record.await_args.kwargs["reviewed_content_sha256"] == service.content_sha256(component)
    assert record.await_args.kwargs["provider_provenance"]["p7_task_id"] == "cst-test"


@pytest.mark.asyncio
async def test_manual_remediation_is_zero_provider_and_review_required(monkeypatch):
    run = {
        "run_id": "csr-test",
        "roster": [{"product_id": "product-3", "role": "TOP10"}],
        "angle_plan": [
            {
                "product_id": "product-3",
                "angle_key": "angle-1",
                "angle_label": "Daily routine",
            }
        ],
        "target_policy": _policy(),
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service.supply_db, "list_tasks", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        service.crud,
        "find_copy_component_by_dedupe_key",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        service,
        "scan_copy_safety",
        lambda *_args, **_kwargs: {"safe": True, "violations": []},
    )
    create_component = AsyncMock(
        return_value={"component_id": "component-manual"}
    )
    monkeypatch.setattr(
        service.crud, "create_copy_component", create_component
    )
    create_task = AsyncMock(
        return_value={"task_id": "cst-manual", "state": "REVIEW_REQUIRED"}
    )
    monkeypatch.setattr(service.supply_db, "create_task", create_task)
    monkeypatch.setattr(
        service,
        "status",
        AsyncMock(return_value={"run": {"run_id": "csr-test"}}),
    )

    result = await service.register_manual_remediation(
        run_id="csr-test",
        product_id="product-3",
        angle_key="angle-1",
        component_type="HOOK",
        contents=["Rutin harian lebih mudah diatur."],
        authored_by="codex-p7-reviewer",
    )

    assert result["task"]["state"] == "REVIEW_REQUIRED"
    assert (
        create_component.await_args.kwargs["status"]
        == service.author_service.STATUS_REVIEW_REQUIRED
    )
    assert create_component.await_args.kwargs["source"] == "P7_MANUAL_REMEDIATION"
    assert create_task.await_args.kwargs["requested_count"] == 0
    assert create_task.await_args.kwargs["state"] == "REVIEW_REQUIRED"
    assert create_task.await_args.kwargs["result"]["provider_calls"] == 0


@pytest.mark.asyncio
async def test_settle_satisfied_tasks_closes_only_met_targets(monkeypatch):
    tasks = [
        {
            "task_id": "met",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "HOOK",
            "state": "PENDING",
            "target_approved_count": 1,
            "result": {},
        },
        {
            "task_id": "open",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "CTA",
            "state": "PENDING",
            "target_approved_count": 2,
            "result": {},
        },
    ]
    components = [
        {
            "angle_key": "angle-1",
            "component_type": "HOOK",
            "status": service.copy_component_service.STATUS_APPROVED,
            "archived": 0,
        }
    ]
    monkeypatch.setattr(
        service.supply_db, "get_run", AsyncMock(return_value={"run_id": "csr-test"})
    )
    monkeypatch.setattr(service.supply_db, "list_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr(
        service.crud,
        "list_copy_components_for_product",
        AsyncMock(return_value=components),
    )
    update_task = AsyncMock(return_value={})
    monkeypatch.setattr(service.supply_db, "update_task", update_task)
    monkeypatch.setattr(service.supply_db, "update_run", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service,
        "status",
        AsyncMock(return_value={"run": {"state": "COMPLETED"}}),
    )

    result = await service.settle_satisfied_tasks("csr-test")

    assert result["settled_task_ids"] == ["met"]
    assert update_task.await_count == 1
    assert update_task.await_args.args[0] == "met"


@pytest.mark.asyncio
async def test_status_completes_satisfied_supply_despite_historical_failure(monkeypatch):
    run = {
        "run_id": "csr-test",
        "state": "RUNNING",
        "roster": [{"product_id": "product-3"}],
        "angle_plan": [],
        "provider_calls_used": 1,
        "provider_budget_max": 120,
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        service.supply_db,
        "list_tasks",
        AsyncMock(return_value=[{"state": "FAILED"}]),
    )
    monkeypatch.setattr(
        service.supply_db, "list_review_events", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        service,
        "_product_status",
        AsyncMock(
            return_value={
                "deficits": [],
                "composable_capacity": 100,
                "capacity_target": 100,
                "blockers": [],
            }
        ),
    )
    update_run = AsyncMock(
        return_value={**run, "state": "COMPLETED"}
    )
    monkeypatch.setattr(service.supply_db, "update_run", update_run)

    result = await service.status("csr-test")

    assert result["run"]["state"] == "COMPLETED"
    update_run.assert_awaited_once_with("csr-test", state="COMPLETED")


@pytest.mark.asyncio
async def test_compose_persistence_refuses_any_unsafe_preview(monkeypatch):
    monkeypatch.setattr(
        service.supply_db,
        "get_run",
        AsyncMock(
            return_value={
                "run_id": "csr-test",
                "roster": [{"product_id": "product-3"}],
            }
        ),
    )
    compose = AsyncMock(
        return_value={
            "items": [
                {
                    "safe": False,
                    "combination_fingerprint": "cc-unsafe",
                    "violations": ["FORBIDDEN_PHRASE"],
                }
            ]
        }
    )
    monkeypatch.setattr(
        service.copy_composer_service, "compose_and_persist", compose
    )

    with pytest.raises(service.CreativeSupplyError, match="refuses to persist"):
        await service.compose_sample("csr-test", "product-3", 1, dry_run=False)

    compose.assert_awaited_once_with("product-3", 1, dry_run=True)


@pytest.mark.asyncio
async def test_composed_copy_review_is_hash_bound_and_uses_existing_approval_gate(
    monkeypatch,
):
    row = {
        "copy_set_id": "copy-1",
        "product_id": "product-3",
        "angle": "Daily routine",
        "hook": "Rutin terasa panjang?",
        "subhook": "Susun langkah yang lebih praktikal.",
        "usp_set_json": '["Mudah digunakan"]',
        "cta": "Pilih sekarang.",
        "platform": "TIKTOK",
        "language": "BM_MS",
        "route_type": "DIRECT",
        "formula_family": "PAS",
        "status": "COPY_REVIEW_REQUIRED",
        "source": service.copy_composer_service.SOURCE_COMPONENT_COMPOSER,
        "provenance_json": '{"component_ids":["component-1"]}',
        "claim_review_json": "{}",
    }
    monkeypatch.setattr(
        service.supply_db,
        "get_run",
        AsyncMock(
            return_value={
                "run_id": "csr-test",
                "roster": [{"product_id": "product-3"}],
            }
        ),
    )
    monkeypatch.setattr(service.crud, "get_copy_set", AsyncMock(return_value=row))
    approve = AsyncMock(return_value={**row, "status": "COPY_APPROVED"})
    monkeypatch.setattr(
        service.copy_set_registry_service, "approve_copy_set", approve
    )

    with pytest.raises(service.CreativeSupplyError, match="hash does not match"):
        await service.review_composed_copy_set(
            run_id="csr-test",
            copy_set_id="copy-1",
            decision="APPROVED",
            reviewed_content_sha256="0" * 64,
            reasons=["safe"],
        )

    current_sha = service.copy_set_content_sha256(row)
    result = await service.review_composed_copy_set(
        run_id="csr-test",
        copy_set_id="copy-1",
        decision="APPROVED",
        reviewed_content_sha256=current_sha,
        reasons=["Actual content reviewed; safe, complete and distinct."],
    )

    assert result["reviewed_content_sha256"] == current_sha
    assert approve.await_args.args[1]["approval_phrase"] == "APPROVE_COPY_SET"
    assert approve.await_args.args[1]["override_formula_review"] is False


@pytest.mark.asyncio
async def test_component_correction_supersedes_approval_with_audited_rejection(
    monkeypatch,
):
    component = {
        "component_id": "component-1",
        "product_id": "product-3",
        "angle_key": "angle-1",
        "component_type": "SUBHOOK",
        "content": "An unsupported statement.",
        "status": service.copy_component_service.STATUS_APPROVED,
        "provenance_json": '{"lane":"text_assist"}',
    }
    monkeypatch.setattr(
        service.supply_db,
        "get_run",
        AsyncMock(
            return_value={
                "run_id": "csr-test",
                "roster": [{"product_id": "product-3"}],
            }
        ),
    )
    monkeypatch.setattr(
        service.crud, "get_copy_component", AsyncMock(return_value=component)
    )
    monkeypatch.setattr(
        service.supply_db,
        "list_tasks",
        AsyncMock(
            return_value=[
                {
                    "task_id": "cst-test",
                    "result": {"component_ids": ["component-1"]},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        service.supply_db,
        "create_task",
        AsyncMock(
            return_value={
                "task_id": "cst-correction",
                "result": {
                    "component_ids": ["component-1"],
                    "review_correction": True,
                },
            }
        ),
    )
    monkeypatch.setattr(
        service.supply_db,
        "list_review_events",
        AsyncMock(
            return_value=[
                {
                    "event_id": "event-approved",
                    "component_id": "component-1",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        service,
        "scan_copy_safety",
        lambda *_args, **_kwargs: {"safe": True, "violations": []},
    )
    record = AsyncMock(return_value={"event_id": "event-corrected"})
    monkeypatch.setattr(
        service.supply_db, "record_review_and_update_component", record
    )
    monkeypatch.setattr(service.supply_db, "update_task", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service,
        "status",
        AsyncMock(return_value={"run": {"state": "RUNNING"}}),
    )

    result = await service.correct_component_review(
        run_id="csr-test",
        component_id="component-1",
        reviewed_content_sha256=service.content_sha256(component),
        reasons=["Composed-output review proved the statement unsupported."],
    )

    assert result["event"]["event_id"] == "event-corrected"
    assert record.await_args.kwargs["decision"] == "REJECTED"
    assert record.await_args.kwargs["task_id"] == "cst-correction"
    assert record.await_args.kwargs["expected_statuses"] == (
        service.copy_component_service.STATUS_APPROVED,
    )
    assert (
        record.await_args.kwargs["provider_provenance"]["review_correction"][
            "prior_event_id"
        ]
        == "event-approved"
    )


@pytest.mark.asyncio
async def test_selected_composition_persists_exact_safe_lineage(monkeypatch):
    components = {
        "hook": {
            "component_id": "hook",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "HOOK",
            "content": "Rutin peribadi perlukan pilihan yang ringkas?",
            "status": service.copy_component_service.STATUS_APPROVED,
            "archived": 0,
        },
        "subhook": {
            "component_id": "subhook",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "SUBHOOK",
            "content": "Saiz kecil membantu rutin kekal tersusun.",
            "status": service.copy_component_service.STATUS_APPROVED,
            "archived": 0,
        },
        "usp": {
            "component_id": "usp",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "USP_SET",
            "content": '["Roll-on 5 ML", "Kegunaan luaran"]',
            "status": service.copy_component_service.STATUS_APPROVED,
            "archived": 0,
        },
        "cta": {
            "component_id": "cta",
            "product_id": "product-3",
            "angle_key": "angle-1",
            "component_type": "CTA",
            "content": "Pilih roll-on 5 ML untuk kegunaan luaran.",
            "status": service.copy_component_service.STATUS_APPROVED,
            "archived": 0,
        },
    }
    monkeypatch.setattr(
        service.supply_db,
        "get_run",
        AsyncMock(
            return_value={
                "run_id": "csr-test",
                "roster": [{"product_id": "product-3"}],
                "angle_plan": [
                    {
                        "product_id": "product-3",
                        "angle_key": "angle-1",
                        "angle_label": "Private routine",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        service.crud,
        "get_copy_component",
        AsyncMock(side_effect=lambda component_id: components[component_id]),
    )
    monkeypatch.setattr(
        service.crud, "get_product", AsyncMock(return_value={"id": "product-3"})
    )
    monkeypatch.setattr(
        service,
        "resolve_copy_grounding",
        AsyncMock(return_value=type("Grounding", (), {"effective_route": "DIRECT"})()),
    )
    monkeypatch.setattr(
        service,
        "scan_copy_safety",
        lambda *_args, **_kwargs: {"safe": True, "violations": []},
    )
    monkeypatch.setattr(
        service.crud, "find_copy_set_by_dedupe_key", AsyncMock(return_value=None)
    )
    create = AsyncMock(
        return_value={
            "copy_set_id": "copy-selected",
            "product_id": "product-3",
            "angle": "Private routine",
            "hook": components["hook"]["content"],
            "subhook": components["subhook"]["content"],
            "usp_set_json": components["usp"]["content"],
            "cta": components["cta"]["content"],
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": "DIRECT",
            "formula_family": "PAS",
            "status": "COPY_REVIEW_REQUIRED",
            "source": service.copy_composer_service.SOURCE_COMPONENT_COMPOSER,
            "provenance_json": "{}",
            "claim_review_json": "{}",
        }
    )
    monkeypatch.setattr(service.crud, "create_copy_set", create)

    result = await service.compose_selected_components(
        run_id="csr-test",
        product_id="product-3",
        hook_component_id="hook",
        subhook_component_id="subhook",
        usp_set_component_id="usp",
        cta_component_id="cta",
    )

    assert result["created"] is True
    assert create.await_args.kwargs["status"] == "COPY_REVIEW_REQUIRED"
    provenance = json.loads(create.await_args.kwargs["provenance_json"])
    assert provenance["component_ids"] == ["hook", "subhook", "usp", "cta"]
    assert provenance["provider_calls"] == 0


@pytest.mark.asyncio
async def test_product_only_frame_alias_preserves_source_pixels_and_lineage(monkeypatch):
    source = {
        "asset_id": "asset-source",
        "product_id": "product-3",
        "semantic_role": "PRODUCT_REFERENCE",
        "display_name": "Physical product",
        "status": "ACTIVE",
        "review_status": "APPROVED",
        "allowed_modes": '["F2V"]',
        "storage_kind": "LOCAL_FILE",
        "local_file_path": "C:/evidence/product.png",
        "preview_url": "/preview/source",
        "download_url": "/download/source",
        "product_truth_status": "PASS",
    }
    monkeypatch.setattr(
        service.supply_db,
        "get_run",
        AsyncMock(
            return_value={
                "run_id": "csr-test",
                "roster": [{"product_id": "product-3"}],
            }
        ),
    )
    monkeypatch.setattr(
        service.crud, "get_creative_asset", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        service.crud, "list_creative_assets", AsyncMock(return_value=[])
    )
    record = type(
        "AssetRecord",
        (),
        {
            "model_dump": lambda self, **_kwargs: {
                "asset_id": "asset-alias",
                "product_id": "product-3",
            }
        },
    )()
    create = AsyncMock(return_value=record)
    monkeypatch.setattr(
        service.creative_asset_service, "create_creative_asset", create
    )

    result = await service.register_product_only_f2v_frame_alias(
        run_id="csr-test",
        product_id="product-3",
        source_asset_id="asset-source",
    )

    assert result["created"] is True
    assert result["provider_media_calls"] == 0
    request = create.await_args.args[0]
    assert request.local_file_path == source["local_file_path"]
    assert request.semantic_role == "COMPOSITE_FRAME_REFERENCE"
    assert request.generation_recipe_id == "P7_PRODUCT_ONLY_F2V_ALIAS"
    assert request.mode_a_metadata_handoff["pixel_mutation"] is False
    assert request.mode_a_metadata_handoff["source_product_reference_asset_id"] == (
        "asset-source"
    )


@pytest.mark.asyncio
async def test_product_only_anchor_916_is_native_pixel_exact_and_review_hash_bound(
    monkeypatch, tmp_path
):
    source_path = tmp_path / "physical-product.png"
    source_image = Image.new("RGBA", (37, 53), (12, 89, 44, 255))
    source_image.putpixel((8, 9), (201, 14, 87, 255))
    source_image.save(source_path)
    source = {
        "asset_id": "asset-source",
        "product_id": "product-3",
        "semantic_role": "PRODUCT_REFERENCE",
        "display_name": "Physical product",
        "status": "ACTIVE",
        "review_status": "APPROVED",
        "allowed_modes": '["F2V"]',
        "storage_kind": "LOCAL_FILE",
        "local_file_path": str(source_path),
    }
    run = {
        "run_id": "csr-test",
        "roster": [{"product_id": "product-3"}],
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        service.crud, "get_creative_asset", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        service.crud, "list_creative_assets", AsyncMock(return_value=[])
    )
    anchor_path = tmp_path / "anchor.png"
    captured_request = None

    async def create(request):
        nonlocal captured_request
        captured_request = request
        anchor_path.write_bytes(base64.b64decode(request.image_base64))
        return type(
            "AssetRecord",
            (),
            {
                "model_dump": lambda self, **_kwargs: {
                    "asset_id": "asset-anchor",
                    "product_id": "product-3",
                    "local_file_path": str(anchor_path),
                    "review_status": "PENDING_REVIEW",
                }
            },
        )()

    monkeypatch.setattr(
        service.creative_asset_service, "create_creative_asset", create
    )
    prepared = await service.prepare_product_only_f2v_anchor_916(
        run_id="csr-test",
        product_id="product-3",
        source_asset_id="asset-source",
    )

    assert prepared["provider_media_calls"] == 0
    assert captured_request.review_status == "PENDING_REVIEW"
    assert captured_request.mode_a_metadata_handoff["source_pixel_mutation"] is False
    with Image.open(anchor_path) as anchor:
        assert anchor.size == (1440, 2560)
        region = prepared["source_region"]
        embedded = anchor.crop(
            (
                region["x"],
                region["y"],
                region["x"] + region["w"],
                region["y"] + region["h"],
            )
        ).convert("RGBA")
    assert service.ImageChops.difference(source_image, embedded).getbbox() is None

    anchor = {
        "asset_id": "asset-anchor",
        "product_id": "product-3",
        "generation_recipe_id": "P7_PRODUCT_ONLY_F2V_ANCHOR_916",
        "local_file_path": str(anchor_path),
        "mode_a_metadata_handoff": json.dumps(
            {
                **captured_request.mode_a_metadata_handoff,
                "p7_run_id": "csr-test",
            }
        ),
    }
    get_asset = AsyncMock(side_effect=[anchor, source, anchor, source])
    monkeypatch.setattr(service.crud, "get_creative_asset", get_asset)
    update = AsyncMock(
        return_value=type(
            "AssetRecord",
            (),
            {
                "model_dump": lambda self, **_kwargs: {
                    "asset_id": "asset-anchor",
                    "review_status": "APPROVED",
                }
            },
        )()
    )
    monkeypatch.setattr(service.creative_asset_service, "update_creative_asset", update)

    with pytest.raises(service.CreativeSupplyError, match="hash does not match"):
        await service.review_product_only_f2v_anchor_916(
            run_id="csr-test",
            asset_id="asset-anchor",
            reviewed_output_sha256="0" * 64,
            reasons=["Visual identity and label reviewed."],
        )

    reviewed = await service.review_product_only_f2v_anchor_916(
        run_id="csr-test",
        asset_id="asset-anchor",
        reviewed_output_sha256=prepared["output_sha256"],
        reasons=["Visual identity, label, scale and 9:16 padding reviewed."],
    )
    assert reviewed["provider_media_calls"] == 0
    request = update.await_args.args[1]
    assert request.review_status == "APPROVED"
    assert request.product_truth_status == "PASS"
    assert request.mode_a_metadata_handoff["reviewed_output_sha256"] == (
        prepared["output_sha256"]
    )


@pytest.mark.asyncio
async def test_anchor_upload_reuses_proven_helper_and_submits_no_generation(
    monkeypatch,
):
    run = {
        "run_id": "csr-test",
        "roster": [{"product_id": "product-3"}],
    }
    asset = {
        "asset_id": "asset-anchor",
        "product_id": "product-3",
        "generation_recipe_id": "P7_PRODUCT_ONLY_F2V_ANCHOR_916",
        "review_status": "APPROVED",
        "media_id": None,
        "mode_a_metadata_handoff": json.dumps(
            {"p7_run_id": "csr-test", "review_state": "APPROVED"}
        ),
    }
    monkeypatch.setattr(service.supply_db, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        service.crud, "get_creative_asset", AsyncMock(return_value=asset)
    )
    monkeypatch.setattr(
        service,
        "get_flow_client",
        lambda: type("FlowClient", (), {"connected": True})(),
    )
    media_id = "00000000-0000-4000-8000-000000000006"
    upload = AsyncMock(return_value=(media_id, None))
    monkeypatch.setattr(
        service.production_queue_service,
        "_upload_slot_to_flow_media",
        upload,
    )
    monkeypatch.setattr(
        service.crud,
        "update_creative_asset",
        AsyncMock(return_value={**asset, "media_id": media_id}),
    )
    normalized = type(
        "AssetRecord",
        (),
        {
            "model_dump": lambda self, **_kwargs: {
                "asset_id": "asset-anchor",
                "media_id": media_id,
            }
        },
    )()
    monkeypatch.setattr(
        service.creative_asset_service,
        "_normalize_record",
        lambda _row: normalized,
    )

    result = await service.upload_product_only_f2v_anchor_916(
        run_id="csr-test",
        asset_id="asset-anchor",
        confirmation=service.P7_ANCHOR_UPLOAD_CONFIRMATION,
    )

    assert result["provider_generation_calls"] == 0
    assert result["credit_spend"] == 0
    assert result["media_id"] == media_id
    upload.assert_awaited_once()
    assert upload.await_args.kwargs["aspect"] == "9:16"
