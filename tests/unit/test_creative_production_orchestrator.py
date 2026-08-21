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
    ProductVideoAllocation,
    ProductionPlanCreateRequest,
    ProductionPlanUpdateRequest,
    QaDecisionRequest,
    StartPlanRequest,
)
from agent.services import creative_production_compile_service as compiler
from agent.services import creative_production_plan_service as plans
from agent.services import creative_production_scheduler_service as scheduler


PRODUCT_ID = "p6-product-1"
PRODUCT_ID_2 = "p6-product-2"
PRODUCT_ID_3 = "p6-product-3"
COPY_SET_ID = "p6-copy-1"
COPY_SET_ID_2 = "p6-copy-2"
COPY_SET_ID_3 = "p6-copy-3"
AVATAR_CODE = "BOS_F_ALYA_01"


async def _seed_authority_inputs() -> None:
    db = await get_db()
    for index, (product_id, copy_set_id) in enumerate(
        (
            (PRODUCT_ID, COPY_SET_ID),
            (PRODUCT_ID_2, COPY_SET_ID_2),
            (PRODUCT_ID_3, COPY_SET_ID_3),
        ),
        start=1,
    ):
        await db.execute(
            "INSERT OR IGNORE INTO product "
            "(id,raw_product_title,product_display_name,product_short_name,"
            "product_type,lifecycle_status) VALUES (?,?,?,?,?,'ACTIVE')",
            (
                product_id,
                f"P6 Product {index}",
                f"P6 Product {index}",
                f"P6 Product {index}",
                "lipstick",
            ),
        )
        await db.execute(
            "INSERT OR IGNORE INTO copy_set "
            "(copy_set_id,product_id,angle,hook,cta,status,dedupe_key) "
            "VALUES (?,?,?,?,?,'COPY_APPROVED',?)",
            (
                copy_set_id,
                product_id,
                "benefit",
                f"hook {index}",
                "buy now",
                f"p6-copy-dedupe-{index}",
            ),
        )
        await db.execute(
            "INSERT OR REPLACE INTO creative_product_selection "
            "(selection_id,product_id,selected_avatar_code,status,created_at,updated_at) "
            "VALUES (?,?,?,'APPROVED',datetime('now'),datetime('now'))",
            (f"p6-selection-{index}", product_id, AVATAR_CODE),
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
        product_video_allocations=[
            ProductVideoAllocation(product_id=PRODUCT_ID, video_count=target)
        ],
        target_video_count=target,
        production_recipe="HYBRID",
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
        product_ids=[PRODUCT_ID, PRODUCT_ID_2, PRODUCT_ID_3],
        products=[
            {
                "product_id": PRODUCT_ID,
                "product_display_name": "P6 Product 1",
                "product_type": "lipstick",
                "scene_strategy_id": "LIP_COLOR",
            },
            {
                "product_id": PRODUCT_ID_2,
                "product_display_name": "P6 Product 2",
                "product_type": "lipstick",
                "scene_strategy_id": "LIP_COLOR",
            },
            {
                "product_id": PRODUCT_ID_3,
                "product_display_name": "P6 Product 3",
                "product_type": "lipstick",
                "scene_strategy_id": "LIP_COLOR",
            },
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
                    ),
                    SimpleNamespace(
                        product_id=PRODUCT_ID_2,
                        terminal_state="P6_READY",
                        scene_strategy_id="LIP_COLOR",
                    ),
                    SimpleNamespace(
                        product_id=PRODUCT_ID_3,
                        terminal_state="P6_READY",
                        scene_strategy_id="LIP_COLOR",
                    ),
                ]
            )
        ),
    )
    return authority


@pytest.mark.asyncio
async def test_cohort_authority_projects_existing_image_readiness(
    monkeypatch, tmp_path
):
    minyak_image = tmp_path / "minyak-warisan.jpg"
    bosmax_image = tmp_path / "bosmax-herbs.png"
    minyak_image.write_bytes(b"minyak-image")
    bosmax_image.write_bytes(b"bosmax-image")
    rows = [
        SimpleNamespace(
            product_id="mwcb-product",
            product_name="Minyak Warisan Cap Burung 25ml",
            product_type_group="herbal_oil",
            scene_strategy_id="HERBAL_OIL",
        ),
        SimpleNamespace(
            product_id="bosmax-product",
            product_name="Bosmax Herbs 5 ML",
            product_type_group="herbal_oil",
            scene_strategy_id="HERBAL_OIL",
        ),
        SimpleNamespace(
            product_id="remote-product",
            product_name="Remote Product",
            product_type_group="serum",
            scene_strategy_id="SERUM",
        ),
        SimpleNamespace(
            product_id="missing-product",
            product_name="Missing Product",
            product_type_group="serum",
            scene_strategy_id="SERUM",
        ),
    ]
    monkeypatch.setattr(
        plans,
        "build_catalog_authority_matrix",
        AsyncMock(
            return_value=SimpleNamespace(
                p6_launch_cohort_product_ids=[row.product_id for row in rows],
                products=rows,
            )
        ),
    )
    monkeypatch.setattr(
        plans.crud,
        "list_products",
        AsyncMock(
            return_value=[
                {
                    "id": "mwcb-product",
                    "image_url": None,
                    "image_asset_status": "DOWNLOADED",
                    "local_image_path": str(minyak_image),
                },
                {
                    "id": "bosmax-product",
                    "image_url": "UNKNOWN",
                    "image_asset_status": "DOWNLOADED",
                    "local_image_path": str(bosmax_image),
                },
                {
                    "id": "remote-product",
                    "image_url": "https://cdn.example.com/product.webp",
                    "image_asset_status": "UNRESOLVED",
                    "local_image_path": None,
                },
                {
                    "id": "missing-product",
                    "image_url": None,
                    "image_asset_status": "UNRESOLVED",
                    "local_image_path": None,
                },
            ]
        ),
    )

    authority = await plans.load_p58_cohort_authority()
    products = {product["product_id"]: product for product in authority.products}

    assert products["mwcb-product"]["image_readiness_status"] == "IMAGE_CACHE_READY"
    assert products["bosmax-product"]["image_readiness_status"] == "IMAGE_CACHE_READY"
    assert products["remote-product"]["image_readiness_status"] == "IMAGE_READY"
    assert (
        products["missing-product"]["image_readiness_status"] == "IMAGE_URL_MISSING"
    )
    assert products["mwcb-product"]["image_url"] == ""
    assert products["bosmax-product"]["image_url"] == "UNKNOWN"


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
async def test_plan_refuses_product_outside_frozen_cohort(p58_authority):
    body = _body("request-p6-outside-cohort-0001")
    body.product_ids = ["outside-frozen-cohort"]
    with pytest.raises(plans.CreativeProductionError) as error:
        await plans.create_plan(body)
    assert error.value.code == "PRODUCT_OUTSIDE_P58_COHORT"


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
async def test_explicit_multi_product_allocation_materializes_exact_counts(
    p58_authority,
):
    body = ProductionPlanCreateRequest(
        request_id="request-p6-allocation-0001",
        operator_id="p6-test-operator",
        name="P6 explicit allocation plan",
        product_ids=[PRODUCT_ID, PRODUCT_ID_2, PRODUCT_ID_3],
        product_video_allocations=[
            ProductVideoAllocation(product_id=PRODUCT_ID, video_count=2),
            ProductVideoAllocation(product_id=PRODUCT_ID_2, video_count=1),
            ProductVideoAllocation(product_id=PRODUCT_ID_3, video_count=3),
        ],
        target_video_count=6,
        production_recipe="HYBRID",
        model_keys=["veo_3_1_lite"],
        duration_seconds=[16],
        pools=CreativePoolSelection(
            copy_set_ids=[COPY_SET_ID, COPY_SET_ID_2, COPY_SET_ID_3],
            avatar_codes=[AVATAR_CODE],
        ),
        controlled_reuse_reason="P6 exact allocation invariant test.",
        controlled_reuse_max_per_dna=3,
    )
    plan = await plans.create_plan(body)
    assert plan["pool_snapshot"]["product_video_allocations"] == [
        {"product_id": PRODUCT_ID, "video_count": 2},
        {"product_id": PRODUCT_ID_2, "video_count": 1},
        {"product_id": PRODUCT_ID_3, "video_count": 3},
    ]
    detail = await plans.get_plan_detail(plan["plan_id"])
    assert detail.snapshot.completeness == "COMPLETE"
    assert [
        (allocation.product_id, allocation.video_count)
        for allocation in detail.snapshot.product_allocations
    ] == [
        (PRODUCT_ID, 2),
        (PRODUCT_ID_2, 1),
        (PRODUCT_ID_3, 3),
    ]
    assert detail.snapshot.video_configurations[0].model_key == "veo_3_1_lite"
    assert (
        detail.snapshot.video_configurations[0].generation_mode
        == "EXTEND"
    )
    assert (
        detail.snapshot.video_configurations[0].engine_block_duration_seconds
        == 8
    )
    assert detail.snapshot.video_configurations[0].segment_count == 2
    assert detail.snapshot.aspect_ratio == "9:16"
    report = await plans.run_capacity_preflight(plan["plan_id"])
    assert report.status == "PREFLIGHT_READY"
    assert report.assumptions["explicit_product_allocation"] is True
    matrix = await plans.materialize_content_matrix(plan["plan_id"])
    counts: dict[str, int] = {}
    for item in matrix["items"]:
        counts[item["product_id"]] = counts.get(item["product_id"], 0) + 1
        dimensions = item["creative_dimensions"]
        assert dimensions["generation_mode"] == "EXTEND"
        assert dimensions["engine_block_duration_seconds"] == "8"
        assert dimensions["segment_count"] == "2"
        assert dimensions["execution_route"] == "VIDEO_JOBS_ORCHESTRATOR"
    assert counts == {PRODUCT_ID: 2, PRODUCT_ID_2: 1, PRODUCT_ID_3: 3}


@pytest.mark.asyncio
async def test_legacy_snapshot_reconciliation_uses_exact_items_and_fails_closed(
    p58_authority,
    monkeypatch,
):
    common = {
        "created_by": "p6-reconciler",
        "name": "Legacy snapshot fixture",
        "product_scope_json": json.dumps([PRODUCT_ID]),
        "p58_cohort_sha256": P58_COHORT_SHA256,
        "p58_cohort_count": P58_COHORT_COUNT,
        "logical_mode": "T2V",
        "model_keys_json": json.dumps(["Veo 3.1 - Lite"]),
        "duration_seconds_json": json.dumps([8]),
        "pool_snapshot_json": "{}",
        "execution_policy_json": json.dumps({"aspect": "9:16"}),
    }
    exact_plan_id = "p6plan-legacy-exact"
    incomplete_plan_id = "p6plan-legacy-incomplete"
    await p6db.create_plan(
        {
            **common,
            "plan_id": exact_plan_id,
            "request_id": "request-legacy-exact",
            "target_video_count": 2,
        }
    )
    await p6db.create_plan(
        {
            **common,
            "plan_id": incomplete_plan_id,
            "request_id": "request-legacy-incomplete",
            "target_video_count": 1,
        }
    )
    await p6db.insert_items(
        [
            {
                "item_id": f"{exact_plan_id}-item-{ordinal}",
                "plan_id": exact_plan_id,
                "item_ordinal": ordinal,
                "product_id": PRODUCT_ID,
                "media_type": "VIDEO",
                "creative_dna_sha256": f"{ordinal + 1:064x}",
                "dedupe_guard_key": f"legacy-exact-{ordinal}",
            }
            for ordinal in range(2)
        ]
        + [
            {
                "item_id": f"{incomplete_plan_id}-item-{ordinal}",
                "plan_id": incomplete_plan_id,
                "item_ordinal": ordinal,
                "product_id": PRODUCT_ID,
                "media_type": "VIDEO",
                "creative_dna_sha256": f"{ordinal + 101:064x}",
                "dedupe_guard_key": f"legacy-incomplete-{ordinal}",
            }
            for ordinal in range(2)
        ]
    )

    result = await plans.reconcile_legacy_plan_snapshots(
        request_id="request-p63-r2-reconcile",
        operator_id="p6-reconciler",
    )
    by_plan = {row["plan_id"]: row for row in result["plans"]}
    assert by_plan[exact_plan_id]["completeness"] == "COMPLETE"
    assert by_plan[exact_plan_id]["allocation_source"] == "PRIMARY_VIDEO_ITEMS"
    assert (
        by_plan[incomplete_plan_id]["completeness"]
        == "LEGACY_INCOMPLETE"
    )
    assert (
        by_plan[incomplete_plan_id]["allocation_source"] == "NOT_PROVABLE"
    )

    exact = await p6db.get_plan(exact_plan_id)
    incomplete = await p6db.get_plan(incomplete_plan_id)
    assert exact is not None
    assert incomplete is not None
    exact_snapshot = json.loads(exact["plan_snapshot_json"])
    incomplete_snapshot = json.loads(incomplete["plan_snapshot_json"])
    assert exact_snapshot["product_allocations"] == [
        {
            "product_id": PRODUCT_ID,
            "product_name": "P6 Product 1",
            "video_count": 2,
        }
    ]
    assert incomplete_snapshot["product_allocations"] == []
    assert "product_allocations" in incomplete_snapshot["missing_fields"]
    await plans.require_complete_plan_snapshot(exact_plan_id)
    with pytest.raises(
        plans.CreativeProductionError,
        match="complete persisted plan snapshot",
    ):
        await plans.require_complete_plan_snapshot(incomplete_plan_id)
    await p6db.update_plan(
        incomplete_plan_id,
        status="SCHEDULED",
        updated_at=datetime.now(UTC).isoformat(),
    )
    monkeypatch.setattr(
        scheduler,
        "live_execution_certified",
        lambda: True,
    )
    with pytest.raises(
        plans.CreativeProductionError,
        match="complete persisted plan snapshot",
    ):
        await scheduler.start_plan(
            incomplete_plan_id,
            StartPlanRequest(
                request_id="request-incomplete-live",
                operator_id="p6-reconciler",
                aspect="9:16",
                live=True,
                credit_confirmation="AUTHORIZE_P6_LIVE_CREDIT_SPEND",
            ),
        )
    audit = await p6db.list_audit_events(incomplete_plan_id)
    assert audit[-1]["action"] == "RECONCILE_PLAN_SNAPSHOT"


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
async def test_extend_compile_creates_durable_video_job_plan_without_single_queue(
    monkeypatch,
):
    execution_package = AsyncMock(
        return_value={
            "workspace_execution_package_id": "wep-p6-extend",
            "execution_allowed": True,
            "blockers": [],
            "copy_binding": {"copy_set_id": COPY_SET_ID},
        }
    )
    generation_package = AsyncMock(
        return_value={
            "workspace_generation_package_id": "wgp-p6-extend",
            "workspace_execution_package_id": "wep-p6-extend",
            "status": "READY_MANUAL",
            "blockers_json": "[]",
            "final_prompt_text": "Reviewed two-block Extend prompt.",
            "prompt_fingerprint": "prompt-fp-p6-extend",
        }
    )
    video_job_plan = AsyncMock(
        return_value={
            "job_id": "vj-p6-extend",
            "plan_fingerprint": "plan-fp-p6-extend",
            "reused": False,
        }
    )
    monkeypatch.setattr(
        compiler.wgp_service,
        "_create_bulk_extend_execution_package",
        execution_package,
    )
    monkeypatch.setattr(
        compiler.wgp_service,
        "create_t2v_generation_package",
        generation_package,
    )
    from agent.api import flow as flow_api

    monkeypatch.setattr(flow_api, "_plan_video_job", video_job_plan)

    _, _, evidence = await compiler._compile_video(
        {
            "item_id": "p6item-extend",
            "item_ordinal": 0,
            "product_id": PRODUCT_ID,
            "creative_dna_sha256": "dna-p6-extend",
        },
        {
            "plan_id": "p6plan-extend",
            "logical_mode": "T2V",
            "execution_policy_json": '{"aspect":"9:16"}',
        },
        {
            "duration_seconds": "16",
            "engine_block_duration_seconds": "8",
            "segment_count": "2",
            "generation_mode": "EXTEND",
            "execution_route": "VIDEO_JOBS_ORCHESTRATOR",
            "model_key": "veo_3_1_lite",
            "copy_set_id": COPY_SET_ID,
            "avatar_code": AVATAR_CODE,
        },
    )

    assert generation_package.await_args.kwargs["duration_seconds"] == 8
    assert (
        generation_package.await_args.kwargs[
            "requested_total_duration_seconds"
        ]
        == 16
    )
    assert generation_package.await_args.kwargs[
        "workspace_execution_package_id"
    ] == "wep-p6-extend"
    request = video_job_plan.await_args.args[0]
    assert request.requested_total_duration_seconds == 16
    assert request.client_request_nonce == "wgp-p6-extend"
    assert video_job_plan.await_args.kwargs["trust_client_authority"] is False
    assert evidence["generation_mode"] == "EXTEND"
    assert evidence["video_job_id"] == "vj-p6-extend"
    assert evidence["execution_route"] == "VIDEO_JOBS_ORCHESTRATOR"


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


@pytest.mark.asyncio
async def test_extend_dry_run_payload_retains_route_blocks_and_video_job_identity(
    monkeypatch,
):
    monkeypatch.setattr(
        scheduler.crud,
        "get_workspace_generation_package",
        AsyncMock(
            return_value={
                "generation_mode": "EXTEND",
                "workspace_execution_package_id": "wep-p6-extend",
                "prompt_blocks_json": json.dumps(
                    [
                        {"duration_seconds": 8},
                        {"duration_seconds": 8},
                        {"duration_seconds": 8},
                    ]
                ),
            }
        ),
    )
    payload, blockers = await scheduler._build_item_payload(
        {
            "media_type": "VIDEO",
            "logical_mode": "T2V",
            "workspace_generation_package_id": "wgp-p6-extend",
            "prompt_package_json": json.dumps(
                {
                    "generation_mode": "EXTEND",
                    "video_job_id": "vj-p6-extend",
                    "video_job_plan_fingerprint": "plan-fp-p6-extend",
                    "requested_total_duration_seconds": 24,
                    "engine_block_duration_seconds": 8,
                }
            ),
            "creative_dimensions_json": json.dumps(
                {
                    "model_key": "veo_3_1_lite",
                    "duration_seconds": 24,
                }
            ),
        },
        {},
        aspect="9:16",
    )
    assert blockers == []
    assert payload["execution_lane"] == "VIDEO_JOBS_ORCHESTRATOR"
    assert payload["generation_mode"] == "EXTEND"
    assert payload["requested_total_duration_seconds"] == 24
    assert payload["engine_block_duration_seconds"] == 8
    assert payload["segment_count"] == 3
    assert payload["video_job_id"] == "vj-p6-extend"


@pytest.mark.asyncio
async def test_extend_dispatch_uses_existing_video_jobs_authority_not_single_door(
    monkeypatch,
):
    attempt = {
        "attempt_id": "attempt-p6-extend",
        "item_id": "item-p6-extend",
        "payload_snapshot_json": json.dumps(
            {
                "generation_mode": "EXTEND",
                "workspace_generation_package_id": "wgp-p6-extend",
                "model": "veo_3_1_lite",
                "aspect": "9:16",
            }
        ),
    }
    monkeypatch.setattr(
        scheduler,
        "_acquire_item_lease",
        AsyncMock(
            return_value=(
                {
                    "lane_id": "google-flow-video-primary",
                    "cooldown_seconds": 1,
                },
                {"lease_id": "lease-p6-extend"},
            )
        ),
    )

    async def update_attempt(attempt_id, **changes):
        return {**attempt, **changes}

    monkeypatch.setattr(scheduler.p6db, "update_attempt", update_attempt)
    monkeypatch.setattr(scheduler.p6db, "update_item", AsyncMock())
    monkeypatch.setattr(
        scheduler.production_queue_service,
        "_fire_extend_via_video_jobs",
        AsyncMock(return_value={"ok": True, "job_id": "vj-p6-extend"}),
    )
    single_door = AsyncMock()
    monkeypatch.setattr(scheduler.make_video, "start_generate", single_door)
    from agent.services import video_production_orchestrator as video_jobs

    monkeypatch.setattr(
        video_jobs,
        "get_job_status",
        AsyncMock(return_value={"job_id": "vj-p6-extend", "status": "CREATED"}),
    )
    monkeypatch.setattr(
        scheduler,
        "_persist_provider_observation",
        AsyncMock(side_effect=lambda current, _: current),
    )

    result = await scheduler._dispatch_attempt(
        {"item_id": "item-p6-extend"},
        attempt,
        credit_confirmation="AUTHORIZE_P6_LIVE_CREDIT_SPEND",
    )
    assert result["provider_job_id"] == "vj-p6-extend"
    scheduler.production_queue_service._fire_extend_via_video_jobs.assert_awaited_once()
    single_door.assert_not_awaited()


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
    with pytest.raises(
        plans.CreativeProductionError,
        match="requires exact product allocations",
    ):
        await plans.update_plan(
            plan["plan_id"],
            ProductionPlanUpdateRequest(
                request_id="request-p6-update-missing-allocation",
                operator_id="p6-owner",
                target_video_count=2,
            ),
        )
    updated = await plans.update_plan(
        plan["plan_id"],
        ProductionPlanUpdateRequest(
                request_id="request-p6-update-0002",
                operator_id="p6-owner",
                target_video_count=2,
                product_video_allocations=[
                    ProductVideoAllocation(
                        product_id=PRODUCT_ID,
                        video_count=2,
                    )
                ],
                operating_window_hours=24,
        ),
    )
    assert updated["target_video_count"] == 2
    assert updated["operating_window_hours"] == 24
    authority = await plans.get_governed_pool_authority(
        PoolAuthorityRequest(
            product_ids=[PRODUCT_ID],
            production_recipe="HYBRID",
        )
    )
    assert authority["credit_spend"] == 0
    assert authority["copy_sets"][0]["copy_set_id"] == COPY_SET_ID
    assert authority["avatar_profiles"][0]["avatar_code"] == AVATAR_CODE
    assert authority["product_reference_assets"] == []
    assert authority["official_product_visual_authority"]["source"] == (
        "PRODUCT_REGISTRATION"
    )
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
            production_recipe="FACELESS",
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
async def test_scheduler_tick_reconciles_existing_attempt_without_live_certification(
    monkeypatch,
):
    reconcile = AsyncMock()
    monkeypatch.setattr(
        scheduler.p6db,
        "list_attempts_for_reconciliation",
        AsyncMock(return_value=[{"attempt_id": "p6attempt-existing"}]),
    )
    monkeypatch.setattr(scheduler, "reconcile_attempt", reconcile)
    monkeypatch.setattr(
        scheduler.production_queue_service,
        "bulk_live_execution_certified",
        lambda: False,
    )

    result = await scheduler.scheduler_tick()

    assert result["live_execution_certified"] is False
    assert result["attempts_dispatched"] == 0
    reconcile.assert_awaited_once_with("p6attempt-existing")


@pytest.mark.asyncio
async def test_reconcile_persists_provider_identity_and_terminal_render_evidence(
    p58_authority,
    monkeypatch,
):
    plan, item = await _approved_plan(monkeypatch)
    attempt = await scheduler._create_attempt(
        {**item, "plan_id": plan["plan_id"]},
        action_request_id="attempt-provider-observation",
        actor_id="p6-reconciliation-test",
        payload={"mode": "F2V", "prompt": "safe"},
        credit_spend_intended=True,
    )
    attempt = await p6db.update_attempt(
        attempt["attempt_id"],
        attempt_state=AttemptState.PROVIDER_JOB_KNOWN.value,
        provider_job_id="g_provider_observation",
        provider_known_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    provider_job = {
        "job_id": "g_provider_observation",
        "status": "RENDER_NOT_MATERIALIZED",
        "stage": "render_not_materialized",
        "project_id": "flow-project-bosmax",
        "approved": True,
        "generation_started": True,
        "generation_identity": {
            "sse_prompt": "safe",
            "expected_model": "veo_3_1_r2v_lite",
            "tool_call_id": "provider-tool-call-1",
            "response_id": "provider-response-1",
            "seed": 314159,
        },
        "identity_captured": True,
        "tools_seen": ["generateVideoFromStartFrame"],
        "correlation_stats": {
            "completed_candidates_seen": 0,
            "completed_candidate_ids": [],
        },
        "credit_state": "CREDIT_UNKNOWN",
        "credit_spent_likely": False,
        "error": "video not found/retrieved in time",
    }
    attempt = await scheduler._persist_provider_observation(attempt, provider_job)
    monkeypatch.setattr(scheduler.make_video, "get_job", lambda _job_id: None)
    start_generate = AsyncMock()
    monkeypatch.setattr(scheduler.make_video, "start_generate", start_generate)

    result = await scheduler.reconcile_attempt(attempt["attempt_id"])

    assert result["provider_state"] == "RENDER_NOT_MATERIALIZED"
    assert result["provider_state_source"] == "DURABLE_PROVIDER_SNAPSHOT"
    assert result["resubmission_allowed"] is True
    assert result["attempt"]["attempt_state"] == AttemptState.FAILED.value
    assert result["attempt"]["provider_project_id"] == "flow-project-bosmax"
    assert (
        result["attempt"]["provider_correlation_id"]
        == "provider-tool-call-1"
    )
    assert (
        result["attempt"]["provider_snapshot"]["correlation_stats"][
            "completed_candidates_seen"
        ]
        == 0
    )
    stored_item = await p6db.get_item(item["item_id"])
    assert stored_item is not None
    assert stored_item["status"] == "FAILED"
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
