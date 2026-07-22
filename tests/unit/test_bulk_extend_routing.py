"""Bulk EXTEND routes to the durable /video-jobs orchestrator, not the one-shot door.

An EXTEND package is MULTI-BLOCK. The single-shot door (make_video.start_generate)
renders exactly ONE 8s block, so sending a 16s/24s request through it truncates the
video and reports the truncation as success. These tests pin the routing decision:
EXTEND goes to plan -> authorize -> drive on the durable lane, everything else keeps
the exact single-shot path it has always used.

CREDIT-FREE by construction. Every provider boundary in this file is a fake: the
durable lane's plan/authorize/drive/status are monkeypatched, and the single-shot
start_generate fake RAISES if it is ever reached from an EXTEND item. Nothing here
can submit work, touch Flow, or spend credit.
"""
import pytest

from agent.api import flow as flow_api
from agent.services import make_video as mv
from agent.services import production_queue_service as pq
from agent.services import video_production_orchestrator as orch

RUN_ID = "run_extend"


def _run() -> dict:
    return {
        "production_run_id": RUN_ID, "status": "RUNNING",
        # A real run config: the durable lane enforces the same model law as the
        # single-shot lane, so a model-less run is refused before anything fires.
        "config_json": '{"model": "Veo 3.1 - Lite", "aspect": "9:16"}',
        # 1s, not 0s: the loop reads these as `x or 45` / `x or 120`, so a 0 is
        # falsy and would restore the full 45-120s production throttle between
        # items. The real throttle path still runs — just at its floor.
        "interval_min_seconds": 1, "interval_max_seconds": 1,
        "cooldown_after_n_jobs": 5, "cooldown_seconds": 1,
        "total_completed": 0, "total_failed": 0, "error_log_json": "[]",
    }


def _extend_pkg(wgp_id: str = "wgp_ext", **over) -> dict:
    """A 16s EXTEND package: two compiled 8s blocks, linked to an execution package."""
    pkg = {
        "workspace_generation_package_id": wgp_id,
        "logical_mode": "T2V", "mode": "T2V",
        "generation_mode": "EXTEND",
        "workspace_execution_package_id": "wep_1",
        "product_id": "prod_1",
        "product_name_snapshot": "Product One",
        "prompt_blocks_json": '[{"duration_seconds": 8}, {"duration_seconds": 8}]',
        "production_job_id": None,
    }
    pkg.update(over)
    return pkg


@pytest.fixture
def lane(monkeypatch):
    """Fake BOTH lanes and record which one an item took."""
    state = {
        "queue": [], "packages": {}, "updates": [],
        "planned": [], "authorized": [], "driven": [], "linked": [],
        "single_shot": [],
        "job_status": {"status": orch.S_COMPLETE, "final_media_id": "med_final"},
        "plan_result": {"job_id": "vj_abc123", "plan_fingerprint": "fp_abc"},
        "plan_error": None,
    }

    async def get_run(rid):
        return _run()

    async def list_pkgs(production_run_id=None, production_status=None, **kw):
        # Status-aware like the real query: an item leaves the QUEUED set the
        # moment the loop marks it RUNNING, so the loop's own "anything left?"
        # re-check does not consume the next item.
        want = str(production_status or "QUEUED").upper()
        return [
            p for p in state["queue"]
            if str(state["packages"].get(p["workspace_generation_package_id"], {})
                   .get("production_status") or "QUEUED").upper() == want
        ][:1]

    async def get_pkg(wgp_id):
        return dict(state["packages"].get(wgp_id) or {})

    async def update_pkg(wgp_id, **kw):
        state["updates"].append({"wgp_id": wgp_id, **kw})
        state["packages"].setdefault(wgp_id, {}).update(kw)
        return {}

    async def update_run(rid, **kw):
        return {}

    async def link_artifacts(job_id, wgp_id):
        state["linked"].append((job_id, wgp_id))
        return 1

    # ── durable /video-jobs lane ──
    async def plan(body, *, trust_client_authority):
        state["planned"].append(
            {"body": body, "trust_client_authority": trust_client_authority})
        if state["plan_error"] is not None:
            raise state["plan_error"]
        return state["plan_result"]

    async def authorize(job_id, *, confirmed_plan_fingerprint, **kw):
        state["authorized"].append((job_id, confirmed_plan_fingerprint))
        return {"authorization_token": "auth_tok"}

    async def drive(job_id, token):
        state["driven"].append((job_id, token))

    async def job_status(job_id):
        return dict(state["job_status"])

    # ── single-shot door: reachable ONLY by a non-EXTEND item ──
    async def start_generate(mode, prompt, **kw):
        state["single_shot"].append({"mode": mode, "prompt": prompt, **kw})
        return {"status": "ACCEPTED", "job_id": "g_single"}

    def get_job(job_id):
        return {"status": "DONE", "artifacts": [{"media_id": "med_single"}]}

    monkeypatch.setattr(pq.crud, "get_production_run", get_run)
    monkeypatch.setattr(pq.crud, "list_production_queue_packages", list_pkgs)
    monkeypatch.setattr(pq.crud, "get_workspace_generation_package", get_pkg)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_pkg)
    monkeypatch.setattr(pq.crud, "update_production_run", update_run)
    monkeypatch.setattr(pq.crud, "link_artifacts_to_generation_package", link_artifacts)
    monkeypatch.setattr(flow_api, "_plan_video_job", plan)
    monkeypatch.setattr(flow_api, "_drive_video_job", drive)
    monkeypatch.setattr(orch, "authorize_job", authorize)
    monkeypatch.setattr(orch, "get_job_status", job_status)
    monkeypatch.setattr(mv, "start_generate", start_generate)
    monkeypatch.setattr(mv, "get_job", get_job)
    # Identity snapshots read make_video's in-memory job map; they are evidence,
    # not routing, and are already fail-soft in production.
    monkeypatch.setattr(pq, "_persist_generation_identity", _noop_2)
    monkeypatch.setattr(pq, "_persist_binding_outcome", _noop_2)
    return state


async def _noop_2(*args, **kw):
    return {}


def _enqueue(state, pkg):
    state["packages"][pkg["workspace_generation_package_id"]] = dict(pkg)
    state["queue"].append(pkg)


# ── routing ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extend_item_routes_to_the_durable_planner(lane):
    """The whole point: EXTEND plans a durable job and NEVER hits start_generate."""
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    assert lane["single_shot"] == []  # the one-shot door was never opened
    assert len(lane["planned"]) == 1
    assert lane["authorized"] == [("vj_abc123", "fp_abc")]
    assert lane["driven"] == [("vj_abc123", "auth_tok")]


@pytest.mark.asyncio
async def test_durable_plan_carries_the_package_authority(lane):
    """The plan is built from the package, and authority is resolved SERVER-side."""
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    call = lane["planned"][0]
    assert call["trust_client_authority"] is False  # SSOT: never trust the caller
    body = call["body"]
    assert body.execution_package_id == "wep_1"
    assert body.product_id == "prod_1"
    # 2 compiled blocks x 8s — read from the package's own plan, never guessed.
    assert body.requested_total_duration_seconds == 16
    # Stable replay identity: re-planning the same package reuses its vj_* job.
    assert body.client_request_nonce == "wgp_ext"


@pytest.mark.asyncio
async def test_non_extend_item_still_uses_the_single_shot_door(lane, monkeypatch):
    """Regression guard: the untouched path must stay untouched."""
    async def bep(item, cfg):
        return ({"logical_mode": "T2V", "mode": "T2V", "prompt": "one block"}, [])
    monkeypatch.setattr(pq, "build_execution_payload", bep)
    _enqueue(lane, {
        "workspace_generation_package_id": "wgp_single",
        "logical_mode": "T2V", "mode": "T2V", "generation_mode": "SINGLE",
    })

    await pq._live_production_loop(RUN_ID)

    assert len(lane["single_shot"]) == 1
    assert lane["single_shot"][0]["prompt"] == "one block"
    assert lane["planned"] == []  # the durable lane was never involved


# ── durable job id lands in the existing production_job_id slot ──────────────

@pytest.mark.asyncio
async def test_durable_job_id_is_written_to_production_job_id(lane):
    """No new column: the vj_* id occupies the existing submission-identity slot."""
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    assert lane["packages"]["wgp_ext"]["production_job_id"] == "vj_abc123"
    # Written BEFORE authorization, so a crash mid-drive can never re-fire it.
    job_writes = [i for i, u in enumerate(lane["updates"]) if u.get("production_job_id")]
    assert job_writes, "the durable job id was never persisted"
    assert lane["authorized"], "nothing was authorized"


@pytest.mark.asyncio
async def test_completed_extend_marks_generated_and_links_artifacts(lane):
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    assert lane["packages"]["wgp_ext"]["production_status"] == "GENERATED"
    assert lane["linked"] == [("vj_abc123", "wgp_ext")]


# ── duplicate-submission guard survives the bypass of _fire_and_wait ─────────

@pytest.mark.asyncio
async def test_already_submitted_extend_package_is_refused(lane):
    """Paying twice for one package is the failure this guard exists to stop."""
    _enqueue(lane, _extend_pkg(production_job_id="vj_earlier"))

    await pq._live_production_loop(RUN_ID)

    assert lane["planned"] == []  # refused BEFORE planning or authorizing
    assert lane["authorized"] == []
    assert lane["packages"]["wgp_ext"]["production_status"] == "FAILED"
    assert lane["packages"]["wgp_ext"]["production_error"] == (
        "DUPLICATE_SUBMISSION_BLOCKED:vj_earlier")


# ── failure isolation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_extend_item_marks_only_itself_failed(lane):
    """A failed plan fails THAT package with the real error and never raises."""
    lane["plan_error"] = RuntimeError("INCOMPLETE_PRODUCTION_PLAN: missing asset")
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)  # must not raise

    pkg = lane["packages"]["wgp_ext"]
    assert pkg["production_status"] == "FAILED"
    assert "INCOMPLETE_PRODUCTION_PLAN: missing asset" in pkg["production_error"]


@pytest.mark.asyncio
async def test_a_failed_extend_item_does_not_stop_the_next_item(lane):
    """The run continues: one stranded video must never abort the fan-out."""
    lane["plan_error"] = RuntimeError("boom")
    _enqueue(lane, _extend_pkg("wgp_a"))
    _enqueue(lane, _extend_pkg("wgp_b"))

    await pq._live_production_loop(RUN_ID)

    assert lane["packages"]["wgp_a"]["production_status"] == "FAILED"
    assert lane["packages"]["wgp_b"]["production_status"] == "FAILED"
    assert len(lane["planned"]) == 2  # the second item was still attempted


@pytest.mark.asyncio
async def test_terminal_orchestrator_failure_reports_the_real_reason(lane):
    lane["job_status"] = {"status": orch.F_EXTEND, "error_code": "SEAM_REJECTED"}
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    pkg = lane["packages"]["wgp_ext"]
    assert pkg["production_status"] == "FAILED"
    assert pkg["production_error"] == f"{orch.F_EXTEND}:SEAM_REJECTED"


@pytest.mark.asyncio
async def test_stuck_job_fails_the_item_instead_of_hanging(lane):
    """AUTHORIZATION_EXPIRED / INITIAL_RECOVERY_REQUIRED are not terminal, but they
    cannot advance without a human — fail the item with that exact reason."""
    lane["job_status"] = {"status": orch.S_INITIAL_RECOVERY}
    _enqueue(lane, _extend_pkg())

    await pq._live_production_loop(RUN_ID)

    assert lane["packages"]["wgp_ext"]["production_error"] == orch.S_INITIAL_RECOVERY


# ── fail-closed preconditions ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extend_without_an_execution_package_fails_closed(lane):
    """The orchestrator resolves all authority from the execution package."""
    _enqueue(lane, _extend_pkg(workspace_execution_package_id=None))

    await pq._live_production_loop(RUN_ID)

    assert lane["planned"] == []
    assert "EXTEND_EXECUTION_PACKAGE_MISSING" in (
        lane["packages"]["wgp_ext"]["production_error"])


@pytest.mark.asyncio
async def test_extend_with_a_single_block_plan_fails_closed(lane):
    """One block is not an Extend — refuse rather than plan a different video."""
    _enqueue(lane, _extend_pkg(prompt_blocks_json='[{"duration_seconds": 8}]'))

    await pq._live_production_loop(RUN_ID)

    assert lane["planned"] == []
    assert "EXTEND_BLOCK_PLAN_INVALID" in lane["packages"]["wgp_ext"]["production_error"]


@pytest.mark.asyncio
async def test_extend_mode_gate_still_applies(lane):
    """USER SETTINGS ARE LAW: EXTEND is not a way around the live-mode gate. The
    loop authorizes T2V by default, so an unauthorized-mode extend item is refused
    exactly like any other item of that mode."""
    _enqueue(lane, _extend_pkg(logical_mode="I2V", mode="I2V"))

    await pq._live_production_loop(RUN_ID)

    assert lane["planned"] == []
    assert lane["single_shot"] == []
    assert "LIVE_T2V_ONLY:I2V" in lane["packages"]["wgp_ext"]["production_error"]
