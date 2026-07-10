"""Reviewable 24-second all-mode fixture builders with no external dependencies."""
from __future__ import annotations

from copy import deepcopy

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt


PRODUCT = {
    "id": "fixture-storyboard-product",
    "name": "Bosmax Daily Calm Serum",
    "category": "Beauty & Personal Care",
}
COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "HSO",
    "hook": "Kulit nampak letih bila rutin rasa terlalu berat.",
    "subhook": "Aku pilih langkah yang rasa ringan untuk dibuat setiap hari.",
    "usps": [
        "Tekstur serum ini cepat terasa kemas pada kulit.",
        "Botolnya mudah dicapai masa rutin pagi.",
        "Cara pegangnya nampak selesa dan terkawal.",
    ],
    "cta": "Kalau sesuai dengan rutin korang, cuba sekarang.",
}

FIXTURE_INPUTS = {
    "F2V_FRAMES_24": {"mode": "F2V", "source_mode": "FRAMES"},
    "T2V_24": {"mode": "T2V", "source_mode": "T2V"},
    "HYBRID_24": {"mode": "F2V", "source_mode": "HYBRID"},
    "I2V_24": {"mode": "I2V", "source_mode": "INGREDIENTS"},
}


def build_fixture(name: str) -> dict:
    """Build a complete 24s proof artifact for one supported source mode."""
    config = FIXTURE_INPUTS[name]
    compiled = compile_ugc_video_prompt(
        product=deepcopy(PRODUCT),
        approved_package={"scene_context": "a bright lived-in bathroom counter"},
        mode=config["mode"],
        source_mode=config["source_mode"],
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=24,
        target_language="BM_MS",
        copy_intelligence=deepcopy(COPY),
    )
    planner = compiled["planner_result"]
    return {
        "fixture_id": name,
        "canonical_inputs": {**config, "product": deepcopy(PRODUCT), "copy": deepcopy(COPY)},
        "route": planner["route_id"],
        "block_plan": planner["resolved_block_plan"],
        "full_story_plan": planner["full_story_plan"],
        "full_dialogue_plan": planner["full_dialogue_plan"],
        "block_allocations": planner["block_allocations"],
        "rendered_prompt_blocks": compiled["prompt_blocks"],
        "continuity_lineage": compiled["continuation_lineage"],
        "final_fingerprint": planner["planner_fingerprint"],
    }
