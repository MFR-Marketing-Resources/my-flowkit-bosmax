"""Representation-specific audio contracts on structured prompt_representations."""
from __future__ import annotations

from copy import deepcopy

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

PRODUCT = {
    "id": "prod-audio-rep",
    "name": "Minyak Warisan Tok Cap Burung 25ml",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "category": "Health & Personal Care",
}

COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "PAS",
    "angle": "Rutin malam",
    "hook": "Anak susah tidur?",
    "subhook": "Hati ibu terganggu.",
    "usps": ["Formula tradisional."],
    "cta": "Cuba malam ini.",
}


def test_each_representation_carries_distinct_audio_contract():
    compiled = compile_ugc_video_prompt(
        product=deepcopy(PRODUCT),
        approved_package={"scene_context": "bedroom"},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        target_language="BM_MS",
        copy_intelligence=deepcopy(COPY),
    )
    b1 = compiled["prompt_blocks"][0]
    b2 = compiled["prompt_blocks"][1]
    reps1 = b1["prompt_representations"]
    assert reps1["INITIAL_GENERATION"]["audio_seam_contract"]["contract_purpose"] == (
        "CLAUSE_COMPLETE_BEFORE_HANDOFF_FOR_EXTEND_CHAIN"
    )
    assert reps1["INDEPENDENT_BLOCK"]["audio_seam_contract"]["contract_purpose"] == (
        "SEAM_READY_HOLD_INDEPENDENT_ROUTE"
    )
    reps2 = b2["prompt_representations"]
    assert reps2["GOOGLE_FLOW_EXTEND"]["audio_seam_contract"]["representation"] == "GOOGLE_FLOW_EXTEND"
    assert reps2["GOOGLE_FLOW_EXTEND"]["audio_seam_contract"]["contract_purpose"] == "CONTINUATION_FROM_PRIOR_VIDEO"
    assert reps2["INDEPENDENT_BLOCK"]["audio_seam_contract"]["representation"] == "INDEPENDENT_BLOCK"
    assert reps2["GOOGLE_FLOW_EXTEND"]["text"].startswith("Extend this video")


def test_audio_seam_contract_carries_explicit_handoff_boundary():
    """Every seam must expose the 0.5s audio-ownership boundary: the outgoing
    (non-final) block declares an outgoing dialogue deadline at end-0.5s, and the
    incoming (continuation) block declares a new-dialogue onset floor at start+0.5s.
    """
    compiled = compile_ugc_video_prompt(
        product=deepcopy(PRODUCT),
        approved_package={"scene_context": "bedroom"},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        target_language="BM_MS",
        copy_intelligence=deepcopy(COPY),
    )
    b1, b2 = compiled["prompt_blocks"][0], compiled["prompt_blocks"][1]
    c1 = b1["audio_seam_contract"]
    c2 = b2["audio_seam_contract"]

    # Outgoing (non-final block 1): dialogue must end by block_end - 0.5s, and no
    # new spoken phrase may begin in the trailing 0.5s handoff window.
    assert c1["outgoing_dialogue_deadline_s"] == 7.5
    assert c1["forbid_new_spoken_phrase_in_final_handoff_window"] is True
    # Block 1 is the first block — it owns no incoming seam.
    assert c1["incoming_new_dialogue_onset_floor_s"] is None
    assert c1["forbid_new_speech_before_onset_floor"] is False

    # Incoming (continuation block 2): no new dialogue before block_start + 0.5s.
    assert c2["incoming_new_dialogue_onset_floor_s"] == 8.5
    assert c2["forbid_new_speech_before_onset_floor"] is True
    # Block 2 is the final block of a 16s chain — it owns no outgoing seam.
    assert c2["outgoing_dialogue_deadline_s"] is None
    assert c2["forbid_new_spoken_phrase_in_final_handoff_window"] is False