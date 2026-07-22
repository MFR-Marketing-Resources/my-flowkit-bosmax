"""Stage 2A — itemized live bulk fan-out contract, up to the CREDIT BOUNDARY.

Two halves:

1. ``plan_bulk_fanout_intents`` — credit-free planning of N SEPARATE intents.
   Bulk is never one blind ``count:N`` submission (``count`` is the provider's
   per-submission copy count, clamped 1..4 — NOT an item multiplier), so each
   item gets its own identity and its own credit metadata.

2. ``_assert_bulk_fanout_live`` — the server-side gate. Every critical check is
   enforced HERE, not in the UI: distinct bulk phrase, pinned package set,
   pinned dialogue set, freshly re-derived per-item readiness, dialogue
   uniqueness, and finally the Stage 3 credit boundary that refuses to spend
   credit at all until bulk live is runtime-certified.

Nothing here fires a provider or Flow call: the compile + payload seams are
faked, and the credit boundary is asserted to hold.
"""
import asyncio
import inspect

import pytest

from agent.services import copy_rotation_service
from agent.services import production_queue_service as pq
from agent.services import workspace_execution_package_service as wxp
from agent.services import workspace_generation_package_service as svc


# ── planning fakes (no DB, no compiler, no provider) ─────────────────────────
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


def _fake_rotation(rows, warnings=None):
    async def _rotate(product_id, count):
        return {"items": list(rows), "warnings": list(warnings or [])}
    return _rotate


def _fake_compile(dialogue_by_copy_set):
    async def _compile(**kw):
        cs = kw.get("copy_set_id")
        dialogue = dialogue_by_copy_set.get(cs, f"fallback {cs}")
        return {
            "final_compiled_prompt_text": f"SECTION 6\n{dialogue}\nSECTION 7",
            "prompt_blocks": [{"exact_dialogue_slice": dialogue, "audio_seam_contract": {}}],
        }
    return _compile


def _plan(monkeypatch, rows, dialogues, *, quantity, generation_mode="SINGLE"):
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(rows))
    monkeypatch.setattr(copy_rotation_service, "select_rotation_copy_sets", _fake_rotation(rows))
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", _fake_compile(dialogues))
    return asyncio.run(svc.plan_bulk_fanout_intents(
        product_id="P", logical_mode="T2V", source_mode="T2V",
        generation_mode=generation_mode, quantity=quantity))


# ── 1 · itemized planning ────────────────────────────────────────────────────
def test_ready_unique_pool_plans_n_itemized_intents(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    out = _plan(monkeypatch, rows, {"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"}, quantity=3)

    assert out["bulk_authorizable"] is True
    assert out["blockers"] == []
    assert out["planned_intent_count"] == 3
    assert len(out["intents"]) == 3
    assert out["copy_pool_readiness_status"] == "READY"
    assert out["dialogue_uniqueness_status"] == "UNIQUE"
    assert out["live_bulk_stage"] == "STAGE_3_AUTHORIZATION_REQUIRED"


def test_every_intent_carries_stable_per_item_metadata(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    dialogues = {"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"}
    out = _plan(monkeypatch, rows, dialogues, quantity=3)

    required = {
        "item_index", "copy_variant_id", "variation_salt", "dialogue_fingerprint",
        "logical_mode", "source_mode", "generation_mode",
        "workspace_generation_package_id", "production_run_id", "production_job_id",
        "item_status", "credit_state", "credit_warning",
    }
    for intent in out["intents"]:
        assert required <= set(intent), f"missing: {required - set(intent)}"
        assert intent["item_status"] == "PLANNED"
        assert intent["credit_state"] == "NOT_AUTHORIZED"
        assert intent["logical_mode"] == "T2V"

    assert len({i["item_index"] for i in out["intents"]}) == 3
    assert len({i["dialogue_fingerprint"] for i in out["intents"]}) == 3
    assert len({i["variation_salt"] for i in out["intents"]}) == 3

    again = _plan(monkeypatch, rows, dialogues, quantity=3)
    assert again["bulk_plan_fingerprint"] == out["bulk_plan_fingerprint"]


def test_no_approved_copy_blocks_the_plan(monkeypatch):
    out = _plan(monkeypatch, [], {}, quantity=3)
    assert out["bulk_authorizable"] is False
    assert any(b.startswith("COPY_POOL_NOT_READY:NO_APPROVED_COPY_AVAILABLE") for b in out["blockers"])


def test_insufficient_unique_dialogue_blocks_the_plan(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    out = _plan(monkeypatch, rows, {"cs1": "aaa", "cs2": "aaa", "cs3": "bbb"}, quantity=3)
    assert out["bulk_authorizable"] is False
    assert any("COPY_POOL_NOT_READY:COPY_POOL_SHORTAGE:short_by_1" in b for b in out["blockers"])


def test_duplicate_dialogue_cannot_pass_into_fanout(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2")]
    out = _plan(monkeypatch, rows, {"cs1": "same", "cs2": "same"}, quantity=2)
    assert out["bulk_authorizable"] is False
    assert out["dialogue_uniqueness_status"] == "DUPLICATE_DIALOGUE_BLOCKED"


def test_bulk_extend_stays_blocked_with_exact_blocker(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2")]
    out = _plan(monkeypatch, rows, {"cs1": "aaa", "cs2": "bbb"},
                quantity=2, generation_mode="EXTEND")
    assert out["bulk_authorizable"] is False
    assert any(b.startswith("BULK_EXTEND_NOT_SUPPORTED") for b in out["blockers"])


def test_planning_is_credit_free_and_calls_no_provider(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    out = _plan(monkeypatch, rows, {"cs1": "a", "cs2": "b", "cs3": "c"}, quantity=3)
    assert out["credit"] == "NONE"
    assert out["provider_calls"] == 0
    assert out["flow_calls"] == 0
    for intent in out["intents"]:
        assert intent["workspace_generation_package_id"] is None
        assert intent["production_job_id"] is None


def test_plan_quantity_out_of_range_fails_closed(monkeypatch):
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool([]))
    for bad in (0, -1, svc.QUANTITY_PREVIEW_MAX + 1):
        with pytest.raises(ValueError, match="QUANTITY_OUT_OF_RANGE"):
            asyncio.run(svc.plan_bulk_fanout_intents(
                product_id="P", logical_mode="T2V", quantity=bad))


# ── 2 · server-side bulk live gate ───────────────────────────────────────────
RUN = {"production_run_id": "prun_1", "config_json": {"last_dry_run_report": {"ready": 3, "blocked": 0}}}


def _item(pkg, fp, *, source="batch", **over):
    """A queued item whose dialogue fingerprint lives in one of the TWO durable
    sources: the BATCH lane's variation_fingerprints_json, or Stage 2C's
    generation_identity_json.bulk_fanout_item (B-01)."""
    row = {
        "workspace_generation_package_id": pkg, "product_id": "P",
        "production_job_id": None,
    }
    if source == "batch":
        row["variation_fingerprints_json"] = {"dialogue_fingerprint": fp}
    elif source == "bulk":
        row["generation_identity_json"] = {
            "bulk_fanout_item": {
                "schema_version": "bulk-fanout-item-v1",
                "dialogue_fingerprint": fp,
            }
        }
    row.update(over)
    return row


def _gate(monkeypatch, items, *, phrase=pq.LIVE_BULK_CONFIRM_PHRASE,
          pkg_ids=None, fps=None, run=None, blockers_by_pkg=None, certified=False):
    async def _list(**kw):
        return list(items)

    async def _payload(item, cfg=None):
        pkg = item["workspace_generation_package_id"]
        # logical_mode comes from the item so the matrix can drive all 4 lanes
        return ({"logical_mode": item.get("logical_mode", "T2V")},
                list((blockers_by_pkg or {}).get(pkg, [])))

    monkeypatch.setattr(pq.crud, "list_production_queue_packages", _list)
    monkeypatch.setattr(pq, "build_execution_payload", _payload)
    monkeypatch.setattr(pq, "BULK_LIVE_EXECUTION_CERTIFIED", certified)
    ids = pkg_ids if pkg_ids is not None else [i["workspace_generation_package_id"] for i in items]
    # derive the pinned set from EITHER durable source, same as the gate does
    fingerprints = fps if fps is not None else [
        pq._persisted_dialogue_fingerprint(i) for i in items]
    return asyncio.run(pq._assert_bulk_fanout_live(
        run or RUN, confirm_phrase=phrase,
        expect_package_ids=ids, expect_dialogue_fingerprints=fingerprints))


def _expect(monkeypatch, items, match, **kw):
    with pytest.raises(ValueError, match=match):
        _gate(monkeypatch, items, **kw)


THREE = [_item("wgp1", "fp1"), _item("wgp2", "fp2"), _item("wgp3", "fp3")]


def test_gate_stops_at_the_credit_boundary_even_when_fully_valid(monkeypatch):
    """The whole set validates — and credit is STILL refused. This is the point."""
    _expect(monkeypatch, THREE, "BULK_LIVE_EXECUTION_NOT_CERTIFIED")


def test_gate_requires_the_distinct_bulk_phrase(monkeypatch):
    _expect(monkeypatch, THREE, "LIVE_BULK_CONFIRM_PHRASE_INVALID",
            phrase=pq.LIVE_CONFIRM_PHRASE)
    _expect(monkeypatch, THREE, "LIVE_BULK_CONFIRM_PHRASE_INVALID", phrase="")


def test_bulk_phrase_is_distinct_from_every_single_run_phrase():
    singles = {pq.LIVE_CONFIRM_PHRASE, pq.LIVE_F2V_CONFIRM_PHRASE, pq.LIVE_I2V_CONFIRM_PHRASE}
    assert pq.LIVE_BULK_CONFIRM_PHRASE not in singles


def test_gate_refuses_a_single_item_run(monkeypatch):
    _expect(monkeypatch, [_item("wgp1", "fp1")], "BULK_REQUIRES_MULTIPLE_ITEMS:1")


def test_gate_requires_a_pinned_package_set(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_REQUIRES_EXPECT_PACKAGE_IDS", pkg_ids=[])


def test_gate_refuses_a_package_set_that_drifted(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_PACKAGE_SET_MISMATCH",
            pkg_ids=["wgp1", "wgp2", "wgp_other"])
    _expect(monkeypatch, THREE, "BULK_PACKAGE_SET_MISMATCH", pkg_ids=["wgp1", "wgp2"])


def test_gate_requires_pinned_dialogue_fingerprints(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_REQUIRES_EXPECT_DIALOGUE_FINGERPRINTS", fps=[])


def test_gate_refuses_when_the_dialogue_set_drifted(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_DIALOGUE_SET_MISMATCH", fps=["fp1", "fp2", "fp_other"])


def test_gate_refuses_duplicate_dialogue_across_items(monkeypatch):
    dupes = [_item("wgp1", "same"), _item("wgp2", "same"), _item("wgp3", "fp3")]
    _expect(monkeypatch, dupes, "BULK_DUPLICATE_DIALOGUE")


def test_gate_refuses_an_item_with_no_dialogue_fingerprint(monkeypatch):
    items = [_item("wgp1", "fp1"), _item("wgp2", "", variation_fingerprints_json={})]
    _expect(monkeypatch, items, "BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING:wgp2", fps=["fp1"])


def test_gate_refuses_a_blocked_item_including_extend(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_ITEM_BLOCKED:wgp2",
            blockers_by_pkg={"wgp2": ["EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN:16s_USE_VIDEO_JOBS_ORCHESTRATOR"]})


def test_gate_refuses_an_item_that_already_fired(monkeypatch):
    items = [_item("wgp1", "fp1"), _item("wgp2", "fp2", production_job_id="job_x")]
    _expect(monkeypatch, items, "LIVE_DUPLICATE_SUBMISSION:wgp2")


def test_gate_refuses_a_fastmoss_reference_product(monkeypatch):
    items = [_item("wgp1", "fp1"), _item("wgp2", "fp2", product_id="fastmoss-ref:x")]
    _expect(monkeypatch, items, "LIVE_FASTMOSS_REF_FORBIDDEN")


def test_gate_requires_every_item_dry_run_ready(monkeypatch):
    _expect(monkeypatch, THREE, "BULK_REQUIRES_ALL_ITEMS_DRY_RUN_READY",
            run={"production_run_id": "prun_1",
                 "config_json": {"last_dry_run_report": {"ready": 2, "blocked": 1}}})
    _expect(monkeypatch, THREE, "LIVE_REQUIRES_DRY_RUN_READY:NO_DRY_RUN",
            run={"production_run_id": "prun_1", "config_json": {}})


def test_gate_passes_only_when_certified_and_everything_valid(monkeypatch):
    """Proves the refusal is the credit boundary, not a broken gate."""
    validated, validated_mode = _gate(monkeypatch, THREE, certified=True)
    assert [i["workspace_generation_package_id"] for i in validated] == ["wgp1", "wgp2", "wgp3"]
    assert validated_mode == "T2V"


def test_gate_reads_the_fingerprint_written_by_stage_2c(monkeypatch):
    """B-01 regression: Stage 2C persists the fingerprint in
    generation_identity_json.bulk_fanout_item, NOT variation_fingerprints_json.

    The gate used to read only the batch column, so a 2C-prepared batch always
    looked fingerprint-less and refused with
    BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING — it could never reach its own credit
    boundary. Reaching BULK_LIVE_EXECUTION_NOT_CERTIFIED proves the whole gate
    now validates a 2C batch end to end."""
    bulk_items = [_item(f"wgp{i}", f"fp{i}", source="bulk") for i in range(1, 4)]
    _expect(monkeypatch, bulk_items, "BULK_LIVE_EXECUTION_NOT_CERTIFIED")


def test_gate_still_reads_the_batch_lane_fingerprint(monkeypatch):
    """The batch lane must keep working — the fix is additive, not a swap."""
    _expect(monkeypatch, THREE, "BULK_LIVE_EXECUTION_NOT_CERTIFIED")


def test_gate_accepts_a_mixed_batch_of_both_sources(monkeypatch):
    mixed = [_item("wgp1", "fp1", source="batch"),
             _item("wgp2", "fp2", source="bulk"),
             _item("wgp3", "fp3", source="bulk")]
    _expect(monkeypatch, mixed, "BULK_LIVE_EXECUTION_NOT_CERTIFIED")


def test_gate_passes_a_stage_2c_batch_when_certified(monkeypatch):
    """Every check passes on a 2C batch; only the credit boundary stops it."""
    bulk_items = [_item(f"wgp{i}", f"fp{i}", source="bulk") for i in range(1, 4)]
    validated, _mode = _gate(monkeypatch, bulk_items, certified=True)
    assert [i["workspace_generation_package_id"] for i in validated] == ["wgp1", "wgp2", "wgp3"]


def test_neither_source_present_still_fails_closed(monkeypatch):
    """Fail-closed is preserved: no fingerprint anywhere is still a refusal."""
    items = [_item("wgp1", "fp1", source="bulk"),
             _item("wgp2", "", source="none")]
    _expect(monkeypatch, items, "BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING:wgp2", fps=["fp1"])


def test_duplicate_dialogue_still_fails_closed_across_sources(monkeypatch):
    """A repeat is a repeat even when the two items store it in DIFFERENT
    durable sources — the fix must not open a duplicate-dialogue hole."""
    dupes = [_item("wgp1", "same", source="batch"),
             _item("wgp2", "same", source="bulk"),
             _item("wgp3", "fp3", source="bulk")]
    _expect(monkeypatch, dupes, "BULK_DUPLICATE_DIALOGUE")


def test_bulk_identity_wins_over_a_stale_batch_column(monkeypatch):
    """When both columns are populated the 2C identity is authoritative — it is
    written by the lane that actually built this batch."""
    item = _item("wgp1", "bulk_fp", source="bulk")
    item["variation_fingerprints_json"] = {"dialogue_fingerprint": "stale_batch_fp"}
    assert pq._persisted_dialogue_fingerprint(item) == "bulk_fp"


# ── B-03 · ONE shared non-EXTEND bulk engine: the 4-lane matrix ─────────────
# The live loop authorizes T2V by default and widens only for a mode recorded in
# cfg["authorized_live_mode"]. Before B-03 the bulk gate never recorded one, so a
# validated F2V/HYBRID/I2V set would have died per item with
# LIVE_MODE_NOT_AUTHORIZED. Reaching the CREDIT BOUNDARY is the proof that mode
# authorization is no longer the thing that stops these lanes.
NON_EXTEND_LANES = ["T2V", "F2V", "HYBRID", "I2V"]


def _lane_items(mode, n=3):
    return [_item(f"wgp{i}", f"fp{i}", logical_mode=mode) for i in range(1, n + 1)]


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_every_non_extend_lane_reaches_the_credit_boundary(monkeypatch, mode):
    """One shared engine: all four single-block lanes behave identically."""
    _expect(monkeypatch, _lane_items(mode), "BULK_LIVE_EXECUTION_NOT_CERTIFIED")


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_every_non_extend_lane_authorizes_exactly_its_own_mode(monkeypatch, mode):
    """The gate must hand the loop EXACTLY the validated mode — never wider."""
    validated, validated_mode = _gate(monkeypatch, _lane_items(mode), certified=True)
    assert validated_mode == mode
    assert len(validated) == 3


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_authorized_mode_satisfies_the_live_loop_admission_rule(monkeypatch, mode):
    """Close the loop on B-03 against the loop's OWN rule, not a paraphrase:
    reproduce `allowed_live_modes` exactly as _live_production_loop computes it
    and prove every lane's items would now be admitted."""
    _validated, validated_mode = _gate(monkeypatch, _lane_items(mode), certified=True)

    # verbatim reproduction of the loop's admission logic
    allowed = {"T2V"}
    auth = str(validated_mode or "").strip().upper()
    if auth in ("F2V", "HYBRID", "I2V"):
        allowed = {auth}

    assert mode in allowed, f"{mode} would still hit LIVE_MODE_NOT_AUTHORIZED"


def test_mixed_modes_fail_closed(monkeypatch):
    """A mixed batch cannot be authorized — the loop admits ONE mode per run, so
    authorizing the union would silently widen the grant beyond validation."""
    mixed = [_item("wgp1", "fp1", logical_mode="T2V"),
             _item("wgp2", "fp2", logical_mode="F2V"),
             _item("wgp3", "fp3", logical_mode="I2V")]
    _expect(monkeypatch, mixed, "BULK_MIXED_MODES_FORBIDDEN")


def test_extend_never_reaches_mode_authorization(monkeypatch):
    """EXTEND is blocked by build_execution_payload BEFORE any mode is collected,
    so it can never be authorized as a bulk mode. Stage 3A does not change this."""
    _expect(monkeypatch, _lane_items("T2V"), "BULK_ITEM_BLOCKED:wgp2",
            blockers_by_pkg={"wgp2": ["EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN:16s_USE_VIDEO_JOBS_ORCHESTRATOR"]})


def test_unknown_mode_fails_closed(monkeypatch):
    items = [_item("wgp1", "fp1", logical_mode="T2V"),
             _item("wgp2", "fp2", logical_mode="")]
    _expect(monkeypatch, items, "BULK_ITEM_MODE_UNKNOWN:wgp2")


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_every_lane_still_fails_closed_on_duplicate_dialogue(monkeypatch, mode):
    """B-03 must not open a uniqueness hole in ANY lane."""
    dupes = [_item("wgp1", "same", logical_mode=mode),
             _item("wgp2", "same", logical_mode=mode),
             _item("wgp3", "fp3", logical_mode=mode)]
    _expect(monkeypatch, dupes, "BULK_DUPLICATE_DIALOGUE")


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_every_lane_still_fails_closed_on_missing_fingerprint(monkeypatch, mode):
    items = [_item("wgp1", "fp1", logical_mode=mode),
             _item("wgp2", "", source="none", logical_mode=mode)]
    _expect(monkeypatch, items, "BULK_ITEM_DIALOGUE_FINGERPRINT_MISSING:wgp2",
            fps=["fp1"])


@pytest.mark.parametrize("mode", NON_EXTEND_LANES)
def test_every_lane_still_requires_the_bulk_phrase(monkeypatch, mode):
    _expect(monkeypatch, _lane_items(mode), "LIVE_BULK_CONFIRM_PHRASE_INVALID",
            phrase=pq.LIVE_CONFIRM_PHRASE)


def test_single_item_still_refused_by_the_bulk_door(monkeypatch):
    """qty 1 stays on its mode-exact one-serial path, in every lane."""
    for mode in NON_EXTEND_LANES:
        _expect(monkeypatch, _lane_items(mode, n=1), "BULK_REQUIRES_MULTIPLE_ITEMS:1")


def test_stage3a_does_not_touch_the_single_flight_guard():
    """Owner decision: serial single-tab stays. Stage 3A must not enable
    concurrency, so make_video's single-flight lane is untouched."""
    import inspect
    from agent.services import make_video as _mv
    src = inspect.getsource(_mv)
    assert "_VIDEO_LANE_JOB" in src
    assert 'error": "VIDEO_JOB_IN_FLIGHT"' in src or "VIDEO_JOB_IN_FLIGHT" in src


def test_bulk_live_is_certified_and_the_gate_above_it_is_intact():
    """Stage 3 was certified 2026-07-22 on live evidence (four bulk runs, each
    item its own provider job — see the constant's comment). So the old
    ``is False`` pin is gone.

    What must NEVER regress is everything ABOVE the boundary: the certification
    removed the last door, it did not remove the locks. If a future change
    deletes one of these, credit becomes reachable without an operator."""
    assert pq.BULK_LIVE_EXECUTION_CERTIFIED is True
    src = inspect.getsource(pq._assert_bulk_fanout_live)
    for guard in (
        "LIVE_BULK_CONFIRM_PHRASE_INVALID",       # the distinct bulk phrase
        "BULK_REQUIRES_MULTIPLE_ITEMS",           # bulk lane is bulk-only
        "BULK_REQUIRES_EXPECT_PACKAGE_IDS",       # caller must pin the set
        "BULK_REQUIRES_EXPECT_DIALOGUE_FINGERPRINTS",
        "BULK_ITEM_BLOCKED",                      # no blocked item may ride along
        "BULK_REQUIRES_ALL_ITEMS_DRY_RUN_READY",  # every item dry-run green
        "BULK_MIXED_MODES_FORBIDDEN",             # one batch = one mode
        "LIVE_DUPLICATE_SUBMISSION",              # never re-fire a fired package
    ):
        assert guard in src, f"bulk credit gate lost its {guard} check"


def test_count_is_provider_copies_not_item_fanout():
    """Regression guard: bulk must never be faked with count:N."""
    import inspect
    src = inspect.getsource(pq.send_to_production)
    assert "max(1, min(4, int(count or 1)))" in src, "count clamp changed — recheck bulk semantics"
