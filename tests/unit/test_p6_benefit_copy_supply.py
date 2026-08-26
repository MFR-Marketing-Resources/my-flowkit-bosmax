"""Round 3 — Production Studio / P6 accepts finalized BENEFIT_COPY_RENDER_V1 copy.

The single P6 copy funnel projects a finalized rendered-copy candidate into the
same DNA the V2 authority produces — provider-free, request-scoped, never touching
the product-global Copy Register V2 binding.
"""

import pytest

from agent.services import copy_render_service as crs
from agent.services import creative_production_plan_service as p6
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


async def _faceless_finalized_candidate():
    boot = await bootstrap_ready_benefit()
    s = await crs.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="FACELESS", target_count=1, duration_seconds=16)
    r = await crs.generate_suggestions(s["session_id"], "req-p6-01", provider=StitchFake())
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    await crs.lock_candidate(shown[0])
    await crs.finalize_session(s["session_id"])
    return boot["product_id"], shown[0]


async def test_benefit_copy_authority_record_projects_finalized_candidate_provider_free():
    product_id, cand = await _faceless_finalized_candidate()
    before = real_calls()
    rec = await p6._benefit_copy_authority_record(product_id, cand, "FACELESS")
    # request-scoped identity — NOT a V2 binding, NOT a legacy copy_set
    assert rec["copy_set_id"] == f"benefit_copy_render:{cand}"
    assert rec["copy_binding_id"] is None and rec["blueprint_id"] is None
    assert rec["benefit_copy_render"]["candidate_id"] == cand
    assert rec["benefit_copy_render"]["authority_kind"] == "BENEFIT_COPY_RENDER_V1"
    assert rec["copy_architecture_v2"]["authority_kind"] == "BENEFIT_COPY_RENDER_V1"
    # projected copy DNA dimensions the P6 matrix consumes
    assert rec["hook"] and rec["cta"] and rec["formula_family"]
    assert real_calls() == before  # provider-free


def test_pool_selection_accepts_benefit_copy_render_and_still_rejects_legacy_copyset():
    from agent.models.creative_production import CreativePoolSelection
    sel = CreativePoolSelection(benefit_copy_render={"prod_x": ["CRC_1", "CRC_2"]})
    assert sel.benefit_copy_render == {"prod_x": ["CRC_1", "CRC_2"]}
    # legacy CopySet pools remain archived/forbidden
    with pytest.raises(ValueError):
        CreativePoolSelection(copy_set_ids=["legacy"])


def test_benefit_copy_render_threads_into_pool_snapshot():
    # model_dump(mode="json") is exactly what create_plan folds into pool_snapshot_json.
    from agent.models.creative_production import CreativePoolSelection
    dumped = CreativePoolSelection(benefit_copy_render={"*": ["CRC_9"]}).model_dump(mode="json")
    assert dumped["benefit_copy_render"] == {"*": ["CRC_9"]}
