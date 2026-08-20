from __future__ import annotations

import json

import pytest

from agent.authority import product_readiness_applicability_registry as registry
from agent.models.creative_treatment import TreatmentActionStep
from agent.models.product_readiness import ProductReadinessEvaluateRequest
from agent.models.scene_choreography_v2 import (
    CHOREOGRAPHY_SCHEMA_VERSION,
    ChoreographyValidationError,
    EntityState,
)
from agent.services import product_treatment_template_service as template_service
from agent.services.canonical_prompt_compiler import compile_prompt_set
from agent.services.scene_choreography_catalog import (
    SPECS,
    action_coverage_receipt,
    all_choreography_variants,
    coverage_map,
    choreography_sha256,
    eligible_variants_for_character_presence,
    select_compatible_variant_for_strategy,
    select_variant_for_strategy,
)
from agent.services.scene_choreography_validator import validate_choreography_variant
from agent.services.scene_strategy_library import (
    SCENE_STRATEGIES,
    build_scene_strategy_context,
    resolve_scene_strategy,
    select_scene_strategy_variant,
)
from agent.services.scene_choreography_lineage import (
    assert_production_treatment_payload,
)
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt


def _product(name: str, **fields: object) -> dict[str, object]:
    return {
        "id": f"product-{name.casefold().replace(' ', '-')}",
        "name": name,
        "raw_product_title": name,
        **fields,
    }


def test_inventory_reconciles_with_live_library_and_workbook() -> None:
    rows = coverage_map()
    by_class = {key: 0 for key in ("P0_REWRITE", "P1_REWRITE", "P2_STATIC", "BLOCK")}
    for row in rows:
        by_class[str(row["audit_classification"])] += 1
    assert set(SCENE_STRATEGIES) == set(SPECS)
    assert len(SCENE_STRATEGIES) == 103
    assert sum(len(entry["allowed_actions"]) for entry in SCENE_STRATEGIES.values()) == 242
    assert by_class == {
        "P0_REWRITE": 67,
        "P1_REWRITE": 23,
        "P2_STATIC": 12,
        "BLOCK": 1,
    }
    assert {row["strategy_id"] for row in rows} == set(SCENE_STRATEGIES)
    for row in rows:
        if row["strategy_id"] == "GENERIC_FALLBACK":
            assert row["migration_status"] == "BLOCKED"
            assert row["choreography_variant_count"] == 0
            continue
        assert row["migration_status"] == "MIGRATED"
        assert row["choreography_variant_count"] >= 1
        assert row["validation_status"] == "VALID"


def test_all_242_actions_have_explicit_or_blocked_receipt() -> None:
    rows = action_coverage_receipt()
    assert len(rows) == 242
    blocked = [row for row in rows if row["coverage"] == "BLOCKED"]
    explicit = [row for row in rows if row["coverage"] == "EXPLICIT"]
    assert len(blocked) == 3
    assert len(explicit) == 239
    assert all(row["strategy_id"] == "GENERIC_FALLBACK" for row in blocked)
    assert all(row["choreography_id"] and row["step_numbers"] for row in explicit)
    assert all(row.get("coverage_status") == "COVERED" for row in explicit)
    assert all(row.get("exact_step_numbers") for row in explicit)
    assert all(row.get("structured_transition_signature") for row in explicit)
    assert all(
        row.get("coverage_kind")
        in {"COMPOSED_SEQUENCE", "ALTERNATIVE_VARIANT", "STATIC_LOCK"}
        for row in explicit
    )
    # No action may claim coverage only via intent_label — require source-tagged steps.
    catalog = all_choreography_variants()
    for row in explicit:
        found = False
        for cid in row["choreography_ids"]:
            for variant in catalog[str(row["strategy_id"])]:
                if variant.choreography_id != cid:
                    continue
                for step in variant.steps:
                    if int(row["action_index"]) in step.source_action_indexes:
                        found = True
                        break
        assert found, row["action_id"]


def test_semantic_source_mapping_not_fake_all_steps() -> None:
    oil = select_variant_for_strategy("TRADITIONAL_HERBAL_OIL", 0)
    # Continuity/final steps may be untagged; action steps must be sparse, not every step for every action.
    by_src: dict[int, list[int]] = {}
    for step in oil.steps:
        for idx in step.source_action_indexes:
            by_src.setdefault(idx, []).append(step.step_number)
    assert set(by_src) == {0, 1, 2, 3, 4}
    for idx, nums in by_src.items():
        assert nums != [s.step_number for s in oil.steps], f"action {idx} mapped to all steps"


def test_lip_color_four_physical_scenarios() -> None:
    variants = all_choreography_variants()["LIP_COLOR"]
    assert len(variants) == 4
    blobs = []
    for variant in variants:
        phys = " ".join(
            f"{st.entity_id}:{st.location}:{st.physical_state}"
            for step in variant.steps
            for st in step.resulting_states
        ).casefold()
        blobs.append((variant.intent_label.casefold(), phys, variant.steps))
    apply_b, swatch_b, mirror_b, bag_b = blobs
    assert "lips" in apply_b[0] and "lips" in apply_b[1]
    assert "swatch" in swatch_b[0] and "back of the hand" in swatch_b[1]
    assert "lips" not in swatch_b[1].split("back of the hand")[0] or "back of the hand" in swatch_b[1]
    # hand swatch must not claim lip application as resulting target product path exclusively lips without hand
    assert "back of the hand" in swatch_b[1]
    assert "mirror" in mirror_b[0] and "mirror" in mirror_b[1]
    assert "handbag" in bag_b[0] and ("handbag" in bag_b[1] or "bag" in bag_b[1])
    # Source indexes unique per scenario
    for i, variant in enumerate(variants):
        tagged = {idx for step in variant.steps for idx in step.source_action_indexes}
        assert tagged == {i}


def test_baby_wipes_three_scenarios() -> None:
    variants = all_choreography_variants()["BABY_WIPES"]
    assert len(variants) == 3
    seals = " ".join(s.transition_signature for s in variants[0].steps)
    pull = " ".join(s.transition_signature for s in variants[1].steps)
    bag = " ".join(s.transition_signature for s in variants[2].steps)
    assert "reseal" in seals
    assert "pull_one" in pull
    assert "into_bag" in bag or "bag" in bag


def test_apparel_four_scenarios() -> None:
    variants = all_choreography_variants()["APPAREL"]
    assert len(variants) == 4
    modes = [" ".join(s.transition_signature for s in v.steps) for v in variants]
    assert any("hanger" in m for m in modes)
    assert any("fit" in m or "wear" in m for m in modes)
    assert any("pinch" in m for m in modes)
    assert any("seam" in m for m in modes)


def test_electronics_small_device_four_scenarios() -> None:
    variants = all_choreography_variants()["ELECTRONICS_SMALL_DEVICE"]
    assert len(variants) == 4
    modes = [" ".join(s.transition_signature for s in v.steps) for v in variants]
    assert any("unbox" in m for m in modes)
    assert any("press" in m for m in modes)
    assert any("show" in m for m in modes)
    assert any("place" in m for m in modes)
    # Fail-closed: place path must not wear
    place = variants[3]
    blob = " ".join(s.action_instruction for s in place.steps).casefold()
    assert "do not wear" in blob or "wear path is not used" in blob


def test_no_positive_physical_branch_in_library() -> None:
    from agent.services.scene_choreography_scenarios import has_positive_physical_branch

    for strategy_id, variants in all_choreography_variants().items():
        for variant in variants:
            for step in variant.steps:
                assert not has_positive_physical_branch(step.action_instruction), (
                    f"{strategy_id} {variant.choreography_id} step {step.step_number}: "
                    f"{step.action_instruction}"
                )


def test_entity_locations_are_not_branching_or_paths() -> None:
    for strategy_id, variants in all_choreography_variants().items():
        for variant in variants:
            for step in variant.steps:
                for state in [*step.initial_states, *step.resulting_states]:
                    assert " or " not in state.location, (
                        f"{strategy_id} {variant.choreography_id} step {step.step_number} "
                        f"{state.entity_id} location={state.location}"
                    )


def test_every_production_variant_validates() -> None:
    catalog = all_choreography_variants()
    assert catalog["GENERIC_FALLBACK"] == ()
    for strategy_id, variants in catalog.items():
        if strategy_id == "GENERIC_FALLBACK":
            continue
        assert variants
        for variant in variants:
            validate_choreography_variant(variant)
            assert variant.schema_version == CHOREOGRAPHY_SCHEMA_VERSION
            assert variant.allowed_character_presence
            assert variant.steps[0].start_s == 0.0
            assert variant.steps[-1].is_final_lock
            assert "product" in {state.entity_id for state in variant.steps[0].initial_states}


def test_traditional_herbal_oil_8s_fixture_reaches_compiled_prompt() -> None:
    strategy = resolve_scene_strategy(
        _product(
            "Minyak Warisan Cap Burung 25ml",
            product_type="TRADITIONAL_HERBAL_OIL",
            product_physics="TRADITIONAL_HERBAL_OIL_BOTTLE",
        )
    )
    selected = select_scene_strategy_variant(strategy, 0)
    context = build_scene_strategy_context(strategy, variation_index=0)
    compiled = compile_ugc_video_prompt(
        product=_product(
            "Minyak Warisan Cap Burung 25ml",
            product_type="TRADITIONAL_HERBAL_OIL",
            product_physics="TRADITIONAL_HERBAL_OIL_BOTTLE",
        ),
        approved_package={},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="SINGLE",
        duration_seconds=8,
        character_presence="FACELESS",
        target_language="BM_MS",
    )
    prompt = str(compiled["final_compiled_prompt_text"])
    assert selected["choreography_id"] == "traditional_herbal_oil.v0"
    assert selected["allowed_character_presence"]
    assert "FACELESS" in selected["allowed_character_presence"]
    assert compiled["scene_choreography"]["choreography_id"] == selected[
        "choreography_id"
    ]
    assert compiled["scene_choreography"]["choreography_sha256"] == selected[
        "choreography_sha256"
    ]
    context_needles = (
        "0.0-1.0s",
        "already present in the avatar's support hand",
        "rotates it exactly 90 degrees",
        "Do not fully unscrew or remove the cap",
        "tilts the same bottle toward the same wrist/forearm",
        "places it label-forward on the table",
        "massages the same external wrist/forearm",
        "bottle remains stationary and visible on the table",
        "7.7-8.0s",
        "Hold the final state",
    )
    for needle in context_needles:
        assert needle in context

    prompt_needles = (
        "0.0-1.0s",
        "already present in the faceless subject's support hand",
        "rotates it exactly 90 degrees",
        "Do not fully unscrew or remove the cap",
        "tilts the same bottle toward the same wrist/forearm",
        "places it label-forward on the table",
        "massages the same external wrist/forearm",
        "bottle remains stationary and visible on the table",
        "7.7-8.0s",
        "Hold the final state",
    )
    for needle in prompt_needles:
        assert needle in prompt
    assert "Allowed product action:" not in prompt


def test_compatible_selection_skips_face_required_variants_for_faceless() -> None:
    strategy = resolve_scene_strategy(
        _product("Velvet Lip Tint", category="Beauty & Personal Care", type="Lip Makeup")
    )
    eligible = eligible_variants_for_character_presence("LIP_COLOR", "FACELESS")
    assert [variant.choreography_id for variant in eligible] == [
        "lip_color.v1",
        "lip_color.v3",
    ]
    assert select_variant_for_strategy("LIP_COLOR", 0).choreography_id == "lip_color.v0"

    selected = select_compatible_variant_for_strategy("LIP_COLOR", 0, "FACELESS")
    rotated = select_compatible_variant_for_strategy("LIP_COLOR", 1, "FACELESS")
    wrapped = select_compatible_variant_for_strategy("LIP_COLOR", 2, "FACELESS")
    assert selected.choreography_id == "lip_color.v1"
    assert rotated.choreography_id == "lip_color.v3"
    assert wrapped.choreography_id == "lip_color.v1"
    assert "FACELESS" in selected.allowed_character_presence
    assert choreography_sha256(selected) == choreography_sha256(
        select_compatible_variant_for_strategy("LIP_COLOR", 0, "FACELESS")
    )

    selected_scene = select_scene_strategy_variant(
        strategy,
        0,
        character_presence="FACELESS",
    )
    assert selected_scene["choreography_id"] == selected.choreography_id
    assert selected_scene["compatible_contexts"] == selected.compatible_contexts

    compiled = compile_ugc_video_prompt(
        product=_product(
            "Velvet Lip Tint",
            category="Beauty & Personal Care",
            type="Lip Makeup",
        ),
        approved_package={},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="SINGLE",
        duration_seconds=8,
        character_presence="FACELESS",
        target_language="BM_MS",
    )
    assert compiled["scene_choreography"]["choreography_id"] == selected.choreography_id
    assert compiled["scene_choreography"]["choreography_sha256"] == choreography_sha256(
        selected
    )


def test_compatible_selection_fails_closed_when_no_variant_is_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.services.scene_choreography_catalog as catalog

    face_required = all_choreography_variants()["LIP_COLOR"][0]
    monkeypatch.setattr(
        catalog,
        "list_production_variants",
        lambda _strategy_id: (face_required,),
    )
    with pytest.raises(ChoreographyValidationError) as exc:
        select_compatible_variant_for_strategy("LIP_COLOR", 0, "FACELESS")
    assert exc.value.code == "ERR_FACELESS_CHOREOGRAPHY_INCOMPATIBLE"
    assert exc.value.strategy_id == "LIP_COLOR"


def test_visible_creator_selection_preserves_raw_variant_order() -> None:
    strategy = resolve_scene_strategy(
        _product("Velvet Lip Tint", category="Beauty & Personal Care", type="Lip Makeup")
    )
    raw = select_variant_for_strategy("LIP_COLOR", 0)
    selected = select_scene_strategy_variant(
        strategy,
        0,
        character_presence="VISIBLE_CREATOR",
    )
    assert raw.choreography_id == "lip_color.v0"
    assert selected["choreography_id"] == raw.choreography_id


def test_roll_on_choreography_is_product_appropriate() -> None:
    strategy = resolve_scene_strategy(
        _product("Bosmax Herbs 5 ML", category="Male Health", type="Herbal Oil Roll On")
    )
    context = build_scene_strategy_context(strategy, variation_index=0)
    assert strategy["strategy_id"] == "HERBAL_ROLL_ON_OIL"
    assert "removes the cap and places the same cap visibly on the table" in context
    assert "rolls one controlled pass" in context
    assert "replace the same cap" in context
    assert "90 degrees" not in context


def test_static_strategy_has_global_continuity_lock() -> None:
    variant = select_variant_for_strategy("BOOK", 0)
    assert variant.classification == "P2_STATIC"
    assert variant.family == "STATIC_LOCK"
    assert any("first-frame presence" in rule for rule in variant.steps[0].continuity_rules)
    assert variant.steps[-1].is_final_lock


def test_broll_match_cut_declares_outgoing_and_incoming_state() -> None:
    variants = all_choreography_variants()["HOUSEHOLD_CLEANER"]
    broll = next(variant for variant in variants if variant.family == "BROLL_MATCH_CUT")
    cuts = [step.camera_cut_boundary for step in broll.steps]
    assert "OUTGOING" in cuts
    assert "REESTABLISH" in cuts
    validate_choreography_variant(broll)


def test_selection_is_a_whole_variant() -> None:
    strategy = resolve_scene_strategy(
        _product("Velvet Lip Tint", category="Beauty & Personal Care", type="Lip Makeup")
    )
    first = select_scene_strategy_variant(strategy, 0)
    second = select_scene_strategy_variant(strategy, 1)
    assert first["choreography_id"] != second["choreography_id"]
    assert first["scene_context"]
    assert first["camera_route"]
    assert first["choreography_schema_version"] == CHOREOGRAPHY_SCHEMA_VERSION


@pytest.mark.parametrize("mode", ("HYBRID", "FRAMES", "T2V"))
def test_f2v_t2v_hybrid_compile_same_oil_choreography(mode: str) -> None:
    product = _product(
        "Minyak Warisan Cap Burung 25ml",
        product_type="TRADITIONAL_HERBAL_OIL",
    )
    compiled = compile_ugc_video_prompt(
        product=product,
        approved_package={},
        mode="F2V" if mode != "T2V" else "T2V",
        source_mode=mode,
        generation_mode="SINGLE",
        duration_seconds=8,
        character_presence="FACELESS",
        target_language="BM_MS",
    )
    prompt = str(compiled["final_compiled_prompt_text"])
    assert "rotates it exactly 90 degrees" in prompt
    assert "places it label-forward on the table" in prompt


def test_generic_fallback_cannot_be_selected_or_compiled() -> None:
    strategy = resolve_scene_strategy(_product("Opaque Novelty Object 742"))
    assert strategy["strategy_id"] == "GENERIC_FALLBACK"
    with pytest.raises(ChoreographyValidationError, match="GENERIC_FALLBACK_BLOCKED"):
        select_scene_strategy_variant(strategy, 0)
    with pytest.raises(ValueError, match="GENERIC_FALLBACK_BLOCKED"):
        compile_ugc_video_prompt(
            product=_product("Opaque Novelty Object 742"),
            approved_package={},
            mode="F2V",
            source_mode="HYBRID",
            generation_mode="SINGLE",
            duration_seconds=8,
            character_presence="FACELESS",
            target_language="BM_MS",
        )


def test_treatment_template_emits_full_sequence_without_placeholders() -> None:
    profile = registry.resolve_applicability_profile("TRADITIONAL_HERBAL_OIL")
    template = template_service.resolve_treatment_template(
        context=ProductReadinessEvaluateRequest(
            product_id="product-oil",
            allowed_action_index=0,
            creative_format="PGC",
            logical_mode="HYBRID",
            generation_mode="SINGLE",
            model_key="veo_3_1_fast",
            duration_seconds=8,
        ),
        profile=profile,
        requirements=[],
    )
    dumped = json.dumps(template.model_dump(mode="json"))
    assert template.template_version == "product-treatment-template-v2"
    assert template.choreography_id == "traditional_herbal_oil.v0"
    assert len(template.action_sequence) == 6
    assert "governed initial product state" not in dumped
    assert "governed resulting product state" not in dumped
    assert template.action_sequence[0].start_time_seconds == 0.0
    assert template.action_sequence[-1].end_time_seconds == 8.0
    assert any("table" in (step.product_location or "") for step in template.action_sequence)


def test_readiness_indexes_choreography_variants() -> None:
    profile = registry.resolve_applicability_profile("LIP_COLOR")
    assert profile.profile_version == "product-readiness-applicability-v2"
    assert profile.indexed_actions
    assert all(action.choreography_id for action in profile.indexed_actions)
    fallback = registry.resolve_applicability_profile("GENERIC_FALLBACK")
    assert fallback.supported is False
    assert fallback.indexed_actions == []


def test_negative_product_appears_after_start() -> None:
    variant = select_variant_for_strategy("TRADITIONAL_HERBAL_OIL", 0).model_copy(deep=True)
    variant.steps[0].initial_states[0] = EntityState(
        entity_id="product",
        location="off-frame",
        custody="TABLE",
        visible=False,
        physical_state="not yet present",
    )
    with pytest.raises(ChoreographyValidationError, match="FIRST_FRAME_PRODUCT_MUST_BE_VISIBLE"):
        validate_choreography_variant(variant)


def test_negative_state_chain_break() -> None:
    variant = select_variant_for_strategy("TRADITIONAL_HERBAL_OIL", 0).model_copy(deep=True)
    variant.steps[1].initial_states = [
        state.model_copy(update={"location": "teleported somewhere else"})
        if state.entity_id == "product"
        else state
        for state in variant.steps[1].initial_states
    ]
    with pytest.raises(ChoreographyValidationError, match="STATE_CHAIN_BREAK"):
        validate_choreography_variant(variant)


def test_negative_timing_overlap() -> None:
    variant = select_variant_for_strategy("BOOK", 0).model_copy(deep=True)
    variant.steps[1] = variant.steps[1].model_copy(update={"start_s": 1.0, "end_s": 2.0})
    with pytest.raises(ChoreographyValidationError, match="STEP_TIME_OVERLAP"):
        validate_choreography_variant(variant)


def test_compiler_rejects_placeholder_and_legacy_atomic_treatment() -> None:
    product = _product("Velvet Lip Tint", category="Beauty & Personal Care", type="Lip Makeup")
    with pytest.raises(ValueError, match="PLACEHOLDER_STATE_FORBIDDEN"):
        compile_prompt_set(
            source_mode="HYBRID",
            duration_seconds=8,
            product=product,
            copy={"hook": "x", "usps": ["y"], "cta": "z"},
            creative_treatment={
                "generation_mode": "SINGLE",
                "duration_seconds": 8,
                "format": "PGC",
                "action_sequence": [
                    {
                        "sequence": 1,
                        "action_text": "hold it",
                        "actor_role": "PRODUCT",
                        "initial_state": "governed initial product state",
                        "resulting_state": "governed resulting product state",
                    },
                    {
                        "sequence": 2,
                        "action_text": "still hold it",
                        "actor_role": "PRODUCT",
                        "initial_state": "ok",
                        "resulting_state": "ok",
                    },
                ],
            },
        )
    with pytest.raises(ChoreographyValidationError, match="LEGACY_ATOMIC_TREATMENT_REJECTED"):
        assert_production_treatment_payload(
            strategy_id="LIP_COLOR",
            decoded={
                "action_sequence": [
                    {
                        "sequence": 1,
                        "action_text": "hold the product label-forward",
                        "actor_role": "PRODUCT",
                        "initial_state": "in hand",
                        "resulting_state": "in hand",
                    }
                ]
            },
        )
    with pytest.raises(ChoreographyValidationError, match="STALE_TREATMENT_LINEAGE"):
        assert_production_treatment_payload(
            strategy_id="LIP_COLOR",
            decoded={
                "choreography_id": "lip_color.v0",
                "choreography_sha256": "0" * 64,
                "action_sequence": [
                    {"sequence": 1, "action_text": "a", "initial_state": "x", "resulting_state": "y"},
                    {"sequence": 2, "action_text": "b", "initial_state": "y", "resulting_state": "z"},
                ],
            },
        )


def test_treatment_action_step_accepts_optional_v2_fields() -> None:
    step = TreatmentActionStep(
        sequence=1,
        allowed_action_index=0,
        action_text="already present",
        actor_role="PRESENTER",
        initial_state="product in support hand",
        resulting_state="product in support hand",
        start_time_seconds=0.0,
        end_time_seconds=1.0,
        support_hand="SUPPORT_HAND",
        active_hand="ACTIVE_HAND",
    )
    assert step.start_time_seconds == 0.0
