"""B-12 — bulk quantity planning must be ledger-aware.

A copy variant's dialogue is a pure function of (product, lane, copy set) —
``variation_salt`` does NOT diverge it — so once a variant's dialogue is in the
``content_combination`` ledger for a lane, prepare will refuse it forever on
that lane. Before B-12, ``preview_quantity_copy_plans`` selected blindly by
rotation order, so a burned variant at the head of the pool produced plans the
prepare gate was GUARANTEED to reject: plan said READY/UNIQUE/authorizable,
prepare 409'd ``BULK_DUPLICATE_COMBINATION`` — a closed loop (live proof
2026-07-21, product 6483d624, variant 4191ad3f/fp 425b3f0b).

These tests pin the corrected contract:
  * a burned candidate is SKIPPED (with a visible warning) and the next
    rotation candidate takes its place;
  * the emitted plan only contains dialogue whose bulk combination fingerprint
    is absent from the ledger — i.e. exactly what prepare will accept;
  * fewer than N fresh variants is a HARD blocker (DIALOGUE_POOL_EXHAUSTED),
    never a silent shrink;
  * a candidate that fails to compile is excluded fail-closed but does not
    block the healthy remainder of the pool;
  * the ledger check uses the SAME fingerprint recipe as the prepare gate.

Everything is faked — no provider, no Flow, no DB, no credit.
"""
import asyncio
import hashlib

import pytest

from agent.services import workspace_generation_package_service as wgps


def _pool_row(cs_id: str, hook: str = "hook"):
    return {"copy_set_id": cs_id, "hook": hook, "status": "COPY_APPROVED"}


def _fake_compiled(dialogue: str) -> dict:
    # Shape consumed by _preview_dialogue_text: the per-block exact dialogue
    # slice is its second-preference source and the simplest stable one to fake.
    return {"prompt_blocks": [{"exact_dialogue_slice": dialogue}]}


def _fp(dialogue: str) -> str:
    return hashlib.sha1(wgps._norm_dialogue(dialogue).encode("utf-8")).hexdigest()


def _install(monkeypatch, *, pool, dialogues, burned_fps, compile_fail: set[str] = frozenset()):
    """Wire fakes: rotation pool, per-variant dialogue, ledger membership."""
    from agent.services import copy_rotation_service as rot
    from agent.services import workspace_execution_package_service as wxp

    async def _pool(product_id):
        return list(pool)

    async def _compile(**kw):
        cs = kw.get("copy_set_id")
        if cs in compile_fail:
            raise RuntimeError("COMPILE_BOOM")
        return _fake_compiled(dialogues[cs])

    async def _already_used(fp):
        return fp in burned_fps

    monkeypatch.setattr(rot, "list_eligible_copy_sets", _pool)
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", _compile)
    monkeypatch.setattr(rot, "combination_already_used", _already_used)
    return rot


def _bulk_fp(product_id: str, mode: str, dialogue: str):
    from agent.services import copy_rotation_service as rot
    return rot.plan_combination_fingerprint(
        product_id, wgps._bulk_combination_plan(mode, {}), dialogue_fingerprint=_fp(dialogue)
    )


PRODUCT = "prod-b12"


def _preview(**overrides):
    kw = dict(
        product_id=PRODUCT, logical_mode="T2V", quantity=2, duration_seconds=8,
        generation_mode="SINGLE", target_language="BM_MS",
    )
    kw.update(overrides)
    return asyncio.run(wgps.preview_quantity_copy_plans(**kw))


def test_burned_head_of_pool_is_skipped_for_next_fresh_candidate(monkeypatch):
    """The live failure shape: pool head burned, healthy variants behind it."""
    dialogues = {"cs-burned": "dialog A", "cs-fresh1": "dialog B", "cs-fresh2": "dialog C"}
    burned = {_bulk_fp(PRODUCT, "T2V", "dialog A")}
    _install(monkeypatch, pool=[_pool_row("cs-burned"), _pool_row("cs-fresh1"), _pool_row("cs-fresh2")],
             dialogues=dialogues, burned_fps=burned)

    out = _preview()

    chosen = [i["copy_variant_id"] for i in out["items"]]
    assert chosen == ["cs-fresh1", "cs-fresh2"], chosen
    assert out["preview_ready"] is True
    assert any("LEDGER_SKIP:cs-burne" in w for w in out["copy_rotation_warnings"])


def test_plan_only_proposes_what_prepare_would_accept(monkeypatch):
    """Coherence: every emitted fingerprint must be absent from the ledger."""
    dialogues = {"cs-a": "dialog A", "cs-b": "dialog B", "cs-c": "dialog C"}
    burned = {_bulk_fp(PRODUCT, "T2V", "dialog B")}
    _install(monkeypatch, pool=[_pool_row("cs-a"), _pool_row("cs-b"), _pool_row("cs-c")],
             dialogues=dialogues, burned_fps=burned)

    out = _preview()

    for item in out["items"]:
        combo = _bulk_fp(PRODUCT, "T2V", dialogues[item["copy_variant_id"]])
        assert combo not in burned, f"plan proposed burned dialogue {item['copy_variant_id']}"
    assert [i["copy_variant_id"] for i in out["items"]] == ["cs-a", "cs-c"]


def test_all_fresh_pool_unchanged_selection(monkeypatch):
    """No ledger hits -> behaviour identical to rotation-order selection."""
    dialogues = {"cs-a": "dialog A", "cs-b": "dialog B"}
    _install(monkeypatch, pool=[_pool_row("cs-a"), _pool_row("cs-b")],
             dialogues=dialogues, burned_fps=set())

    out = _preview()

    assert [i["copy_variant_id"] for i in out["items"]] == ["cs-a", "cs-b"]
    assert out["preview_ready"] is True
    assert not any(w.startswith("LEDGER_SKIP") for w in out["copy_rotation_warnings"])


def test_exhausted_pool_is_a_hard_blocker_not_a_silent_shrink(monkeypatch):
    dialogues = {"cs-a": "dialog A", "cs-b": "dialog B", "cs-c": "dialog C"}
    burned = {_bulk_fp(PRODUCT, "T2V", d) for d in ("dialog B", "dialog C")}
    _install(monkeypatch, pool=[_pool_row("cs-a"), _pool_row("cs-b"), _pool_row("cs-c")],
             dialogues=dialogues, burned_fps=burned)

    out = _preview()

    assert out["preview_ready"] is False
    assert any(b.startswith("DIALOGUE_POOL_EXHAUSTED:fresh=1<2") for b in out["blockers"]), out["blockers"]
    # The single fresh variant wraps to fill the quantity (pre-existing
    # plan_batch_items behaviour) — and that wrap is ITSELF caught as duplicate
    # dialogue, so the plan is doubly fail-closed, never silently shrunk.
    assert {i["copy_variant_id"] for i in out["items"]} == {"cs-a"}
    assert out["dialogue_uniqueness_status"] != "UNIQUE"


def test_plan_bulk_fanout_intents_refuses_exhausted_plan(monkeypatch):
    """The bulk planner must surface the exhaustion as NOT authorizable."""
    dialogues = {"cs-a": "dialog A"}
    burned = {_bulk_fp(PRODUCT, "T2V", "dialog A")}
    _install(monkeypatch, pool=[_pool_row("cs-a")], dialogues=dialogues, burned_fps=burned)

    plan = asyncio.run(wgps.plan_bulk_fanout_intents(
        product_id=PRODUCT, logical_mode="T2V", quantity=1,
    ))

    assert plan["bulk_authorizable"] is False
    assert any("DIALOGUE_POOL_EXHAUSTED" in b or "PREVIEW_NOT_UNIQUE" in b or "COPY_POOL" in b
               for b in plan["blockers"]), plan["blockers"]


def test_compile_failure_excluded_fail_closed_without_blocking_pool(monkeypatch):
    """A broken variant cannot prove freshness -> skipped with a warning; the
    healthy remainder still fills the quantity."""
    dialogues = {"cs-ok1": "dialog A", "cs-ok2": "dialog B"}
    _install(monkeypatch,
             pool=[_pool_row("cs-broken"), _pool_row("cs-ok1"), _pool_row("cs-ok2")],
             dialogues=dialogues, burned_fps=set(), compile_fail={"cs-broken"})

    out = _preview()

    assert [i["copy_variant_id"] for i in out["items"]] == ["cs-ok1", "cs-ok2"]
    assert out["preview_ready"] is True
    assert any("CANDIDATE_COMPILE_FAILED:cs-broke" in w for w in out["copy_rotation_warnings"])


def test_ledger_check_uses_prepare_fingerprint_recipe(monkeypatch):
    """The filter must call combination_already_used with EXACTLY the
    fingerprint prepare derives — product x logical lane x dialogue fp."""
    seen_fps: list[str] = []
    dialogues = {"cs-a": "dialog A"}
    rot = _install(monkeypatch, pool=[_pool_row("cs-a")], dialogues=dialogues, burned_fps=set())

    async def _spy(fp):
        seen_fps.append(fp)
        return False
    monkeypatch.setattr(rot, "combination_already_used", _spy)

    _preview(quantity=1)

    expected = _bulk_fp(PRODUCT, "T2V", "dialog A")
    assert seen_fps == [expected]


def test_certification_flag_untouched():
    from agent.services import production_queue_service as pq
    assert pq.BULK_LIVE_EXECUTION_CERTIFIED is False
