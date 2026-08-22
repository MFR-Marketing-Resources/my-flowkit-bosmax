from __future__ import annotations

from copy import deepcopy

import pytest

from agent.services.full_storyboard_extend_planner import (
    PlannerValidationError,
    plan_full_storyboard,
)
from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)


PRODUCT = {
    "id": "copy-v2-immutable-product",
    "name": "Bosmax Daily Calm Serum",
    "product_display_name": "Bosmax Daily Calm Serum",
    "category": "Beauty & Personal Care",
    "product_type": "Beauty Serum",
}

STAGES = [
    {
        "stage_key": "stage-0-problem",
        "formula_stage_key": "problem",
        "semantic_role": "problem",
        "text": "Mulakan dengan masalah ringkas.",
    },
    {
        "stage_key": "stage-1-solution",
        "formula_stage_key": "solution",
        "semantic_role": "solution",
        "text": "Tunjukkan rutin mudah.",
    },
    {
        "stage_key": "stage-2-cta",
        "formula_stage_key": "cta",
        "semantic_role": "cta",
        "text": "Cuba sekarang.",
    },
]


def _approved(stages: list[dict] | None = None) -> str:
    return " ".join(item["text"] for item in stages or STAGES)


def _v2_copy(stages: list[dict] | None = None) -> dict:
    selected = deepcopy(stages or STAGES)
    return {
        "copy_source": "copy_blueprint_v2",
        # Deliberately different compatibility projections prove they cannot
        # replace the formula-native stage receipt.
        "hook": "Derived hook hint only.",
        "usps": ["Derived body hint only."],
        "cta": "Derived CTA hint only.",
        "approved_execution_text": selected,
        "estimated_word_count": len(_approved(selected).split()),
    }


def _plan(
    *,
    stages: list[dict] | None = None,
    blocks: list[int] | None = None,
    target_duration_seconds: int | None = None,
):
    copy = _v2_copy(stages)
    if target_duration_seconds is not None:
        copy["target_duration_seconds"] = target_duration_seconds
    return plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=copy,
        resolved_block_plan=blocks or [8],
        target_language="BM_MS",
        wps_mode="SWEET",
        scene_context="a calm bathroom counter",
        approved_dialogue=_approved(stages),
        shot_count_by_block=[2] * len(blocks or [8]),
    )


def _compile(*, stages: list[dict] | None = None, blocks: list[int] | None = None):
    selected = deepcopy(stages or STAGES)
    resolved_blocks = blocks or [8]
    return compile_ugc_video_prompt(
        product=PRODUCT,
        approved_package={"mode": "T2V", "scene_context": "a calm bathroom counter"},
        mode="T2V",
        source_mode="T2V",
        generation_mode="EXTEND" if len(resolved_blocks) > 1 else "SINGLE",
        duration_seconds=8,
        blocks=(
            [
                {"block_index": index, "duration_seconds": seconds}
                for index, seconds in enumerate(resolved_blocks, start=1)
            ]
            if len(resolved_blocks) > 1
            else None
        ),
        requested_total_duration_seconds=sum(resolved_blocks)
        if len(resolved_blocks) > 1
        else None,
        engine_duration_target="GOOGLE_FLOW" if len(resolved_blocks) > 1 else None,
        character_presence="FACELESS",
        copy_intelligence=_v2_copy(selected),
        approved_dialogue=_approved(selected),
    )


def test_v2_single_8s_preserves_one_exact_approved_slice():
    result = _plan()
    assert result.block_allocations[0].exact_dialogue_slice == _approved()


def test_v2_punctuation_is_not_added_or_removed():
    stages = deepcopy(STAGES)
    stages[0]["text"] = "Masalah ringkas, bukan slogan!"
    stages[1]["text"] = "Rutin mudah: kekal tepat?"
    stages[2]["text"] = "Cuba sekarang."
    result = _plan(stages=stages)
    assert result.full_dialogue_plan.full_dialogue_text == _approved(stages)


def test_v2_cta_is_not_substituted_by_derived_projection():
    result = _plan()
    assert result.block_allocations[0].final_cta_text == "Cuba sekarang."
    assert "Derived CTA hint" not in result.full_dialogue_plan.full_dialogue_text


def test_v2_overbudget_fails_with_precise_blocker():
    stages = deepcopy(STAGES)
    stages[0]["text"] = " ".join(["kata"] * 25) + "."
    with pytest.raises(PlannerValidationError) as blocked:
        _plan(stages=stages)
    assert blocked.value.code == "COPY_V2_APPROVED_DIALOGUE_EXCEEDS_DURATION_BUDGET"
    assert "approved_words=30" in blocked.value.detail
    assert "allowed_words=22" in blocked.value.detail


def test_v2_duration_binding_mismatch_fails_before_planning():
    with pytest.raises(PlannerValidationError) as blocked:
        _plan(target_duration_seconds=16)
    assert blocked.value.code == "COPY_V2_DURATION_BINDING_MISMATCH"
    assert "bound_duration_seconds=16" in blocked.value.detail
    assert "requested_duration_seconds=8" in blocked.value.detail


def test_v2_four_stage_order_remains_formula_order():
    stages = deepcopy(STAGES)
    stages.insert(
        2,
        {
            "stage_key": "stage-2-proof",
            "formula_stage_key": "proof",
            "semantic_role": "proof",
            "text": "Kekalkan bukti yang diluluskan.",
        },
    )
    result = _plan(stages=stages)
    assert [u.text for u in result.full_dialogue_plan.utterances] == [
        item["text"] for item in stages
    ]


def test_v2_empty_derived_projection_cannot_delete_approved_text():
    stages = deepcopy(STAGES)
    copy = _v2_copy(stages)
    copy.update({"hook": "", "usps": [], "cta": ""})
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=copy,
        resolved_block_plan=[8],
        target_language="BM_MS",
        wps_mode="SWEET",
        approved_dialogue=_approved(stages),
        shot_count_by_block=[2],
    )
    assert result.full_dialogue_plan.full_dialogue_text == _approved(stages)


def test_v2_path_records_no_compression_or_omission():
    result = _plan()
    receipt = result.full_dialogue_plan.compliance_metadata
    assert receipt["approved_dialogue_immutable"] is True
    assert receipt["compression_version"] == "immutable_approved_execution_text_v1"
    assert receipt["omitted_utterances"] == []
    assert result.full_dialogue_plan.actual_total_word_count == len(_approved().split())


def test_v2_extend_preserves_lossless_order_across_blocks():
    result = _plan(blocks=[8, 8])
    rendered = " ".join(a.exact_dialogue_slice for a in result.block_allocations)
    assert rendered == _approved()
    assert result.block_allocations[-1].final_cta_text == "Cuba sekarang."


def test_v2_rendered_block_concatenation_is_exact():
    result = _compile()
    rendered = " ".join(block["exact_dialogue_slice"] for block in result["prompt_blocks"])
    assert rendered == _approved()
    assert result["planner_result"]["full_dialogue_plan"]["full_dialogue_text"] == _approved()


def test_legacy_copy_path_keeps_legacy_compression_receipt():
    result = compile_ugc_video_prompt(
        product=PRODUCT,
        approved_package={"mode": "T2V", "scene_context": "a calm bathroom counter"},
        mode="T2V",
        source_mode="T2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        character_presence="FACELESS",
        copy_intelligence={
            "copy_source": "selected_copy_set",
            "hook": "Hook legacy.",
            "usps": ["Body legacy."],
            "cta": "Cuba legacy sekarang.",
        },
    )
    receipt = result["planner_result"]["full_dialogue_plan"]["compliance_metadata"]
    assert receipt["approved_dialogue_immutable"] is False
    assert receipt["compression_version"] == "dialogue_packable_compress_v1"


def test_faceless_prepare_compiler_accepts_short_exact_v2_route():
    result = _compile()
    assert result["character_presence"] == "FACELESS"
    assert result["generation_mode"] == "SINGLE"
    assert result["prompt_blocks"][0]["exact_dialogue_slice"] == _approved()


def test_prepare_compiler_has_no_provider_call_surface(monkeypatch):
    calls: list[object] = []

    def forbidden_provider_call(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("provider call reached provider-free prepare")

    monkeypatch.setattr("agent.services.make_video.start_generate", forbidden_provider_call)
    _compile()
    assert calls == []
