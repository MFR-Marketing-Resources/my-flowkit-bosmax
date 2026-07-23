"""Stage-1 RPA Studio quantity PREVIEW — credit-free, fail-closed dialogue uniqueness.

The preview plans + compiles N items purely to show the operator the planned
copy/dialogue variants. It MUST: spend no credit, call no provider/Flow, write no
DB, and BLOCK (not warn) when any two items share dialogue (the pool<N reuse case).
Live bulk fan-out stays Stage 2 (unbuilt) — nothing here fires or enqueues.

Compilation + rotation are monkeypatched so the test is hermetic (no DB/compile):
this isolates the orchestration + the fail-closed uniqueness contract.
"""
import asyncio

import pytest

from agent.services import copy_rotation_service
from agent.services import workspace_execution_package_service as wxp
from agent.services import workspace_generation_package_service as svc


def _fake_rotation(items, warnings=None):
    async def _rotate(product_id, count):
        return {"items": list(items), "warnings": list(warnings or [])}
    return _rotate


def _fake_pool(items):
    async def _list(product_id):
        return list(items)
    return _list


def _fake_compile(dialogue_by_copy_set, *, extend=False, counter=None):
    async def _compile(**kw):
        if counter is not None:
            counter.append(kw)
        cs = kw.get("copy_set_id")
        dialogue = dialogue_by_copy_set.get(cs, f"fallback dialogue {cs}")
        if extend:
            return {
                "final_compiled_prompt_text": f"SECTION 6\n{dialogue}\nSECTION 7",
                "prompt_blocks": [
                    {"exact_dialogue_slice": dialogue,
                     "audio_seam_contract": {"outgoing_dialogue_deadline_s": 7.22,
                                             "seam_outgoing_margin_s": 0.78}},
                    {"exact_dialogue_slice": dialogue + " tail",
                     "audio_seam_contract": {"incoming_new_dialogue_onset_floor_s": 8.5,
                                             "seam_incoming_margin_s": 0.5,
                                             "voice_continuity_required": True,
                                             "voice_profile_lock": "REUSE_PREVIOUS_BLOCK_SPEAKER_VOICE_EXACTLY"}},
                ],
            }
        return {
            "final_compiled_prompt_text": f"SECTION 6\n{dialogue}\nSECTION 7",
            "prompt_blocks": [{"exact_dialogue_slice": dialogue, "audio_seam_contract": {}}],
        }
    return _compile


# ── pure fail-closed evaluator ───────────────────────────────────────────────
def test_uniqueness_evaluator_passes_distinct():
    items = [
        {"item_index": 0, "dialogue_fingerprint": "a", "dialogue_summary": "one"},
        {"item_index": 1, "dialogue_fingerprint": "b", "dialogue_summary": "two"},
        {"item_index": 2, "dialogue_fingerprint": "c", "dialogue_summary": "three"},
    ]
    v = svc._evaluate_preview_uniqueness(items)
    assert v["status"] == "UNIQUE"
    assert v["blockers"] == []


def test_uniqueness_evaluator_blocks_duplicate_dialogue():
    items = [
        {"item_index": 0, "dialogue_fingerprint": "same", "dialogue_summary": "x"},
        {"item_index": 1, "dialogue_fingerprint": "same", "dialogue_summary": "x"},
        {"item_index": 2, "dialogue_fingerprint": "c", "dialogue_summary": "y"},
    ]
    v = svc._evaluate_preview_uniqueness(items)
    assert v["status"] == "DUPLICATE_DIALOGUE_BLOCKED"
    assert v["duplicate_groups"] == [[0, 1]]
    assert any(b.startswith("DUPLICATE_DIALOGUE_ACROSS_ITEMS:0,1") for b in v["blockers"])


def test_uniqueness_evaluator_blocks_empty_or_failed():
    items = [
        {"item_index": 0, "dialogue_fingerprint": None, "dialogue_summary": ""},
        {"item_index": 1, "compile_error": "ValueError:boom"},
    ]
    v = svc._evaluate_preview_uniqueness(items)
    assert v["status"] == "DUPLICATE_DIALOGUE_BLOCKED"
    assert any("ITEM_0_EMPTY_DIALOGUE" in b for b in v["blockers"])
    assert any("ITEM_1_COMPILE_FAILED" in b for b in v["blockers"])


# ── end-to-end preview (hermetic) ────────────────────────────────────────────
def test_preview_unique_copy_passes_credit_free(monkeypatch):
    rows = [{"copy_set_id": f"cs{i}", "hook": f"hook {i}"} for i in range(3)]
    monkeypatch.setattr(copy_rotation_service, "select_rotation_copy_sets", _fake_rotation(rows))
    calls: list = []
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview",
        _fake_compile({"cs0": "aaa", "cs1": "bbb", "cs2": "ccc"}, counter=calls))

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="T2V", source_mode="T2V", quantity=3))

    assert out["quantity_requested"] == 3
    assert out["planned_item_count"] == 3
    assert out["dialogue_uniqueness_status"] == "UNIQUE"
    assert out["preview_ready"] is True
    assert out["blockers"] == []
    # credit-free contract
    assert out["credit"] == "NONE" and out["provider_calls"] == 0 and out["flow_calls"] == 0
    # exactly N credit-free compiles, nothing else
    assert len(calls) == 3
    # each item carries a distinct fingerprint + a variant id
    fps = {it["dialogue_fingerprint"] for it in out["items"]}
    assert len(fps) == 3
    # seeded rotation may offset the order; every distinct copy set must appear once
    assert {it["copy_variant_id"] for it in out["items"]} == {"cs0", "cs1", "cs2"}
    assert out["live_bulk_status"] == "Bulk live fan-out not certified yet"


def test_hybrid_preview_compiles_as_f2v_with_hybrid_lineage(monkeypatch):
    """Logical HYBRID preview must not pass an unsupported mode to the compiler."""
    rows = [{"copy_set_id": f"cs{i}", "hook": f"hook {i}"} for i in range(3)]
    calls: list[dict] = []

    async def _unused(combo_fingerprint):
        return False

    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(rows))
    monkeypatch.setattr(copy_rotation_service, "combination_already_used", _unused)
    monkeypatch.setattr(
        wxp,
        "compile_workspace_prompt_preview",
        _fake_compile({"cs0": "aaa", "cs1": "bbb", "cs2": "ccc"}, counter=calls),
    )

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="HYBRID", source_mode="HYBRID", quantity=3))

    assert out["preview_ready"] is True
    assert all(call["mode"] == "F2V" for call in calls)
    assert all(call["source_mode"] == "HYBRID" for call in calls)


def test_preview_duplicate_dialogue_blocks(monkeypatch):
    rows = [{"copy_set_id": f"cs{i}", "hook": f"hook {i}"} for i in range(3)]
    monkeypatch.setattr(copy_rotation_service, "select_rotation_copy_sets", _fake_rotation(rows))
    # cs0 and cs2 resolve to the SAME dialogue -> must block
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview",
        _fake_compile({"cs0": "identical", "cs1": "different", "cs2": "identical"}))

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="T2V", quantity=3))

    assert out["dialogue_uniqueness_status"] == "DUPLICATE_DIALOGUE_BLOCKED"
    assert out["preview_ready"] is False
    assert any(b.startswith("DUPLICATE_DIALOGUE_ACROSS_ITEMS") for b in out["blockers"])
    assert out["provider_calls"] == 0


def test_preview_pool_smaller_than_quantity_blocks(monkeypatch):
    # Only ONE approved copy set for a request of 3 -> rotation wraps + warns; the
    # wrap forces duplicate dialogue, which must FAIL CLOSED (not warn-only).
    rows = [{"copy_set_id": "cs0", "hook": "only hook"}]
    monkeypatch.setattr(
        copy_rotation_service, "select_rotation_copy_sets",
        _fake_rotation(rows, warnings=["POOL_SMALLER_THAN_BATCH:1<3:scripts_repeat_with_different_visuals"]))
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview", _fake_compile({"cs0": "the only script"}))

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="T2V", quantity=3))

    assert out["dialogue_uniqueness_status"] == "DUPLICATE_DIALOGUE_BLOCKED"
    assert out["preview_ready"] is False
    assert any(b.startswith("APPROVED_COPY_POOL_SMALLER_THAN_QUANTITY") for b in out["blockers"])


def test_preview_quantity_one_is_trivially_unique(monkeypatch):
    monkeypatch.setattr(
        copy_rotation_service, "select_rotation_copy_sets",
        _fake_rotation([{"copy_set_id": "cs0", "hook": "h"}]))
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview", _fake_compile({"cs0": "solo dialogue"}))

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="T2V", quantity=1))
    assert out["planned_item_count"] == 1
    assert out["dialogue_uniqueness_status"] == "UNIQUE"
    assert out["preview_ready"] is True


@pytest.mark.parametrize("bad", [0, -1, 6, 99])
def test_preview_quantity_out_of_range_fails_closed(bad):
    with pytest.raises(ValueError) as ei:
        asyncio.run(svc.preview_quantity_copy_plans(
            product_id="P", logical_mode="T2V", quantity=bad))
    assert "QUANTITY_OUT_OF_RANGE" in str(ei.value)


def test_preview_extend_preserves_seam_voice_contract(monkeypatch):
    rows = [{"copy_set_id": f"cs{i}", "hook": f"hook {i}"} for i in range(2)]
    monkeypatch.setattr(copy_rotation_service, "select_rotation_copy_sets", _fake_rotation(rows))
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview",
        _fake_compile({"cs0": "extend one", "cs1": "extend two"}, extend=True))

    out = asyncio.run(svc.preview_quantity_copy_plans(
        product_id="P", logical_mode="T2V", source_mode="T2V",
        generation_mode="EXTEND", requested_total_duration_seconds=16, quantity=2))

    assert out["dialogue_uniqueness_status"] == "UNIQUE"
    for it in out["items"]:
        sv = it["seam_voice"]
        assert sv is not None
        assert sv["voice_profile_lock"] == "REUSE_PREVIOUS_BLOCK_SPEAKER_VOICE_EXACTLY"
        assert sv["voice_continuity_required"] is True
        assert sv["outgoing_dialogue_deadline_s"] == 7.22
        assert sv["seam_incoming_margin_s"] == 0.5
