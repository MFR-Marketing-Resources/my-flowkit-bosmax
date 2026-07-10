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
        "ACTIVE_FINAL_SECOND_FOR_EXTEND_CHAIN"
    )
    assert reps1["INDEPENDENT_BLOCK"]["audio_seam_contract"]["contract_purpose"] == (
        "SEAM_READY_HOLD_INDEPENDENT_ROUTE"
    )
    reps2 = b2["prompt_representations"]
    assert reps2["GOOGLE_FLOW_EXTEND"]["audio_seam_contract"]["representation"] == "GOOGLE_FLOW_EXTEND"
    assert reps2["GOOGLE_FLOW_EXTEND"]["audio_seam_contract"]["contract_purpose"] == "CONTINUATION_FROM_PRIOR_VIDEO"
    assert reps2["INDEPENDENT_BLOCK"]["audio_seam_contract"]["representation"] == "INDEPENDENT_BLOCK"
    assert reps2["GOOGLE_FLOW_EXTEND"]["text"].startswith("Extend this video")