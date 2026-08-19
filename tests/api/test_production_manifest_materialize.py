"""Provider-free proof that a materialized Approved Generation Manifest item
hash-MATCHES the production-queue dispatch it authorises.

The whole point of the queue/studio/bulk materialize paths is the WYSIWYG
invariant at the credit boundary:

    approved_execution_envelope_sha256 == dispatched_execution_envelope_sha256

So these tests seed a real production package + run, materialize the manifest via
``build_package_manifest_item`` + ``execution_approval_service.create_manifest``,
and prove parity two ways:

  1. Pure hashing — the frozen item's execution envelope equals the envelope the
     queue dispatch (``_fire_and_wait_inner`` -> ``start_generate``) recomputes.
  2. End-to-end at the dispatch boundary — BEFORE approval the same dispatch is
     REJECTED (DISPATCH_NOT_APPROVED, fail-closed under enforcement); AFTER human
     approval it resolves the item by envelope hash and is SUBMITTED.

IMG is not a production-queue engine mode (planner.ENGINE_MODES has no IMG), so
the queue path is exercised with a text-only T2V package — the simplest mode that
carries no image slots. Each test uses a UNIQUE prompt (hence a unique envelope)
so a lingering approval from another test can never satisfy this one's check
(see conftest._unlink_db_safe, which tolerates Windows WinError 32).
"""

from __future__ import annotations

import json

from agent.db import crud
from agent.services import execution_approval_service as eas
from agent.services import production_queue_service as pq


_MODEL = "veo_3_1_lite"  # resolves in video_models; 8s cost is defined (=10)


async def _seed_queue_package(
    *, wgp_id: str, run_id: str, prompt: str,
    model: str = _MODEL, aspect: str = "9:16", count: int = 1, duration_s: int = 8,
) -> None:
    """Seed a minimal, dispatchable T2V package + its production run (whose
    config_json IS the run_config the queue dispatch feeds build_execution_payload)."""
    await crud.create_production_run(
        run_id,
        config_json=json.dumps({"model": model, "aspect": aspect, "count": count}),
    )
    await crud.create_workspace_generation_package(
        wgp_id,
        mode="T2V",
        product_id="prod_mat_1",
        product_name_snapshot="Test Product",
        source_lane="T2V",
        prompt_package_snapshot_id="snap_mat_1",
        workspace_execution_package_id=None,
        generation_mode="SINGLE",
        final_prompt_text=prompt,
        prompt_blocks_json="[]",
        selected_assets_json="{}",
        resolved_engine_slots_json="{}",
        resolver_output_json="{}",
        image_assets_json="{}",
        manual_handoff_json="{}",
        dom_handoff_payload_json=json.dumps({"settings": {"duration_seconds": duration_s}}),
        blockers_json="[]",
        warnings_json="[]",
        status="READY_MANUAL",
    )
    # production_run_id is set post-creation (as the send-to-production flow does).
    await crud.update_workspace_generation_package(wgp_id, production_run_id=run_id)


async def _dispatch_params(wgp_id: str, run_id: str) -> dict:
    """The exact params build_execution_payload feeds start_generate for this
    package on the queue lane (_fire_and_wait_inner)."""
    pkg = await crud.get_workspace_generation_package(wgp_id)
    run = await crud.get_production_run(run_id)
    payload, blockers = await pq.build_execution_payload(pkg, json.loads(run["config_json"]))
    assert blockers == [], blockers
    return payload


async def test_build_item_envelope_equals_queue_dispatch_envelope():
    """Pure hash parity: the frozen manifest item and the queue dispatch produce
    the SAME execution-envelope sha256 (no product_id / source_mode / image_model;
    asset_fingerprints=[] because a manifest dispatch binds no volatile media)."""
    prompt = "MAT_hash_1 a clean provider-ready T2V prompt for parity"
    wgp_id, run_id = "wgp_mat_hash_1", "prun_mat_hash_1"
    await _seed_queue_package(wgp_id=wgp_id, run_id=run_id, prompt=prompt)

    item = await pq.build_package_manifest_item(wgp_id)
    assert item == {
        "item_key": wgp_id,
        "mode": "T2V",
        "final_prompt_text": prompt,
        "model": _MODEL,
        "aspect": "9:16",
        "duration_s": 8,
        "count": 1,
    }

    # The manifest freezes the item exactly as create_review_snapshot would
    # (every unset provider field -> None; assets -> []).
    frozen = eas.compute_dispatch_identity(
        mode=item["mode"], final_prompt_text=item["final_prompt_text"],
        model=item["model"], aspect=item["aspect"], duration_s=item["duration_s"],
        count=item["count"],
    )
    # The queue dispatch recomputes with _gate_assets=[] and no product/source/image_model.
    payload = await _dispatch_params(wgp_id, run_id)
    dispatched = eas.compute_dispatch_identity(
        mode=payload["mode"], final_prompt_text=payload["prompt"], source_mode=None,
        model=payload.get("model"), aspect=payload.get("aspect") or "9:16",
        duration_s=payload.get("duration_s"), count=payload.get("num_videos") or 1,
        image_model=None, asset_media_ids=[], product_id=None,
    )
    assert frozen["execution_envelope_sha256"] == dispatched["execution_envelope_sha256"]


async def test_queue_materialized_manifest_authorises_dispatch_only_after_approval(monkeypatch):
    """End-to-end at the real dispatch boundary: before approval the queue dispatch
    fails closed; after human approval the materialized item resolves by hash."""
    import asyncio

    from agent.services import make_video

    prompt = "MAT_e2e_1 a clean provider-ready T2V prompt end to end"
    wgp_id, run_id = "wgp_mat_e2e_1", "prun_mat_e2e_1"
    await _seed_queue_package(wgp_id=wgp_id, run_id=run_id, prompt=prompt)

    # Materialize the 1-item manifest (run_ref == wgp_id == queue lookup key).
    item = await pq.build_package_manifest_item(wgp_id)
    manifest = await eas.create_manifest(
        surface="production_queue", run_ref=wgp_id, items=[item], created_by="operator",
    )
    manifest_id = manifest["manifest_id"]
    assert manifest["state"] == "REVIEW_REQUIRED"

    payload = await _dispatch_params(wgp_id, run_id)

    eas._DISPATCH_AUTH.set(None)
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")

    async def _noop(*_a, **_k):
        return None

    # Keep every provider lane inert — the gate runs before any lane/provider work.
    monkeypatch.setattr(make_video, "_run_generate", _noop)
    monkeypatch.setattr(make_video, "_run_generate_direct", _noop)

    async def _dispatch():
        return await make_video.start_generate(
            payload["mode"], payload["prompt"],
            image_media_ids=payload.get("image_media_ids"),
            aspect=payload.get("aspect") or "9:16",
            model=payload.get("model"),
            duration_s=payload.get("duration_s"),
            num_videos=payload.get("num_videos") or 1,
            manifest_id=manifest_id,
        )

    # BEFORE approval: manifest present but REVIEW_REQUIRED -> resolve None ->
    # enforced gate BLOCKS (never auto-approved from the manifest reference).
    monkeypatch.setattr(make_video, "_VIDEO_LANE_JOB", None)
    blocked = await _dispatch()
    assert blocked["status"] == "REJECTED", blocked
    assert blocked["error"] == "DISPATCH_NOT_APPROVED", blocked

    # AFTER human approval: the exact item resolves by envelope hash -> SUBMITTED.
    await eas.approve_manifest(manifest_id, approved_by="faris")
    monkeypatch.setattr(make_video, "_VIDEO_LANE_JOB", None)
    ok = await _dispatch()
    await asyncio.sleep(0)
    assert ok["status"] == "SUBMITTED", ok
    # The resolved snapshot is bound single-use (DISPATCHED).
    dispatched_items = (await eas.get_manifest_with_items(manifest_id))["items"]
    assert any(i["approval_state"] == "DISPATCHED" for i in dispatched_items)
