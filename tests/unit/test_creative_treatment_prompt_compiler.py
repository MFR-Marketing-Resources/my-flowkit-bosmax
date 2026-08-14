"""P7.5-C format grammar and deterministic prompt proof."""

from __future__ import annotations

import copy

import pytest

from agent.services.canonical_prompt_compiler import compile_prompt_set
from agent.services.full_storyboard_extend_planner import (
    plan_full_storyboard,
)
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


def _extend_treatment(segment_count: int) -> dict:
    treatment = _treatment("UGC")
    total_seconds = segment_count * 8
    planner = plan_full_storyboard(
        route_id="VIDEO_JOBS_ORCHESTRATOR",
        source_mode="FRAMES",
        product={
            "id": "rempah-product",
            "name": "Rempah Nasi Khowmok",
            "category": "SPICE_SEASONING",
        },
        copy_intelligence={
            "hook": "Harum rempah terus naik.",
            "subhook": "Masakan terasa lengkap untuk keluarga.",
            "cta": "Cuba hari ini.",
        },
        resolved_block_plan=[8] * segment_count,
        target_language="BM_MS",
        wps_mode="SWEET",
        scene_context="dapur rumah",
        dialogue_enabled=True,
        approved_dialogue=(
            "Harum rempah terus naik. Masakan terasa lengkap untuk keluarga. "
            "Cuba hari ini."
        ),
        shot_count_by_block=[1] * segment_count,
    ).to_dict()
    segments = []
    for index, allocation in enumerate(
        planner["block_allocations"],
        start=1,
    ):
        segment_sha256 = str(index) * 64
        segments.append(
            {
                "segment_index": index,
                "operation": "INITIAL" if index == 1 else "EXTEND",
                "duration_seconds": 8,
                "action_sequence": [
                    {
                        "sequence": index,
                        "allowed_action_index": index - 1,
                        "action_text": f"Governed action segment {index}",
                        "actor_role": "HANDS",
                        "initial_state": f"state-{index - 1}",
                        "resulting_state": f"state-{index}",
                        "continuity_requirements": ["identity remains stable"],
                    },
                ],
                "shot_grammar": [
                    {
                        "sequence": index,
                        "action_sequences": [index],
                        "purpose": f"governed shot segment {index}",
                        "framing": "close-up",
                        "camera_motion": "controlled push",
                        "subject": "rempah product",
                        "duration_seconds": 8,
                        "continuity_in": [f"state-{index - 1}"],
                        "continuity_out": [f"state-{index}"],
                    },
                ],
                "exact_dialogue_slice": allocation["exact_dialogue_slice"],
                "planner_allocation": allocation,
                "segment_sha256": segment_sha256,
            }
        )
    treatment.update(
        {
            "generation_mode": "EXTEND",
            "duration_seconds": total_seconds,
            "segment_plan": {
                "plan_version": planner["plan_version"],
                "input_fingerprint": planner["input_fingerprint"],
                "planner_fingerprint": planner["planner_fingerprint"],
                "generation_mode": "EXTEND",
                "requested_total_duration_seconds": total_seconds,
                "engine_block_duration_seconds": 8,
                "segment_count": segment_count,
                "execution_route": "VIDEO_JOBS_ORCHESTRATOR",
                "resolved_block_plan": [8] * segment_count,
                "ordered_segment_sha256s": [
                    segment["segment_sha256"] for segment in segments
                ],
                "segments": segments,
                "segment_plan_sha256": "d" * 64,
            },
        }
    )
    return treatment


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


def test_v2_approved_dialogue_is_immutable_at_compiler_boundary() -> None:
    treatment = _treatment("UGC")
    approved = treatment["dialogue_text"]
    compiled = compile_ugc_video_prompt(
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
        approved_dialogue=approved,
    )
    assert compiled["prompt_blocks"][0]["exact_dialogue_slice"] == approved

    replacement = "Approved wording that the treatment must not rewrite."
    v2_compiled = compile_ugc_video_prompt(
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
        approved_dialogue=replacement,
    )
    assert v2_compiled["prompt_blocks"][0]["exact_dialogue_slice"] == replacement
    assert treatment["dialogue_text"] not in v2_compiled["final_compiled_prompt_text"]
    assert v2_compiled["treatment_lineage"]["treatment_id"] == treatment["treatment_id"]
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


@pytest.mark.parametrize(
    ("total_seconds", "segment_count"),
    [(16, 2), (24, 3)],
)
def test_treatment_extend_preserves_stored_segment_authority(
    total_seconds: int,
    segment_count: int,
) -> None:
    treatment = _extend_treatment(segment_count)
    canonical = compile_prompt_set(
        source_mode="FRAMES",
        duration_seconds=total_seconds,
        product={
            "id": "rempah-product",
            "name": "Rempah Nasi Khowmok",
            "category": "SPICE_SEASONING",
        },
        creative_treatment=copy.deepcopy(treatment),
    )
    assert canonical["block_plan"] == [8] * segment_count
    assert canonical["total_blocks"] == segment_count
    assert canonical["planner_result"]["block_allocations"] == [
        segment["planner_allocation"]
        for segment in treatment["segment_plan"]["segments"]
    ]
    assert canonical["treatment_lineage"] == {
        "treatment_id": treatment["treatment_id"],
        "treatment_sha256": treatment["treatment_sha256"],
        "visual_fingerprint_sha256": treatment[
            "visual_fingerprint_sha256"
        ],
        "format": "UGC",
        "generation_mode": "EXTEND",
        "segment_plan_sha256": "d" * 64,
        "ordered_segment_sha256s": treatment["segment_plan"][
            "ordered_segment_sha256s"
        ],
    }
    for index, block in enumerate(canonical["blocks"], start=1):
        action_section = block["sections"][
            "SECTION 3 - CONTINUITY & STATE LOCK"
        ]
        assert f"Governed action segment {index}" in action_section
        assert (
            f"purpose=governed shot segment {index}"
            in block["sections"]["SECTION 4 - VISUAL STORY"]
        )

    ugc = compile_ugc_video_prompt(
            product={"id": "rempah-product", "name": "Rempah"},
            approved_package={"mode": "F2V"},
            mode="F2V",
            source_mode="FRAMES",
            generation_mode="EXTEND",
            duration_seconds=8,
            requested_total_duration_seconds=total_seconds,
            route="VIDEO_JOBS_ORCHESTRATOR",
            creative_treatment=copy.deepcopy(treatment),
    )
    assert len(ugc["prompt_blocks"]) == segment_count
    assert ugc["planner_result"]["block_allocations"] == canonical[
        "planner_result"
    ]["block_allocations"]
    assert ugc["treatment_lineage"]["ordered_segment_sha256s"] == treatment[
        "segment_plan"
    ]["ordered_segment_sha256s"]


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
