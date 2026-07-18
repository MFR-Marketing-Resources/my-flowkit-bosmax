"""Script Library P2 — content combination ledger + planner script rotation.

The on-platform uniqueness law: a CONTENT is the combination
(script x avatar/visuals x scene). These tests pin:
  - the fingerprint is deterministic, mode-aware, and key-order independent;
  - copy_set_ids rotate index-aligned with hook_angles in plan_batch_items
    (the copy_set lineage must stay paired with its hook text);
  - the ledger refuses a duplicate fingerprint (record returns None);
  - the batch script resolver prefers explicit hooks, then the Script
    Library, then claim-safe angles — never silently mixes sources.
"""
import pytest

from agent.services import batch_prompt_planner as planner
from agent.services import copy_rotation_service as rot

PID = "prod-combo-1"


def _plan(mode="T2V", **kw):
    base = {
        "item_index": 0,
        "logical_mode": mode,
        "variation_strategy": "SAME_SCRIPT_DIFF_VISUALS",
        "scene_context_override": "kitchen morning light",
        "hook_override": "Jangan beli sebelum tengok ni",
        "copy_set_id": None,
    }
    base.update(kw)
    return base


# ── Fingerprint ───────────────────────────────────────────────────────────


def test_fingerprint_is_deterministic_and_key_order_independent():
    vk = {"avatar_code": "BOS_F_MAYA", "scene_context": "kitchen"}
    a = rot.combination_fingerprint(PID, "T2V", "copy_set:cs_01", vk)
    b = rot.combination_fingerprint(
        PID, "t2v", "copy_set:cs_01",
        {"scene_context": "kitchen", "avatar_code": "BOS_F_MAYA"},
    )
    assert a == b
    assert len(a) == 64


def test_fingerprint_changes_with_each_combination_axis():
    vk = {"avatar_code": "BOS_F_MAYA", "scene_context": "kitchen"}
    base = rot.combination_fingerprint(PID, "T2V", "copy_set:cs_01", vk)
    assert base != rot.combination_fingerprint(PID, "T2V", "copy_set:cs_02", vk)
    assert base != rot.combination_fingerprint(
        PID, "T2V", "copy_set:cs_01", {**vk, "avatar_code": "BOS_M_AMIR"}
    )
    assert base != rot.combination_fingerprint(
        PID, "T2V", "copy_set:cs_01", {**vk, "scene_context": "beach"}
    )
    assert base != rot.combination_fingerprint("prod-2", "T2V", "copy_set:cs_01", vk)
    assert base != rot.combination_fingerprint(PID, "HYBRID", "copy_set:cs_01", vk)


def test_visual_key_is_mode_aware():
    t2v = rot.visual_key_for_plan(_plan("T2V", avatar_code="BOS_F_MAYA"))
    assert t2v == {"scene_context": "kitchen morning light", "avatar_code": "BOS_F_MAYA"}

    i2v = rot.visual_key_for_plan(_plan(
        "I2V", character_asset_id="ca_1", scene_asset_id="ca_2", style_asset_id="ca_3",
    ))
    assert i2v["character_asset_id"] == "ca_1"
    assert i2v["scene_asset_id"] == "ca_2"
    assert i2v["style_asset_id"] == "ca_3"

    f2v = rot.visual_key_for_plan(_plan("F2V", finished_frame_asset_id="ca_frame"))
    assert f2v["finished_frame_asset_id"] == "ca_frame"


def test_script_key_precedence_copy_set_then_dialogue_then_hook():
    # Library lineage is the strongest identity — beats everything.
    assert rot.script_key_for_plan(
        _plan(copy_set_id="cs_07"), dialogue_fingerprint="dfp"
    ) == "copy_set:cs_07"
    # Angle-based items: post-compile the REAL script is the dialogue
    # (DIFF_DIALOGUE strategies diverge dialogue from the same angle).
    assert rot.script_key_for_plan(
        _plan(), dialogue_fingerprint="dfp"
    ) == "dialogue:dfp"
    # Pre-compile fallback: normalized hook text.
    assert rot.script_key_for_plan(
        _plan(hook_override="  Jangan   BELI sebelum tengok ni ")
    ) == "hook:jangan beli sebelum tengok ni"


# ── Ledger record/check (crud monkeypatched) ──────────────────────────────


@pytest.mark.asyncio
async def test_record_and_duplicate_refusal(monkeypatch):
    ledger: dict[str, dict] = {}

    async def create_content_combination(**kw):
        fp = kw["combination_fingerprint"]
        if fp in ledger:
            return None  # UNIQUE index refusal contract
        ledger[fp] = {"combination_id": "cc_1", **kw}
        return ledger[fp]

    async def get_by_fp(fp):
        return ledger.get(fp)

    monkeypatch.setattr(rot.crud, "create_content_combination", create_content_combination)
    monkeypatch.setattr(rot.crud, "get_content_combination_by_fingerprint", get_by_fp)

    plan = _plan(avatar_code="BOS_F_MAYA", copy_set_id="cs_01")
    fp = rot.plan_combination_fingerprint(PID, plan)
    assert await rot.combination_already_used(fp) is False

    row = await rot.record_combination(
        product_id=PID, logical_mode="T2V", plan=plan, fingerprint=fp,
        workspace_generation_package_id="wgp_1", batch_run_id="bgr_1",
    )
    assert row is not None
    assert row["copy_set_id"] == "cs_01"
    assert row["script_key"] == "copy_set:cs_01"

    assert await rot.combination_already_used(fp) is True
    dup = await rot.record_combination(
        product_id=PID, logical_mode="T2V", plan=plan, fingerprint=fp,
    )
    assert dup is None


# ── Planner: copy_set_ids rotate aligned with hooks ───────────────────────


def test_planner_copy_set_ids_stay_paired_with_hooks():
    hooks = ["hook A", "hook B", "hook C"]
    cs_ids = ["cs_a", "cs_b", "cs_c"]
    items = planner.plan_batch_items(
        logical_mode="T2V",
        variation_strategy="DIFF_SCRIPT_DIFF_VISUALS",
        quantity=7,
        product_id=PID,
        avatar_codes=["AV1", "AV2"],
        hook_angles=hooks,
        copy_set_ids=cs_ids,
    )
    pair = dict(zip(hooks, cs_ids))
    for item in items:
        assert item["copy_set_id"] == pair[item["hook_override"]]


def test_planner_same_script_pins_first_copy_set():
    items = planner.plan_batch_items(
        logical_mode="T2V",
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=4,
        product_id=PID,
        avatar_codes=["AV1", "AV2", "AV3"],
        hook_angles=["hook A", "hook B"],
        copy_set_ids=["cs_a", "cs_b"],
    )
    assert all(i["hook_override"] == "hook A" for i in items)
    assert all(i["copy_set_id"] == "cs_a" for i in items)


def test_planner_without_library_sets_copy_set_id_none():
    items = planner.plan_batch_items(
        logical_mode="T2V",
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=2,
        product_id=PID,
        avatar_codes=["AV1"],
        hook_angles=["hook A"],
    )
    assert all(i["copy_set_id"] is None for i in items)


# ── Batch script source resolution (library-first) ────────────────────────


@pytest.mark.asyncio
async def test_batch_resolver_prefers_library_then_claim_safe(monkeypatch):
    from agent.services import workspace_generation_package_service as wgps

    async def select_ok(product_id, count):
        return {
            "items": [
                {"copy_set_id": "cs_01", "hook": "hook satu"},
                {"copy_set_id": "cs_02", "hook": "hook dua"},
                {"copy_set_id": "cs_01", "hook": "hook satu"},  # wrap repeat
            ],
            "pool_size": 2,
            "warnings": [],
        }

    async def select_empty(product_id, count):
        return {"items": [], "pool_size": 0,
                "warnings": ["NO_APPROVED_COPY_AVAILABLE:generate_and_approve_scripts_first"]}

    captured = {}

    async def fake_plan(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(rot, "select_rotation_copy_sets", select_ok)

    # The resolver lives inline in start_batch_prompt_run; drive it through a
    # minimal call that stops right after planning by stubbing the planner.
    import agent.services.batch_prompt_planner as bpp
    monkeypatch.setattr(bpp, "validate_mode_inputs", lambda *a, **k: [])

    def plan_capture(**kw):
        captured.update(kw)
        raise RuntimeError("STOP_AFTER_PLAN")
    monkeypatch.setattr(bpp, "plan_batch_items", plan_capture)

    async def get_product(pid):
        return {"id": pid, "claim_safe_copy_payload": '{"safe_hook_angles": ["angle X"]}'}
    monkeypatch.setattr(wgps.crud, "get_product", get_product)

    with pytest.raises(RuntimeError, match="STOP_AFTER_PLAN"):
        await wgps.start_batch_prompt_run(
            product_id=PID, logical_mode="T2V", quantity=3,
            avatar_codes=["AV1"],
        )
    # Library won: hooks from copy sets, lineage aligned, wrap repeat deduped.
    assert captured["hook_angles"] == ["hook satu", "hook dua"]
    assert captured["copy_set_ids"] == ["cs_01", "cs_02"]

    captured.clear()
    monkeypatch.setattr(rot, "select_rotation_copy_sets", select_empty)
    with pytest.raises(RuntimeError, match="STOP_AFTER_PLAN"):
        await wgps.start_batch_prompt_run(
            product_id=PID, logical_mode="T2V", quantity=3,
            avatar_codes=["AV1"],
        )
    # Empty library -> legacy claim-safe fallback, no lineage.
    assert captured["hook_angles"] == ["angle X"]
    assert captured["copy_set_ids"] == []


# ── End-to-end loop (real test DB): usage wiring + re-run refusal ─────────


async def _wait_for_run(crud_mod, batch_run_id, timeout=10.0):
    import asyncio
    waited = 0.0
    while waited < timeout:
        run = await crud_mod.get_batch_generation_run(batch_run_id)
        if run and run["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return run
        await asyncio.sleep(0.05)
        waited += 0.05
    raise AssertionError("batch prompt run did not finish in time")


@pytest.mark.asyncio
async def test_library_batch_records_usage_and_refuses_identical_rerun(monkeypatch):
    """The mathematical guarantee end-to-end: a library-scripted batch burns
    its combinations + script usage; re-running the identical batch config is
    refused item-by-item (COMBINATION_ALREADY_USED), never silently repeated.
    """
    from agent.db import crud
    from agent.services import workspace_generation_package_service as svc

    pid = "prod-combo-e2e"
    from agent.db.schema import get_db
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO product (id, raw_product_title, product_display_name,"
        " product_short_name, image_url) VALUES (?,?,?,?,?)",
        (pid, "Combo E2E", "Combo E2E", "CE", "http://example.com/p.jpg"),
    )
    await db.commit()

    cs_rows = []
    for i in (1, 2):
        cs_rows.append(await crud.create_copy_set(
            pid,
            angle=f"angle {i}", hook=f"hook e2e {i}", subhook="",
            usp_set_json="[]", cta="beli", platform="TIKTOK", language="BM_MS",
            route_type="DIRECT", formula_family="HSO",
            status="COPY_APPROVED", dedupe_key=f"ded-e2e-{i}",
        ))

    import uuid as _uuid

    async def stub_creator(*, product_id, generation_mode, batch_run_id, **kwargs):
        wgp_id = f"wgp_stub_{_uuid.uuid4().hex[:10]}"
        hook = kwargs.get("copy_intelligence", {}).get("hook", "")
        return await crud.create_workspace_generation_package(
            wgp_id, mode="T2V", product_id=product_id,
            product_name_snapshot="Combo E2E", source_lane="T2V",
            prompt_package_snapshot_id="snap", workspace_execution_package_id=None,
            generation_mode=generation_mode,
            final_prompt_text=(
                f"SECTION 6 - SPOKEN DIALOGUE\n{hook} via {kwargs.get('avatar_id')}"
            ),
            prompt_blocks_json="[]", selected_assets_json="{}",
            resolved_engine_slots_json="{}", resolver_output_json="{}",
            image_assets_json="{}", manual_handoff_json="{}",
            dom_handoff_payload_json="{}", blockers_json="[]",
            warnings_json="[]", status="READY_MANUAL", batch_run_id=batch_run_id,
        )

    monkeypatch.setitem(svc._MODE_CREATORS, "T2V", stub_creator)

    run1 = await svc.start_batch_prompt_run(
        product_id=pid, logical_mode="T2V", quantity=2,
        interval_seconds=0, avatar_codes=["BOS_A", "BOS_B"],
    )
    cfg1 = __import__("json").loads(run1["config_json"])
    assert cfg1["copy_source"] == "SCRIPT_LIBRARY"
    assert sorted(cfg1["copy_set_ids"]) == sorted(r["copy_set_id"] for r in cs_rows)

    final1 = await _wait_for_run(crud, run1["batch_run_id"])
    assert final1["status"] == "COMPLETED"
    assert final1["total_completed"] == 2 and final1["total_failed"] == 0

    # Usage wired: each script burned exactly one reuse.
    for r in cs_rows:
        row = await crud.get_copy_set(r["copy_set_id"])
        assert row["usage_count"] == 1
        assert row["last_used_at"]

    combos = await crud.list_content_combinations_for_product(pid)
    assert len(combos) == 2
    assert all(c["script_key"].startswith("copy_set:") for c in combos)
    assert all(c["batch_run_id"] == run1["batch_run_id"] for c in combos)

    # Identical re-run: every item is the same (script x avatar x scene)
    # combination — refused pre-create, and NO extra usage is burned.
    run2 = await svc.start_batch_prompt_run(
        product_id=pid, logical_mode="T2V", quantity=2,
        interval_seconds=0, avatar_codes=["BOS_A", "BOS_B"],
    )
    final2 = await _wait_for_run(crud, run2["batch_run_id"])
    assert final2["total_completed"] == 0 and final2["total_failed"] == 2
    errors = __import__("json").loads(final2["error_log_json"])
    assert all("COMBINATION_ALREADY_USED" in e for e in errors)
    for r in cs_rows:
        row = await crud.get_copy_set(r["copy_set_id"])
        assert row["usage_count"] == 1  # unchanged — refusal burns nothing
    assert len(await crud.list_content_combinations_for_product(pid)) == 2
