"""P7.5-C P6 treatment authority, lineage, and anti-Cartesian proof."""

from __future__ import annotations

import json

import pytest

from agent.models.creative_production import (
    CreativePoolSelection,
    ProductionPlanCreateRequest,
)
from agent.services import creative_production_compile_service as compiler
from agent.services import creative_production_plan_service as plans
from agent.services import creative_production_scheduler_service as scheduler
from agent.services import creative_treatment_service


def _projection(treatment_id: str = "treatment-1") -> dict:
    return {
        "treatment_id": treatment_id,
        "treatment_sha256": "a" * 64,
        "product_id": "product-1",
        "format": "UGC",
        "generation_mode": "SINGLE",
        "duration_seconds": 8.0,
        "copy_set_id": "copy-1",
        "content_angle": "mudah",
        "dialogue_text": "Dialog yang diluluskan.",
        "avatar_code": "AVATAR_01",
        "wardrobe_text": "neutral",
        "scene_strategy_id": "SPICE_SEASONING",
        "scene_template_id": "scene-1",
        "camera_preset_code": "camera-1",
        "asset_bindings": [
            {"role": "PRODUCT_REFERENCE", "asset_id": "asset-product"},
        ],
        "action_sequence": [
            {
                "sequence": 1,
                "action_text": "Tuang rempah",
                "actor_role": "HANDS",
                "initial_state": "tertutup",
                "resulting_state": "dituang",
                "continuity_requirements": [],
            }
        ],
        "shot_grammar": [
            {
                "sequence": 1,
                "action_sequences": [1],
                "purpose": "demo",
                "framing": "close-up",
                "camera_motion": "push",
                "subject": "produk",
                "duration_seconds": 8,
                "continuity_in": [],
                "continuity_out": [],
            }
        ],
        "compatibility_profile": {
            "logical_mode": "T2V",
            "source_mode": "T2V",
            "model_keys": ["Veo 3.1 - Lite"],
            "required_asset_roles": ["PRODUCT_REFERENCE"],
        },
        "compatible_model_keys": ["Veo 3.1 - Lite"],
        "selected_model_key": "Veo 3.1 - Lite",
        "visual_fingerprint_sha256": "b" * 64,
        "variation_group": None,
        "variation_group_id": None,
        "variation_ordinal": None,
        "dependency_hashes": {"copy_set_sha256": "c" * 64},
        "segment_plan": [],
    }


def _plan(*, treatment_ids: list[str], target: int = 1) -> dict:
    return {
        "plan_id": "plan-1",
        "product_scope_json": json.dumps(["product-1"]),
        "target_video_count": target,
        "target_image_count": 0,
        "target_poster_count": 0,
        "logical_mode": "T2V",
        "model_keys_json": json.dumps(["Veo 3.1 - Lite"]),
        "duration_seconds_json": json.dumps([8]),
        "pool_snapshot_json": json.dumps(
            {
                "treatment_ids": treatment_ids,
                "product_video_allocations": [],
            }
        ),
    }


def test_video_request_allows_server_authoritative_treatment_allocation() -> None:
    request = ProductionPlanCreateRequest(
        request_id="request-p75c-0001",
        operator_id="operator",
        name="Treatment plan",
        product_ids=["product-1"],
        product_video_allocations=[
            {"product_id": "product-1", "video_count": 1},
        ],
        target_video_count=1,
        model_keys=["Veo 3.1 - Lite"],
        duration_seconds=[8],
        pools=CreativePoolSelection(),
    )
    assert request.pools.treatment_ids == []
    assert request.product_video_allocations[0].video_count == 1


@pytest.mark.asyncio
async def test_treatment_availability_is_deterministic_and_reports_exact_shortage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    treatment_ids_by_product = {
        "product-1": ["treatment-a-2", "treatment-a-1"],
        "product-2": ["treatment-b-1"],
    }

    async def list_treatments(
        *,
        product_id: str,
        status: str,
        limit: int,
    ) -> list[dict]:
        assert status == "APPROVED"
        assert limit == 200
        return [
            {"treatment_id": treatment_id}
            for treatment_id in treatment_ids_by_product[product_id]
        ]

    async def resolve(treatment_id: str) -> dict:
        projection = _projection(treatment_id)
        projection["product_id"] = (
            "product-2" if treatment_id.startswith("treatment-b") else "product-1"
        )
        return projection

    monkeypatch.setattr(plans.treatment_db, "list_treatments", list_treatments)
    monkeypatch.setattr(plans, "resolve_treatment_authority", resolve)

    shortage = await plans.resolve_treatment_availability(
        product_video_allocations=[
            {"product_id": "product-1", "video_count": 2},
            {"product_id": "product-2", "video_count": 2},
        ],
        logical_mode="T2V",
        model_key="Veo 3.1 - Lite",
        duration_seconds=8,
    )
    assert shortage["ready"] is False
    assert shortage["selected_treatment_ids"] == [
        "treatment-a-1",
        "treatment-a-2",
        "treatment-b-1",
    ]
    assert shortage["product_results"][1]["shortage"] == 1
    assert shortage["blockers"][0]["code"] == "TREATMENT_CAPACITY_INSUFFICIENT"

    ready = await plans.resolve_treatment_availability(
        product_video_allocations=[
            {"product_id": "product-1", "video_count": 2},
        ],
        logical_mode="T2V",
        model_key="Veo 3.1 - Lite",
        duration_seconds=8,
    )
    repeated = await plans.resolve_treatment_availability(
        product_video_allocations=[
            {"product_id": "product-1", "video_count": 2},
        ],
        logical_mode="T2V",
        model_key="Veo 3.1 - Lite",
        duration_seconds=8,
    )
    assert ready["ready"] is True
    assert ready["selection_mode"] == "AUTO"
    assert ready["availability_sha256"] == repeated["availability_sha256"]


@pytest.mark.asyncio
async def test_plan_treatments_preserve_order_and_bound_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(
        treatment_id: str,
        *,
        plan: dict | None = None,
        expected: dict | None = None,
    ) -> dict:
        del plan, expected
        return _projection(treatment_id)

    monkeypatch.setattr(plans, "resolve_treatment_authority", resolve)
    resolved = await plans._resolve_plan_treatments(
        _plan(treatment_ids=["treatment-2", "treatment-1"], target=2)
    )
    assert [row["treatment_id"] for row in resolved] == [
        "treatment-2",
        "treatment-1",
    ]
    with pytest.raises(
        plans.CreativeProductionError,
        match="Video target exceeds eligible unique treatment authority",
    ):
        await plans._resolve_plan_treatments(
            _plan(treatment_ids=["treatment-1"], target=2)
        )


@pytest.mark.asyncio
async def test_unapproved_treatment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_treatment(treatment_id: str) -> dict:
        return {"treatment_id": treatment_id, "status": "DRAFT"}

    monkeypatch.setattr(plans.treatment_db, "get_treatment", get_treatment)
    with pytest.raises(plans.CreativeProductionError) as error:
        await plans.resolve_treatment_authority("treatment-draft")
    assert error.value.code == "TREATMENT_NOT_APPROVED"


@pytest.mark.asyncio
async def test_incompatible_treatment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        **_projection(),
        "status": "APPROVED",
        "source_mode": "T2V",
    }

    async def get_treatment(treatment_id: str) -> dict:
        del treatment_id
        return row

    monkeypatch.setattr(plans.treatment_db, "get_treatment", get_treatment)
    monkeypatch.setattr(
        plans.treatment_service,
        "_decode_treatment",
        lambda value: {
            **value,
            "compatibility_profile": {
                "logical_mode": "F2V",
                "source_mode": "T2V",
                "model_keys": [],
            },
        },
    )
    with pytest.raises(plans.CreativeProductionError) as error:
        await plans.resolve_treatment_authority("treatment-incompatible")
    assert error.value.code == "TREATMENT_INCOMPATIBLE"


@pytest.mark.asyncio
async def test_dependency_drift_is_rejected_with_stable_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {**_projection(), "status": "APPROVED"}

    async def get_treatment(treatment_id: str) -> dict:
        del treatment_id
        return row

    async def stale(value: dict) -> dict:
        del value
        raise creative_treatment_service.CreativeTreatmentError(
            "COPY_SET_NOT_APPROVED"
        )

    monkeypatch.setattr(plans.treatment_db, "get_treatment", get_treatment)
    monkeypatch.setattr(
        plans.treatment_service,
        "_decode_treatment",
        lambda value: value,
    )
    monkeypatch.setattr(plans.treatment_service, "_revalidate", stale)
    with pytest.raises(plans.CreativeProductionError) as error:
        await plans.resolve_treatment_authority("treatment-stale")
    assert error.value.code == "TREATMENT_DEPENDENCY_STALE"


def test_video_dimensions_are_one_row_per_treatment_not_cartesian() -> None:
    approved = {
        "raw": {
            "layout_ids": [],
            "product_reference_asset_ids": [],
            "finished_frame_asset_ids": [],
            "character_asset_ids": [],
            "scene_asset_ids": [],
            "style_asset_ids": [],
        },
        "approved_layouts": {},
        "avatar_profiles": {},
        "assets": {},
        "scene_strategies": {},
        "creative_selections": {},
        "treatments": [_projection()],
    }
    capacity, rows, blockers = plans._product_dimension_rows(
        plan=_plan(treatment_ids=["treatment-1"]),
        approved=approved,
        product_id="product-1",
        media_type="VIDEO",
    )
    assert capacity == 1
    assert len(rows) == 1
    assert not blockers
    assert rows[0]["treatment_id"] == "treatment-1"
    assert rows[0]["creative_treatment"]["shot_grammar"]


@pytest.mark.asyncio
async def test_legacy_nonterminal_video_item_fails_lineage() -> None:
    payload, blockers = await scheduler._build_item_payload(
        {
            "media_type": "VIDEO",
            "prompt_package_json": "{}",
            "creative_dimensions_json": json.dumps(
                {"model_key": "Veo 3.1 - Lite", "duration_seconds": "8"}
            ),
        },
        _plan(treatment_ids=["treatment-1"]),
        aspect="9:16",
    )
    assert payload == {}
    assert blockers == ["TREATMENT_LINEAGE_REQUIRED"]


@pytest.mark.asyncio
async def test_extend_compile_links_one_wep_and_wgp_to_master_segment_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    treatment = {
        **_projection(),
        "generation_mode": "EXTEND",
        "duration_seconds": 16,
        "segment_plan": {
            "segment_plan_sha256": "d" * 64,
            "ordered_segment_sha256s": ["1" * 64, "2" * 64],
            "segment_count": 2,
            "segments": [
                {
                    "segment_index": 1,
                    "duration_seconds": 8,
                    "segment_sha256": "1" * 64,
                },
                {
                    "segment_index": 2,
                    "duration_seconds": 8,
                    "segment_sha256": "2" * 64,
                },
            ],
        },
    }
    calls: dict[str, dict] = {}

    async def resolve_item(dimensions: dict, plan: dict) -> dict:
        del dimensions, plan
        return treatment

    async def create_wep(**kwargs) -> dict:
        calls["wep"] = kwargs
        return {
            "workspace_execution_package_id": "wep-treatment-extend",
            "readiness": "READY",
            "blockers": [],
        }

    async def create_wgp(**kwargs) -> dict:
        calls["wgp"] = kwargs
        return {
            "workspace_generation_package_id": "wgp-treatment-extend",
            "prompt_fingerprint": "f" * 64,
            "final_prompt_text": "approved governed EXTEND prompt",
            "status": "READY",
            "blockers_json": "[]",
        }

    monkeypatch.setattr(compiler, "resolve_item_treatment", resolve_item)
    monkeypatch.setattr(
        compiler.wep_service,
        "create_workspace_execution_package",
        create_wep,
    )
    monkeypatch.setattr(
        compiler.wgp_service,
        "create_t2v_generation_package",
        create_wgp,
    )

    package_id, prompt_sha, prompt_package = await compiler._compile_video(
        {
            "item_id": "item-treatment-extend",
            "product_id": "product-1",
            "creative_dna_sha256": "e" * 64,
        },
        {
            "plan_id": "plan-treatment-extend",
            "logical_mode": "T2V",
            "execution_policy_json": json.dumps({"aspect": "9:16"}),
        },
        {
            "generation_mode": "EXTEND",
            "duration_seconds": 16,
            "engine_block_duration_seconds": 8,
            "segment_count": 2,
            "execution_route": "VIDEO_JOBS_ORCHESTRATOR",
            "model_key": "Veo 3.1 - Lite",
        },
    )

    assert package_id == "wgp-treatment-extend"
    assert prompt_sha == "f" * 64
    assert calls["wep"]["generation_mode"] == "EXTEND"
    assert calls["wep"]["requested_total_duration_seconds"] == 16
    assert calls["wep"]["creative_treatment"] == treatment
    assert (
        calls["wgp"]["workspace_execution_package_id"]
        == "wep-treatment-extend"
    )
    assert calls["wgp"]["creative_treatment"] == treatment
    assert prompt_package["workspace_execution_package_id"] == (
        "wep-treatment-extend"
    )
    assert prompt_package["treatment_lineage"]["segment_plan_sha256"] == (
        "d" * 64
    )
    assert prompt_package["treatment_lineage"][
        "ordered_segment_sha256s"
    ] == ["1" * 64, "2" * 64]


@pytest.mark.asyncio
async def test_extend_scheduler_persists_job_plan_without_provider_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.api import flow as flow_api

    treatment = {
        **_projection(),
        "generation_mode": "EXTEND",
        "duration_seconds": 16,
        "segment_plan": {
            "segment_plan_sha256": "d" * 64,
            "ordered_segment_sha256s": ["1" * 64, "2" * 64],
        },
    }
    lineage = {
        "treatment_id": treatment["treatment_id"],
        "treatment_sha256": treatment["treatment_sha256"],
        "visual_fingerprint_sha256": treatment[
            "visual_fingerprint_sha256"
        ],
        "dependency_hashes": treatment["dependency_hashes"],
        "variation_group": None,
        "format": "UGC",
        "generation_mode": "EXTEND",
        "segment_plan_sha256": "d" * 64,
        "ordered_segment_sha256s": ["1" * 64, "2" * 64],
    }
    plan_calls: list[tuple[object, bool]] = []

    async def resolve_item(dimensions: dict, plan: dict) -> dict:
        del dimensions, plan
        return treatment

    async def get_wgp(wgp_id: str) -> dict:
        assert wgp_id == "wgp-treatment-extend"
        return {
            "workspace_generation_package_id": wgp_id,
            "workspace_execution_package_id": "wep-treatment-extend",
            "product_id": "product-1",
            "product_name_snapshot": "P6 Product",
            "generation_mode": "EXTEND",
        }

    def extend_preconditions(
        wgp: dict,
        settings: dict,
    ) -> tuple[dict, list[str]]:
        assert wgp["workspace_generation_package_id"] == (
            "wgp-treatment-extend"
        )
        assert settings == {
            "model": "Veo 3.1 - Lite",
            "aspect": "9:16",
        }
        return (
            {
                "logical_mode": "T2V",
                "total_seconds": 16,
                "execution_package_id": "wep-treatment-extend",
            },
            [],
        )

    async def plan_video_job(
        body: object,
        *,
        trust_client_authority: bool,
    ) -> dict:
        plan_calls.append((body, trust_client_authority))
        return {
            "job_id": "video-job-treatment-extend",
            "plan_fingerprint": "9" * 64,
        }

    monkeypatch.setattr(scheduler, "resolve_item_treatment", resolve_item)
    monkeypatch.setattr(scheduler.crud, "get_workspace_generation_package", get_wgp)
    monkeypatch.setattr(
        scheduler.production_queue_service,
        "extend_execution_preconditions",
        extend_preconditions,
    )
    monkeypatch.setattr(flow_api, "_plan_video_job", plan_video_job)

    payload, blockers = await scheduler._build_item_payload(
        {
            "media_type": "VIDEO",
            "logical_mode": "T2V",
            "workspace_generation_package_id": "wgp-treatment-extend",
            "prompt_package_json": json.dumps(
                {
                    "generation_mode": "EXTEND",
                    "requested_total_duration_seconds": 16,
                    "engine_block_duration_seconds": 8,
                    "treatment_lineage": lineage,
                }
            ),
            "creative_dimensions_json": json.dumps(
                {
                    "model_key": "Veo 3.1 - Lite",
                    "duration_seconds": "16",
                    "generation_mode": "EXTEND",
                    "creative_treatment": treatment,
                }
            ),
        },
        _plan(treatment_ids=["treatment-1"]),
        aspect="9:16",
    )

    assert blockers == []
    assert payload["video_job_id"] == "video-job-treatment-extend"
    assert payload["video_job_plan_fingerprint"] == "9" * 64
    assert payload["execution_lane"] == "VIDEO_JOBS_ORCHESTRATOR"
    assert payload["creative_treatment_lineage"] == lineage
    assert len(plan_calls) == 1
    request, trust_client_authority = plan_calls[0]
    assert trust_client_authority is False
    assert request.client_request_nonce == "wgp-treatment-extend"
    assert request.requested_total_duration_seconds == 16


@pytest.mark.asyncio
async def test_payload_hash_input_carries_revalidated_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    treatment = _projection()
    lineage = {
        "treatment_id": treatment["treatment_id"],
        "treatment_sha256": treatment["treatment_sha256"],
        "visual_fingerprint_sha256": treatment[
            "visual_fingerprint_sha256"
        ],
        "dependency_hashes": treatment["dependency_hashes"],
        "variation_group": None,
        "format": "UGC",
        "generation_mode": "SINGLE",
        "segment_plan_sha256": None,
        "ordered_segment_sha256s": [],
    }

    async def resolve_item(dimensions: dict, plan: dict) -> dict:
        del dimensions, plan
        return treatment

    async def get_wgp(wgp_id: str) -> dict:
        return {
            "workspace_generation_package_id": wgp_id,
            "generation_mode": "SINGLE",
            "final_prompt_text": "approved prompt",
        }

    async def build_payload(wgp: dict, settings: dict) -> tuple[dict, list]:
        del wgp, settings
        return {"mode": "T2V", "prompt": "approved prompt"}, []

    monkeypatch.setattr(scheduler, "resolve_item_treatment", resolve_item)
    monkeypatch.setattr(scheduler.crud, "get_workspace_generation_package", get_wgp)
    monkeypatch.setattr(
        scheduler.production_queue_service,
        "build_execution_payload",
        build_payload,
    )
    payload, blockers = await scheduler._build_item_payload(
        {
            "media_type": "VIDEO",
            "logical_mode": "T2V",
            "workspace_generation_package_id": "wgp-1",
            "prompt_package_json": json.dumps({"treatment_lineage": lineage}),
            "creative_dimensions_json": json.dumps(
                {
                    "model_key": "Veo 3.1 - Lite",
                    "duration_seconds": "8",
                    "creative_treatment": treatment,
                }
            ),
        },
        _plan(treatment_ids=["treatment-1"]),
        aspect="9:16",
    )
    assert not blockers
    assert payload["creative_treatment_lineage"] == lineage
    assert payload["compiled_shot_grammar"] == treatment["shot_grammar"]
