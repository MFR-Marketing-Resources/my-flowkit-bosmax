"""Durable full-video job — initial segment obeys the SAME per-mode reference
contract as one-block generation (unified all-mode orchestration).

The plan resolver produces an ORDERED `initial_reference_media_ids` list, the
orchestrator persists it, and `_initial_gen_preconditions` hands exactly that
list to the ONE door — F2V 1-2 · HYBRID 1 · I2V 2-3 · T2V 0, fail-closed.
"""
import json

import pytest

from agent.api import flow
from agent.services import production_plan_resolver as resolver
from agent.services import video_production_orchestrator as orch


def _job(**over):
    base = {
        "job_id": "vj_t", "product_id": "p1",
        "approved_asset_id": "product-image:p1:subject",
        "approved_asset_sha256": "hashZ",
        "initial_mode": "I2V", "initial_prompt_text": "reviewed block 1",
        "initial_asset_media_id": "m-a",
        "initial_reference_media_ids_json": json.dumps(["m-a", "m-b"]),
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
    }
    base.update(over)
    return base


# ── _initial_gen_preconditions: the ordered list reaches the one door ────────
def test_preconditions_return_ordered_reference_list():
    prompt, mode, refs, aspect = flow._initial_gen_preconditions(_job())
    assert mode == "I2V" and refs == ["m-a", "m-b"] and aspect == "9:16"


def test_preconditions_legacy_row_falls_back_to_single_asset():
    job = _job(initial_reference_media_ids_json=None)
    _, _, refs, _ = flow._initial_gen_preconditions(job)
    assert refs == ["m-a"]


def test_preconditions_t2v_is_text_only_and_needs_no_asset_authority():
    job = _job(initial_mode="T2V", approved_asset_id=None,
               approved_asset_sha256=None, initial_asset_media_id=None,
               initial_reference_media_ids_json=json.dumps([]))
    _, mode, refs, _ = flow._initial_gen_preconditions(job)
    assert mode == "T2V" and refs == []


def test_preconditions_t2v_rejects_inherited_references():
    job = _job(initial_mode="T2V",
               initial_reference_media_ids_json=json.dumps(["stale-1"]))
    with pytest.raises(flow.InitialGenerationError) as exc:
        flow._initial_gen_preconditions(job)
    assert "ZERO reference images" in str(exc.value)


def test_preconditions_reject_over_cap_reference_counts():
    job = _job(initial_reference_media_ids_json=json.dumps(["a", "b", "c", "d"]))
    with pytest.raises(flow.InitialGenerationError):
        flow._initial_gen_preconditions(job)


def test_preconditions_image_mode_still_requires_asset_authority():
    job = _job(approved_asset_sha256=None)
    with pytest.raises(flow.InitialGenerationError) as exc:
        flow._initial_gen_preconditions(job)
    assert "asset authority" in str(exc.value)


# ── resolver: ordered refs + per-mode contract in `missing` ──────────────────
def _intent(**over):
    base = {
        "product_id": "p1", "execution_package_id": "wep_x",
        "approved_asset_id": "product-image:p1:subject",
        "approved_asset_sha256": "hashZ", "initial_asset_media_id": "m-a",
        "requested_duration_seconds": 16, "engine": "GOOGLE_FLOW", "model": "veo",
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT", "initial_mode": "I2V",
        "initial_prompt_text": "reviewed block 1",
        "continuation_prompts": [{"position": 1, "block_index": 2,
                                  "prompt": "reviewed continuation", "is_final": True}],
    }
    base.update(over)
    return base


async def test_resolver_defaults_refs_from_single_asset_with_hard_caps_only():
    out = await resolver.resolve_production_authority(
        _intent(), trust_client_authority=True)
    # surface mode unknown → transport hard caps only; the proven single-image
    # (HYBRID-style) flow stays a COMPLETE plan
    assert out["initial_reference_media_ids"] == ["m-a"]
    assert out["missing"] == []


async def test_resolver_enforces_full_contract_when_surface_mode_known():
    out = await resolver.resolve_production_authority(
        _intent(initial_source_mode="I2V"), trust_client_authority=True)
    # user selected INGREDIENTS (2-3) but only one reference resolved → fail closed
    assert any(m.startswith("initial_reference_contract") for m in out["missing"])

    ok = await resolver.resolve_production_authority(
        _intent(initial_source_mode="I2V",
                initial_reference_media_ids=["m-a", "m-b"]),
        trust_client_authority=True)
    assert ok["initial_reference_media_ids"] == ["m-a", "m-b"]
    assert ok["missing"] == []


async def test_resolver_hybrid_surface_is_exactly_one_reference():
    out = await resolver.resolve_production_authority(
        _intent(initial_source_mode="HYBRID", initial_mode="F2V",
                initial_reference_media_ids=["m-a", "m-b"]),
        trust_client_authority=True)
    assert any(m.startswith("initial_reference_contract") for m in out["missing"])


async def test_resolver_t2v_needs_no_asset_and_clears_references():
    out = await resolver.resolve_production_authority(
        _intent(initial_mode="T2V", approved_asset_id=None,
                approved_asset_sha256=None, initial_asset_media_id=None,
                initial_reference_media_ids=["stale-1"]),
        trust_client_authority=True)
    # stale image state is explicitly cleared for a text-only initial
    assert out["initial_reference_media_ids"] == []
    assert out["missing"] == []


# ── orchestrator: the ordered list is PERSISTED on the job at plan time ──────
async def test_plan_job_persists_ordered_reference_list():
    intent = _intent(initial_source_mode="I2V",
                     initial_reference_media_ids=["m-a", "m-b"],
                     client_request_nonce="refpersist")
    planned = await orch.plan_job(intent, trust_client_authority=True)
    from agent.db import crud
    job = await crud.get_video_production_job(planned["job_id"])
    assert json.loads(job["initial_reference_media_ids_json"]) == ["m-a", "m-b"]
    assert job["initial_asset_media_id"] == "m-a"
