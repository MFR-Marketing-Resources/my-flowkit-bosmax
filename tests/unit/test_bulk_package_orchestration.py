"""Stage 2C — N-package orchestration: create -> approve -> enqueue, CREDIT-FREE.

Turns the Stage 2A itemized plan into N REAL packages, one per planned item,
each bound to its own approved Copy Set via the Stage 2B copy_set_id seam. That
is what makes "no duplicate dialogue" enforceable at the package level rather
than only in a preview.

Everything is fail-closed and proven BEFORE any write:
  * copy-pool readiness READY + preview UNIQUE (re-derived server-side)
  * a STALE client plan fingerprint is refused
  * every item must carry copy_variant_id + dialogue_fingerprint
  * duplicate dialogue is refused
  * package creation is ALL-OR-NOTHING — a failed item approves/enqueues nothing
  * idempotent per plan — re-running returns the existing batch

The DB, creators, approval and enqueue seams are faked, so no provider, Flow,
text-LLM or credit call is possible here.
"""
import asyncio
import json

import pytest

from agent.services import copy_rotation_service
from agent.services import production_queue_service as pq
from agent.services import workspace_execution_package_service as wxp
from agent.services import workspace_generation_package_service as svc


def _approved(cs_id):
    return {
        "copy_set_id": cs_id, "product_id": "P", "status": "COPY_APPROVED",
        "archived": 0, "usage_count": 0, "hook": f"hook {cs_id}",
        "angle": f"angle {cs_id}", "created_at": f"2026-07-20T00:00:0{cs_id[-1]}Z",
        "last_used_at": None,
    }


def _fake_pool(rows):
    async def _list(product_id):
        return list(rows)
    return _list


def _fake_rotation(rows):
    async def _rotate(product_id, count):
        return {"items": list(rows), "warnings": []}
    return _rotate


def _fake_compile(dialogues):
    async def _compile(**kw):
        d = dialogues.get(kw.get("copy_set_id"), f"fallback {kw.get('copy_set_id')}")
        return {
            "final_compiled_prompt_text": f"SECTION 6\n{d}\nSECTION 7",
            "prompt_blocks": [{"exact_dialogue_slice": d, "audio_seam_contract": {}}],
        }
    return _compile


class _Harness:
    """Records every write so we can assert all-or-nothing + zero provider work."""

    def __init__(self):
        self.created: list[dict] = []
        self.approved: list[list[str]] = []
        self.runs: list[dict] = []
        self.identity_writes: list[tuple] = []
        self.existing_batch: list[dict] = []
        self.fail_on_index: int | None = None
        self.approve_ok = True


def _install(monkeypatch, rows, dialogues, h: _Harness):
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(rows))
    monkeypatch.setattr(copy_rotation_service, "select_rotation_copy_sets", _fake_rotation(rows))
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", _fake_compile(dialogues))

    async def _creator(**kw):
        idx = len(h.created)
        if h.fail_on_index is not None and idx == h.fail_on_index:
            raise RuntimeError("compiler exploded")
        h.created.append(kw)
        return {"workspace_generation_package_id": f"wgp_{idx}"}

    monkeypatch.setattr(svc, "create_t2v_generation_package", _creator)
    monkeypatch.setattr(svc, "create_f2v_generation_package", _creator)
    monkeypatch.setattr(svc, "create_i2v_generation_package", _creator)

    async def _list_wgp(**kw):
        return list(h.existing_batch)

    async def _get_wgp(wgp_id):
        return {"workspace_generation_package_id": wgp_id, "generation_identity_json": "{}"}

    async def _update_wgp(wgp_id, **kw):
        h.identity_writes.append((wgp_id, kw))
        return {}

    async def _update_run(run_id, **kw):
        h.runs.append({"run_id": run_id, **kw})
        return {}

    monkeypatch.setattr(svc.crud, "list_workspace_generation_packages", _list_wgp)
    monkeypatch.setattr(svc.crud, "get_workspace_generation_package", _get_wgp)
    monkeypatch.setattr(svc.crud, "update_workspace_generation_package", _update_wgp)
    monkeypatch.setattr(svc.crud, "update_production_run", _update_run)

    async def _approve(ids):
        h.approved.append(list(ids))
        if not h.approve_ok:
            return {"approved": 0, "results": [{"package_id": ids[0], "ok": False, "error": "NOT_APPROVABLE_STATUS:BLOCKED"}]}
        return {"approved": len(ids), "results": [{"package_id": i, "ok": True} for i in ids]}

    async def _send(package_ids, **kw):
        h.runs.append({"send": list(package_ids), **kw})
        return {"production_run_id": "prun_bulk_1", "config_json": "{}"}

    monkeypatch.setattr(pq, "approve_packages", _approve)
    monkeypatch.setattr(pq, "send_to_production", _send)
    return h


def _prepare(monkeypatch, rows, dialogues, h=None, **over):
    h = _install(monkeypatch, rows, dialogues, h or _Harness())
    kwargs = dict(product_id="P", logical_mode="T2V", source_mode="T2V",
                  quantity=len(rows), model="Veo 3.1 - Lite", aspect="9:16")
    kwargs.update(over)
    return asyncio.run(svc.prepare_bulk_fanout_packages(**kwargs)), h


THREE = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
UNIQUE3 = {"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"}


# ── happy path ───────────────────────────────────────────────────────────────
def test_n3_ready_unique_creates_three_packages_with_distinct_identity(monkeypatch):
    out, h = _prepare(monkeypatch, THREE, UNIQUE3)

    assert out["prepared_package_count"] == 3
    assert out["package_ids"] == ["wgp_0", "wgp_1", "wgp_2"]
    assert out["stage"] == "PACKAGES_PREPARED"
    assert len(h.created) == 3

    # One package per planned item, each bound to its OWN copy set. Rotation is
    # seeded/LRU so the ORDER may be offset — the contract is that all three
    # distinct approved variants are used exactly once, never reused.
    assert {c["copy_set_id"] for c in h.created} == {"cs1", "cs2", "cs3"}
    assert len([c["copy_set_id"] for c in h.created]) == 3

    # itemized manifest carries full per-item identity
    for item in out["items"]:
        for key in ("item_index", "copy_variant_id", "variation_salt",
                    "dialogue_fingerprint", "logical_mode", "source_mode",
                    "generation_mode", "workspace_generation_package_id"):
            assert item.get(key) is not None, f"missing {key}"
        assert item["item_status"] == "PREPARED"
        assert item["credit_state"] == "NOT_AUTHORIZED"
    assert len({i["dialogue_fingerprint"] for i in out["items"]}) == 3
    assert len({i["variation_salt"] for i in out["items"]}) == 3


def test_prepare_approves_then_enqueues_all_n_without_count_shortcut(monkeypatch):
    out, h = _prepare(monkeypatch, THREE, UNIQUE3)
    assert h.approved == [["wgp_0", "wgp_1", "wgp_2"]]
    send = [r for r in h.runs if "send" in r][0]
    assert send["send"] == ["wgp_0", "wgp_1", "wgp_2"]      # N ITEMS...
    assert send["count"] == 1                               # ...NOT count:N
    assert out["production_run_id"] == "prun_bulk_1"


def test_per_item_identity_is_persisted_durably(monkeypatch):
    out, h = _prepare(monkeypatch, THREE, UNIQUE3)
    assert len(h.identity_writes) == 3
    import json
    for wgp_id, kw in h.identity_writes:
        payload = json.loads(kw["generation_identity_json"])["bulk_fanout_item"]
        assert payload["schema_version"] == "bulk-fanout-item-v1"
        assert payload["bulk_run_id"] == out["bulk_run_id"]
        for key in ("item_index", "copy_variant_id", "variation_salt",
                    "dialogue_fingerprint", "generation_mode"):
            assert key in payload
    # the run manifest is persisted too
    manifest_write = [r for r in h.runs if "config_json" in r][0]
    assert "bulk-fanout-manifest-v1" in manifest_write["config_json"]


def test_run_manifest_exposes_the_fingerprints_the_live_gate_will_pin(monkeypatch):
    out, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    assert len(out["expect_dialogue_fingerprints"]) == 3
    assert len(set(out["expect_dialogue_fingerprints"])) == 3


# ── fail-closed ──────────────────────────────────────────────────────────────
def test_duplicate_dialogue_is_rejected_before_any_package_is_created(monkeypatch):
    dupes = {"cs1": "same", "cs2": "same", "cs3": "ccc"}
    h = _Harness()
    with pytest.raises(ValueError, match="BULK_PREPARE_REFUSED"):
        _prepare(monkeypatch, THREE, dupes, h)
    assert h.created == [], "packages created despite duplicate dialogue"
    assert h.approved == []


def test_no_approved_copy_is_rejected_before_creation(monkeypatch):
    h = _Harness()
    with pytest.raises(ValueError, match="BULK_PREPARE_REFUSED.*NO_APPROVED_COPY_AVAILABLE"):
        _prepare(monkeypatch, [], {}, h, quantity=3)
    assert h.created == []


def test_stale_client_plan_fingerprint_is_rejected(monkeypatch):
    h = _Harness()
    with pytest.raises(ValueError, match="BULK_PLAN_FINGERPRINT_STALE"):
        _prepare(monkeypatch, THREE, UNIQUE3, h,
                 expect_bulk_plan_fingerprint="deadbeef" * 8)
    assert h.created == [], "packages created from a stale preview"
    assert h.approved == []


def test_matching_plan_fingerprint_is_accepted(monkeypatch):
    plan_out, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fp = plan_out["bulk_plan_fingerprint"]
    out2, _ = _prepare(monkeypatch, THREE, UNIQUE3, expect_bulk_plan_fingerprint=fp)
    assert out2["prepared_package_count"] == 3


def test_one_failed_package_aborts_the_whole_batch(monkeypatch):
    """All-or-nothing: a partial batch must never reach approval or a run."""
    h = _Harness()
    h.fail_on_index = 1
    with pytest.raises(ValueError, match=r"BULK_PACKAGE_CREATE_FAILED:item#1.*created_before_failure=1"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)
    assert h.approved == [], "approved despite a failed item"
    assert [r for r in h.runs if "send" in r] == [], "enqueued despite a failed item"


def test_failed_approval_aborts_before_enqueue(monkeypatch):
    h = _Harness()
    h.approve_ok = False
    with pytest.raises(ValueError, match="BULK_APPROVE_FAILED"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)
    assert [r for r in h.runs if "send" in r] == [], "enqueued despite failed approval"


def test_unsupported_mode_is_refused(monkeypatch):
    h = _Harness()
    with pytest.raises(ValueError, match="BULK_PREPARE_UNSUPPORTED_MODE:IMG"):
        _prepare(monkeypatch, THREE, UNIQUE3, h, logical_mode="IMG")
    assert h.created == []


def test_bulk_extend_remains_blocked_with_exact_blocker(monkeypatch):
    """EXTEND is NOT faked: multi-block belongs to the durable /video-jobs
    orchestrator, so bulk EXTEND is refused with its exact blocker."""
    h = _Harness()
    with pytest.raises(ValueError, match="BULK_EXTEND_NOT_SUPPORTED:use_video_jobs_orchestrator_per_item"):
        _prepare(monkeypatch, THREE, UNIQUE3, h,
                 generation_mode="EXTEND", requested_total_duration_seconds=16)
    assert h.created == [], "EXTEND packages created despite the blocker"


# ── idempotency ──────────────────────────────────────────────────────────────
def _prev(idx, fp, pkg=None):
    """An already-created package carrying its DURABLE bulk identity."""
    return {
        "workspace_generation_package_id": pkg or f"wgp_prev_{idx}",
        "production_run_id": "prun_prev",
        "generation_identity_json": json.dumps({
            "bulk_fanout_item": {
                "schema_version": "bulk-fanout-item-v1",
                "item_index": idx, "dialogue_fingerprint": fp,
            }
        }),
    }


def test_rerunning_the_same_plan_does_not_duplicate_packages(monkeypatch):
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)          # learn the real fps
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    h.existing_batch = [_prev(i, fps[i]) for i in range(3)]
    out, h2 = _prepare(monkeypatch, THREE, UNIQUE3, h)
    assert out["reused_existing_batch"] is True
    assert out["production_run_id"] == "prun_prev"
    assert h2.created == [], "created a second set of packages for the same plan"
    assert h2.approved == []


def test_reuse_pairs_packages_by_item_index_not_list_order(monkeypatch):
    """B-02 regression: the crud listing comes back created_at DESC, so zipping
    it against the plan's intents attributed each dialogue to the WRONG package
    on every re-run. Pairing must follow the durable item_index."""
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    # listing deliberately REVERSED, as the real created_at DESC order would be
    h.existing_batch = [_prev(i, fps[i]) for i in (2, 1, 0)]

    out, _ = _prepare(monkeypatch, THREE, UNIQUE3, h)

    # every item must be paired with the package that actually carries its
    # dialogue — not with whatever the listing happened to return first
    for item in out["items"]:
        assert item["workspace_generation_package_id"] == f"wgp_prev_{item['item_index']}"
        assert item["dialogue_fingerprint"] == fps[item["item_index"]]
    assert out["package_ids"] == ["wgp_prev_0", "wgp_prev_1", "wgp_prev_2"]


def test_reuse_fails_closed_when_a_package_lacks_bulk_identity(monkeypatch):
    """Without item_index the pairing is unprovable — refuse, never guess."""
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    h.existing_batch = [_prev(0, fps[0]), _prev(1, fps[1]),
                        {"workspace_generation_package_id": "wgp_orphan",
                         "production_run_id": "prun_prev"}]
    with pytest.raises(ValueError, match="BULK_REUSE_IDENTITY_MISSING:wgp_orphan"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)


def test_reuse_fails_closed_on_an_incomplete_batch(monkeypatch):
    """A batch missing an item cannot satisfy the plan — refuse."""
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    h.existing_batch = [_prev(0, fps[0]), _prev(1, fps[1])]   # item 2 absent
    with pytest.raises(ValueError, match=r"BULK_REUSE_INCOMPLETE_BATCH:missing_item_indexes=\[2\]"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)


# ── B-06 · kwargs must match the REAL creator signatures ────────────────────
# The orchestration tests mock the creators, so a kwarg the real creator does not
# accept passes silently here and only explodes at runtime. F2V/HYBRID bulk
# prepare was fully broken this way (TypeError: unexpected keyword argument
# 'product_reference_asset_id'). These tests bind against inspect.signature of the
# REAL functions so a signature drift fails in CI, not in production.
import inspect as _inspect

# Captured AT IMPORT TIME, before any monkeypatch replaces the creators — this is
# the whole point: comparing against a patched spy would prove nothing.
_REAL_CREATOR_PARAMS = {
    name: set(_inspect.signature(getattr(svc, name)).parameters)
    for name in ("create_t2v_generation_package",
                 "create_f2v_generation_package",
                 "create_i2v_generation_package")
}


def _real_params(fn_name):
    return _REAL_CREATOR_PARAMS[fn_name]


@pytest.mark.parametrize("mode,fn_name", [
    ("T2V", "create_t2v_generation_package"),
    ("F2V", "create_f2v_generation_package"),
    ("HYBRID", "create_f2v_generation_package"),
    ("I2V", "create_i2v_generation_package"),
])
def test_orchestrator_only_passes_kwargs_the_real_creator_accepts(monkeypatch, mode, fn_name):
    seen: list[dict] = []

    async def _spy(**kw):
        seen.append(kw)
        return {"workspace_generation_package_id": f"wgp_{len(seen)}"}

    h = _Harness()
    _install(monkeypatch, THREE, UNIQUE3, h)
    for target in ("create_t2v_generation_package", "create_f2v_generation_package",
                   "create_i2v_generation_package"):
        monkeypatch.setattr(svc, target, _spy)

    asyncio.run(svc.prepare_bulk_fanout_packages(
        product_id="P", logical_mode=mode, source_mode=None, quantity=3,
        model="Veo 3.1 - Lite", aspect="9:16",
        start_frame_asset_id="ca_frame", product_reference_asset_id="ca_anchor",
        character_reference_asset_id="ca_char", scene_context_reference_asset_id="ca_scene"))

    accepted = _real_params(fn_name)
    assert seen, "creator was never called"
    for kw in seen:
        unexpected = set(kw) - accepted
        assert not unexpected, (
            f"{mode} bulk passes kwargs {fn_name} does not accept: {sorted(unexpected)}")


def test_hybrid_anchor_rides_the_start_frame_slot(monkeypatch):
    """HYBRID's padded 9:16 PRODUCT_REFERENCE anchor must reach the F2V creator
    through start_frame_asset_id — the same convention the batch lane uses."""
    seen: list[dict] = []

    async def _spy(**kw):
        seen.append(kw)
        return {"workspace_generation_package_id": f"wgp_{len(seen)}"}

    h = _Harness()
    _install(monkeypatch, THREE, UNIQUE3, h)
    monkeypatch.setattr(svc, "create_f2v_generation_package", _spy)
    asyncio.run(svc.prepare_bulk_fanout_packages(
        product_id="P", logical_mode="HYBRID", quantity=3,
        model="Veo 3.1 - Lite", aspect="9:16",
        start_frame_asset_id="ca_frame", product_reference_asset_id="ca_anchor"))

    assert seen
    for kw in seen:
        assert kw["start_frame_asset_id"] == "ca_anchor", "HYBRID must ride the anchor"
        assert kw["source_mode"] == "HYBRID"
        assert "product_reference_asset_id" not in kw


def test_f2v_uses_the_start_frame_not_the_anchor(monkeypatch):
    seen: list[dict] = []

    async def _spy(**kw):
        seen.append(kw)
        return {"workspace_generation_package_id": f"wgp_{len(seen)}"}

    h = _Harness()
    _install(monkeypatch, THREE, UNIQUE3, h)
    monkeypatch.setattr(svc, "create_f2v_generation_package", _spy)
    asyncio.run(svc.prepare_bulk_fanout_packages(
        product_id="P", logical_mode="F2V", quantity=3,
        model="Veo 3.1 - Lite", aspect="9:16",
        start_frame_asset_id="ca_frame", product_reference_asset_id="ca_anchor"))

    assert seen
    for kw in seen:
        assert kw["start_frame_asset_id"] == "ca_frame"


# ── B-07 / B-08 · reuse honesty + HYBRID compile mapping ───────────────────
def test_reuse_fails_closed_on_a_blocked_prior_batch(monkeypatch):
    """A prior attempt can leave BLOCKED packages that were never approved or
    enqueued. Returning them as PREPARED produced a manifest with
    production_run_id=None — a batch that claims to exist but cannot run."""
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    blocked = [_prev(i, fps[i]) for i in range(3)]
    for row in blocked:
        row["status"] = "BLOCKED"
        row["production_run_id"] = None
    h.existing_batch = blocked
    with pytest.raises(ValueError, match="BULK_REUSE_BATCH_BLOCKED"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)


def test_reuse_fails_closed_when_prior_batch_never_reached_a_run(monkeypatch):
    h = _Harness()
    plan, _ = _prepare(monkeypatch, THREE, UNIQUE3)
    fps = [i["dialogue_fingerprint"] for i in plan["items"]]
    rows = [_prev(i, fps[i]) for i in range(3)]
    for row in rows:
        row["production_run_id"] = None
    h.existing_batch = rows
    with pytest.raises(ValueError, match="BULK_REUSE_BATCH_NOT_ENQUEUED"):
        _prepare(monkeypatch, THREE, UNIQUE3, h)


def test_hybrid_compiles_as_f2v_with_source_mode_hybrid(monkeypatch):
    """B-08: the compiler raises UNSUPPORTED_MODE for logical 'HYBRID'. Prepare
    must remap the COMPILE call to F2V + source_mode=HYBRID while keeping HYBRID
    as the logical identity for creator dispatch."""
    seen_compile: list[dict] = []

    async def _compile(**kw):
        seen_compile.append(kw)
        d = UNIQUE3.get(kw.get("copy_set_id"), "x")
        return {"final_compiled_prompt_text": f"SECTION 6\n{d}\nSECTION 7",
                "prompt_blocks": [{"exact_dialogue_slice": d, "audio_seam_contract": {}}]}

    seen_creator: list[dict] = []

    async def _spy(**kw):
        seen_creator.append(kw)
        return {"workspace_generation_package_id": f"wgp_{len(seen_creator)}"}

    h = _Harness()
    _install(monkeypatch, THREE, UNIQUE3, h)
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", _compile)
    monkeypatch.setattr(svc, "create_f2v_generation_package", _spy)

    asyncio.run(svc.prepare_bulk_fanout_packages(
        product_id="P", logical_mode="HYBRID", quantity=3,
        model="Veo 3.1 - Lite", aspect="9:16",
        product_reference_asset_id="ca_anchor"))

    assert seen_compile, "compiler never called"
    for kw in seen_compile:
        assert kw["mode"] == "F2V", "HYBRID must COMPILE as F2V"
        assert kw["source_mode"] == "HYBRID", "source_mode must carry the HYBRID identity"
    # creator dispatch still uses the HYBRID convention
    for kw in seen_creator:
        assert kw["source_mode"] == "HYBRID"
        assert kw["start_frame_asset_id"] == "ca_anchor"


def test_f2v_and_hybrid_do_not_share_a_batch(monkeypatch):
    """B-09: HYBRID compiles as F2V, so both plans carry the SAME
    bulk_plan_fingerprint. Keying the batch on that alone made a HYBRID request
    reuse an F2V batch — identical dialogue, but FRAMES packages instead of the
    product-anchor ones. The group key must separate the logical lanes."""
    async def _spy(**kw):
        return {"workspace_generation_package_id": "wgp_x"}

    ids = {}
    for lane, extra in (("F2V", {"start_frame_asset_id": "ca_frame"}),
                        ("HYBRID", {"product_reference_asset_id": "ca_anchor"})):
        h = _Harness()
        _install(monkeypatch, THREE, UNIQUE3, h)
        monkeypatch.setattr(svc, "create_f2v_generation_package", _spy)
        out = asyncio.run(svc.prepare_bulk_fanout_packages(
            product_id="P", logical_mode=lane, quantity=3,
            model="Veo 3.1 - Lite", aspect="9:16", **extra))
        ids[lane] = out["bulk_run_id"]

    assert ids["F2V"] != ids["HYBRID"], (
        f"F2V and HYBRID collided on bulk_run_id {ids['F2V']} — a HYBRID request "
        "would reuse the F2V batch")


# ── credit / provider contract ───────────────────────────────────────────────
def test_prepare_is_credit_free_and_touches_no_provider(monkeypatch):
    out, h = _prepare(monkeypatch, THREE, UNIQUE3)
    assert out["credit"] == "NONE"
    assert out["provider_calls"] == 0
    assert out["flow_calls"] == 0
    assert out["live_bulk_stage"] == "STAGE_3_RUNTIME_CERTIFICATION_REQUIRED"
    assert out["next_step"] == "DRY_RUN_VALIDATE_ALL_ITEMS"
    # nothing in the created packages asks for live/credit
    for kw in h.created:
        assert "confirm_live_credit_burn" not in kw


def test_prepare_never_flips_the_certification_flag():
    assert pq.BULK_LIVE_EXECUTION_CERTIFIED is False


@pytest.mark.parametrize("qty", [1, 0, -1])
def test_bulk_prepare_refuses_quantity_below_two(monkeypatch, qty):
    """Stage 2C is BULK-only: a single item keeps its mode-exact one-serial path.

    Hardening — previously quantity=1 would happily prepare one package even
    though the bulk LIVE gate refuses a 1-item run, so that batch could never be
    authorized as bulk. Now refused server-side BEFORE any create/approve/
    enqueue/dry-run, regardless of what the UI routes.
    """
    one = [_approved("cs1")]
    h = _Harness()
    with pytest.raises(ValueError, match=f"BULK_PREPARE_REQUIRES_MULTIPLE_ITEMS:{qty}"):
        _prepare(monkeypatch, one, {"cs1": "aaa"}, h, quantity=qty)
    assert h.created == [], "packages created for a sub-bulk quantity"
    assert h.approved == []
    assert [r for r in h.runs if "send" in r] == [], "enqueued for a sub-bulk quantity"


def test_quantity_two_is_the_minimum_accepted_bulk(monkeypatch):
    """The boundary is exactly 2 — the guard must not over-reject real bulk."""
    two = [_approved("cs1"), _approved("cs2")]
    out, h = _prepare(monkeypatch, two, {"cs1": "aaa", "cs2": "bbb"}, quantity=2)
    assert out["prepared_package_count"] == 2
    assert len(h.created) == 2


def test_bulk_live_gate_still_refuses_a_single_item_run():
    """The server-side live gate remains the second, independent chokepoint."""
    import inspect
    assert "BULK_REQUIRES_MULTIPLE_ITEMS" in inspect.getsource(pq._assert_bulk_fanout_live)
