"""Idempotency, single-flight, and crash-recovery (amendment 6 / guard 11).

A duplicate paid request never burns a second provider call; a concurrent authoring
is refused; a crashed RESERVED/RUNNING batch is reconciled to FAILED (never
auto-repeated) so the session cannot deadlock. PROVIDER-FREE.
"""

import pytest

from agent.db import copy_render_crud as crud
from agent.services import copy_render_service as svc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


async def _open_session(target: int = 5):
    boot = await bootstrap_ready_benefit()
    return await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                    lane="HYBRID", target_count=target, duration_seconds=16)


async def test_duplicate_request_id_is_one_provider_call():
    before = real_calls()
    s = await _open_session()
    fake = StitchFake()
    r1 = await svc.generate_suggestions(s["session_id"], "req-idem-00001", provider=fake)
    r2 = await svc.generate_suggestions(s["session_id"], "req-idem-00001", provider=fake)
    assert fake.calls == 1                          # the replay burned no second call
    a = {c["candidate_id"] for c in r1["candidates"] if c["status"] == "SHOWN"}
    b = {c["candidate_id"] for c in r2["candidates"] if c["status"] == "SHOWN"}
    assert a == b and len(a) == 5                   # same batch replayed
    assert real_calls() == before


async def test_single_flight_refuses_concurrent_authoring():
    s = await _open_session()
    # Inject a FRESH RESERVED batch (as if another request is mid-flight).
    await crud.reserve_batch({
        "batch_id": crud.new_id("CRB"), "session_id": s["session_id"], "batch_number": 1,
        "request_id": "req-inflight-0001", "action": "GENERATE", "recipe_plan": [],
        "requested_recipe_count": 5,
    })
    fake = StitchFake()
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-different-0002", provider=fake)
    assert e.value.code == "COPY_RENDER_BATCH_IN_PROGRESS"
    assert fake.calls == 0                           # never reached the provider


async def test_crash_recovery_reconciles_stale_running_then_proceeds():
    before = real_calls()
    s = await _open_session()
    # A RUNNING batch whose provider outcome is unknowable and is long stale.
    stale_id = crud.new_id("CRB")
    await crud.reserve_batch({
        "batch_id": stale_id, "session_id": s["session_id"], "batch_number": 1,
        "request_id": "req-crashed-0001", "action": "GENERATE", "recipe_plan": [],
        "requested_recipe_count": 5,
    })
    await crud.update_batch(stale_id, {"status": "RUNNING", "provider_started_at": "2020-01-01T00:00:00Z"})

    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-recover-0002", provider=fake)
    # the crashed batch is reconciled fail-closed, never auto-repeated
    stale = await crud.get_batch(stale_id)
    assert stale["status"] == "FAILED" and stale["failure_code"] == "UNKNOWN_OUTCOME"
    # and the fresh request proceeds normally (one real logical call)
    assert fake.calls == 1
    assert len([c for c in r["candidates"] if c["status"] == "SHOWN"]) == 5
    assert real_calls() == before


async def test_fresh_reserved_batch_is_not_reconciled():
    s = await _open_session()
    fresh_id = crud.new_id("CRB")
    await crud.reserve_batch({
        "batch_id": fresh_id, "session_id": s["session_id"], "batch_number": 1,
        "request_id": "req-fresh-0001", "action": "GENERATE", "recipe_plan": [],
        "requested_recipe_count": 5,
    })
    # A recent RESERVED batch must block (not be swept as crashed).
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-other-0002", provider=StitchFake())
    assert e.value.code == "COPY_RENDER_BATCH_IN_PROGRESS"
    assert (await crud.get_batch(fresh_id))["status"] == "RESERVED"
