"""Contracts for the Production Queue service (prompt/production split).

Covers: approval gate, send-to-production transition, execution payload
mapping by logical mode, dry-run safety (nothing fires, no credits), and
the live fire path against a FAKE make_video (never the real lane).
"""
import asyncio
import json

import pytest

from agent.db import crud
from agent.services import production_queue_service as pq

_UUID = "550e8400-e29b-41d4-a716-446655440000"


async def _seed_package(
    wgp_id: str,
    *,
    mode: str = "T2V",
    source_lane: str = "T2V",
    status: str = "READY_MANUAL",
    prompt: str = "SECTION 1 - ROLE & OBJECTIVE\nfinal polished prompt",
    slots: dict | None = None,
) -> dict:
    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id="prod-1",
        product_name_snapshot="Test Product",
        source_lane=source_lane,
        prompt_package_snapshot_id="snap-1",
        workspace_execution_package_id=None,
        generation_mode="SINGLE",
        final_prompt_text=prompt,
        prompt_blocks_json="[]",
        selected_assets_json="{}",
        resolved_engine_slots_json=json.dumps(slots or {}),
        resolver_output_json="{}",
        image_assets_json="{}",
        manual_handoff_json="{}",
        dom_handoff_payload_json="{}",
        blockers_json="[]",
        warnings_json="[]",
        status=status,
    )
    return row


# ── Approval gate ─────────────────────────────────────────────────────────


async def test_ready_manual_package_can_be_approved():
    await _seed_package("wgp_a1")
    result = await pq.approve_packages(["wgp_a1"])
    assert result["approved"] == 1
    row = await crud.get_workspace_generation_package("wgp_a1")
    assert row["production_status"] == "APPROVED"
    assert row["approved_at"]


async def test_blocked_and_draft_packages_are_not_approvable():
    await _seed_package("wgp_b1", status="BLOCKED")
    await _seed_package("wgp_b2", status="DRAFT")
    result = await pq.approve_packages(["wgp_b1", "wgp_b2", "wgp_missing"])
    assert result["approved"] == 0
    errors = {r["package_id"]: r["error"] for r in result["results"]}
    assert errors["wgp_b1"].startswith("NOT_APPROVABLE_STATUS")
    assert errors["wgp_b2"].startswith("NOT_APPROVABLE_STATUS")
    assert errors["wgp_missing"] == "NOT_FOUND"


async def test_package_already_in_production_cannot_be_reapproved():
    await _seed_package("wgp_c1")
    await pq.approve_packages(["wgp_c1"])
    await crud.update_workspace_generation_package("wgp_c1", production_status="QUEUED")
    result = await pq.approve_packages(["wgp_c1"])
    assert result["approved"] == 0
    assert result["results"][0]["error"] == "ALREADY_IN_PRODUCTION:QUEUED"


# ── Send to production ────────────────────────────────────────────────────


async def test_send_to_production_requires_approval():
    await _seed_package("wgp_d1")  # READY_MANUAL but not APPROVED
    with pytest.raises(ValueError, match="NO_APPROVED_PACKAGES"):
        await pq.send_to_production(["wgp_d1"])


async def test_send_to_production_queues_items_and_creates_dry_run():
    await _seed_package("wgp_e1")
    await _seed_package("wgp_e2")
    await pq.approve_packages(["wgp_e1", "wgp_e2"])
    run = await pq.send_to_production(
        ["wgp_e1", "wgp_e2"],
        interval_min_seconds=10, interval_max_seconds=20,
        cooldown_after_n_jobs=2, cooldown_seconds=60,
    )
    assert run["status"] == "PENDING"
    assert run["dry_run"] == 1  # fail-closed default
    assert run["total_expected"] == 2
    assert run["interval_min_seconds"] == 10
    assert run["cooldown_after_n_jobs"] == 2
    for wgp_id in ("wgp_e1", "wgp_e2"):
        row = await crud.get_workspace_generation_package(wgp_id)
        assert row["production_status"] == "QUEUED"
        assert row["production_run_id"] == run["production_run_id"]
        assert row["sent_to_production_at"]


async def test_send_to_production_rejects_bad_interval_range():
    await _seed_package("wgp_f1")
    await pq.approve_packages(["wgp_f1"])
    with pytest.raises(ValueError, match="INVALID_INTERVAL_RANGE"):
        await pq.send_to_production(
            ["wgp_f1"], interval_min_seconds=60, interval_max_seconds=30,
        )


# ── Payload mapping ───────────────────────────────────────────────────────


async def test_t2v_payload_needs_no_media_ids():
    row = await _seed_package("wgp_g1")
    await crud.update_workspace_generation_package("wgp_g1", logical_mode="T2V")
    row = await crud.get_workspace_generation_package("wgp_g1")
    payload, blockers = await pq.build_execution_payload(row, {"aspect": "9:16"})
    assert blockers == []
    assert payload["mode"] == "T2V"
    assert payload["logical_mode"] == "T2V"
    assert payload["execution_lane"] == "TEXT_TO_VIDEO"
    assert payload["image_media_ids"] is None


async def test_hybrid_payload_maps_to_f2v_engine_but_keeps_logical_mode():
    await _seed_package(
        "wgp_h1", mode="F2V", source_lane="HYBRID",
        slots={"start_frame": _UUID},
    )
    await crud.update_workspace_generation_package("wgp_h1", logical_mode="HYBRID")
    row = await crud.get_workspace_generation_package("wgp_h1")
    payload, blockers = await pq.build_execution_payload(row, {})
    assert blockers == []
    assert payload["mode"] == "F2V"  # engine lane
    assert payload["logical_mode"] == "HYBRID"  # never relabelled
    assert payload["execution_lane"] == "PRODUCT_ANCHOR_PRESENTER"
    assert payload["image_media_ids"] == [_UUID]


async def test_legacy_hybrid_source_lane_is_derived_when_logical_mode_missing():
    await _seed_package(
        "wgp_h2", mode="F2V", source_lane="HYBRID", slots={"start_frame": _UUID},
    )
    row = await crud.get_workspace_generation_package("wgp_h2")
    payload, _ = await pq.build_execution_payload(row, {})
    assert payload["logical_mode"] == "HYBRID"


async def test_image_mode_without_flow_media_is_blocked_not_fired():
    await _seed_package(
        "wgp_i1", mode="F2V", source_lane="F2V",
        slots={"start_frame": "product-image:prod-1:start_frame"},
    )
    row = await crud.get_workspace_generation_package("wgp_i1")
    payload, blockers = await pq.build_execution_payload(row, {})
    assert any(b.startswith("SLOT_NOT_UPLOADED_TO_FLOW") for b in blockers)
    assert "NO_FLOW_MEDIA_FOR_IMAGE_MODE" in blockers


async def test_empty_prompt_is_a_payload_blocker():
    await _seed_package("wgp_j1", prompt="")
    row = await crud.get_workspace_generation_package("wgp_j1")
    _, blockers = await pq.build_execution_payload(row, {})
    assert "EMPTY_FINAL_PROMPT" in blockers


# ── Dry run safety ────────────────────────────────────────────────────────


async def test_dry_run_reports_without_firing_or_mutating_items():
    await _seed_package("wgp_k1")
    await crud.update_workspace_generation_package("wgp_k1", logical_mode="T2V")
    await pq.approve_packages(["wgp_k1"])
    run = await pq.send_to_production(["wgp_k1"])
    result = await pq.run_production_queue(run["production_run_id"])
    assert result["dry_run"] is True
    assert result["report"]["checked"] == 1
    assert result["report"]["ready"] == 1
    # Items untouched, run not started, nothing fired.
    row = await crud.get_workspace_generation_package("wgp_k1")
    assert row["production_status"] == "QUEUED"
    run_row = await crud.get_production_run(run["production_run_id"])
    assert run_row["status"] == "PENDING"
    assert run_row["dry_run"] == 1


# ── Live fire path (FAKE engine only) ─────────────────────────────────────


class _FakeMakeVideo:
    """Stands in for make_video — no extension, no Flow, no credits."""

    def __init__(self, final_status="DONE"):
        self.calls = []
        self._final = final_status
        self._job = {
            "job_id": "g_fake123", "status": final_status,
            "media_id": _UUID, "local_path": "C:/tmp/fake.mp4",
            "artifacts": [{"media_id": _UUID}],
            "error": None if final_status == "DONE" else "SOME_ERROR",
        }

    async def start_generate(self, mode, prompt, **kwargs):
        self.calls.append({"mode": mode, "prompt": prompt, **kwargs})
        return {"job_id": "g_fake123", "status": "SUBMITTED"}

    def get_job(self, job_id):
        return dict(self._job)


async def test_fire_and_wait_marks_downloaded_and_links_artifacts():
    await _seed_package("wgp_l1")
    await crud.update_workspace_generation_package("wgp_l1", logical_mode="T2V")
    fake = _FakeMakeVideo("DONE")
    row = await crud.get_workspace_generation_package("wgp_l1")
    payload, blockers = await pq.build_execution_payload(row, {})
    assert not blockers
    outcome = await pq._fire_and_wait(fake, payload, "wgp_l1")
    assert outcome["ok"] is True
    assert fake.calls and fake.calls[0]["mode"] == "T2V"
    row = await crud.get_workspace_generation_package("wgp_l1")
    assert row["production_status"] == "DOWNLOADED"
    assert row["production_job_id"] == "g_fake123"
    assert json.loads(row["artifact_media_ids_json"]) == [_UUID]


async def test_fire_and_wait_marks_failed_on_engine_failure():
    await _seed_package("wgp_m1")
    await crud.update_workspace_generation_package("wgp_m1", logical_mode="T2V")
    fake = _FakeMakeVideo("FAILED")
    row = await crud.get_workspace_generation_package("wgp_m1")
    payload, _ = await pq.build_execution_payload(row, {})
    outcome = await pq._fire_and_wait(fake, payload, "wgp_m1")
    assert outcome["ok"] is False
    row = await crud.get_workspace_generation_package("wgp_m1")
    assert row["production_status"] == "FAILED"
    assert row["production_error"]


async def test_generated_but_unretrieved_is_never_reported_as_plain_failure():
    await _seed_package("wgp_n1")
    await crud.update_workspace_generation_package("wgp_n1", logical_mode="T2V")
    fake = _FakeMakeVideo("GENERATED_BUT_UNRETRIEVED")
    row = await crud.get_workspace_generation_package("wgp_n1")
    payload, _ = await pq.build_execution_payload(row, {})
    outcome = await pq._fire_and_wait(fake, payload, "wgp_n1")
    assert outcome["ok"] is True  # credits were spent; the video exists in Flow
    row = await crud.get_workspace_generation_package("wgp_n1")
    assert row["production_status"] == "GENERATED"
    assert row["production_error"] == "GENERATED_BUT_UNRETRIEVED"


# ── Retry / cancel ────────────────────────────────────────────────────────


async def test_retry_failed_items_requeues_them():
    await _seed_package("wgp_o1")
    await pq.approve_packages(["wgp_o1"])
    run = await pq.send_to_production(["wgp_o1"])
    run_id = run["production_run_id"]
    await crud.update_workspace_generation_package(
        "wgp_o1", production_status="FAILED", production_error="X",
    )
    await crud.update_production_run(run_id, status="FAILED")
    result = await pq.retry_failed_items(run_id)
    assert result["retried"] == 1
    row = await crud.get_workspace_generation_package("wgp_o1")
    assert row["production_status"] == "QUEUED"
    assert row["production_error"] is None
    run_row = await crud.get_production_run(run_id)
    assert run_row["status"] == "PENDING"


async def test_cancel_remaining_marks_queued_items_cancelled():
    await _seed_package("wgp_p1")
    await pq.approve_packages(["wgp_p1"])
    run = await pq.send_to_production(["wgp_p1"])
    await pq._cancel_remaining(run["production_run_id"])
    row = await crud.get_workspace_generation_package("wgp_p1")
    assert row["production_status"] == "CANCELLED"
