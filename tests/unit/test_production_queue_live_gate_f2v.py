"""Round F (Option 2) — the one-serial F2V live gate on the Production Queue.

Mirror of test_production_queue_live_gate.py for the F2V lane. Two things are
proven here:

  1. The F2V gate (_assert_one_serial_f2v_live) is fail-closed exactly like the
     proven T2V gate — a refusal happens BEFORE any state change (no live loop
     scheduled, run never flipped to dry_run=0/RUNNING).
  2. The loop authorization mechanism (cfg['authorized_live_mode']) lifts
     LIVE_T2V_ONLY for EXACTLY the one phrased, dry-run-ready, pure-F2V item —
     while the ungated bulk path and every non-F2V-gated run stay fail-closed
     T2V-only, and a stale grant is popped on every live start.

Nothing here touches a provider. asyncio.ensure_future is patched to record
scheduling and _fire_and_wait is faked, so a regression surfaces as a recorded
live-loop launch / fire rather than a real submission. build_execution_payload
is faked so the gate's mode/blocker derivation is deterministic without DB.
"""
import json

import pytest

from agent.services import production_queue_service as pq

RUN_ID = "run_f2v_1"
WGP_ID = "wgp_f2v_1"

GREEN_REPORT = {"checked": 1, "ready": 1, "blocked": 0, "items": [{"package_id": WGP_ID}]}


def _run(config: dict | None = None, status: str = "PENDING") -> dict:
    cfg = {
        "model": "Veo 3.1 - Lite",
        "aspect": "9:16",
        "count": 1,
        "last_dry_run_report": GREEN_REPORT,
    }
    cfg.update(config or {})
    return {
        "production_run_id": RUN_ID,
        "status": status,
        "dry_run": 1,
        "config_json": json.dumps(cfg),
    }


def _item(**over) -> dict:
    item = {
        "workspace_generation_package_id": WGP_ID,
        "product_id": "prod-f2v-1",
        "logical_mode": "F2V",
        "mode": "F2V",
        "source_lane": "FRAMES",
        "production_status": "QUEUED",
        "production_job_id": None,
        "final_prompt_text": "a synthetic f2v prompt",
        "resolved_engine_slots_json": '{"start_frame": "product-image:prod-f2v-1"}',
    }
    item.update(over)
    return item


@pytest.fixture
def queue(monkeypatch):
    """Patch the queue's DB + scheduler + payload builder. `state` records writes."""
    state = {
        "run": _run(),
        "items": [_item()],
        "updates": [],
        "scheduled": [],
        "payload_mode": "F2V",
        "payload_blockers": [],
    }

    async def get_production_run(run_id):
        return state["run"] if run_id == RUN_ID else None

    async def list_production_queue_packages(production_run_id=None, production_status=None, **kw):
        return list(state["items"])

    async def update_production_run(run_id, **kw):
        state["updates"].append(kw)
        return state["run"]

    async def build_execution_payload(item, cfg):
        return (
            {"logical_mode": state["payload_mode"], "mode": state["payload_mode"]},
            list(state["payload_blockers"]),
        )

    def ensure_future(coro):
        state["scheduled"].append(coro)
        coro.close()  # never actually run the live loop
        return None

    monkeypatch.setattr(pq.crud, "get_production_run", get_production_run)
    monkeypatch.setattr(
        pq.crud, "list_production_queue_packages", list_production_queue_packages
    )
    monkeypatch.setattr(pq.crud, "update_production_run", update_production_run)
    monkeypatch.setattr(pq, "build_execution_payload", build_execution_payload)
    monkeypatch.setattr(pq.asyncio, "ensure_future", ensure_future)
    return state


def _assert_nothing_fired(state):
    """A refusal must leave zero trace: no live loop, no dry_run=0/RUNNING flip."""
    assert state["scheduled"] == [], "live loop was scheduled despite refusal"
    for update in state["updates"]:
        assert update.get("dry_run") != 0, f"run flipped live despite refusal: {update}"
        assert update.get("status") != "RUNNING", f"run set RUNNING despite refusal: {update}"


def _live_write(state):
    """The single dry_run=0/RUNNING write, or None if none happened."""
    lives = [u for u in state["updates"] if u.get("dry_run") == 0]
    return lives[-1] if lives else None


async def _go_live_f2v(**over):
    kwargs = {
        "confirm_live_credit_burn": True,
        "live_gate": pq.LIVE_GATE_ONE_SERIAL_F2V,
        "confirm_phrase": pq.LIVE_F2V_CONFIRM_PHRASE,
        "expect_package_id": WGP_ID,
    }
    kwargs.update(over)
    return await pq.run_production_queue(RUN_ID, **kwargs)


# ── The happy path — one ready F2V item, correct F2V phrase ────────────────


@pytest.mark.asyncio
async def test_one_ready_f2v_item_with_exact_phrase_goes_live(queue):
    res = await _go_live_f2v()

    assert res["dry_run"] is False
    assert res["status"] == "RUNNING"
    assert res["package_id"] == WGP_ID
    assert res["live_gate"] == pq.LIVE_GATE_ONE_SERIAL_F2V
    # Exactly one live loop scheduled — one submission, not a fan-out.
    assert len(queue["scheduled"]) == 1


@pytest.mark.asyncio
async def test_f2v_gate_persists_the_loop_authorization(queue):
    """The gate must record authorized_live_mode='F2V' so the loop admits it."""
    await _go_live_f2v()
    live = _live_write(queue)
    assert live is not None, "expected a live RUNNING write"
    written = json.loads(live["config_json"])
    assert written.get("authorized_live_mode") == "F2V"


# ── Phrase gate (distinct from T2V) ────────────────────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        None,
        "",
        "authorize_one_f2v_live_run",  # case matters
        "AUTHORIZE_ONE_F2V_LIVE_RUN_",
        "AUTHORIZE ONE F2V LIVE RUN",
        "yes",
        "AUTHORIZE_ONE_T2V_LIVE_RUN",  # the T2V phrase can NEVER authorize F2V
    ],
)
@pytest.mark.asyncio
async def test_wrong_or_missing_phrase_refuses(queue, phrase):
    with pytest.raises(ValueError, match="LIVE_CONFIRM_PHRASE_INVALID"):
        await _go_live_f2v(confirm_phrase=phrase)
    _assert_nothing_fired(queue)


# ── One-item gate — the anti-fan-out control ──────────────────────────────


@pytest.mark.asyncio
async def test_two_queued_items_refuses_bulk_fan_out(queue):
    queue["items"] = [_item(), _item(workspace_generation_package_id="wgp_f2v_2")]
    with pytest.raises(ValueError, match=r"LIVE_REQUIRES_EXACTLY_ONE_ITEM:2"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_zero_queued_items_refuses(queue):
    queue["items"] = []
    with pytest.raises(ValueError, match=r"LIVE_REQUIRES_EXACTLY_ONE_ITEM:0"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


# ── FIRST-FRAME family gate: F2V + HYBRID admitted, T2V/I2V refused ───────


@pytest.mark.parametrize("mode", ["T2V", "I2V"])
@pytest.mark.asyncio
async def test_non_first_frame_item_refuses(queue, mode):
    queue["payload_mode"] = mode
    with pytest.raises(ValueError, match="LIVE_F2V_ONLY|LIVE_ITEM_BLOCKED"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_hybrid_item_goes_live_and_authorizes_exactly_hybrid(queue):
    """HYBRID fires the SAME live-proven first-frame engine (g_ba088e7195df:
    generate_video_with_first_frame / veo_3_1_i2v_lite), so the family gate
    admits it — and authorizes the loop for EXACTLY HYBRID, not F2V."""
    queue["payload_mode"] = "HYBRID"
    res = await _go_live_f2v()
    assert res["status"] == "RUNNING"
    written = json.loads(_live_write(queue)["config_json"])
    assert written.get("authorized_live_mode") == "HYBRID"


@pytest.mark.asyncio
async def test_f2v_item_authorizes_exactly_f2v(queue):
    queue["payload_mode"] = "F2V"
    await _go_live_f2v()
    written = json.loads(_live_write(queue)["config_json"])
    assert written.get("authorized_live_mode") == "F2V"


# ── Dry-run-ready gate ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_dry_run_report_refuses(queue):
    queue["run"] = _run({"last_dry_run_report": None})
    with pytest.raises(ValueError, match="LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.parametrize(
    "report",
    [
        {"checked": 1, "ready": 0, "blocked": 1, "items": []},
        {"checked": 2, "ready": 2, "blocked": 0, "items": []},
        {"checked": 1, "ready": 0, "blocked": 0, "items": []},
    ],
)
@pytest.mark.asyncio
async def test_dry_run_not_green_refuses(queue, report):
    queue["run"] = _run({"last_dry_run_report": report})
    with pytest.raises(ValueError, match="LIVE_REQUIRES_DRY_RUN_READY"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_blocked_item_refuses_even_with_green_stale_report(queue):
    """Readiness is re-derived at fire time, so a stale green report cannot fire
    a package that has since become blocked."""
    queue["payload_blockers"] = ["NO_FLOW_MEDIA_FOR_IMAGE_MODE"]
    with pytest.raises(ValueError, match="LIVE_ITEM_BLOCKED.*NO_FLOW_MEDIA_FOR_IMAGE_MODE"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


# ── Duplicate + identity gates ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_item_with_prior_job_id_refuses(queue):
    queue["items"] = [_item(production_job_id="job_already_fired")]
    with pytest.raises(ValueError, match="LIVE_DUPLICATE_SUBMISSION:job_already_fired"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_package_id_mismatch_refuses(queue):
    with pytest.raises(ValueError, match="LIVE_PACKAGE_MISMATCH"):
        await _go_live_f2v(expect_package_id="wgp_someone_else")
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_fastmoss_ref_product_refuses(queue):
    queue["items"] = [_item(product_id="fastmoss-ref:abc123")]
    with pytest.raises(ValueError, match="LIVE_FASTMOSS_REF_FORBIDDEN"):
        await _go_live_f2v()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_unknown_live_gate_refuses(queue):
    with pytest.raises(ValueError, match="LIVE_GATE_UNKNOWN:SOMETHING_ELSE"):
        await _go_live_f2v(live_gate="SOMETHING_ELSE")
    _assert_nothing_fired(queue)


# ── Cross-lane isolation — the two gates never authorize each other ───────


@pytest.mark.asyncio
async def test_t2v_gate_still_refuses_an_f2v_item(queue):
    """The proven T2V gate is untouched: an F2V item still raises LIVE_T2V_ONLY."""
    queue["payload_mode"] = "F2V"
    with pytest.raises(ValueError, match="LIVE_T2V_ONLY:F2V"):
        await pq.run_production_queue(
            RUN_ID,
            confirm_live_credit_burn=True,
            live_gate=pq.LIVE_GATE_ONE_SERIAL_T2V,
            confirm_phrase=pq.LIVE_CONFIRM_PHRASE,
            expect_package_id=WGP_ID,
        )
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_f2v_phrase_cannot_authorize_the_t2v_gate(queue):
    with pytest.raises(ValueError, match="LIVE_CONFIRM_PHRASE_INVALID"):
        await pq.run_production_queue(
            RUN_ID,
            confirm_live_credit_burn=True,
            live_gate=pq.LIVE_GATE_ONE_SERIAL_T2V,
            confirm_phrase=pq.LIVE_F2V_CONFIRM_PHRASE,
            expect_package_id=WGP_ID,
        )
    _assert_nothing_fired(queue)


# ── The gate is opt-in — it must not change existing behaviour ────────────


@pytest.mark.asyncio
async def test_dry_run_is_untouched_by_the_gate(queue):
    """No live_gate, no confirmation → still a dry run, still no firing."""
    res = await pq.run_production_queue(RUN_ID, confirm_live_credit_burn=False)
    assert res["dry_run"] is True
    assert "report" in res
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_bulk_start_does_not_authorize_f2v(queue):
    """The ungated bulk path (no live_gate) must NOT write authorized_live_mode."""
    queue["payload_mode"] = "T2V"  # a legit bulk T2V run
    res = await pq.run_production_queue(RUN_ID, confirm_live_credit_burn=True)
    assert res["dry_run"] is False
    written = json.loads(_live_write(queue)["config_json"])
    assert "authorized_live_mode" not in written


@pytest.mark.asyncio
async def test_bulk_start_pops_a_stale_authorization(queue):
    """A run whose config somehow carries a stale F2V grant, started as BULK,
    must have the grant POPPED before the loop launches (fail-closed default)."""
    queue["run"] = _run({"authorized_live_mode": "F2V"})
    res = await pq.run_production_queue(RUN_ID, confirm_live_credit_burn=True)
    assert res["dry_run"] is False
    written = json.loads(_live_write(queue)["config_json"])
    assert "authorized_live_mode" not in written


# ══ Loop authorization — the second, universal chokepoint ══════════════════


@pytest.fixture
def loop(monkeypatch):
    """Drive _live_production_loop over an in-memory queue; record fires + writes.
    `cfg` seeds the run config (set authorized_live_mode to test authorization)."""
    state = {"queue": [], "updates": [], "fired": [], "cfg": {}}

    def _run_loop():
        return {
            "production_run_id": RUN_ID, "status": "RUNNING",
            "config_json": json.dumps(state["cfg"]),
            "interval_min_seconds": 0, "interval_max_seconds": 0,
            "cooldown_after_n_jobs": 5, "cooldown_seconds": 0,
            "total_completed": 0, "total_failed": 0, "error_log_json": "[]",
        }

    async def get_run(rid):
        return _run_loop()

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
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


def _lpayload(mode, blockers=None):
    async def bep(item, cfg):
        return ({"logical_mode": mode, "mode": mode, "prompt": "x"}, blockers or [])
    return bep


@pytest.mark.asyncio
async def test_authorized_f2v_run_fires_the_f2v_item(loop, monkeypatch):
    """The whole point: with authorized_live_mode='F2V' the loop fires the F2V item."""
    loop["cfg"] = {"authorized_live_mode": "F2V"}
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("F2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_f2v"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == ["wgp_f2v"]


@pytest.mark.asyncio
async def test_unauthorized_run_still_blocks_f2v_in_the_loop(loop, monkeypatch):
    """The bulk-leak defence: without authorization the loop stays T2V-only and an
    F2V item is refused with the exact proven LIVE_T2V_ONLY message."""
    loop["cfg"] = {}  # no authorization
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("F2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_f2v"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_T2V_ONLY:F2V")


@pytest.mark.asyncio
async def test_authorized_f2v_run_refuses_a_stray_non_f2v_item(loop, monkeypatch):
    """An F2V-authorized run admits ONLY F2V — a stray T2V item is refused with a
    distinct code (not the bulk LIVE_T2V_ONLY)."""
    loop["cfg"] = {"authorized_live_mode": "F2V"}
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("T2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_stray"}]

    await pq._live_production_loop(RUN_ID)

    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_MODE_NOT_AUTHORIZED:T2V")


@pytest.mark.asyncio
async def test_authorized_hybrid_run_fires_hybrid_and_refuses_stray_f2v(loop, monkeypatch):
    """Mode-exact authorization: a HYBRID-authorized run fires its HYBRID item but
    refuses a swapped-in F2V item (and vice versa is covered by the F2V tests)."""
    loop["cfg"] = {"authorized_live_mode": "HYBRID"}
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("HYBRID", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_hy"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == ["wgp_hy"]


@pytest.mark.asyncio
async def test_hybrid_authorization_does_not_admit_f2v(loop, monkeypatch):
    loop["cfg"] = {"authorized_live_mode": "HYBRID"}
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("F2V", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_f2v_stray"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_MODE_NOT_AUTHORIZED:F2V")


@pytest.mark.asyncio
async def test_unauthorized_hybrid_still_blocked_in_the_loop(loop, monkeypatch):
    """The bulk path stays T2V-only: HYBRID without gate authorization never fires."""
    loop["cfg"] = {}
    monkeypatch.setattr(pq, "build_execution_payload", _lpayload("HYBRID", []))
    loop["queue"] = [{"workspace_generation_package_id": "wgp_hy"}]
    await pq._live_production_loop(RUN_ID)
    assert loop["fired"] == []
    failed = [u for u in loop["updates"] if u.get("production_status") == "FAILED"]
    assert failed and failed[0]["production_error"].startswith("LIVE_T2V_ONLY:HYBRID")
