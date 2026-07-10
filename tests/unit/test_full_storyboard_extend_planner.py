"""Behavioral contracts for the canonical storyboard-first EXTEND planner."""
from __future__ import annotations

from copy import deepcopy

import pytest

from agent.services import canonical_prompt_compiler as canonical
from agent.services.full_storyboard_extend_planner import (
    PLAN_VERSION,
    PlannerValidationError,
    plan_full_storyboard,
    validate_planner_result,
)
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
from agent.services.workspace_generation_package_service import (
    _build_dom_scaffold,
    _build_manual_handoff,
)
from tests.fixtures.full_storyboard_extend_planner.storyboard_fixtures import (
    FIXTURE_INPUTS,
    build_fixture,
)


PRODUCT = {
    "id": "prod-storyboard-first",
    "name": "Bosmax Calm Daily Serum",
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


@pytest.mark.parametrize(
    ("source_mode", "adapter"),
    [
        ("FRAMES", "F2V_FRAMES_CONTINUITY"),
        ("T2V", "T2V_SCENE_CONTINUITY"),
        ("HYBRID", "HYBRID_REFERENCE_CONTINUITY"),
        ("INGREDIENTS", "I2V_REFERENCE_CONTINUITY"),
    ],
)
def test_full_storyboard_plan_is_deterministic_and_complete_for_each_video_mode(
    source_mode: str,
    adapter: str,
) -> None:
    first = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode=source_mode,
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        scene_context="a bright lived-in bathroom counter",
        shot_count_by_block=[2, 2, 2],
    )
    second = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode=source_mode,
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        scene_context="a bright lived-in bathroom counter",
        shot_count_by_block=[2, 2, 2],
    )

    assert first.plan_version == PLAN_VERSION
    assert first.to_dict() == second.to_dict()
    assert first.planner_fingerprint == second.planner_fingerprint
    assert first.full_story_plan.source_mode_adapter == adapter
    assert first.full_story_plan.total_duration_seconds == 24
    assert [allocation.duration_seconds for allocation in first.block_allocations] == [8, 8, 8]
    assert [(allocation.start_s, allocation.end_s) for allocation in first.block_allocations] == [
        (0, 8),
        (8, 16),
        (16, 24),
    ]
    assert [allocation.is_final for allocation in first.block_allocations] == [False, False, True]
    assert all(
        beat.assigned_block_index is not None
        for beat in first.full_story_plan.story_beats
    )
    assert all(
        utterance.assigned_block_index is not None
        for utterance in first.full_dialogue_plan.utterances
    )
    assert first.block_allocations[0].entry_continuity_state.reference_frame_relationship
    assert first.block_allocations[1].entry_continuity_state == first.block_allocations[0].exit_continuity_state
    assert first.block_allocations[2].entry_continuity_state == first.block_allocations[1].exit_continuity_state
    assert all(not allocation.final_cta_text for allocation in first.block_allocations[:-1])
    assert first.block_allocations[-1].final_cta_text == COPY["cta"]
    assert "CTA" not in {
        beat.role
        for allocation in first.block_allocations[:-1]
        for beat in allocation.assigned_story_beats
    }
    assert "CTA" in {
        beat.role
        for beat in first.block_allocations[-1].assigned_story_beats
    }
    assert all(
        allocation.actual_dialogue_word_count <= allocation.dialogue_word_budget
        for allocation in first.block_allocations
    )
    assert " ".join(
        allocation.exact_dialogue_slice for allocation in first.block_allocations
    ).split() == first.full_dialogue_plan.full_dialogue_text.split()
    dialogue_clauses = [
        clause.lower()
        for utterance in first.full_dialogue_plan.utterances
        for clause in canonical._split_clauses(utterance.text)
    ]
    assert len(dialogue_clauses) == len(set(dialogue_clauses))


@pytest.mark.parametrize("total, expected", [(16, [8, 8]), (24, [8, 8, 8]), (32, [8, 8, 8, 8])])
def test_authorized_duration_plans_allocate_every_story_beat_and_utterance_once(
    total: int,
    expected: list[int],
) -> None:
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=expected,
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2] * len(expected),
    )

    assert result.total_duration_seconds == total
    assert sum(allocation.duration_seconds for allocation in result.block_allocations) == total
    assert result.block_allocations[0].start_s == 0
    assert result.block_allocations[-1].end_s == total
    assert len({beat_id for allocation in result.block_allocations for beat_id in allocation.assigned_story_beat_ids}) == len(result.full_story_plan.story_beats)
    assert len({utterance_id for allocation in result.block_allocations for utterance_id in allocation.assigned_dialogue_utterance_ids}) == len(result.full_dialogue_plan.utterances)
    assert result.block_allocations[-1].final_cta_text == COPY["cta"]


def test_validator_rejects_dialogue_budget_overflow_with_stable_error_code() -> None:
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2],
    ).to_dict()
    result["block_allocations"][0]["actual_dialogue_word_count"] = 999

    with pytest.raises(PlannerValidationError, match="DIALOGUE_PLAN_EXCEEDS_WPS_BUDGET"):
        validate_planner_result(result)


def test_extend_renderer_uses_only_its_assigned_story_and_dialogue_slices() -> None:
    result = compile_ugc_video_prompt(
        product=PRODUCT,
        approved_package={"scene_context": "a bright lived-in bathroom counter"},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=24,
        target_language="BM_MS",
        copy_intelligence=COPY,
    )

    planner = result["planner_result"]
    assert planner["plan_version"] == PLAN_VERSION
    assert planner["full_story_plan"]
    assert planner["full_dialogue_plan"]
    assert len(planner["block_allocations"]) == 3

    first_block = result["prompt_blocks"][0]
    first_allocation = deepcopy(first_block["allocation"])
    first_allocation["assigned_story_beats"][0]["visual_action"] = "Allocated alternate visual beat only."
    first_allocation["exact_dialogue_slice"] = "Dialog yang diperuntukkan sahaja."
    mutated_copy = {**COPY, "hook": "RAW COPY MUST NOT REBUILD THIS BLOCK.", "cta": "RAW CTA MUST NOT LEAK."}

    rerendered = canonical.render_block(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        block_index=1,
        total_blocks=3,
        block_seconds=8,
        product=PRODUCT,
        scene_context="a bright lived-in bathroom counter",
        copy=mutated_copy,
        target_language="BM_MS",
        wps_mode="SWEET",
        allocation=first_allocation,
    )

    assert "Allocated alternate visual beat only." in rerendered["sections"]["SECTION 4 - VISUAL STORY"]
    assert rerendered["sections"]["SECTION 6 - SPOKEN DIALOGUE"] == "Dialog yang diperuntukkan sahaja."
    assert "RAW COPY MUST NOT REBUILD THIS BLOCK" not in rerendered["sections"]["SECTION 4 - VISUAL STORY"]
    assert "RAW CTA MUST NOT LEAK" not in rerendered["sections"]["SECTION 6 - SPOKEN DIALOGUE"]


@pytest.mark.parametrize("fixture_name", sorted(FIXTURE_INPUTS))
def test_all_mode_24_second_proof_fixtures_include_complete_canonical_artifacts(
    fixture_name: str,
) -> None:
    fixture = build_fixture(fixture_name)

    assert fixture["route"] == "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS"
    assert list(fixture["block_plan"]) == [8, 8, 8]
    assert fixture["full_story_plan"]["story_beats"]
    assert fixture["full_dialogue_plan"]["utterances"]
    assert len(fixture["block_allocations"]) == 3
    assert len(fixture["rendered_prompt_blocks"]) == 3
    assert fixture["continuity_lineage"]
    assert fixture["final_fingerprint"]
    assert fixture["block_allocations"][-1]["final_cta_text"] == COPY["cta"]
    assert all(not block["final_cta_text"] for block in fixture["block_allocations"][:-1])


def test_handoff_payloads_retain_the_exact_previewed_planner_result() -> None:
    planner = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    ).to_dict()
    manual = _build_manual_handoff(
        mode="F2V",
        final_prompt_text="prompt",
        image_assets={},
        upload_order=[],
        blockers=[],
        warnings=[],
        planner_result=planner,
    )
    scaffold = _build_dom_scaffold(
        mode="F2V",
        product_id=PRODUCT["id"],
        prompt_package_snapshot_id="pps_1",
        workspace_execution_package_id="wep_1",
        workspace_generation_package_id="wgp_1",
        final_prompt_text="prompt",
        prompt_blocks=[],
        generation_mode="EXTEND",
        asset_map={},
        settings={},
        semantic_resolution={},
        upload_order=[],
        blockers=[],
        warnings=[],
        prompt_fingerprint="prompt-fingerprint",
        asset_fingerprints=[],
        planner_result=planner,
    )

    assert manual["storyboard_plan"] == planner
    assert scaffold["prompt"]["planner_result"] == planner
