"""P6 durable control-plane and zero-credit orchestration proofs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.db import creative_production_crud as p6db
from agent.db import crud
from agent.db.schema import get_db
from agent.models.creative_production import (
    AttemptState,
    AttemptTransitionRequest,
    CreativePoolSelection,
    DryRunRequest,
    P58_COHORT_COUNT,
    P58_COHORT_SHA256,
    P58CohortAuthorityResponse,
    PlanActionRequest,
    PoolAuthorityRequest,
    ProductionPlanCreateRequest,
    ProductionPlanUpdateRequest,
    QaDecisionRequest,
)
from agent.services import creative_production_compile_service as compiler
from agent.services import creative_production_plan_service as plans
from agent.services import creative_production_scheduler_service as scheduler


PRODUCT_ID = "p6-product-1"
COPY_SET_ID = "p6-copy-1"
AVATAR_CODE = "BOS_F_ALYA_01"


async def _seed_authority_inputs() -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO product "
        "(id,raw_product_title,product_display_name,product_short_name,"
        "product_type,lifecycle_status) VALUES (?,?,?,?,?,'ACTIVE')",
        (
            PRODUCT_ID,
            "P6 Product",
            "P6 Product",
            "P6 Product",
            "lipstick",
        ),
    )
    await db.execute(
        "INSERT OR IGNORE INTO copy_set "
        "(copy_set_id,product_id,angle,hook,cta,status,dedupe_key) "
        "VALUES (?,?,?,?,?,'COPY_APPROVED',?)",
        (
            COPY_SET_ID,
            PRODUCT_ID,
            "benefit",
            "hook",
            "buy now",
            "p6-copy-dedupe",
        ),
    )
    await db.execute(
        "INSERT OR REPLACE INTO creative_product_selection "
        "(selection_id,product_id,selected_avatar_code,status,created_at,updated_at) "
        "VALUES (?,?,?,'APPROVED',datetime('now'),datetime('now'))",
        ("p6-selection-1", PRODUCT_ID, AVATAR_CODE),
    )
    await db.commit()


def _body(
    request_id: str,
    *,
    target: int = 2,
    controlled_reuse_reason: str | None = None,
) -> ProductionPlanCreateRequest:
    return ProductionPlanCreateRequest(
        request_id=request_id,
        operator_id="p6-test-operator",
        name="P6 deterministic plan",
        product_ids=[PRODUCT_ID],
        target_video_count=target,
        logical_mode="T2V",
        model_keys=["Veo 3.1 - Lite"],
        duration_seconds=[8],
        pools=CreativePoolSelection(
            copy_set_ids=[COPY_SET_ID],
            avatar_codes=[AVATAR_CODE],
        ),
        controlled_reuse_reason=controlled_reuse_reason,
        controlled_reuse_max_per_dna=2 if controlled_reuse_reason else 1,
    )


@pytest.fixture
async def p58_authority(monkeypatch):
    db = await get_db()
    for table in (
        "creative_output_qa",
        "creative_execution_lane_lease",
        "creative_generation_attempt",
        "creative_production_item",
        "creative_production_batch",
        "creative_production_wave",
        "creative_production_plan",
    ):
        await db.execute(f"DELETE FROM {table}")
    await db.commit()
    await _seed_authority_inputs()
    authority = P58CohortAuthorityResponse(
        cohort_count=P58_COHORT_COUNT,
        cohort_sha256=P58_COHORT_SHA256,
        product_ids=[PRODUCT_ID],
        products=[
            {
                "product_id": PRODUCT_ID,
                "product_display_name": "P6 Product",
                "product_type": "lipstick",
                "scene_strategy_id": "LIP_COLOR",
            }
        ],
        matches_frozen_authority=True,
        p6_not_started=False,
    )
    monkeypatch.setattr(
        plans,
        "load_p58_cohort_authority",
        AsyncMock(return_value=authority),
    )
    monkeypatch.setattr(
        plans,
        "build_catalog_authority_matrix",
        AsyncMock(
            return_value=SimpleNamespace(
                products=[
                    SimpleNamespace(
                        product_id=PRODUCT_ID,
                        terminal_state="P6_READY",
                        scene_strategy_id="LIP_COLOR",
                    )
                ]
            )
        ),
    )
    return authority


@pytest.mark.asyncio
async def test_schema_has_constraints_indexes_and_conservative_lanes():
    db = await get_db()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'creative_%' ORDER BY name"
    )
    names = {row[0] for row in await cursor.fetchall()}
    assert {
        "creative_production_plan",
        "creative_production_wave",
        "creative_production_batch",
        "creative_production_item",
        "creative_generation_attempt",
        "creative_execution_lane",
        "creative_execution_lane_lease",
        "creative_output_qa",
    } <= names
    lanes = await p6db.list_lanes()
    assert lanes[0]["verified_max_inflight"] == 1
    image_lane = next(
        lane for lane in lanes if lane["lane_id"] == "google-flow-image-primary"
    )
    assert image_lane["enabled"] == 0
    assert image_lane["runtime_proof_status"] == "UNVERIFIED"


@pytest.mark.asyncio
async def test_plan_creation_is_idempotent_and_binds_frozen_cohort(p58_authority):
    first = await plans.create_plan(_body("request-p6-create-0001"))
    second = await plans.create_plan(_body("request-p6-create-0001"))
    assert first["plan_id"] == second["plan_id"]
    assert first["p58_cohort_count"] == P58_COHORT_COUNT
    assert first["p58_cohort_sha256"] == P58_COHORT_SHA256

    changed = _body("request-p6-create-0001", target=3)
    with pytest.raises(
        plans.CreativeProductionError,
        match="different production plan",
    ) as error:
        await plans.create_plan(changed)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


@pytest.mark.asyncio
async def test_preflight_capacity_matrix_and_historical_dna(p58_authority):
    plan = await plans.create_plan(_body("request-p6-capacity-0001"))
    report = await plans.run_capacity_preflight(plan["plan_id"])
    assert report.status == "PREFLIGHT_READY"
    assert report.safe_capacity["VIDEO"] == 4
    assert report.historical_exclusions == 0
    matrix = await plans.materialize_content_matrix(plan["plan_id"])
    assert matrix["created"] == 2
    assert len(
        {item["creative_dna_sha256"] for item in matrix["items"]}
    ) == 2

    second = await plans.create_plan(_body("request-p6-capacity-0002"))
    second_report = await plans.run_capacity_preflight(second["plan_id"])
    assert second_report.historical_exclusions == 2
    assert second_report.safe_capacity["VIDEO"] == 2


@pytest.mark.asyncio
async def test_capacity_shortfall_blocks_unless_controlled_reuse_is_explicit(
    p58_authority,
):
    blocked = await plans.create_plan(
        _body("request-p6-shortfall-0001", target=5)
    )
    report = await plans.run_capacity_preflight(blocked["plan_id"])
    assert report.status == "PREFLIGHT_BLOCKED"
    assert {
        blocker["code"] for blocker in report.blockers
    } >= {"UNIQUE_CAPACITY_SHORTFALL"}

    allowed = await plans.create_plan(
        _body(
            "request-p6-controlled-0001",
            target=5,
            controlled_reuse_reason="Owner-approved campaign control reuse.",
        )
    )
    allowed_report = await plans.run_capacity_preflight(allowed["plan_id"])
    assert allowed_report.status == "PREFLIGHT_READY"
    matrix = await plans.materialize_content_matrix(allowed["plan_id"])
    reused = [
        item
        for item in matrix["items"]
        if item["controlled_reuse_reason"]
    ]
    assert len(reused) == 1


@pytest.mark.asyncio
async def test_compile_reuses_existing_wgp_compiler_and_spends_zero(
    p58_authority,
    monkeypatch,
):
    plan = await plans.create_plan(_body("request-p6-compile-0001", target=1))
    await plans.run_capacity_preflight(plan["plan_id"])
    await plans.materialize_content_matrix(plan["plan_id"])
    db = await get_db()
    await db.execute(
        "INSERT INTO workspace_generation_package "
        "(workspace_generation_package_id,mode,product_id,"
        "product_name_snapshot,final_prompt_text,status) "
        "VALUES ('wgp-p6-1','T2V',?,'P6 Product','compiled','READY_MANUAL')",
        (PRODUCT_ID,),
    )
    await db.commit()
    fake = AsyncMock(
        return_value={
            "workspace_generation_package_id": "wgp-p6-1",
            "status": "READY_MANUAL",
            "blockers_json": "[]",
            "final_prompt_text": "Compiled through existing WGP authority.",
            "prompt_fingerprint": "prompt-fp-p6",
        }
    )
    monkeypatch.setattr(
        compiler.wgp_service,
        "create_t2v_generation_package",
        fake,
    )
    result = await compiler.compile_plan(plan["plan_id"])
    assert result["status"] == "PENDING_APPROVAL"
    assert result["credit_spend"] == 0
    assert result["provider_media_calls"] == 0
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_f2v_compile_preserves_frames_source_lane(
    monkeypatch,
):
    fake = AsyncMock(
        return_value={
            "workspace_generation_package_id": "wgp-p6-f2v-1",
            "status": "READY_MANUAL",
            "blockers_json": "[]",
            "final_prompt_text": "Compiled F2V frames prompt.",
            "prompt_fingerprint": "prompt-fp-p6-f2v",
        }
    )
    monkeypatch.setattr(
        compiler.wgp_service,
        "create_f2v_generation_package",
        fake,
    )

    await compiler._compile_video(
        {
            "item_id": "p6item-f2v",
            "product_id": PRODUCT_ID,
            "creative_dna_sha256": "dna-p6-f2v",
        },
        {
            "plan_id": "p6plan-f2v",
            "logical_mode": "F2V",
        },
        {
            "duration_seconds": "8",
            "copy_set_id": COPY_SET_ID,
            "scene_strategy_context": "Approved F2V scene strategy.",
            "finished_frame_asset_id": "asset-p6-f2v-frame",
        },
    )

    assert fake.await_args.kwargs["source_mode"] == "FRAMES"
    assert fake.await_args.kwargs["start_frame_asset_id"] == (
        "asset-p6-f2v-frame"
    )
    assert "avatar_id" not in fake.await_args.kwargs


@pytest.mark.asyncio
async def test_img_payload_preserves_compiler_and_resolves_flow_reference(
    monkeypatch,
):
    flow_media_id = "00000000-0000-4000-8000-000000000006"
    monkeypatch.setattr(
        scheduler.crud,
        "get_workspace_generation_package",
        AsyncMock(
            return_value={
                "product_id": PRODUCT_ID,
                "final_prompt_text": "Governed IMG prompt.",
                "resolved_engine_slots_json": json.dumps(
                    {"subject": "asset-p6-subject"}
                ),
            }
        ),
    )
    monkeypatch.setattr(
        scheduler.crud,
        "get_creative_asset",
        AsyncMock(return_value={"media_id": flow_media_id}),
    )
    payload, blockers = await scheduler._build_item_payload(
        {
            "media_type": "IMAGE",
            "workspace_generation_package_id": "wgp-p6-img",
            "prompt_package_json": "{}",
            "creative_dimensions_json": json.dumps(
                {"model_key": "NANO_BANANA_PRO", "duration_seconds": 8}
            ),
        },
        {},
        aspect="9:16",
    )
    assert blockers == []
    assert payload["mode"] == "IMG"
    assert payload["prompt"] == "Governed IMG prompt."
    assert payload["image_media_ids"] == [flow_media_id]
    assert payload["image_model"] == "NANO_BANANA_PRO"


async def _approved_plan(monkeypatch) -> tuple[dict, dict]:
    plan = await plans.create_plan(_body("request-p6-scheduler-0001", target=1))
    await plans.run_capacity_preflight(plan["plan_id"])
    matrix = await plans.materialize_content_matrix(plan["plan_id"])
    item = matrix["items"][0]
    await p6db.update_item(
        item["item_id"],
        workspace_generation_package_id=None,
        prompt_fingerprint="fp",
        prompt_package_json=json.dumps({"kind": "WGP"}),
        status="PENDING_APPROVAL",
        updated_at=datetime.now(UTC).isoformat(),
    )
    await p6db.update_plan(
        plan["plan_id"],
        status="PENDING_APPROVAL",
        updated_at=datetime.now(UTC).isoformat(),
    )
    await plans.approve_plan(
        plan["plan_id"],
        request_id="request-p6-approve-0001",
        operator_id="owner",
    )
    monkeypatch.setattr(
        scheduler,
        "_build_item_payload",
        AsyncMock(return_value=({"mode": "T2V", "prompt": "safe"}, [])),
    )
    return plan, item


@pytest.mark.asyncio
async def test_dry_run_attempt_is_durable_idempotent_and_zero_credit(
    p58_authority,
    monkeypatch,
):
    plan, _ = await _approved_plan(monkeypatch)
    request = DryRunRequest(
        request_id="request-p6-dryrun-0001",
        operator_id="owner",
    )
    first = await scheduler.dry_run_plan(plan["plan_id"], request)
    second = await scheduler.dry_run_plan(plan["plan_id"], request)
    assert first["credit_spend"] == 0
    assert first["provider_media_calls"] == 0
    assert first["items"][0]["attempt_id"] == second["items"][0]["attempt_id"]
    attempts = await p6db.list_attempts(plan["plan_id"])
    assert len(attempts) == 1
    assert attempts[0]["attempt_state"] == "NOT_SUBMITTED"
    assert attempts[0]["credit_spend_intended"] == 0


@pytest.mark.asyncio
async def test_live_start_fails_closed_before_generation_door(
    p58_authority,
    monkeypatch,
):
    plan, _ = await _approved_plan(monkeypatch)
    monkeypatch.delenv("BULK_LIVE_EXECUTION_CERTIFIED", raising=False)
    start_generate = AsyncMock()
    monkeypatch.setattr(scheduler.make_video, "start_generate", start_generate)
    from agent.models.creative_production import StartPlanRequest

    with pytest.raises(plans.CreativeProductionError) as error:
        await scheduler.start_plan(
            plan["plan_id"],
            StartPlanRequest(
                request_id="request-p6-live-0001",
                operator_id="owner",
                live=True,
                credit_confirmation="AUTHORIZE_P6_LIVE_CREDIT_SPEND",
            ),
        )
    assert error.value.code == "P6_LIVE_EXECUTION_NOT_CERTIFIED"
    start_generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_lane_lease_capacity_and_expiry_are_durable(p58_authority):
    plan = await plans.create_plan(_body("request-p6-lease-0001", target=1))
    await plans.run_capacity_preflight(plan["plan_id"])
    matrix = await plans.materialize_content_matrix(plan["plan_id"])
    item = matrix["items"][0]
    now = datetime.now(UTC)
    await p6db.patch_lane(
        "google-flow-video-primary",
        health_status="HEALTHY",
        enabled=True,
        runtime_proof_status="VERIFIED",
        evidence_reference="test proof",
        updated_at=now.isoformat(),
    )
    first = await p6db.create_attempt(
        {
            "attempt_id": "attempt-lease-1",
            "item_id": item["item_id"],
            "attempt_number": 1,
            "idempotency_key": "lease-key-1",
            "action_request_id": "lease-action-1",
            "attempt_state": "NOT_SUBMITTED",
            "payload_snapshot_json": "{}",
            "payload_sha256": "sha-1",
            "credit_spend_intended": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    lease = await p6db.acquire_lease(
        lane_id="google-flow-video-primary",
        attempt_id=first["attempt_id"],
        lease_id="lease-1",
        lease_token="token-1",
        owner_instance_id="test",
        acquired_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=1)).isoformat(),
    )
    assert lease is not None

    # A second item/attempt cannot consume the verified single-flight slot.
    replacement = dict(matrix["items"][0])
    replacement.update(
        {
            "item_id": "p6item-lease-2",
            "item_ordinal": 1,
            "creative_dna_sha256": "dna-lease-2",
            "dedupe_guard_key": "dna:dna-lease-2",
            "creative_dimensions_json": "{}",
            "execution_policy_json": "{}",
            "status": "PLANNED",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    for key in list(replacement):
        if key not in {
            "item_id",
            "plan_id",
            "item_ordinal",
            "product_id",
            "media_type",
            "logical_mode",
            "creative_dimensions_json",
            "creative_dna_sha256",
            "dedupe_guard_key",
            "controlled_reuse_reason",
            "execution_policy_json",
            "status",
            "created_at",
            "updated_at",
        }:
            replacement.pop(key)
    await p6db.insert_items([replacement])
    second = await p6db.create_attempt(
        {
            "attempt_id": "attempt-lease-2",
            "item_id": replacement["item_id"],
            "attempt_number": 1,
            "idempotency_key": "lease-key-2",
            "action_request_id": "lease-action-2",
            "attempt_state": "NOT_SUBMITTED",
            "payload_snapshot_json": "{}",
            "payload_sha256": "sha-2",
            "credit_spend_intended": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    blocked = await p6db.acquire_lease(
        lane_id="google-flow-video-primary",
        attempt_id=second["attempt_id"],
        lease_id="lease-2",
        lease_token="token-2",
        owner_instance_id="test",
        acquired_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=5)).isoformat(),
    )
    assert blocked is None
    recovered = await p6db.acquire_lease(
        lane_id="google-flow-video-primary",
        attempt_id=second["attempt_id"],
        lease_id="lease-2",
        lease_token="token-2",
        owner_instance_id="test",
        acquired_at=(now + timedelta(seconds=2)).isoformat(),
        expires_at=(now + timedelta(minutes=5)).isoformat(),
    )
    assert recovered is not None


@pytest.mark.asyncio
async def test_attempt_transition_and_restart_uncertainty_prevent_blind_retry(
    p58_authority,
    monkeypatch,
):
    plan, item = await _approved_plan(monkeypatch)
    attempt = await scheduler._create_attempt(
        {**item, "plan_id": plan["plan_id"]},
        action_request_id="attempt-transition-action",
        actor_id="p6-test-operator",
        payload={"mode": "T2V", "prompt": "safe"},
        credit_spend_intended=True,
    )
    await scheduler.transition_attempt(
        attempt["attempt_id"],
        AttemptTransitionRequest(
            request_id="request-transition-0001",
            operator_id="owner",
            attempt_state=AttemptState.SUBMISSION_STARTED,
        ),
    )
    recovered = await scheduler.recover_after_restart()
    assert recovered["attempts_marked_uncertain"] == 1
    assert recovered["blind_resubmissions"] == 0
    with pytest.raises(plans.CreativeProductionError) as error:
        await scheduler.retry_attempt(
            attempt["attempt_id"],
            PlanActionRequest(
                request_id="request-retry-0001",
                operator_id="owner",
            ),
        )
    assert error.value.code == "RECONCILIATION_REQUIRED_BEFORE_RETRY"


@pytest.mark.asyncio
async def test_qa_rejection_creates_explicit_replacement_lineage(
    p58_authority,
    monkeypatch,
):
    plan, item = await _approved_plan(monkeypatch)
    attempt = await scheduler._create_attempt(
        {**item, "plan_id": plan["plan_id"]},
        action_request_id="attempt-qa-action",
        actor_id="p6-test-operator",
        payload={"mode": "T2V", "prompt": "safe"},
        credit_spend_intended=False,
    )
    await p6db.update_attempt(
        attempt["attempt_id"],
        attempt_state="REGISTERED",
        artifact_media_id="media-p6-qa",
        registered_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    result = await scheduler.qa_decision(
        item["item_id"],
        QaDecisionRequest(
            request_id="request-p6-qa-0001",
            operator_id="reviewer",
            decision="QA_REJECTED",
            reviewer_note="Product label is not legible.",
            request_replacement=True,
        ),
    )
    replacement = result["replacement_item"]
    assert replacement["replacement_for_item_id"] == item["item_id"]
    original = await p6db.get_item(item["item_id"])
    assert original["replaced_by_item_id"] == replacement["item_id"]
    assert original["status"] == "REPLACEMENT_PLANNED"
    assert result["credit_spend"] == 0


@pytest.mark.asyncio
async def test_plan_update_and_governed_pool_authority_are_fail_closed(
    p58_authority,
):
    plan = await plans.create_plan(_body("request-p6-update-0001", target=1))
    updated = await plans.update_plan(
        plan["plan_id"],
        ProductionPlanUpdateRequest(
            request_id="request-p6-update-0002",
            operator_id="p6-owner",
            target_video_count=2,
            operating_window_hours=24,
        ),
    )
    assert updated["target_video_count"] == 2
    assert updated["operating_window_hours"] == 24
    authority = await plans.get_governed_pool_authority(
        PoolAuthorityRequest(
            product_ids=[PRODUCT_ID],
            logical_mode="T2V",
        )
    )
    assert authority["credit_spend"] == 0
    assert authority["copy_sets"][0]["copy_set_id"] == COPY_SET_ID
    assert authority["avatar_profiles"][0]["avatar_code"] == AVATAR_CODE
    assert authority["blockers"] == []

    await plans.run_capacity_preflight(plan["plan_id"])
    await plans.materialize_content_matrix(plan["plan_id"])
    with pytest.raises(plans.CreativeProductionError) as error:
        await plans.update_plan(
            plan["plan_id"],
            ProductionPlanUpdateRequest(
                request_id="request-p6-update-0003",
                operator_id="p6-owner",
                target_video_count=1,
            ),
        )
    assert error.value.code == "PLAN_CONFIGURATION_LOCKED"


@pytest.mark.asyncio
async def test_f2v_pool_authority_does_not_invent_avatar_requirement(
    p58_authority,
):
    db = await get_db()
    await db.execute(
        "UPDATE creative_product_selection SET status='DRAFT' WHERE product_id=?",
        (PRODUCT_ID,),
    )
    await db.commit()
    authority = await plans.get_governed_pool_authority(
        PoolAuthorityRequest(
            product_ids=[PRODUCT_ID],
            logical_mode="F2V",
        )
    )
    assert authority["avatar_profiles"] == []
    assert "APPROVED_PRODUCT_AVATAR_SELECTION_REQUIRED" not in {
        blocker["code"] for blocker in authority["blockers"]
    }


@pytest.mark.asyncio
async def test_actor_bound_audit_trail_records_zero_credit_transitions(
    p58_authority,
):
    plan = await plans.create_plan(_body("request-p6-audit-0001", target=1))
    action = PlanActionRequest(
        request_id="request-p6-audit-0002",
        operator_id="p6-auditor",
    )
    await plans.run_capacity_preflight(plan["plan_id"], action)
    await plans.materialize_content_matrix(
        plan["plan_id"],
        PlanActionRequest(
            request_id="request-p6-audit-0003",
            operator_id="p6-auditor",
        ),
    )
    detail = await plans.get_plan_detail(plan["plan_id"])
    actions = [event["action"] for event in detail.audit_events]
    assert actions == [
        "CREATE_PLAN",
        "RUN_CAPACITY_PREFLIGHT",
        "MATERIALIZE_CONTENT_MATRIX",
    ]
    assert detail.audit_events[-1]["actor_id"] == "p6-auditor"
    assert detail.audit_events[-1]["evidence"]["credit_spend"] == 0


@pytest.mark.asyncio
async def test_scheduler_tick_is_inert_without_existing_bulk_certification(
    monkeypatch,
):
    start_generate = AsyncMock()
    monkeypatch.setattr(
        scheduler.production_queue_service,
        "bulk_live_execution_certified",
        lambda: False,
    )
    monkeypatch.setattr(scheduler.make_video, "start_generate", start_generate)
    result = await scheduler.scheduler_tick()
    assert result == {
        "live_execution_certified": False,
        "plans_examined": 0,
        "attempts_dispatched": 0,
        "credit_spend": 0,
    }
    start_generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_recovery_registers_existing_artifact_without_resubmit(
    p58_authority,
    monkeypatch,
):
    plan, item = await _approved_plan(monkeypatch)
    attempt = await scheduler._create_attempt(
        {**item, "plan_id": plan["plan_id"]},
        action_request_id="attempt-ledger-recovery",
        actor_id="p6-recovery",
        payload={"mode": "T2V", "prompt": "safe"},
        credit_spend_intended=True,
    )
    await p6db.update_attempt(
        attempt["attempt_id"],
        attempt_state="PROVIDER_JOB_KNOWN",
        provider_job_id="provider-job-ledger-1",
        updated_at=datetime.now(UTC).isoformat(),
    )
    await crud.insert_generated_artifact(
        "media-ledger-1",
        job_id="provider-job-ledger-1",
        mode="T2V",
    )
    monkeypatch.setattr(scheduler.make_video, "get_job", lambda _job_id: None)
    start_generate = AsyncMock()
    monkeypatch.setattr(scheduler.make_video, "start_generate", start_generate)
    recovered = await scheduler.reconcile_attempt(attempt["attempt_id"])
    assert recovered["provider_state"] == "ARTIFACT_LEDGER_REGISTERED"
    assert recovered["attempt"]["attempt_state"] == "REGISTERED"
    assert recovered["attempt"]["artifact_media_id"] == "media-ledger-1"
    start_generate.assert_not_awaited()
