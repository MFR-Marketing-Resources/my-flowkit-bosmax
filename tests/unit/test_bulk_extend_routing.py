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
from agent.services import copy_rotation_service as rot
from agent.services import make_video as mv
from agent.services import production_queue_service as pq
from agent.services import video_production_orchestrator as orch
from agent.services import workspace_execution_package_service as wxp
from agent.services import workspace_generation_package_service as svc

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


# ── bulk PREPARE gives every EXTEND item its execution package ───────────────
# The precondition above (EXTEND_EXECUTION_PACKAGE_MISSING) was failing EVERY
# real bulk item: prepare created generation packages with
# workspace_execution_package_id = NULL, and the durable planner resolves ALL
# authority from an execution package. These tests pin the fix at the prepare
# door. CREDIT-FREE by construction: the compiler, both package creators, the
# ledger, approval and enqueue are all fakes — nothing here can compile, fire,
# or touch the DB.

def _copy(cs_id: str) -> dict:
    return {
        "copy_set_id": cs_id, "product_id": "P", "status": "COPY_APPROVED",
        "archived": 0, "usage_count": 0, "hook": f"hook {cs_id}",
        "angle": f"angle {cs_id}", "created_at": f"2026-07-20T00:00:0{cs_id[-1]}Z",
        "last_used_at": None,
    }


TWO_BLOCKS = [{"block_index": 1, "duration_seconds": 8},
              {"block_index": 2, "duration_seconds": 8}]


@pytest.fixture
def prepare(monkeypatch):
    """Fake every seam bulk prepare touches and record what it built."""
    state = {
        "created": [], "wep_calls": [], "approved": [], "sent": [],
        # Per-item execution package the faked door returns; a test overrides
        # these to simulate a refusal, a BLOCKED package, or a drifted plan.
        "wep_error": None,
        "wep_execution_allowed": True,
        "wep_blockers": [],
        "wep_prompt_blocks": list(TWO_BLOCKS),
        "wep_bound_copy_set_id": None,   # None = bind what was asked for
        "pkg_prompt_blocks": list(TWO_BLOCKS),
    }
    rows = [_copy("cs1"), _copy("cs2")]
    dialogues = {"cs1": "aaa", "cs2": "bbb"}

    async def list_pool(product_id):
        return list(rows)

    async def rotate(product_id, count):
        return {"items": list(rows), "warnings": []}

    async def compile_preview(**kw):
        d = dialogues.get(kw.get("copy_set_id"), f"fallback {kw.get('copy_set_id')}")
        return {
            "final_compiled_prompt_text": f"SECTION 6\n{d}\nSECTION 7",
            "prompt_blocks": [{"exact_dialogue_slice": d, "audio_seam_contract": {}}],
        }

    async def create_wep(**kw):
        state["wep_calls"].append(dict(kw))
        if state["wep_error"] is not None:
            raise state["wep_error"]
        return {
            "workspace_execution_package_id": f"wep_{len(state['wep_calls'])}",
            "execution_allowed": state["wep_execution_allowed"],
            "blockers": list(state["wep_blockers"]),
            "copy_binding": {
                "copy_set_id": state["wep_bound_copy_set_id"] or kw.get("copy_set_id")},
            "prompt_blocks": list(state["wep_prompt_blocks"]),
        }

    async def creator(**kw):
        idx = len(state["created"])
        state["created"].append(dict(kw))
        return {
            "workspace_generation_package_id": f"wgp_{idx}",
            "workspace_execution_package_id": kw.get("workspace_execution_package_id"),
            "prompt_blocks_json": list(state["pkg_prompt_blocks"]),
        }

    async def list_wgp(**kw):
        return []

    async def get_wgp(wgp_id):
        return {"workspace_generation_package_id": wgp_id, "generation_identity_json": "{}"}

    async def update_wgp(wgp_id, **kw):
        return {}

    async def update_run(run_id, **kw):
        return {}

    async def approve(ids):
        state["approved"].append(list(ids))
        return {"approved": len(ids),
                "results": [{"package_id": i, "ok": True} for i in ids]}

    async def send(package_ids, **kw):
        state["sent"].append({"ids": list(package_ids), **kw})
        return {"production_run_id": "prun_bulk_ext", "config_json": "{}"}

    async def already_used(fp):
        return False

    async def record_combo(**kw):
        return dict(kw)

    async def record_usage(copy_set_id, logical_mode):
        return {}

    monkeypatch.setattr(rot, "list_eligible_copy_sets", list_pool)
    monkeypatch.setattr(rot, "select_rotation_copy_sets", rotate)
    monkeypatch.setattr(rot, "combination_already_used", already_used)
    monkeypatch.setattr(rot, "record_combination", record_combo)
    monkeypatch.setattr(rot, "record_rotation_usage", record_usage)
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", compile_preview)
    monkeypatch.setattr(wxp, "create_workspace_execution_package", create_wep)
    monkeypatch.setattr(svc, "create_t2v_generation_package", creator)
    monkeypatch.setattr(svc.crud, "list_workspace_generation_packages", list_wgp)
    monkeypatch.setattr(svc.crud, "get_workspace_generation_package", get_wgp)
    monkeypatch.setattr(svc.crud, "update_workspace_generation_package", update_wgp)
    monkeypatch.setattr(svc.crud, "update_production_run", update_run)
    monkeypatch.setattr(pq, "approve_packages", approve)
    monkeypatch.setattr(pq, "send_to_production", send)
    return state


async def _prepare_extend(**over):
    kwargs = dict(
        product_id="P", logical_mode="T2V", source_mode="T2V",
        generation_mode="EXTEND", requested_total_duration_seconds=16,
        quantity=2, model="Veo 3.1 - Lite", aspect="9:16",
    )
    kwargs.update(over)
    return await svc.prepare_bulk_fanout_packages(**kwargs)


@pytest.mark.asyncio
async def test_extend_prepare_binds_an_execution_package_to_every_package(prepare):
    """THE FIX: every EXTEND item is created WITH its execution package id."""
    out = await _prepare_extend()

    assert out["prepared_package_count"] == 2
    assert len(prepare["wep_calls"]) == 2
    bound = [c["workspace_execution_package_id"] for c in prepare["created"]]
    assert bound == ["wep_1", "wep_2"]          # persisted at INSERT, never NULL
    assert len(set(bound)) == 2                 # one package per item, never shared


@pytest.mark.asyncio
async def test_the_execution_package_carries_the_items_own_approved_copy(prepare):
    """Same authority, not a re-compile: the WEP binds the dialogue this item was
    planned on, and inherits the run's model/aspect/duration law."""
    await _prepare_extend()

    planned = {c["copy_set_id"] for c in prepare["created"]}
    assert {c["copy_set_id"] for c in prepare["wep_calls"]} == planned
    for call in prepare["wep_calls"]:
        assert call["generation_mode"] == "EXTEND"
        assert call["requested_total_duration_seconds"] == 16
        assert call["model"] == "Veo 3.1 - Lite"
        assert call["aspect_ratio"] == "9:16"
        assert call["manual_override"] is False


@pytest.mark.asyncio
async def test_a_prepared_extend_package_now_passes_the_queue_precondition(prepare):
    """Closes the loop: the row prepare produces no longer trips the blocker that
    failed every dry run."""
    await _prepare_extend()

    resolved, blockers = pq.extend_execution_preconditions(
        {"generation_mode": "EXTEND", "logical_mode": "T2V",
         "workspace_execution_package_id": prepare["created"][0][
             "workspace_execution_package_id"],
         "prompt_blocks_json": '[{"duration_seconds": 8}, {"duration_seconds": 8}]'},
        {"model": "Veo 3.1 - Lite", "aspect": "9:16"},
    )
    assert blockers == []
    assert resolved["execution_package_id"] == "wep_1"


@pytest.mark.asyncio
async def test_non_extend_prepare_creates_no_execution_package(prepare):
    """Regression guard: the untouched path must stay untouched."""
    out = await _prepare_extend(generation_mode="SINGLE",
                                requested_total_duration_seconds=None)

    assert out["prepared_package_count"] == 2
    assert prepare["wep_calls"] == []
    for call in prepare["created"]:
        assert "workspace_execution_package_id" not in call


# ── fail closed: no execution package means no batch, never a fallback ───────

@pytest.mark.asyncio
async def test_a_failed_execution_package_blocks_the_batch(prepare):
    """Never fire without one: the exact reason is named and nothing is enqueued."""
    prepare["wep_error"] = RuntimeError("PRODUCT_NOT_FOUND")

    with pytest.raises(ValueError) as err:
        await _prepare_extend()

    msg = str(err.value)
    assert "BULK_EXTEND_EXECUTION_PACKAGE_FAILED:item#0" in msg
    assert "PRODUCT_NOT_FOUND" in msg          # the REAL cause, not a generic code
    assert prepare["created"] == []            # refused BEFORE the ledger burn
    assert prepare["approved"] == [] and prepare["sent"] == []


@pytest.mark.asyncio
async def test_a_blocked_execution_package_blocks_the_batch(prepare):
    """A BLOCKED package can never mint a production plan — refuse at prepare."""
    prepare["wep_execution_allowed"] = False
    prepare["wep_blockers"] = ["START_FRAME_REQUIRED"]

    with pytest.raises(ValueError, match="BULK_EXTEND_EXECUTION_PACKAGE_BLOCKED"):
        await _prepare_extend()

    assert prepare["created"] == []
    assert prepare["approved"] == [] and prepare["sent"] == []


@pytest.mark.asyncio
async def test_a_drifted_copy_binding_blocks_the_batch(prepare):
    """Different words than the operator reviewed is a refusal, not a warning."""
    prepare["wep_bound_copy_set_id"] = "cs_someone_else"

    with pytest.raises(ValueError, match="BULK_EXTEND_WEP_COPY_BINDING_DRIFT"):
        await _prepare_extend()

    assert prepare["approved"] == [] and prepare["sent"] == []


@pytest.mark.asyncio
async def test_a_drifted_block_plan_blocks_the_batch(prepare):
    """The planner's segment plan and the reviewed package must be the same video."""
    prepare["wep_prompt_blocks"] = [{"block_index": 1, "duration_seconds": 8}]

    with pytest.raises(ValueError, match="BULK_EXTEND_WEP_BLOCK_PLAN_DRIFT"):
        await _prepare_extend()

    assert prepare["approved"] == [] and prepare["sent"] == []


@pytest.mark.asyncio
async def test_a_single_block_extend_never_reaches_a_run(prepare):
    """One block is not an Extend — refused at prepare, before any credit gate."""
    prepare["wep_prompt_blocks"] = [{"block_index": 1, "duration_seconds": 8}]
    prepare["pkg_prompt_blocks"] = [{"block_index": 1, "duration_seconds": 8}]

    with pytest.raises(ValueError, match="BULK_EXTEND_WEP_BLOCK_PLAN_DRIFT"):
        await _prepare_extend()

    assert prepare["approved"] == [] and prepare["sent"] == []


# ── lane remap: the WEP door accepts ENGINE modes, not surface labels ─────────
# Live bug: bulk EXTEND HYBRID (16s) hit
#   BULK_EXTEND_EXECUTION_PACKAGE_FAILED:item#0:ValueError:UNSUPPORTED_MODE
# because the builder passed the RAW logical mode "HYBRID" to
# create_workspace_execution_package -> get_approved_product_package, and
# normalize_mode("HYBRID") is NOT in SUPPORTED_MODES {T2V,F2V,I2V,IMG}. The builder
# must remap the logical lane to its compiler transport identity (HYBRID -> F2V,
# lineage kept in source_mode) via the SAME helper the proven non-extend path uses,
# BEFORE the door is called. Asset splits stay keyed on the LOGICAL mode.

_ACCEPTED_WEP_MODES = {"T2V", "F2V", "I2V", "IMG"}


@pytest.fixture
def wep_door(monkeypatch):
    """A fake execution-package door that enforces the REAL mode gate — it raises
    UNSUPPORTED_MODE for a surface label exactly like get_approved_product_package —
    and records the kwargs it was handed."""
    calls: list = []

    async def door(**kw):
        calls.append(dict(kw))
        if str(kw.get("mode")) not in _ACCEPTED_WEP_MODES:
            raise ValueError("UNSUPPORTED_MODE")
        return {
            "workspace_execution_package_id": "wep_x",
            "execution_allowed": True, "blockers": [],
            "copy_binding": {"copy_set_id": kw.get("copy_set_id")},
            "prompt_blocks": list(TWO_BLOCKS),
        }
    monkeypatch.setattr(wxp, "create_workspace_execution_package", door)
    return calls


async def _build_wep(logical_mode, **over):
    kwargs = dict(
        item_index=0, product_id="P", logical_mode=logical_mode, source_mode=None,
        generation_mode="EXTEND", duration_seconds=8,
        requested_total_duration_seconds=16, target_language="BM_MS",
        model="Veo 3.1 - Lite", aspect="9:16", copy_set_id="cs1",
        start_frame_asset_id="ca_frame", product_reference_asset_id="ca_anchor",
        character_reference_asset_id="ca_char",
        scene_context_reference_asset_id="ca_scene",
    )
    kwargs.update(over)
    return await svc._create_bulk_extend_execution_package(**kwargs)


@pytest.mark.asyncio
async def test_hybrid_extend_builds_a_wep_remapped_to_f2v(wep_door):
    """THE FIX: HYBRID reaches the door as F2V + HYBRID lineage — a WEP is BUILT,
    never refused with UNSUPPORTED_MODE."""
    wep = await _build_wep("HYBRID", source_mode="HYBRID")

    assert wep["workspace_execution_package_id"] == "wep_x"   # built, not refused
    call = wep_door[0]
    assert call["mode"] == "F2V"            # remapped for the compiler door
    assert call["source_mode"] == "HYBRID"  # logical lineage preserved
    # asset split stays keyed on the LOGICAL mode: HYBRID -> product reference,
    # never a start frame.
    assert call["product_reference_asset_id"] == "ca_anchor"
    assert "start_frame_asset_id" not in call


@pytest.mark.asyncio
@pytest.mark.parametrize("logical, exp_mode, exp_src, exp_dur", [
    ("T2V", "T2V", "T2V", 8),
    ("F2V", "F2V", "FRAMES", 8),
    ("HYBRID", "F2V", "HYBRID", 8),
    ("I2V", "I2V", None, 8),   # I2V compiles at a fixed 8s block
])
async def test_every_lane_reaches_a_mode_the_wep_door_accepts(
    wep_door, logical, exp_mode, exp_src, exp_dur
):
    """All four lanes land on a mode the door accepts after the remap — no lane
    still fails UNSUPPORTED_MODE, and each keeps its reviewed lineage + duration."""
    await _build_wep(logical)

    call = wep_door[0]
    assert call["mode"] == exp_mode
    assert call["mode"] in _ACCEPTED_WEP_MODES     # never a surface label
    assert call["source_mode"] == exp_src          # lineage unchanged by the remap
    assert call["duration_seconds"] == exp_dur     # I2V fixed-8s handling intact
