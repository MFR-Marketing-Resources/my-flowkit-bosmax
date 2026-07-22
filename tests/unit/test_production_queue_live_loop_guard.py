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
    """End-to-end through the loop: an EXTEND item NEVER reaches the single-shot
    door — it is routed to the durable /video-jobs orchestrator instead.

    `loop["fired"] == []` is the LOAD-BEARING safety property of this test and must
    never be relaxed: `fired` records _fire_and_wait, i.e. the single-shot
    make_video.start_generate door, which renders exactly ONE 8s block. Letting an
    EXTEND item through it would truncate a 16s/24s request and report the
    truncation as success. Multi-block execution is a DIFFERENT lane, and this
    asserts the item took that lane instead.
    """
    real_bep = pq.build_execution_payload

    async def bep(item, cfg):
        return await real_bep(item, cfg)
    monkeypatch.setattr(pq, "build_execution_payload", bep)

    routed: list[str] = []

    async def _durable(item, cfg, wgp_id):
        routed.append(wgp_id)
        return {"ok": True, "job_id": "vj_test"}
    monkeypatch.setattr(pq, "_fire_extend_via_video_jobs", _durable)

    loop["queue"] = [{
        "workspace_generation_package_id": "wgp_ext",
        "logical_mode": "T2V", "mode": "T2V",
        "generation_mode": "EXTEND",
        "requested_total_duration_seconds": 16,
        "final_prompt_text": "block 1 prompt",
    }]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []  # NEVER relax: the single-shot door stays unused
    assert routed == ["wgp_ext"]  # routed to the durable multi-block orchestrator


@pytest.mark.asyncio
async def test_single_package_unaffected_by_the_extend_guard(loop, monkeypatch):
    """generation_mode SINGLE (or absent) keeps the exact existing behaviour."""
    monkeypatch.setattr(pq, "build_execution_payload", _payload("T2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_single"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == ["wgp_single"]


# ── Reference dedupe + reference-count contract at DRY-RUN ────────────────
#
# Live I2V wgp_99e9961ae1ac5413: subject + product_reference both auto-seeded
# from the product image → the duplicate pushed 3 real refs to 4 and the fire
# died at the door (ERR_REFERENCE_COUNT_CONTRACT) AFTER a green dry-run.
# build_execution_payload now dedupes media ids and applies the same contract
# authority as a dry-run blocker.


@pytest.mark.asyncio
async def test_duplicate_slot_media_ids_are_deduped(monkeypatch):
    async def fake_resolve(asset_ref, pkg):
        return {"product-image:p1:subject": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "product-image:p1:product_reference": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "ca_char": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "ca_scene": "cccccccc-cccc-cccc-cccc-cccccccccccc"}.get(asset_ref)
    monkeypatch.setattr(pq, "_resolve_flow_media_id", fake_resolve)

    import json as _j
    payload, blockers = await pq.build_execution_payload(
        {"workspace_generation_package_id": "wgp_i", "logical_mode": "I2V",
         "final_prompt_text": "p",
         "resolved_engine_slots_json": _j.dumps({
             "subject": "product-image:p1:subject",
             "scene": "ca_char", "style": "ca_scene",
             "product_reference": "product-image:p1:product_reference"})},
        {"model": "Veo 3.1 - Lite", "aspect": "9:16"},
    )
    assert blockers == []
    # 4 slots, but the duplicate product image collapses to 3 unique refs ≤ cap.
    assert payload["image_media_ids"] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
    ]


@pytest.mark.asyncio
async def test_reference_count_contract_is_a_dry_run_blocker(monkeypatch):
    """4 UNIQUE refs on I2V (cap 3) blocks at payload build — the dry run can
    never again report GREEN for an item the door would reject."""
    ids = iter(["11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                "33333333-3333-3333-3333-333333333333",
                "44444444-4444-4444-4444-444444444444"])

    async def fake_resolve(asset_ref, pkg):
        return next(ids)
    monkeypatch.setattr(pq, "_resolve_flow_media_id", fake_resolve)

    import json as _j
    payload, blockers = await pq.build_execution_payload(
        {"workspace_generation_package_id": "wgp_i", "logical_mode": "I2V",
         "final_prompt_text": "p",
         "resolved_engine_slots_json": _j.dumps({
             "a": "r1", "b": "r2", "c": "r3", "d": "r4"})},
        {"model": "Veo 3.1 - Lite", "aspect": "9:16"},
    )
    assert any(b.startswith("REFERENCE_COUNT_CONTRACT:") for b in blockers)
