"""Contracts for the Batch Prompt runner (start_batch_prompt_run).

Uses a stubbed creator in _MODE_CREATORS so the runner mechanics — mode law,
qty expansion, fingerprint annotation, anti-redundancy blocking — are proven
without the full compiler/product-approval stack (covered by its own suites).
"""
import asyncio
import json

import pytest

from agent.db import crud
from agent.services import workspace_generation_package_service as svc


async def _seed_product(product_id="prod-bp", with_image=True):
    from agent.db.schema import get_db
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO product (id, raw_product_title, product_display_name, "
        "product_short_name, image_url) VALUES (?,?,?,?,?)",
        (product_id, "BP Test", "BP Test", "BP",
         "http://example.com/p.jpg" if with_image else None),
    )
    await db.commit()


def _stub_creator(prompt_for_plan):
    """Fake mode creator: writes a REAL wgp row (so annotation updates work)."""
    import uuid as _uuid
    counter = {"n": 0}

    async def _create(*, product_id, generation_mode, batch_run_id, **kwargs):
        counter["n"] += 1
        wgp_id = f"wgp_stub_{_uuid.uuid4().hex[:10]}"
        prompt = prompt_for_plan(kwargs, counter["n"])
        return await crud.create_workspace_generation_package(
            wgp_id,
            mode="T2V",
            product_id=product_id,
            product_name_snapshot="BP Test",
            source_lane="T2V",
            prompt_package_snapshot_id="snap",
            workspace_execution_package_id=None,
            generation_mode=generation_mode,
            final_prompt_text=prompt,
            prompt_blocks_json="[]",
            selected_assets_json="{}",
            resolved_engine_slots_json="{}",
            resolver_output_json="{}",
            image_assets_json="{}",
            manual_handoff_json="{}",
            dom_handoff_payload_json="{}",
            blockers_json="[]",
            warnings_json="[]",
            status="READY_MANUAL",
            batch_run_id=batch_run_id,
        )

    return _create


async def _wait_for_run(batch_run_id, timeout=10.0):
    waited = 0.0
    while waited < timeout:
        run = await crud.get_batch_generation_run(batch_run_id)
        if run and run["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return run
        await asyncio.sleep(0.05)
        waited += 0.05
    raise AssertionError("batch prompt run did not finish in time")


async def test_mixed_or_unknown_mode_is_rejected_fail_closed():
    await _seed_product()
    with pytest.raises(ValueError, match="MODE_CONTRACT_VIOLATION"):
        await svc.start_batch_prompt_run(
            product_id="prod-bp", logical_mode="IMG", quantity=2,
        )


async def test_t2v_with_image_slots_is_rejected():
    await _seed_product()
    with pytest.raises(ValueError, match="T2V_FORBIDS_IMAGE_SLOTS"):
        await svc.start_batch_prompt_run(
            product_id="prod-bp", logical_mode="T2V", quantity=2,
            character_asset_ids=["a1"],
        )


async def test_f2v_without_finished_frame_is_rejected():
    await _seed_product()
    with pytest.raises(ValueError, match="F2V_REQUIRES_FINISHED_FRAME"):
        await svc.start_batch_prompt_run(
            product_id="prod-bp", logical_mode="F2V", quantity=2,
        )


async def test_hybrid_without_product_anchor_is_rejected():
    await _seed_product(product_id="prod-noimg", with_image=False)
    with pytest.raises(ValueError, match="HYBRID_REQUIRES_PRODUCT_ANCHOR"):
        await svc.start_batch_prompt_run(
            product_id="prod-noimg", logical_mode="HYBRID", quantity=2,
        )


async def test_i2v_without_avatar_reference_is_rejected():
    await _seed_product()
    with pytest.raises(ValueError, match="I2V_REQUIRES_AVATAR_REFERENCE"):
        await svc.start_batch_prompt_run(
            product_id="prod-bp", logical_mode="I2V", quantity=2,
        )


async def test_qty_5_creates_5_annotated_prompt_items(monkeypatch):
    await _seed_product()
    # Distinct prompt per hook/avatar → no redundancy collisions.
    stub = _stub_creator(
        lambda kwargs, n: (
            "SECTION 1 - ROLE\nrole\n"
            f"SECTION 6 - SPOKEN DIALOGUE\n{kwargs.get('copy_intelligence', {}).get('hook', '')} "
            f"variant {kwargs.get('avatar_id')} {n}\nSECTION 7 - VOICE\nv"
        )
    )
    monkeypatch.setitem(svc._MODE_CREATORS, "T2V", stub)

    run = await svc.start_batch_prompt_run(
        product_id="prod-bp", logical_mode="T2V", quantity=5,
        interval_seconds=0,
        avatar_codes=["BOS_A", "BOS_B", "BOS_C"],
        hook_angles=["hook satu", "hook dua", "hook tiga"],
    )
    assert run["logical_mode"] == "T2V"
    assert run["total_expected"] == 5
    final = await _wait_for_run(run["batch_run_id"])
    assert final["status"] == "COMPLETED"
    assert final["total_completed"] == 5
    assert final["total_failed"] == 0

    packages = await crud.list_workspace_generation_packages(
        batch_run_id=run["batch_run_id"], limit=50,
    )
    assert len(packages) == 5
    for pkg in packages:
        assert pkg["logical_mode"] == "T2V"
        assert pkg["variation_strategy"] == "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS"
        assert pkg["prompt_fingerprint"]
        fps = json.loads(pkg["variation_fingerprints_json"])
        assert fps["dialogue_fingerprint"]
        assert fps["avatar_fingerprint"]
        assert (pkg["production_status"] or "NONE") == "NONE"  # prompt only — nothing sent
    # 5 distinct polished prompts — no duplicate fingerprints.
    assert len({p["prompt_fingerprint"] for p in packages}) == 5


async def test_identical_compiles_are_hard_blocked_not_duplicated(monkeypatch):
    await _seed_product()
    stub = _stub_creator(lambda kwargs, n: "SECTION 6 - SPOKEN DIALOGUE\nsame text")
    monkeypatch.setitem(svc._MODE_CREATORS, "T2V", stub)

    run = await svc.start_batch_prompt_run(
        product_id="prod-bp", logical_mode="T2V", quantity=3, interval_seconds=0,
    )
    final = await _wait_for_run(run["batch_run_id"])
    assert final["total_completed"] == 1  # first item accepted
    assert final["total_failed"] == 2  # duplicates blocked, not silently stored

    packages = await crud.list_workspace_generation_packages(
        batch_run_id=run["batch_run_id"], limit=50,
    )
    blocked = [p for p in packages if p["status"] == "BLOCKED"]
    assert len(blocked) == 2
    for pkg in blocked:
        anti = json.loads(pkg["anti_redundancy_json"])
        assert "DUPLICATE_PROMPT_FINGERPRINT_IN_BATCH" in anti["hard_blocks"]
