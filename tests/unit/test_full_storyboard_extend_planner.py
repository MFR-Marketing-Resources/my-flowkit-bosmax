"""Behavioral contracts for the canonical storyboard-first EXTEND planner."""
from __future__ import annotations

from copy import deepcopy

import pytest

from agent.services import canonical_prompt_compiler as canonical
from agent.services import ugc_video_prompt_compiler_service as ugc_compiler
from agent.services.full_storyboard_extend_planner import (
    PLAN_VERSION,
    DialogueUtterance,
    FullDialoguePlan,
    PlannerValidationError,
    _allocate_dialogue_utterances,
    _build_dialogue_plan,
    _build_story_plan,
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


def test_full_dialogue_plan_is_global_and_never_calls_the_per_block_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_per_block_generation(**_: object) -> str:
        raise AssertionError("per-block dialogue generation is forbidden in the storyboard planner")

    monkeypatch.setattr(canonical, "build_block_dialogue", reject_per_block_generation)

    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    )

    assert len(result.full_dialogue_plan.utterances) > len(result.block_allocations)
    assert {utterance.role for utterance in result.full_dialogue_plan.utterances} >= {
        "HOOK",
        "USP",
        "CTA",
    }
    assert result.full_dialogue_plan.compliance_metadata["generated_once"] is True


def test_global_dialogue_utterances_exist_before_window_allocation() -> None:
    normalized_copy = canonical.normalize_copy_intelligence(COPY, product=PRODUCT)
    global_story = _build_story_plan(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        normalized_copy=normalized_copy,
        resolved_block_plan=[8, 8, 8],
        scene_context="a bright lived-in bathroom counter",
        shot_count_by_block=[2, 2, 2],
        input_fingerprint="global-dialogue-proof",
    )
    global_dialogue = _build_dialogue_plan(
        product=PRODUCT,
        normalized_copy=normalized_copy,
        story_plan=global_story,
        target_language="BM_MS",
        wps_mode="SWEET",
        dialogue_enabled=True,
        approved_dialogue=None,
        input_fingerprint="global-dialogue-proof",
    )

    assert all(utterance.assigned_block_index is None for utterance in global_dialogue.utterances)
    assert [utterance.role for utterance in global_dialogue.utterances] == [
        "HOOK",
        "CONTEXT",
        "USP",
        "USP",
        "USP",
        "CTA",
    ]
    assert global_dialogue.utterances[0].start_s == 0
    assert global_dialogue.utterances[-1].end_s == 24


def test_story_arc_is_global_then_reallocated_without_per_block_shot_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = canonical._default_shot_plan
    calls: list[dict[str, object]] = []

    def record_global_story_generation(*args: object, **kwargs: object) -> list[str]:
        calls.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(canonical, "_default_shot_plan", record_global_story_generation)

    three_blocks = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    )

    assert len(calls) == 1
    assert all(beat.assigned_block_index is not None for beat in three_blocks.full_story_plan.story_beats)
    assert len({beat.beat_id for beat in three_blocks.full_story_plan.story_beats}) == len(
        three_blocks.full_story_plan.story_beats
    )

    calls.clear()
    two_blocks = plan_full_storyboard(
        route_id="PLANNER_ALLOCATION_PROOF_ONLY",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[16, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2],
    )

    assert len(calls) == 1
    assert [beat.role for beat in two_blocks.full_story_plan.story_beats] == [
        beat.role for beat in three_blocks.full_story_plan.story_beats
    ]
    assert [len(block.assigned_story_beats) for block in two_blocks.block_allocations] != [
        len(block.assigned_story_beats) for block in three_blocks.block_allocations
    ]


def test_global_story_beats_exist_before_block_allocation_assigns_them() -> None:
    normalized_copy = canonical.normalize_copy_intelligence(COPY, product=PRODUCT)
    global_story = _build_story_plan(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        normalized_copy=normalized_copy,
        resolved_block_plan=[8, 8, 8],
        scene_context="a bright lived-in bathroom counter",
        shot_count_by_block=[2, 2, 2],
        input_fingerprint="global-story-proof",
    )

    assert all(beat.assigned_block_index is None for beat in global_story.story_beats)
    allocated = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    )
    assert all(beat.assigned_block_index is not None for beat in allocated.full_story_plan.story_beats)


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


def test_validator_requires_the_final_cta_in_spoken_dialogue_and_no_earlier_block() -> None:
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    ).to_dict()
    final_allocation = result["block_allocations"][-1]
    final_allocation["exact_dialogue_slice"] = "Dialog penutup tanpa CTA yang diwajibkan."

    with pytest.raises(PlannerValidationError, match="FINAL_CTA_CANNOT_FIT_WPS_BUDGET"):
        validate_planner_result(result)


def test_final_cta_that_exceeds_the_final_block_budget_fails_closed() -> None:
    copy_with_oversized_cta = {
        **COPY,
        "cta": " ".join(["Tindakan"] * 23),
    }

    with pytest.raises(PlannerValidationError, match="FINAL_CTA_CANNOT_FIT_WPS_BUDGET"):
        plan_full_storyboard(
            route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
            source_mode="T2V",
            product=PRODUCT,
            copy_intelligence=copy_with_oversized_cta,
            resolved_block_plan=[8, 8],
            target_language="BM_MS",
            wps_mode="SWEET",
            shot_count_by_block=[2, 2],
        )


def test_final_cta_is_spoken_only_in_the_final_rendered_section_six() -> None:
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
    cta = COPY["cta"]
    allocations = result["planner_result"]["block_allocations"]

    for block, allocation in zip(result["prompt_blocks"], allocations):
        section_six = block["engine_prompt_text"].split("SECTION 6 - SPOKEN DIALOGUE\n", 1)[1].split(
            "\n\nSECTION 7 - VOICE & DELIVERY", 1
        )[0]
        assert section_six == allocation["exact_dialogue_slice"]
        if allocation["is_final"]:
            assert cta in section_six
        else:
            assert cta not in section_six


def test_changed_camera_and_grip_state_propagate_to_the_next_block_entry() -> None:
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    )
    first_exit = result.block_allocations[0].exit_continuity_state
    second_exit = result.block_allocations[1].exit_continuity_state
    third_entry = result.block_allocations[2].entry_continuity_state

    assert second_exit.camera_direction_path != first_exit.camera_direction_path
    assert second_exit.product_grip != first_exit.product_grip
    assert third_entry == second_exit
    assert result.block_allocations[1].assigned_story_beats[-1].continuity_out == second_exit


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


def test_canonical_package_fingerprint_tracks_planner_and_rendered_block_mutations() -> None:
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
    fingerprint_builder = getattr(ugc_compiler, "canonical_package_fingerprint", None)

    assert callable(fingerprint_builder)
    baseline = fingerprint_builder(
        planner_result=deepcopy(result["planner_result"]),
        rendered_prompt_blocks=deepcopy(result["prompt_blocks"]),
        renderer_version=result["compiler_version"],
    )
    assert result["prompt_fingerprint"] == baseline

    same_inputs = compile_ugc_video_prompt(
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
    assert same_inputs["prompt_fingerprint"] == baseline

    changed_story = deepcopy(result["planner_result"])
    changed_story["full_story_plan"]["story_beats"][0]["visual_action"] = "Changed allocated story beat."
    changed_dialogue = deepcopy(result["planner_result"])
    changed_dialogue["block_allocations"][0]["exact_dialogue_slice"] = "Changed allocated dialogue."
    changed_duration = deepcopy(result["planner_result"])
    changed_duration["total_duration_seconds"] = 32
    changed_version = deepcopy(result["planner_result"])
    changed_version["plan_version"] = "full_storyboard_first_extend_planner_test_v2"
    for planner in (changed_story, changed_dialogue, changed_duration, changed_version):
        assert fingerprint_builder(
            planner_result=planner,
            rendered_prompt_blocks=deepcopy(result["prompt_blocks"]),
            renderer_version=result["compiler_version"],
        ) != baseline

    changed_render = deepcopy(result["prompt_blocks"])
    changed_render[0]["engine_prompt_text"] = "Changed engine-facing prompt block."
    assert fingerprint_builder(
        planner_result=deepcopy(result["planner_result"]),
        rendered_prompt_blocks=changed_render,
        renderer_version=result["compiler_version"],
    ) != baseline

    volatile = deepcopy(result["planner_result"])
    volatile["generated_at"] = "2026-07-10T00:00:00Z"
    volatile["request_uuid"] = "86c1fdd2-c4db-4795-bc59-2d95e7aed690"
    assert fingerprint_builder(
        planner_result=volatile,
        rendered_prompt_blocks=deepcopy(result["prompt_blocks"]),
        renderer_version=result["compiler_version"],
    ) == baseline


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


@pytest.mark.parametrize(
    "source_mode",
    ["FRAMES", "T2V", "HYBRID", "INGREDIENTS"],
)
@pytest.mark.parametrize(
    ("block_plan", "total"),
    [([8, 8], 16), ([8, 8, 8], 24)],
)
def test_extend_seam_handoff_timing_all_modes(
    source_mode: str, block_plan: list[int], total: int
) -> None:
    """The global EXTEND audio handoff holds for every mode and both 16s/24s chains:
    outgoing dialogue ends by end-0.78s (wider tail), incoming dialogue starts at/after
    start+0.5s, and nothing is dropped, duplicated, or reordered."""
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode=source_mode,
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=block_plan,
        target_language="BM_MS",
        wps_mode="SAFE",
        shot_count_by_block=[2] * len(block_plan),
    )
    eps = 1e-6
    for allocation in result.block_allocations:
        utts = list(allocation.assigned_dialogue_utterances)
        if not utts:
            continue
        first_start = min(u.start_s for u in utts)
        last_end = max(u.end_s for u in utts)
        if not allocation.is_final:
            assert last_end <= allocation.end_s - 0.78 + eps, (
                source_mode, allocation.block_index, last_end, allocation.end_s,
            )
        if allocation.block_index >= 2:
            assert first_start >= allocation.start_s + 0.5 - eps, (
                source_mode, allocation.block_index, first_start, allocation.start_s,
            )
    # Complete, ordered, no-loss preservation.
    concat = " ".join(
        allocation.exact_dialogue_slice for allocation in result.block_allocations
    ).split()
    assert concat == result.full_dialogue_plan.full_dialogue_text.split()


def test_single_block_receives_no_seam_handoff_margins() -> None:
    """SINGLE = one complete block, no seam. Its dialogue timing must span the
    whole block (start at 0.0, end at the block end) — no handoff margin applied."""
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=COPY,
        resolved_block_plan=[8],
        target_language="BM_MS",
        wps_mode="SAFE",
        shot_count_by_block=[2],
    )
    assert len(result.block_allocations) == 1
    allocation = result.block_allocations[0]
    assert allocation.is_final is True
    utts = list(allocation.assigned_dialogue_utterances)
    assert utts, "single block should carry dialogue"
    assert min(u.start_s for u in utts) == 0.0        # no incoming margin
    assert max(u.end_s for u in utts) == float(allocation.end_s)  # no outgoing margin


def test_extend_seam_handoff_fails_closed_when_block_cannot_fit() -> None:
    """A block too short to hold both 0.5s seam handoff margins (no positive speaking
    window) fails closed with the existing planner-error style. Dialogue is never
    dropped, reordered, or crammed past the seam to force a fit."""
    hook = " ".join(["kata"] * 22)   # fills the first 8s block to budget
    mid = "satu dua tiga empat"       # 4 words forced into a 1s middle block → window 0
    cta = "beli sekarang juga terus"  # final CTA
    plan = FullDialoguePlan(
        plan_version="fail_closed_probe",
        target_language="BM_MS",
        wps_mode="SWEET",
        total_duration_seconds=17,
        total_word_budget=30,
        actual_total_word_count=30,
        full_dialogue_text=f"{hook} {mid} {cta}",
        utterances=(
            DialogueUtterance("u1", "HOOK", 0.0, 0.0, hook, 22, "test"),
            DialogueUtterance("u2", "USP", 0.0, 0.0, mid, 4, "test"),
            DialogueUtterance("u3", "CTA", 0.0, 0.0, cta, 4, "test"),
        ),
        approved_copy_provenance={},
        compliance_metadata={},
    )
    with pytest.raises(
        PlannerValidationError, match="DIALOGUE_CANNOT_FORM_NATURAL_EXTENSION_SEAMS"
    ):
        _allocate_dialogue_utterances(plan, [8, 1, 8])
