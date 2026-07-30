"""P7.5-C P6 treatment authority, lineage, and anti-Cartesian proof."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent.models.creative_production import (
    CreativePoolSelection,
    ProductionPlanCreateRequest,
)
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


def test_video_request_requires_explicit_treatment_ids() -> None:
    with pytest.raises(ValidationError, match="TREATMENT_IDS_REQUIRED_FOR_VIDEO"):
        ProductionPlanCreateRequest(
            request_id="request-p75c-0001",
            operator_id="operator",
            name="Treatment plan",
            product_ids=["product-1"],
            target_video_count=1,
            model_keys=["Veo 3.1 - Lite"],
            duration_seconds=[8],
            pools=CreativePoolSelection(),
        )


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
