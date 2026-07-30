"""P7.5-C format grammar and deterministic prompt proof."""

from __future__ import annotations

import copy

import pytest

from agent.services.canonical_prompt_compiler import compile_prompt_set
from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)


def _treatment(format_name: str) -> dict:
    return {
        "treatment_id": f"treatment-{format_name.lower()}",
        "treatment_sha256": "a" * 64,
        "visual_fingerprint_sha256": "b" * 64,
        "format": format_name,
        "generation_mode": "SINGLE",
        "duration_seconds": 8,
        "content_angle": "rempah mudah untuk hidangan keluarga",
        "dialogue_text": "Ini cara mudah saya siapkan rempah untuk keluarga.",
        "asset_bindings": [
            {"role": "PRODUCT_REFERENCE", "asset_id": "asset-rempah"},
        ],
        "action_sequence": [
            {
                "sequence": 1,
                "allowed_action_index": 0,
                "action_text": "Tuang rempah ke dalam mangkuk",
                "actor_role": "HANDS",
                "initial_state": "pek rempah tertutup",
                "resulting_state": "rempah berada di dalam mangkuk",
                "continuity_requirements": ["label pek kekal jelas"],
            }
        ],
        "shot_grammar": [
            {
                "sequence": 1,
                "action_sequences": [1],
                "purpose": "reveal tindakan produk",
                "framing": "close-up",
                "camera_motion": "slow push",
                "subject": "pek rempah dan mangkuk",
                "duration_seconds": 8,
                "continuity_in": ["pek rempah tertutup"],
                "continuity_out": ["rempah berada di dalam mangkuk"],
            }
        ],
        "dependency_hashes": {"copy_set_sha256": "c" * 64},
        "variation_group": None,
    }


def _compile(format_name: str) -> dict:
    treatment = _treatment(format_name)
    return compile_ugc_video_prompt(
        product={
            "id": "rempah-product",
            "name": "Rempah Nasi Khowmok",
            "category": "SPICE_SEASONING",
        },
        approved_package={"mode": "F2V", "scene_context": "dapur rumah"},
        mode="F2V",
        source_mode="FRAMES",
        generation_mode="SINGLE",
        duration_seconds=8,
        creative_treatment=treatment,
    )


def test_formats_compile_distinct_structured_shot_grammars() -> None:
    ugc = _compile("UGC")
    pgc = _compile("PGC")
    cinematic = _compile("CINEMATIC")

    assert "authentic presenter-led creator grammar" in ugc[
        "final_compiled_prompt_text"
    ]
    assert "product-led commercial grammar" in pgc[
        "final_compiled_prompt_text"
    ]
    assert "composed cinematic grammar" in cinematic[
        "final_compiled_prompt_text"
    ]
    assert len(
        {
            ugc["prompt_fingerprint"],
            pgc["prompt_fingerprint"],
            cinematic["prompt_fingerprint"],
        }
    ) == 3
    for result in (ugc, pgc, cinematic):
        assert "Tuang rempah ke dalam mangkuk" in result[
            "final_compiled_prompt_text"
        ]
        assert "purpose=reveal tindakan produk" in result[
            "final_compiled_prompt_text"
        ]
        assert result["compiled_shot_grammar"]
        assert result["treatment_lineage"]["treatment_id"]


def test_treatment_prompt_hash_is_deterministic() -> None:
    first = _compile("CINEMATIC")
    second = _compile("CINEMATIC")
    assert first["prompt_fingerprint"] == second["prompt_fingerprint"]
    assert (
        first["rendered_prompt_fingerprint"]
        == second["rendered_prompt_fingerprint"]
    )


def test_pgc_has_no_creator_camera_fallback() -> None:
    result = _compile("PGC")
    prompt = result["final_compiled_prompt_text"]
    assert "no visible presenter" in prompt.lower()
    assert "no handheld creator sway" in prompt.lower()


def test_treatment_extend_is_rejected_before_planning() -> None:
    treatment = _treatment("UGC")
    treatment["generation_mode"] = "EXTEND"
    with pytest.raises(ValueError, match="TREATMENT_EXTEND_UNSUPPORTED"):
        compile_ugc_video_prompt(
            product={"id": "rempah-product", "name": "Rempah"},
            approved_package={"mode": "F2V"},
            mode="F2V",
            source_mode="FRAMES",
            generation_mode="SINGLE",
            duration_seconds=8,
            creative_treatment=treatment,
        )


def test_canonical_entrypoint_preserves_treatment_lineage() -> None:
    treatment = _treatment("UGC")
    compiled = compile_prompt_set(
        source_mode="FRAMES",
        duration_seconds=8,
        product={"id": "rempah-product", "name": "Rempah"},
        creative_treatment=copy.deepcopy(treatment),
    )
    assert compiled["total_blocks"] == 1
    assert compiled["planner_result"] is None
    assert compiled["treatment_lineage"]["treatment_id"] == treatment[
        "treatment_id"
    ]
