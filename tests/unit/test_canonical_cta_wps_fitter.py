"""System-wide CTA WPS spoken-fitter regression matrix.

Covers T2V / F2V(FRAMES) / I2V(INGREDIENTS) / HYBRID for SINGLE+EXTEND,
plus P6 logical modes, without provider calls or Approved Copy mutation.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent.services.canonical_cta_fitter import (
    FIT_BLOCKED,
    FIT_DETERMINISTIC_COMPACT,
    FIT_EXACT,
    fit_spoken_cta,
)
from agent.services.canonical_prompt_compiler import dialogue_word_budget
from agent.services.full_storyboard_extend_planner import (
    PlannerValidationError,
    plan_full_storyboard,
)
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

PRODUCT = {
    "id": "prod-cta-fitter",
    "name": "Bosmax Calm Daily Serum",
    "category": "Beauty & Personal Care",
}

SHORT_CTA = "Kalau sesuai dengan rutin korang, cuba sekarang."
OVERSIZED_CTA = (
    "Kalau sesuai dengan rutin korang dan korang rasa produk ni memang berbaloi "
    "untuk dicuba setiap hari di rumah, terus checkout di beg kuning sekarang ya."
)
IMPOSSIBLE_CTA = " ".join(["Tindakan"] * 23)

BASE_COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "HSO",
    "hook": "Kulit nampak letih bila rutin rasa terlalu berat.",
    "subhook": "Aku pilih langkah yang rasa ringan untuk dibuat setiap hari.",
    "usps": [
        "Tekstur serum ini cepat terasa kemas pada kulit.",
        "Botolnya mudah dicapai masa rutin pagi.",
    ],
    "cta": OVERSIZED_CTA,
    "cta_type": "direct_checkout",
}


def _copy(**overrides: Any) -> dict[str, Any]:
    row = deepcopy(BASE_COPY)
    row.update(overrides)
    return row


def _assert_final_only_cta(result, spoken_cta: str, canonical_cta: str) -> dict[str, Any]:
    fit = result.full_dialogue_plan.compliance_metadata["cta_fit"]
    assert fit["canonical_cta_text"] == canonical_cta
    assert fit["spoken_cta_text"] == spoken_cta
    assert fit["spoken_word_count"] <= fit["final_block_word_budget"]
    assert fit["spoken_word_count"] == len(spoken_cta.split())
    cta_roles = [u for u in result.full_dialogue_plan.utterances if u.role == "CTA"]
    assert len(cta_roles) == 1
    assert cta_roles[0].text == spoken_cta
    final = result.block_allocations[-1]
    assert final.is_final
    assert final.final_cta_text == spoken_cta
    assert spoken_cta in final.exact_dialogue_slice
    for prior in result.block_allocations[:-1]:
        assert spoken_cta not in prior.exact_dialogue_slice
        assert prior.final_cta_text == ""
        assert all(u.role != "CTA" for u in prior.assigned_dialogue_utterances)
    # Canonical approved text is provenance only — not mutated in metadata.
    assert result.full_dialogue_plan.approved_copy_provenance["canonical_cta_text"] == canonical_cta
    return fit


@pytest.mark.parametrize(
    ("label", "block_plan", "wps_mode"),
    [
        ("t2v_single_8s", [8], "SWEET"),
        ("t2v_single_10s", [10], "SWEET"),
        ("t2v_extend_8s", [8, 8], "SWEET"),
        ("t2v_single_8s_safe", [8], "SAFE"),
        ("t2v_single_10s_safe", [10], "SAFE"),
    ],
)
def test_t2v_oversized_cta_compacts_within_final_budget(label: str, block_plan: list[int], wps_mode: str) -> None:
    del label
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_BLOCKS",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=_copy(),
        resolved_block_plan=block_plan,
        target_language="BM_MS",
        wps_mode=wps_mode,
        shot_count_by_block=[2] * len(block_plan),
    )
    fit = result.full_dialogue_plan.compliance_metadata["cta_fit"]
    assert fit["fit_status"] in {FIT_EXACT, FIT_DETERMINISTIC_COMPACT}
    if len(OVERSIZED_CTA.split()) > dialogue_word_budget(block_plan[-1], "BM_MS", wps_mode=wps_mode):
        assert fit["fit_status"] == FIT_DETERMINISTIC_COMPACT
        assert fit["was_compacted"] is True
    _assert_final_only_cta(result, fit["spoken_cta_text"], OVERSIZED_CTA)


@pytest.mark.parametrize("source_mode", ["FRAMES", "INGREDIENTS", "HYBRID"])
@pytest.mark.parametrize(
    ("block_plan", "gen"),
    [
        ([8], "SINGLE"),
        ([8, 8], "EXTEND"),
        ([10], "SINGLE"),
        ([10, 10], "EXTEND"),
    ],
)
def test_reference_lanes_oversized_cta_compacts(source_mode: str, block_plan: list[int], gen: str) -> None:
    del gen
    result = plan_full_storyboard(
        route_id="GOOGLE_FLOW_INDEPENDENT_BLOCKS",
        source_mode=source_mode,
        product=PRODUCT,
        copy_intelligence=_copy(),
        resolved_block_plan=block_plan,
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2] * len(block_plan),
    )
    fit = _assert_final_only_cta(
        result,
        result.full_dialogue_plan.compliance_metadata["cta_fit"]["spoken_cta_text"],
        OVERSIZED_CTA,
    )
    assert fit["fit_status"] in {FIT_EXACT, FIT_DETERMINISTIC_COMPACT}
    assert fit["spoken_word_count"] <= dialogue_word_budget(block_plan[-1], "BM_MS", wps_mode="SWEET")


@pytest.mark.parametrize(
    ("mode", "source_mode", "generation_mode", "duration"),
    [
        ("T2V", "T2V", "SINGLE", 8),
        ("T2V", "T2V", "EXTEND", 16),
        ("F2V", "FRAMES", "SINGLE", 8),
        ("F2V", "FRAMES", "EXTEND", 16),
        ("I2V", "INGREDIENTS", "SINGLE", 8),
        ("I2V", "INGREDIENTS", "EXTEND", 16),
        ("F2V", "HYBRID", "SINGLE", 8),
        ("F2V", "HYBRID", "EXTEND", 16),
    ],
)
def test_compile_ugc_video_prompt_lanes_accept_oversized_cta(
    mode: str,
    source_mode: str,
    generation_mode: str,
    duration: int,
) -> None:
    kwargs: dict[str, Any] = dict(
        product=PRODUCT,
        approved_package={"scene_context": "a bright lived-in bathroom counter"},
        mode=mode,
        source_mode=source_mode,
        generation_mode=generation_mode,
        engine_duration_target="GOOGLE_FLOW",
        target_language="BM_MS",
        copy_intelligence=_copy(),
        wps_mode="SWEET",
    )
    if source_mode in {"T2V", "HYBRID"}:
        kwargs["avatar_id"] = "BOS_F_AINA_01"
    if generation_mode == "EXTEND":
        kwargs["requested_total_duration_seconds"] = duration
        kwargs["duration_seconds"] = 8
    else:
        kwargs["duration_seconds"] = duration
    result = compile_ugc_video_prompt(**kwargs)
    planner = result["planner_result"]
    fit = planner["full_dialogue_plan"]["compliance_metadata"]["cta_fit"]
    assert fit["canonical_cta_text"] == OVERSIZED_CTA
    assert fit["spoken_word_count"] <= fit["final_block_word_budget"]
    assert fit["fit_status"] in {FIT_EXACT, FIT_DETERMINISTIC_COMPACT}
    spoken = fit["spoken_cta_text"]
    allocations = planner["block_allocations"]
    assert allocations[-1]["final_cta_text"] == spoken
    assert spoken in allocations[-1]["exact_dialogue_slice"]
    for prior in allocations[:-1]:
        assert spoken not in prior["exact_dialogue_slice"]
        assert prior["final_cta_text"] in ("", None)
    # No provider surface on compile path.
    assert "provider_call" not in result
    assert result.get("provider_invoked") in (None, False)


def test_short_cta_remains_exact_and_unchanged() -> None:
    result = plan_full_storyboard(
        route_id="X",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=_copy(cta=SHORT_CTA),
        resolved_block_plan=[8],
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    fit = result.full_dialogue_plan.compliance_metadata["cta_fit"]
    assert fit["fit_status"] == FIT_EXACT
    assert fit["was_compacted"] is False
    assert fit["spoken_cta_text"] == SHORT_CTA
    assert fit["canonical_cta_text"] == SHORT_CTA


def test_impossible_cta_still_fail_closed() -> None:
    with pytest.raises(PlannerValidationError, match="FINAL_CTA_CANNOT_FIT_WPS_BUDGET"):
        plan_full_storyboard(
            route_id="X",
            source_mode="T2V",
            product=PRODUCT,
            copy_intelligence=_copy(cta=IMPOSSIBLE_CTA),
            resolved_block_plan=[8],
            target_language="BM_MS",
            wps_mode="SWEET",
        )
    blocked = fit_spoken_cta(
        canonical_cta_text=IMPOSSIBLE_CTA,
        final_block_word_budget=dialogue_word_budget(8, "BM_MS", wps_mode="SWEET"),
        target_language="BM_MS",
        wps_mode="SWEET",
        cta_type="direct_checkout",
    )
    assert blocked.fit_status == FIT_BLOCKED
    assert blocked.spoken_cta_text == ""


def test_compact_is_deterministic_and_fingerprint_stable() -> None:
    kwargs = dict(
        route_id="X",
        source_mode="HYBRID",
        product=PRODUCT,
        copy_intelligence=_copy(),
        resolved_block_plan=[8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2],
    )
    a = plan_full_storyboard(**kwargs)
    b = plan_full_storyboard(**kwargs)
    assert a.planner_fingerprint == b.planner_fingerprint
    assert a.input_fingerprint == b.input_fingerprint
    assert (
        a.full_dialogue_plan.compliance_metadata["cta_fit"]
        == b.full_dialogue_plan.compliance_metadata["cta_fit"]
    )
    fit_a = fit_spoken_cta(
        canonical_cta_text=OVERSIZED_CTA,
        final_block_word_budget=22,
        target_language="BM_MS",
        wps_mode="SWEET",
        cta_type="direct_checkout",
    )
    fit_b = fit_spoken_cta(
        canonical_cta_text=OVERSIZED_CTA,
        final_block_word_budget=22,
        target_language="BM_MS",
        wps_mode="SWEET",
        cta_type="direct_checkout",
    )
    assert fit_a == fit_b


def test_no_duplicate_cta_after_compaction() -> None:
    result = plan_full_storyboard(
        route_id="X",
        source_mode="T2V",
        product=PRODUCT,
        copy_intelligence=_copy(),
        resolved_block_plan=[8, 8, 8],
        target_language="BM_MS",
        wps_mode="SWEET",
        shot_count_by_block=[2, 2, 2],
    )
    spoken = result.full_dialogue_plan.compliance_metadata["cta_fit"]["spoken_cta_text"]
    texts = [u.text for u in result.full_dialogue_plan.utterances if u.role == "CTA"]
    assert texts == [spoken]
    # Canonical long form must not also appear as a non-CTA utterance.
    for u in result.full_dialogue_plan.utterances:
        if u.role != "CTA":
            assert u.text != OVERSIZED_CTA


@pytest.mark.asyncio
@pytest.mark.parametrize("logical_mode", ["T2V", "F2V", "I2V", "HYBRID"])
async def test_p6_compile_video_routes_through_shared_wgp_and_cta_fitter(
    logical_mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P6 must not re-implement fitting — it routes through WGP create_* → compile_ugc."""
    from agent.services import creative_production_compile_service as compiler

    source_mode = {
        "T2V": "T2V",
        "F2V": "FRAMES",
        "I2V": "INGREDIENTS",
        "HYBRID": "HYBRID",
    }[logical_mode]
    compile_mode = "T2V" if logical_mode == "T2V" else ("I2V" if logical_mode == "I2V" else "F2V")

    compiled = compile_ugc_video_prompt(
        product=PRODUCT,
        approved_package={"scene_context": "bathroom counter"},
        mode=compile_mode,
        source_mode=source_mode,
        generation_mode="SINGLE",
        engine_duration_target="GOOGLE_FLOW",
        duration_seconds=8,
        target_language="BM_MS",
        copy_intelligence=_copy(),
        wps_mode="SWEET",
        **({"avatar_id": "BOS_F_AINA_01"} if source_mode in {"T2V", "HYBRID"} else {}),
    )
    fit = compiled["planner_result"]["full_dialogue_plan"]["compliance_metadata"]["cta_fit"]
    assert fit["canonical_cta_text"] == OVERSIZED_CTA
    assert fit["spoken_word_count"] <= fit["final_block_word_budget"]
    assert fit["fit_status"] in {FIT_EXACT, FIT_DETERMINISTIC_COMPACT}

    create_name = {
        "T2V": "create_t2v_generation_package",
        "F2V": "create_f2v_generation_package",
        "I2V": "create_i2v_generation_package",
        "HYBRID": "create_hybrid_generation_package",
    }[logical_mode]
    fake = AsyncMock(
        return_value={
            "workspace_generation_package_id": f"wgp-p6-{logical_mode.lower()}",
            "status": "READY_MANUAL",
            "blockers_json": "[]",
            "final_prompt_text": compiled.get("final_prompt_text") or "Compiled oversized-CTA prompt.",
            "prompt_fingerprint": compiled.get("prompt_fingerprint") or "prompt-fp-cta",
            "planner_result": compiled.get("planner_result"),
        }
    )
    monkeypatch.setattr(compiler.wgp_service, create_name, fake)
    monkeypatch.setattr(
        compiler,
        "resolve_item_treatment",
        AsyncMock(
            return_value={
                "treatment_id": "trt-1",
                "treatment_sha256": "sha-trt",
                "visual_fingerprint_sha256": "sha-vis",
                "dependency_hashes": {},
                "variation_group": "vg",
                "format": logical_mode,
                "copy_set_id": "copy-1",
                "segment_plan": [],
                "shot_grammar": {"style": "UGC", "pace": "natural"},
                "compatibility_profile": {"source_mode": source_mode},
            }
        ),
    )

    package_id, prompt_fp, evidence = await compiler._compile_video(
        {
            "item_id": f"p6item-{logical_mode.lower()}",
            "product_id": PRODUCT["id"],
            "creative_dna_sha256": f"dna-{logical_mode.lower()}",
        },
        {
            "plan_id": f"p6plan-{logical_mode.lower()}",
            "logical_mode": logical_mode,
            "execution_policy_json": '{"aspect":"9:16"}',
        },
        {
            "duration_seconds": "8",
            "copy_set_id": "copy-1",
            "generation_mode": "SINGLE",
            "scene_strategy_context": "Approved scene.",
            "model_key": "veo_3_1_lite",
            "finished_frame_asset_id": "asset-frame",
            "product_reference_asset_id": "asset-product",
            "character_asset_id": "asset-character",
            "scene_asset_id": "asset-scene",
            "style_asset_id": "asset-style",
            "avatar_code": "BOS_F_01",
        },
    )
    assert package_id == f"wgp-p6-{logical_mode.lower()}"
    assert prompt_fp
    assert evidence["logical_mode"] == logical_mode
    assert fake.await_count == 1
    # Shared compiler already proved oversized CTA fits; P6 only routes to it.


def test_ui_surfaces_cta_fit_diagnostics_contract() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    wgp = (root / "dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx").read_text(encoding="utf-8")
    operator = (root / "dashboard/src/pages/OperatorPage.tsx").read_text(encoding="utf-8")
    types = (root / "dashboard/src/types/index.ts").read_text(encoding="utf-8")
    assert "cta-fit-diagnostics" in wgp
    assert "operator-cta-fit-diagnostics" in operator
    assert "StoryboardCtaFitDiagnostics" in types
    assert "was_compacted" in types
