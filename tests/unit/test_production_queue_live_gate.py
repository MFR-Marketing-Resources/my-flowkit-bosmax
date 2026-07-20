"""Round F — the one-serial T2V live gate on the Production Queue.

The live branch of `run_production_queue` fans out over EVERY queued item, so the
only thing standing between a click and an unbounded credit burn is this gate.
These tests exist to prove the gate is fail-closed: each one asserts that a
refusal happens BEFORE any state change, i.e. `_live_production_loop` is never
scheduled and the run is never flipped to `dry_run=0/RUNNING`.

Nothing here touches a provider. `asyncio.ensure_future` is patched to record
scheduling, so a regression surfaces as a recorded live-loop launch rather than a
real submission.
"""
import pytest

from agent.services import production_queue_service as pq

RUN_ID = "run_f_1"
WGP_ID = "wgp_f_1"

GREEN_REPORT = {"checked": 1, "ready": 1, "blocked": 0, "items": [{"package_id": WGP_ID}]}


def _run(config: dict | None = None, status: str = "PENDING") -> dict:
    import json

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
        "product_id": "prod-safe-1",
        "logical_mode": "T2V",
        "mode": "T2V",
        "source_lane": "T2V",
        "production_status": "QUEUED",
        "production_job_id": None,
        "final_prompt_text": "a synthetic t2v prompt",
        "resolved_engine_slots_json": "{}",
        "dom_handoff_payload_json": '{"settings": {"duration_seconds": 8}}',
    }
    item.update(over)
    return item


@pytest.fixture
def queue(monkeypatch):
    """Patch the queue's DB + scheduler. `state` records everything written."""
    state = {"run": _run(), "items": [_item()], "updates": [], "scheduled": []}

    async def get_production_run(run_id):
        return state["run"] if run_id == RUN_ID else None

    async def list_production_queue_packages(production_run_id=None, production_status=None, **kw):
        return list(state["items"])

    async def update_production_run(run_id, **kw):
        state["updates"].append(kw)
        return state["run"]

    def ensure_future(coro):
        state["scheduled"].append(coro)
        coro.close()  # never actually run the live loop
        return None

    monkeypatch.setattr(pq.crud, "get_production_run", get_production_run)
    monkeypatch.setattr(
        pq.crud, "list_production_queue_packages", list_production_queue_packages
    )
    monkeypatch.setattr(pq.crud, "update_production_run", update_production_run)
    monkeypatch.setattr(pq.asyncio, "ensure_future", ensure_future)
    return state


def _assert_nothing_fired(state):
    """A refusal must leave zero trace: no live loop, no dry_run=0/RUNNING flip."""
    assert state["scheduled"] == [], "live loop was scheduled despite refusal"
    for update in state["updates"]:
        assert update.get("dry_run") != 0, f"run flipped live despite refusal: {update}"
        assert update.get("status") != "RUNNING", f"run set RUNNING despite refusal: {update}"


async def _go_live(**over):
    kwargs = {
        "confirm_live_credit_burn": True,
        "live_gate": pq.LIVE_GATE_ONE_SERIAL_T2V,
        "confirm_phrase": pq.LIVE_CONFIRM_PHRASE,
        "expect_package_id": WGP_ID,
    }
    kwargs.update(over)
    return await pq.run_production_queue(RUN_ID, **kwargs)


# ── The happy path — one ready T2V item, correct phrase ────────────────────


@pytest.mark.asyncio
async def test_one_ready_t2v_item_with_exact_phrase_goes_live(queue):
    res = await _go_live()

    assert res["dry_run"] is False
    assert res["status"] == "RUNNING"
    assert res["package_id"] == WGP_ID
    assert res["live_gate"] == pq.LIVE_GATE_ONE_SERIAL_T2V
    # Exactly one live loop scheduled — one submission, not a fan-out.
    assert len(queue["scheduled"]) == 1


# ── Phrase gate ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        None,
        "",
        "authorize_one_t2v_live_run",  # case matters
        "AUTHORIZE_ONE_T2V_LIVE_RUN_",
        "AUTHORIZE ONE T2V LIVE RUN",
        "yes",
    ],
)
@pytest.mark.asyncio
async def test_wrong_or_missing_phrase_refuses(queue, phrase):
    with pytest.raises(ValueError, match="LIVE_CONFIRM_PHRASE_INVALID"):
        await _go_live(confirm_phrase=phrase)
    _assert_nothing_fired(queue)


# ── One-item gate — the anti-fan-out control ──────────────────────────────


@pytest.mark.asyncio
async def test_two_queued_items_refuses_bulk_fan_out(queue):
    queue["items"] = [_item(), _item(workspace_generation_package_id="wgp_f_2")]
    with pytest.raises(ValueError, match=r"LIVE_REQUIRES_EXACTLY_ONE_ITEM:2"):
        await _go_live()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_zero_queued_items_refuses(queue):
    queue["items"] = []
    with pytest.raises(ValueError, match=r"LIVE_REQUIRES_EXACTLY_ONE_ITEM:0"):
        await _go_live()
    _assert_nothing_fired(queue)


# ── T2V-only gate ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["F2V", "I2V", "HYBRID"])
@pytest.mark.asyncio
async def test_non_t2v_item_refuses(queue, mode):
    queue["items"] = [_item(logical_mode=mode, mode=mode, source_lane=mode)]
    with pytest.raises(ValueError, match="LIVE_T2V_ONLY|LIVE_ITEM_BLOCKED"):
        await _go_live()
    _assert_nothing_fired(queue)


# ── Dry-run-ready gate ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_dry_run_report_refuses(queue):
    queue["run"] = _run({"last_dry_run_report": None})
    with pytest.raises(ValueError, match="LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN"):
        await _go_live()
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
        await _go_live()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_blocked_item_refuses_even_with_green_stale_report(queue):
    """Readiness is re-derived at fire time, so a stale green report cannot fire
    a package that has since become blocked."""
    queue["items"] = [_item(final_prompt_text="")]  # EMPTY_FINAL_PROMPT
    with pytest.raises(ValueError, match="LIVE_ITEM_BLOCKED.*EMPTY_FINAL_PROMPT"):
        await _go_live()
    _assert_nothing_fired(queue)


# ── Duplicate + identity gates ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_item_with_prior_job_id_refuses(queue):
    queue["items"] = [_item(production_job_id="job_already_fired")]
    with pytest.raises(ValueError, match="LIVE_DUPLICATE_SUBMISSION:job_already_fired"):
        await _go_live()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_package_id_mismatch_refuses(queue):
    with pytest.raises(ValueError, match="LIVE_PACKAGE_MISMATCH"):
        await _go_live(expect_package_id="wgp_someone_else")
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_fastmoss_ref_product_refuses(queue):
    queue["items"] = [_item(product_id="fastmoss-ref:abc123")]
    with pytest.raises(ValueError, match="LIVE_FASTMOSS_REF_FORBIDDEN"):
        await _go_live()
    _assert_nothing_fired(queue)


@pytest.mark.asyncio
async def test_unknown_live_gate_refuses(queue):
    with pytest.raises(ValueError, match="LIVE_GATE_UNKNOWN:SOMETHING_ELSE"):
        await _go_live(live_gate="SOMETHING_ELSE")
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
async def test_preexisting_single_item_live_path_without_live_gate_is_unchanged(queue):
    """The pre-existing SINGLE-item live path (ProductionQueuePage) is a protected
    system: omitting live_gate must NOT start requiring a phrase for one item."""
    queue["items"] = [_item()]
    res = await pq.run_production_queue(RUN_ID, confirm_live_credit_burn=True)
    assert res["dry_run"] is False
    assert res["status"] == "RUNNING"


@pytest.mark.asyncio
async def test_ungated_multi_item_live_is_now_refused(queue):
    """Owner decision 2026-07-20 — supersedes the earlier carve-out that let the
    pre-existing path start a MULTI-item live run with no gate at all.

    `allowed_live_modes` in the live loop constrains MODE, never COUNT, so an
    ungated N-item start used to fan out over every queued item with no phrase,
    no readiness and no preview correlation. Bulk now requires an explicit gate;
    single-item behaviour above is untouched."""
    queue["items"] = [_item(), _item(workspace_generation_package_id="wgp_f_2")]
    with pytest.raises(ValueError, match="BULK_LIVE_REQUIRES_BULK_GATE:2_items"):
        await pq.run_production_queue(RUN_ID, confirm_live_credit_burn=True)
    _assert_nothing_fired(queue)
