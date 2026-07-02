"""API-level validation for the prompt/production split endpoints.

Calls the route functions directly (no TestClient), matching the existing
test_generate_validation.py pattern. Validation fires before any DB or
extension dependency, so these stay hermetic.
"""
import pytest
from fastapi import HTTPException

from agent.api import production_queue as pq_api
from agent.api import workspace_generation_packages as wgp_api


# ── Batch Prompt Builder endpoint ─────────────────────────────────────────


async def _expect_http(coro, status, needle=None):
    with pytest.raises(HTTPException) as exc_info:
        await coro
    assert exc_info.value.status_code == status, exc_info.value.detail
    if needle:
        assert needle.lower() in str(exc_info.value.detail).lower()


async def test_mixed_modes_in_one_batch_are_rejected_422():
    body = wgp_api.BatchPromptRequest(
        product_id="p1", logical_mode="T2V", modes=["T2V", "F2V"],
    )
    await _expect_http(wgp_api.start_batch_prompts(body), 422, "mixed_modes_forbidden")


async def test_img_is_not_a_video_batch_prompt_mode():
    body = wgp_api.BatchPromptRequest(product_id="p1", logical_mode="IMG")
    await _expect_http(wgp_api.start_batch_prompts(body), 422, "unsupported_logical_mode")


async def test_t2v_batch_with_image_slots_is_422_mode_contract():
    body = wgp_api.BatchPromptRequest(
        product_id="p1", logical_mode="T2V", character_asset_ids=["a1"],
    )
    await _expect_http(
        wgp_api.start_batch_prompts(body), 422, "t2v_forbids_image_slots",
    )


async def test_f2v_batch_without_frame_is_422_mode_contract():
    body = wgp_api.BatchPromptRequest(product_id="p1", logical_mode="F2V")
    await _expect_http(
        wgp_api.start_batch_prompts(body), 422, "f2v_requires_finished_frame",
    )


async def test_hybrid_batch_without_product_anchor_is_422():
    body = wgp_api.BatchPromptRequest(product_id="missing-product", logical_mode="HYBRID")
    await _expect_http(
        wgp_api.start_batch_prompts(body), 422, "hybrid_requires_product_anchor",
    )


async def test_i2v_batch_without_role_map_is_422():
    body = wgp_api.BatchPromptRequest(product_id="p1", logical_mode="I2V")
    await _expect_http(
        wgp_api.start_batch_prompts(body), 422, "i2v_requires_avatar_reference",
    )


async def test_approve_requires_package_ids():
    body = wgp_api.ApprovePackagesRequest(package_ids=[])
    await _expect_http(wgp_api.approve_packages_endpoint(body), 422)


# ── Production queue endpoints ────────────────────────────────────────────


async def test_send_to_production_with_unapproved_ids_is_422():
    body = pq_api.SendToProductionRequest(package_ids=["nope"], model="Veo 3.1 - Lite")
    await _expect_http(pq_api.send_to_production(body), 422, "no_approved_packages")


async def test_unknown_run_is_404_on_get_start_pause_cancel_retry():
    await _expect_http(pq_api.get_run("prun_missing"), 404)
    await _expect_http(
        pq_api.start_run("prun_missing", pq_api.StartRunRequest()), 404,
    )
    await _expect_http(pq_api.pause_run("prun_missing"), 404)
    await _expect_http(pq_api.cancel_run("prun_missing"), 404)
    await _expect_http(pq_api.retry_run("prun_missing"), 404)


# ── Duration authority endpoint ───────────────────────────────────────────


async def test_duration_authority_serves_the_workbook_durations():
    result = await wgp_api.duration_authority(engine="GOOGLE_FLOW")
    assert result["engine"] == "GOOGLE_FLOW"
    assert 8 in result["allowed_durations"]
    assert 7 not in result["allowed_durations"]
    assert result["source"].endswith("wps_blocking_authority.json")


async def test_duration_authority_unknown_engine_is_404():
    await _expect_http(wgp_api.duration_authority(engine="NO_SUCH_ENGINE"), 404)


# ── Model law at the API surface ──────────────────────────────────────────


async def test_send_to_production_without_model_is_422_model_required():
    body = pq_api.SendToProductionRequest(package_ids=["x"], model=None)
    await _expect_http(pq_api.send_to_production(body), 422, "model_required")


async def test_send_to_production_with_stale_model_is_422_unknown_model():
    body = pq_api.SendToProductionRequest(package_ids=["x"], model="Veo 3.1 Pro")
    await _expect_http(pq_api.send_to_production(body), 422, "err_unknown_model")
