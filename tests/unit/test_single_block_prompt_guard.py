"""ONE generation = ONE block (live-incident regression guard).

The live incident: the FULL multi-block compiled document (both 9-section blocks)
was submitted as one prompt → the Flow agent proposed one generation PER block
("2 video generations, costing 30 credits") → the count-mismatch steer fired →
the agent dropped the reference image and compressed both blocks' dialogue into
a single 8s clip with the wrong product appearance.

These tests pin every layer that must refuse a multi-block prompt:
  * the one-door /generate endpoint (422 MULTI_BLOCK_PROMPT_REJECTED);
  * the manual execute-flow-job lane (ERR_MULTI_BLOCK_PROMPT, telemetry recorded);
  * the durable-job resolver (pkg.prompt_text multi-block → NOT used as initial);
  * the durable-job initial adapter (last-line fail-closed).
Single-block prompts remain untouched — the proven video-1 flow is unchanged.
"""
import pytest
from copy import deepcopy
from fastapi import HTTPException

from agent.api import flow
from agent.services import production_plan_resolver as resolver
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

_HDR = "SECTION 1 - ROLE & OBJECTIVE"
BLOCK1 = f"{_HDR}\nYou are generating an 8-second block (opening block 1 of 2).\n...body..."
BLOCK2 = f"{_HDR}\nYou are generating an 8-second block (final block 2 of 2).\n...body..."
MULTI = BLOCK1 + "\n\n" + BLOCK2


def test_detector_single_vs_multi():
    assert flow._is_multi_block_prompt(BLOCK1) is False       # proven single-block: allowed
    assert flow._is_multi_block_prompt(MULTI) is True
    assert flow._is_multi_block_prompt("plain prompt, no headers") is False
    assert flow._is_multi_block_prompt("") is False


async def test_one_door_generate_rejects_multi_block():
    body = flow.GenerateRequest(mode="I2V", prompt=MULTI)
    with pytest.raises(HTTPException) as exc:
        await flow.generate(body)
    assert exc.value.status_code == 422
    assert "MULTI_BLOCK_PROMPT_REJECTED" in str(exc.value.detail)


async def test_manual_lane_rejects_multi_block_before_any_work(monkeypatch):
    """The guard fires via _fail_manual_request (422) BEFORE asset resolution,
    credit checks, or any Flow call. Telemetry writers are stubbed — the shared
    _fail_manual_request path is already proven by the other lane guards."""
    events = []

    async def rec_event(*a, **k):
        events.append(a)

    async def rec_telemetry(*a, **k):
        events.append(a)

    from agent.db import crud
    monkeypatch.setattr(crud, "add_stage_event", rec_event)
    monkeypatch.setattr(crud, "upsert_request_telemetry", rec_telemetry)
    with pytest.raises(HTTPException) as exc:
        await flow._run_manual_job_via_generate(
            {"request_id": "manual_multiblock_test", "prompt": MULTI}, "F2V", None)
    assert exc.value.status_code == 422
    assert "ERR_MULTI_BLOCK_PROMPT" in str(exc.value.detail)
    assert events  # fail-closed telemetry was recorded


async def test_resolver_never_uses_multi_block_pkg_prompt(monkeypatch):
    """A multi-block execution-package prompt_text must NOT become the initial
    prompt — the compile door must resolve block-1 (here absent → fail-closed)."""
    async def fake_pkg(pkg_id):
        return {"workspace_execution_package_id": pkg_id, "product_id": "p1",
                "mode": "I2V", "model": "veo",
                "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
                "prompt_text": MULTI, "resolved_assets": "[]"}
    from agent.db import crud
    monkeypatch.setattr(crud, "get_workspace_execution_package", fake_pkg)

    async def fake_compile(**kwargs):
        raise RuntimeError("compiler unavailable in this test")
    import agent.services.workspace_execution_package_service as weps
    monkeypatch.setattr(weps, "compile_workspace_prompt_preview", fake_compile)

    out = await resolver.resolve_production_authority(
        {"product_id": "p1", "execution_package_id": "wep_multi",
         "requested_duration_seconds": 16})
    assert not out.get("initial_prompt_text")            # multi-block NOT accepted
    assert "initial_prompt_text" in out["missing"]        # → fail-closed 422 upstream


async def test_resolver_accepts_single_block_pkg_prompt(monkeypatch):
    async def fake_pkg(pkg_id):
        return {"workspace_execution_package_id": pkg_id, "product_id": "p1",
                "mode": "I2V", "model": "veo",
                "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
                "prompt_text": BLOCK1, "resolved_assets": "[]"}
    from agent.db import crud
    monkeypatch.setattr(crud, "get_workspace_execution_package", fake_pkg)
    out = await resolver.resolve_production_authority(
        {"product_id": "p1", "execution_package_id": "wep_single",
         "requested_duration_seconds": 16,
         "continuation_prompts": [{"position": 1, "prompt": "cont", "is_final": True}]},
        trust_client_authority=True)
    assert out["initial_prompt_text"] == BLOCK1          # proven single-block unchanged


def test_missing_fields_flags_multi_block_initial():
    out = {"initial_prompt_text": MULTI, "duration_valid": True}
    missing = resolver._missing_fields(out, extend_ops=0)
    assert "single_block_initial_prompt" in missing


async def test_durable_adapter_rejects_multi_block_last_line():
    job = {"job_id": "vj_x", "product_id": "p", "approved_asset_id": "a",
           "approved_asset_sha256": "s", "initial_asset_media_id": "m",
           "initial_mode": "I2V", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
           "initial_prompt_text": MULTI}
    with pytest.raises(flow.InitialGenerationError):
        flow._initial_gen_preconditions(job)


_SINGLE_PRODUCT = {
    "id": "prod-single-guard", "name": "Minyak Warisan Tok Cap Burung 25ml",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "category": "Health & Personal Care",
}
_SINGLE_COPY = {
    "copy_source": "selected_copy_set", "formula_family": "PAS", "angle": "Rutin malam",
    "hook": "Anak susah tidur?", "subhook": "Hati ibu terganggu.",
    "usps": ["Formula tradisional."], "cta": "Cuba malam ini.",
}


def test_single_block_carries_no_audio_handoff_metadata():
    """SINGLE = one complete 8s block, no seam. It must NOT inherit any Extend-only
    handoff timing metadata or seam prompt wording; its initial prompt stays the
    unchanged independent-block prompt."""
    compiled = compile_ugc_video_prompt(
        product=deepcopy(_SINGLE_PRODUCT),
        approved_package={"scene_context": "bedroom"},
        mode="F2V", source_mode="HYBRID", generation_mode="SINGLE",
        engine_duration_target="GOOGLE_FLOW",
        target_language="BM_MS",
        copy_intelligence=deepcopy(_SINGLE_COPY),
    )
    blocks = compiled["prompt_blocks"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["is_final"] is True
    assert block["flow_extend_prompt_text"] in (None, "")
    # SINGLE prompt text is unchanged: the research seam is never injected.
    assert block["initial_generation_prompt_text"] == block["independent_block_prompt_text"]
    assert "half a second before" not in (block["initial_generation_prompt_text"] or "").lower()
    # No outgoing/incoming handoff boundary is attached to a lone final block.
    contract = block["audio_seam_contract"]
    assert contract["outgoing_dialogue_deadline_s"] is None
    assert contract["incoming_new_dialogue_onset_floor_s"] is None
    assert contract["forbid_new_spoken_phrase_in_final_handoff_window"] is False
    assert contract["forbid_new_speech_before_onset_floor"] is False
