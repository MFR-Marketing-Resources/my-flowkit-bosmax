"""Request-scoped BENEFIT_COPY_RENDER_V1 authority + multiplexer honesty (amendment 1).

Proves the renderer NEVER fabricates a Copy-Register-V2 binding, that the execution
-copy multiplexer routes a benefit-render selection to the distinct authority, and
that WITHOUT a render selection it delegates to the existing V2 resolver unchanged.
PROVIDER-FREE.
"""

import pytest

from agent.db import copy_render_crud as crud
from agent.services import copy_execution_resolver as cer
from agent.services import copy_render_service as svc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


async def _finalized_candidate(target: int = 1, lane: str = "HYBRID"):
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=16)
    r = await svc.generate_suggestions(s["session_id"], "req-res-00001", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    for c in shown[:target]:
        await svc.lock_candidate(c["candidate_id"])
    await svc.finalize_session(s["session_id"])
    return boot, s, shown


async def test_rendered_authority_is_honest_no_v2_spoof():
    before = real_calls()
    boot, s, shown = await _finalized_candidate()
    cid = shown[0]["candidate_id"]
    art = await crud.get_artifact(shown[0]["artifact_id"])

    res = await cer.resolve_execution_copy(
        boot["product_id"], "HYBRID", {"benefit_copy_render": {"candidate_id": cid}})

    assert res.authority_kind == "BENEFIT_COPY_RENDER_V1"
    assert res.v2_enabled is False          # never claims a V2 binding exists
    assert res.copy_ready is True           # but IS a usable copy authority
    assert res.binding is None and res.projection is None
    assert res.status == "READY"
    assert res.approved_dialogue == art["full_copy_text"]
    ci = res.compiler_copy_intelligence
    assert ci["copy_source"] == "benefit_copy_render_v1"
    stages = {x["stage_key"]: x["text"] for x in crud.decode(art["stage_json"], [])}
    assert ci["hook"] == stages["problem"]  # PAS output_mapping: hook<-problem
    assert ci["cta"] == stages["cta"]

    md = res.to_metadata()
    assert md["authority_kind"] == "BENEFIT_COPY_RENDER_V1" and md["v2_enabled"] is False
    assert "binding" not in md              # NO fabricated V2 binding in lineage
    assert real_calls() == before


async def test_multiplexer_delegates_to_v2_when_render_absent():
    boot = await bootstrap_ready_benefit()

    async def _outcome(fn):
        # Capture the FULL outcome — return shape or error code — so parity is exact
        # regardless of whether the V2 resolver returns or fail-closes.
        try:
            r = await fn()
            return ("return", r.authority_kind, r.v2_enabled, r.copy_ready)
        except cer.CopyExecutionResolutionError as ex:
            return ("raise", ex.code)

    direct = await _outcome(
        lambda: cer.resolve_persisted_copy_execution_binding(boot["product_id"], "HYBRID", {}, None))
    via_mux = await _outcome(
        lambda: cer.resolve_execution_copy(boot["product_id"], "HYBRID", {}))
    # Multiplexer-without-render == the pure V2 resolver, byte-for-byte unchanged…
    assert via_mux == direct
    # …and it is NEVER silently promoted to the render authority.
    assert "BENEFIT_COPY_RENDER" not in str(via_mux)


async def test_rendered_resolution_rejects_lane_mismatch():
    boot, _s, shown = await _finalized_candidate(lane="HYBRID")
    cid = shown[0]["candidate_id"]
    with pytest.raises(cer.CopyExecutionResolutionError) as e:
        await cer.resolve_execution_copy(
            boot["product_id"], "FACELESS", {"benefit_copy_render": {"candidate_id": cid}})
    assert e.value.code == "BENEFIT_COPY_RENDER_LANE_MISMATCH"


async def test_rendered_resolution_rejects_unselected_candidate():
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=2, duration_seconds=16)
    r = await svc.generate_suggestions(s["session_id"], "req-res-unsel-1", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    with pytest.raises(cer.CopyExecutionResolutionError) as e:
        await cer.resolve_execution_copy(
            boot["product_id"], "HYBRID", {"benefit_copy_render": {"candidate_id": shown[0]["candidate_id"]}})
    assert e.value.code == "BENEFIT_COPY_RENDER_CANDIDATE_NOT_SELECTED"
