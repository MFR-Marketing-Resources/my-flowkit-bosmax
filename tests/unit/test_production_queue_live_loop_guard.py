"""T2V-only guard on the unphrased bulk live loop.

The ONE_SERIAL_T2V gate (LIVE_T2V_ONLY in _assert_one_serial_t2v_live) protects the
Studio's opt-in live path. But run_production_queue can also be started with
confirm_live_credit_burn=True and NO live_gate (ProductionQueuePage's bulk start) —
that path skips the gate and goes straight to _live_production_loop, which fired
every un-blocked queued item regardless of mode. Today F2V/I2V are safe only because
they BLOCK (no Flow media); the instant an image-mode item reaches ready=1 that
loop would fire it ungated. This guard refuses any non-T2V item in the loop too.

No provider is touched: _fire_and_wait is faked and must never be called for a
non-T2V item; a regression shows up as a recorded fire.
"""
import pytest

from agent.services import production_queue_service as pq

RUN_ID = "run_guard"


def _run() -> dict:
    return {
        "production_run_id": RUN_ID, "status": "RUNNING", "config_json": "{}",
        "interval_min_seconds": 0, "interval_max_seconds": 0,
        "cooldown_after_n_jobs": 5, "cooldown_seconds": 0,
        "total_completed": 0, "total_failed": 0, "error_log_json": "[]",
    }


@pytest.fixture
def loop(monkeypatch):
    """Drive _live_production_loop over an in-memory queue; record fires + writes."""
    state = {"queue": [], "updates": [], "fired": []}

    async def get_run(rid):
        return _run()

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
        # Each iteration selects one QUEUED item; a processed item leaves the set.
        return [state["queue"].pop(0)] if state["queue"] else []

    async def update_wgp(wgp_id, **kw):
        state["updates"].append({"wgp_id": wgp_id, **kw})
        return {}

    async def update_run(rid, **kw):
        return {}

    async def fire(make_video, payload, wgp_id):
        state["fired"].append(wgp_id)
        return {"ok": True}

    monkeypatch.setattr(pq.crud, "get_production_run", get_run)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_wgp)
    monkeypatch.setattr(pq.crud, "update_production_run", update_run)
    monkeypatch.setattr(pq, "_fire_and_wait", fire)
    return state


def _payload(mode, blockers=None):
    async def bep(item, cfg):
        return ({"logical_mode": mode, "mode": mode, "prompt": "x"}, blockers or [])
    return bep


@pytest.mark.parametrize("mode", ["F2V", "I2V", "HYBRID", "IMG", "", "UNKNOWN"])
@pytest.mark.asyncio
async def test_non_t2v_item_is_refused_in_the_live_loop(loop, monkeypatch, mode):
    """The core fix: a ready (no-blocker) non-T2V item is NEVER fired here."""
    monkeypatch.setattr(pq, "build_execution_payload", _payload(mode, []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_x"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []  # provider boundary never reached
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["production_error"].startswith("LIVE_T2V_ONLY:")


@pytest.mark.asyncio
async def test_t2v_item_still_fires_in_the_live_loop(loop, monkeypatch):
    """The guard must not touch the T2V happy path — a ready T2V item still fires."""
    monkeypatch.setattr(pq, "build_execution_payload", _payload("T2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_t2v"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == ["wgp_t2v"]


@pytest.mark.asyncio
async def test_blocked_t2v_item_still_refused_by_the_existing_blocker_path(loop, monkeypatch):
    """Regression: the pre-existing blocker refusal is unchanged."""
    monkeypatch.setattr(pq, "build_execution_payload", _payload("T2V", ["EMPTY_FINAL_PROMPT"]))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_blk"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert "EMPTY_FINAL_PROMPT" in failed[0]["production_error"]


@pytest.mark.asyncio
async def test_non_t2v_refused_but_a_t2v_sibling_in_the_same_run_still_fires(loop, monkeypatch):
    """Per-item: the F2V item is refused, the T2V item in the same run still fires."""
    async def bep(item, cfg):
        mode = "F2V" if item["workspace_generation_package_id"] == "wgp_f2v" else "T2V"
        return ({"logical_mode": mode, "mode": mode, "prompt": "x"}, [])
    monkeypatch.setattr(pq, "build_execution_payload", bep)
    loop["queue"] = [
        {"workspace_generation_package_id": "wgp_f2v"},
        {"workspace_generation_package_id": "wgp_t2v"},
    ]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == ["wgp_t2v"]
    assert any(
        u.get("production_error", "").startswith("LIVE_T2V_ONLY:F2V")
        for u in loop["updates"]
    )


# ── EXTEND packages must NEVER fire through the single-shot lane ──────────
#
# An EXTEND package is multi-block (16s+ = N blocks + seam handoff + concat).
# Firing it here would silently render ONE 8s block for the whole request —
# truncation presented as success. Multi-block execution belongs to the durable
# /video-jobs orchestrator lane.


@pytest.mark.asyncio
async def test_extend_package_is_refused_by_build_execution_payload():
    payload, blockers = await pq.build_execution_payload(
        {
            "workspace_generation_package_id": "wgp_ext",
            "logical_mode": "T2V", "mode": "T2V",
            "generation_mode": "EXTEND",
            "requested_total_duration_seconds": 16,
            "final_prompt_text": "block 1 prompt",
        },
        {"model": "Veo 3.1 - Lite", "aspect": "9:16"},
    )
    assert payload == {"logical_mode": "T2V"}  # mode kept so the loop reports THIS blocker
    assert blockers == ["EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN:16s_USE_VIDEO_JOBS_ORCHESTRATOR"]


@pytest.mark.asyncio
async def test_extend_item_never_fires_in_the_live_loop(loop, monkeypatch):
    """End-to-end through the loop: an EXTEND item FAILS with the blocker, no fire."""
    real_bep = pq.build_execution_payload

    async def bep(item, cfg):
        return await real_bep(item, cfg)
    monkeypatch.setattr(pq, "build_execution_payload", bep)
    loop["queue"] = [{
        "workspace_generation_package_id": "wgp_ext",
        "logical_mode": "T2V", "mode": "T2V",
        "generation_mode": "EXTEND",
        "requested_total_duration_seconds": 16,
        "final_prompt_text": "block 1 prompt",
    }]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and "EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN" in failed[0]["production_error"]


@pytest.mark.asyncio
async def test_single_package_unaffected_by_the_extend_guard(loop, monkeypatch):
    """generation_mode SINGLE (or absent) keeps the exact existing behaviour."""
    monkeypatch.setattr(pq, "build_execution_payload", _payload("T2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_single"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == ["wgp_single"]
