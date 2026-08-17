"""Synthetic golden coverage for provider-free Storyboard Landbank V3 validators."""

from __future__ import annotations

import inspect
import pytest

from agent.authority.copy_blueprint_v2_authority import (
    formula_version,
    required_formula_stage_keys,
    strict_formula_contract,
)
from agent.models.copy_blueprint_v2 import EvidenceFact, EvidenceRegistry, digest_evidence_text
from agent.models.storyboard_landbank_v3 import (
    V3Angle,
    V3BridgeContract,
    V3DurationProjection,
    V3FormulaStage,
    V3FormulaRef,
    V3MasterStoryboard,
    V3Objective,
    V3ProductTruthLineage,
    V3RevisionRef,
    V3SeamState,
    V3StoryboardComponent,
    V3StorylineFamily,
    V3ValidationReceipt,
    deterministic_digest,
    digest_text,
    exact_resolved_content_fingerprint,
    master_content_digest,
    projection_content_digest,
    validation_receipt_digest,
    word_count,
)
from agent.services import canonical_prompt_compiler as canonical
from agent.services.storyboard_landbank_v3_validators import (
    BridgeContinuityValidator,
    ComponentStageValidator,
    DeterministicDigestValidator,
    DurationProjectionValidator,
    EvidenceLineageValidator,
    ExactDuplicateValidator,
    FormulaContractValidator,
    MasterStoryboardValidator,
    RevisionImmutabilityValidator,
    StorylineCompatibilityValidator,
)


CANONICAL_FORMULAS = ("PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA")


def _truth() -> V3ProductTruthLineage:
    return V3ProductTruthLineage(
        product_id="synthetic-product",
        snapshot_id="synthetic-snapshot-1",
        snapshot_version=1,
        snapshot_digest="c" * 64,
        snapshot_status="APPROVED",
    )


def _registry() -> EvidenceRegistry:
    text = "The synthetic product has a lightweight daily formula."
    return EvidenceRegistry(
        facts=(
            EvidenceFact(
                snapshot_id="synthetic-snapshot-1",
                fact_id="fact-lightweight",
                product_id="synthetic-product",
                fact_kind="PRODUCT_ATTRIBUTE",
                text=text,
                text_digest=digest_evidence_text(text),
                snapshot_version=1,
                snapshot_status="APPROVED",
                approved=True,
                source_ref="synthetic-fixture",
            ),
        )
    )


def _evidence_ids_digest(ids: tuple[str, ...] | list[str]) -> str:
    return deterministic_digest(list(ids))


def _receipt(name: str, *, valid: bool = True) -> V3ValidationReceipt:
    issue_codes = () if valid else ("SYNTHETIC_FAILURE",)
    base = V3ValidationReceipt(
        validator=name,
        validator_version="storyboard-landbank-v3-validator-1",
        valid=valid,
        issue_codes=issue_codes,
        receipt_digest="0" * 64,
    )
    return base.model_copy(update={"receipt_digest": validation_receipt_digest(base)})


def _semantic_class(formula_id: str, stage_key: str) -> str:
    contract = strict_formula_contract(formula_id)
    hook = contract["output_mapping"]["hook"]
    cta = contract["output_mapping"]["cta"]
    hook_keys = {hook} if isinstance(hook, str) else set(hook)
    cta_keys = {cta} if isinstance(cta, str) else set(cta)
    if stage_key in hook_keys:
        return "HOOK"
    if stage_key in cta_keys:
        return "CTA"
    return "BODY_CORE"


def _component(
    *,
    component_id: str,
    formula: V3FormulaRef,
    objective: V3Objective,
    angle_ref: V3RevisionRef,
    family_ref: V3RevisionRef,
    truth: V3ProductTruthLineage,
    semantic_class: str,
    stage_keys: tuple[str, ...],
    coverage: tuple[int, ...],
    text: str,
    entry: str,
    exit: str,
    evidence_ids: tuple[str, ...] = ("fact-lightweight",),
    claim_bearing: bool = True,
) -> V3StoryboardComponent:
    return V3StoryboardComponent(
        component_id=component_id,
        revision=1,
        product_id=truth.product_id,
        product_truth=truth,
        objective=objective,
        angle=angle_ref,
        storyline_family=family_ref,
        formula=formula,
        semantic_class=semantic_class,
        formula_stage_keys=stage_keys,
        ordered_stage_coverage=coverage,
        authored_text=text,
        entry_key=entry,
        exit_key=exit,
        bridge_contract=V3BridgeContract(entry_key=entry, exit_key=exit),
        evidence_fact_ids=evidence_ids,
        evidence_digest=_evidence_ids_digest(evidence_ids),
        claim_bearing=claim_bearing,
        content_digest=digest_text(text),
        semantic_fingerprint=None,
        word_count=word_count(text),
        status="VALIDATED",
        source="synthetic-fixture",
        created_at="2026-08-17T00:00:00Z",
        created_by="synthetic-owner",
    )


def _context(formula_id: str = "PAS", master_id: str | None = None) -> dict:
    truth = _truth()
    objective = V3Objective(objective_id="objective-1", definition="Drive a safe product trial.")
    formula = V3FormulaRef(formula_id=formula_id, formula_version=formula_version(formula_id))
    angle_ref = V3RevisionRef(entity_id=f"angle-{formula_id.lower()}", revision=1)
    family_ref = V3RevisionRef(entity_id=f"family-{formula_id.lower()}", revision=1)
    evidence_ids = ("fact-lightweight",)
    angle = V3Angle(
        angle_id=angle_ref.entity_id,
        revision=1,
        product_id=truth.product_id,
        product_truth=truth,
        definition="A lightweight daily routine angle.",
        objective_compatibility={"objective_ids": [objective.objective_id]},
        audience_compatibility={"audience": ["daily-routine"]},
        evidence_fact_ids=evidence_ids,
        evidence_digest=_evidence_ids_digest(evidence_ids),
        formula=formula,
        source="synthetic-fixture",
        status="VALIDATED",
        angle_digest="a" * 64,
        created_at="2026-08-17T00:00:00Z",
        created_by="synthetic-owner",
    )
    family = V3StorylineFamily(
        family_id=family_ref.entity_id,
        revision=1,
        product_id=truth.product_id,
        product_truth=truth,
        angle=angle_ref,
        formula=formula,
        objective_compatibility={"objective_ids": [objective.objective_id]},
        reviewed_definition="A single continuous product-routine route.",
        source="synthetic-fixture",
        status="VALIDATED",
        family_digest="b" * 64,
        created_at="2026-08-17T00:00:00Z",
        created_by="synthetic-owner",
    )

    stages: list[V3FormulaStage] = []
    components: list[V3StoryboardComponent] = []
    required = tuple(required_formula_stage_keys(formula_id))
    for index, stage_key in enumerate(required):
        entry = "arc:start" if index == 0 else f"arc:{index - 1}"
        exit = "arc:end" if index == len(required) - 1 else f"arc:{index}"
        text = f"{formula_id} {stage_key} synthetic fact-safe copy"
        component_id = f"component-{formula_id.lower()}-{stage_key}"
        stage_ref = V3RevisionRef(entity_id=component_id, revision=1)
        stage = V3FormulaStage(
            stage_key=f"stage-{stage_key}",
            order=index,
            formula_stage_key=stage_key,
            semantic_class=_semantic_class(formula_id, stage_key),
            authored_text=text,
            entry_key=entry,
            exit_key=exit,
            bridge_contract=V3BridgeContract(entry_key=entry, exit_key=exit),
            claim_bearing=True,
            evidence_fact_ids=evidence_ids,
            text_digest=digest_text(text),
            component_ref=stage_ref,
        )
        stages.append(stage)
        components.append(
            _component(
                component_id=component_id,
                formula=formula,
                objective=objective,
                angle_ref=angle_ref,
                family_ref=family_ref,
                truth=truth,
                semantic_class=stage.semantic_class,
                stage_keys=(stage_key,),
                coverage=(index,),
                text=text,
                entry=entry,
                exit=exit,
            )
        )

    evidence_map = {stage.stage_key: evidence_ids for stage in stages}
    master = V3MasterStoryboard(
        master_id=master_id or f"master-{formula_id.lower()}",
        revision=1,
        recipe=V3RevisionRef(entity_id=f"recipe-{formula_id.lower()}", revision=1),
        product_id=truth.product_id,
        product_truth=truth,
        objective=objective,
        angle=angle_ref,
        storyline_family=family_ref,
        formula=formula,
        stages=tuple(stages),
        resolved_component_refs=tuple(
            V3RevisionRef(entity_id=item.component_id, revision=item.revision)
            for item in components
        ),
        evidence_map=evidence_map,
        evidence_digest=deterministic_digest(evidence_map),
        bridge_continuity_receipt=_receipt("BridgeContinuityValidator"),
        formula_validation_receipt=_receipt("FormulaContractValidator"),
        claim_safety_receipt=_receipt("EvidenceLineageValidator"),
        exact_content_digest="0" * 64,
        duplicate_fingerprint="0" * 64,
        word_count=sum(word_count(stage.authored_text) for stage in stages),
        status="VALIDATED",
        source="synthetic-fixture",
        created_at="2026-08-17T00:00:00Z",
        created_by="synthetic-owner",
    )
    master = master.model_copy(update={"exact_content_digest": master_content_digest(master)})
    master = master.model_copy(
        update={"duplicate_fingerprint": exact_resolved_content_fingerprint(master)}
    )
    return {
        "truth": truth,
        "objective": objective,
        "formula": formula,
        "angle": angle,
        "family": family,
        "stages": tuple(stages),
        "components": tuple(components),
        "master": master,
        "registry": _registry(),
    }


def _projection(master: V3MasterStoryboard, duration: int) -> V3DurationProjection:
    blocks = tuple(canonical.resolve_block_plan("GOOGLE_FLOW", duration))
    slices = tuple(f"hook body cta block {index + 1}" for index in range(len(blocks)))
    seams = tuple(
        V3SeamState(
            block_index=index,
            outgoing_exit_key=f"arc:{index}",
            incoming_entry_key=f"arc:{index}",
            dialogue_start_seconds=float((index + 1) * blocks[index]),
            dialogue_end_seconds=float((index + 1) * blocks[index]),
        )
        for index in range(len(blocks) - 1)
    )
    projection = V3DurationProjection(
        projection_id=f"projection-{duration}",
        revision=1,
        master=V3RevisionRef(entity_id=master.master_id, revision=master.revision),
        product_id=master.product_id,
        product_truth=master.product_truth,
        target_duration_seconds=duration,
        engine="GOOGLE_FLOW",
        language_profile="Malay",
        wps_mode="SAFE",
        wps_authority_version=canonical.wps_authority_version(),
        wps_authority_digest=canonical.wps_authority_digest(),
        block_plan_seconds=blocks,
        exact_resolved_dialogue=" ".join(slices),
        per_block_slices=slices,
        per_block_word_counts=tuple(word_count(item) for item in slices),
        per_block_word_budgets=tuple(
            canonical.strict_dialogue_word_budget(item, "Malay", wps_mode="SAFE")
            for item in blocks
        ),
        cta_block_index=len(blocks) - 1,
        cta_stage_key=master.stages[-1].stage_key,
        seam_states=seams,
        continuity_receipt=_receipt("BridgeContinuityValidator"),
        formula_arc_receipt=_receipt("MasterStoryboardValidator"),
        master_stage_keys=tuple(stage.stage_key for stage in master.stages),
        master_stage_text_digests=tuple(stage.text_digest for stage in master.stages),
        master_exact_content_digest=master_content_digest(master),
        exact_projection_digest="0" * 64,
        status="VALIDATED",
        source="synthetic-fixture",
        created_at="2026-08-17T00:00:00Z",
        created_by="synthetic-owner",
    )
    return projection.model_copy(
        update={"exact_projection_digest": projection_content_digest(projection)}
    )


@pytest.mark.parametrize("formula_id", CANONICAL_FORMULAS)
def test_all_six_canonical_formula_contracts_are_production_valid(formula_id):
    context = _context(formula_id)
    formula = context["formula"]
    result = FormulaContractValidator.validate(
        formula.formula_id,
        formula.formula_version,
        required_formula_stage_keys(formula_id),
    )
    assert result.valid is True
    assert result.production_valid is True
    assert all(ComponentStageValidator.validate(item).valid for item in context["components"])
    master_result = MasterStoryboardValidator.validate(
        context["master"],
        evidence_registry=context["registry"],
        angle=context["angle"],
        storyline_family=context["family"],
        components=context["components"],
    )
    assert master_result.valid is True, master_result.details


@pytest.mark.parametrize("formula_id", ("SavagePAS", "HPAS"))
def test_operator_review_draft_formulas_fail_production_path(formula_id):
    result = FormulaContractValidator.validate(
        formula_id,
        formula_version(formula_id),
        required_formula_stage_keys(formula_id),
    )
    assert result.valid is False
    assert result.production_valid is False
    assert "FORMULA_NOT_PRODUCTION_ELIGIBLE" in result.issue_codes


def test_component_stage_bridge_storyline_and_evidence_boundaries_fail_closed():
    context = _context("PAS")
    component = context["components"][0]
    assert ComponentStageValidator.validate(component).valid is True
    assert BridgeContinuityValidator.validate(
        context["stages"], expected_stage_keys=required_formula_stage_keys("PAS")
    ).valid is True
    broken_stage = context["stages"][0].model_copy(update={"exit_key": "arc:broken"})
    broken_bridge = BridgeContinuityValidator.validate(
        (broken_stage, *context["stages"][1:]),
        expected_stage_keys=required_formula_stage_keys("PAS"),
    )
    assert "BRIDGE_CONTINUITY_BROKEN" in broken_bridge.issue_codes
    bad_component = component.model_copy(update={"semantic_class": "CTA"})
    assert "SEMANTIC_CLASS_MAPPING_INVALID" in ComponentStageValidator.validate(
        bad_component
    ).issue_codes
    missing_claim_evidence = component.model_copy(
        update={
            "evidence_fact_ids": (),
            "evidence_digest": _evidence_ids_digest(()),
        }
    )
    missing_claim_evidence = missing_claim_evidence.model_copy(update={"claim_bearing": True})
    assert "CLAIM_EVIDENCE_REQUIRED" in ComponentStageValidator.validate(
        missing_claim_evidence
    ).issue_codes
    missing_fact = EvidenceLineageValidator.validate(
        context["truth"], ("does-not-exist",), context["registry"], claim_bearing=True
    )
    assert "EVIDENCE_FACT_MISSING" in missing_fact.issue_codes
    cross_storyline = context["components"][1].model_copy(
        update={"storyline_family": V3RevisionRef(entity_id="other-family", revision=1)}
    )
    cross_result = StorylineCompatibilityValidator.validate_component_set(
        (context["components"][0], cross_storyline)
    )
    assert "CROSS_STORYLINE_COMPOSITION_BLOCKED" in cross_result.issue_codes


def test_master_full_arc_exact_digest_and_receipts_are_enforced():
    context = _context("PAS")
    master = context["master"]
    result = MasterStoryboardValidator.validate(
        master,
        evidence_registry=context["registry"],
        angle=context["angle"],
        storyline_family=context["family"],
        components=context["components"],
    )
    assert result.valid is True, result.details
    assert {item.semantic_class for item in master.stages} >= {"HOOK", "BODY_CORE", "CTA"}
    bad_digest = master.model_copy(update={"exact_content_digest": "f" * 64})
    assert "MASTER_CONTENT_DIGEST_MISMATCH" in MasterStoryboardValidator.validate(
        bad_digest,
        evidence_registry=context["registry"],
        angle=context["angle"],
        storyline_family=context["family"],
        components=context["components"],
    ).issue_codes
    bad_count = master.model_copy(update={"word_count": master.word_count + 1})
    assert "MASTER_WORD_COUNT_MISMATCH" in MasterStoryboardValidator.validate(
        bad_count,
        evidence_registry=context["registry"],
        angle=context["angle"],
        storyline_family=context["family"],
        components=context["components"],
    ).issue_codes
    bad_receipt = master.model_copy(
        update={"claim_safety_receipt": _receipt("EvidenceLineageValidator", valid=False)}
    )
    assert "INVALID_VALIDATION_RECEIPT" in MasterStoryboardValidator.validate(
        bad_receipt,
        evidence_registry=context["registry"],
        angle=context["angle"],
        storyline_family=context["family"],
        components=context["components"],
    ).issue_codes


def test_strict_language_profiles_cover_authority_without_malay_fallback():
    expected = {
        "BM_MS": "Malay",
        "EN": "English",
        "ID": "Indonesian",
        "ZH": "Mandarin",
        "HI": "Hindustani",
        "TA": "Tamil",
        "BN": "Bengali",
        "MY": "Burmese",
        "TH": "Thai",
    }
    for alias, canonical_name in expected.items():
        assert canonical.strict_language_name(alias) == canonical_name
        assert canonical.strict_wps_profile(alias) == canonical.strict_wps_profile(canonical_name)
    with pytest.raises(ValueError, match="UNSUPPORTED_LANGUAGE_PROFILE"):
        canonical.strict_language_name("not-a-language")
    with pytest.raises(ValueError, match="UNSUPPORTED_WPS_MODE"):
        canonical.strict_dialogue_word_budget(8, "Malay", wps_mode="UNKNOWN")
    assert canonical.language_name("not-a-language") == "Malay"


def test_duration_golden_8_16_24_uses_canonical_authority_and_preserves_parent_intent():
    context = _context("PAS")
    master = context["master"]
    for duration in (8, 16, 24):
        projection = _projection(master, duration)
        result = DurationProjectionValidator.validate(projection, master)
        assert result.valid is True, result.details
        blocks = canonical.resolve_block_plan("GOOGLE_FLOW", duration)
        authority_profile = canonical.strict_wps_profile("Malay")
        expected_safe = tuple(
            max(4, round(seconds * float(authority_profile["safe_wps"])))
            for seconds in blocks
        )
        assert projection.block_plan_seconds == tuple(blocks)
        assert projection.per_block_word_budgets == expected_safe
        assert projection.master_exact_content_digest == master_content_digest(master)
        assert projection.master_stage_keys == tuple(stage.stage_key for stage in master.stages)
        assert projection.cta_stage_key == master.stages[-1].stage_key
        assert projection.cta_block_index == len(blocks) - 1
    invalid_language = _projection(master, 8).model_copy(update={"language_profile": "Unknown"})
    assert "LANGUAGE_PROFILE_UNKNOWN" in DurationProjectionValidator.validate(
        invalid_language, master
    ).issue_codes
    invented_copy = _projection(master, 8).model_copy(
        update={"exact_resolved_dialogue": "unrelated invented copy"}
    )
    assert "DIALOGUE_SLICE_CONCATENATION_MISMATCH" in DurationProjectionValidator.validate(
        invented_copy, master
    ).issue_codes


def test_fast54_is_theoretical_capacity_and_adversarial_gates_reduce_valid_count():
    truth = _truth()
    objective = V3Objective(objective_id="objective-1", definition="Drive a safe product trial.")
    formula = V3FormulaRef(formula_id="PAS", formula_version=formula_version("PAS"))
    angle_ref = V3RevisionRef(entity_id="angle-fast54", revision=1)
    family_ref = V3RevisionRef(entity_id="family-fast54", revision=1)
    hooks = tuple(
        _component(
            component_id=f"fast54-hook-{index}",
            formula=formula,
            objective=objective,
            angle_ref=angle_ref,
            family_ref=family_ref,
            truth=truth,
            semantic_class="HOOK",
            stage_keys=("problem",),
            coverage=(0,),
            text=f"hook variant {index} fact-safe",
            entry="arc:start",
            exit="arc:join",
        )
        for index in range(6)
    )
    bodies = tuple(
        _component(
            component_id=f"fast54-body-{index}",
            formula=formula,
            objective=objective,
            angle_ref=angle_ref,
            family_ref=family_ref,
            truth=truth,
            semantic_class="BODY_CORE",
            stage_keys=("agitate", "solution"),
            coverage=(1, 2),
            text=f"body variant {index} fact-safe",
            entry="arc:join",
            exit="arc:resolve",
        )
        for index in range(3)
    )
    ctas = tuple(
        _component(
            component_id=f"fast54-cta-{index}",
            formula=formula,
            objective=objective,
            angle_ref=angle_ref,
            family_ref=family_ref,
            truth=truth,
            semantic_class="CTA",
            stage_keys=("cta",),
            coverage=(3,),
            text=f"cta variant {index} fact-safe",
            entry="arc:resolve",
            exit="arc:end",
        )
        for index in range(3)
    )
    duration_gate = DurationProjectionValidator.validate(_projection(_context("PAS")["master"], 8), _context("PAS")["master"])
    assert duration_gate.valid is True
    bridge_blocked = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)}
    duplicate_blocked = {(4, 1, 1), (5, 1, 1)}
    evidence_blocked = {(0, 2, 2)}
    attempted = valid = bridge_count = duplicate_count = evidence_count = 0
    for hook_index, hook in enumerate(hooks):
        for body_index, body in enumerate(bodies):
            for cta_index, cta in enumerate(ctas):
                attempted += 1
                key = (hook_index, body_index, cta_index)
                assert all(
                    ComponentStageValidator.validate(item).valid
                    for item in (hook, body, cta)
                )
                assert StorylineCompatibilityValidator.validate_component_set((hook, body, cta)).valid
                if key in bridge_blocked:
                    bridge_count += 1
                    continue
                if key in duplicate_blocked:
                    duplicate_count += 1
                    duplicate = ExactDuplicateValidator.validate(
                        {"hook": hook.component_id, "body": body.component_id, "cta": cta.component_id},
                        existing_fingerprints=(
                            ExactDuplicateValidator.fingerprint(
                                {"hook": hook.component_id, "body": body.component_id, "cta": cta.component_id}
                            ),
                        ),
                    )
                    assert "EXACT_DUPLICATE" in duplicate.issue_codes
                    continue
                if key in evidence_blocked:
                    evidence_count += 1
                    missing = EvidenceLineageValidator.validate(
                        truth,
                        ("missing-fast54-fact",),
                        _registry(),
                        claim_bearing=True,
                    )
                    assert "EVIDENCE_FACT_MISSING" in missing.issue_codes
                    continue
                bridge = BridgeContinuityValidator.validate(
                    (
                        V3FormulaStage(
                            stage_key="hook",
                            order=0,
                            formula_stage_key="problem",
                            semantic_class="HOOK",
                            authored_text=hook.authored_text,
                            entry_key="arc:start",
                            exit_key="arc:join",
                            bridge_contract=V3BridgeContract(entry_key="arc:start", exit_key="arc:join"),
                            claim_bearing=True,
                            evidence_fact_ids=("fact-lightweight",),
                            text_digest=digest_text(hook.authored_text),
                        ),
                        V3FormulaStage(
                            stage_key="body-agitate",
                            order=1,
                            formula_stage_key="agitate",
                            semantic_class="BODY_CORE",
                            authored_text=body.authored_text,
                            entry_key="arc:join",
                            exit_key="arc:resolve",
                            bridge_contract=V3BridgeContract(entry_key="arc:join", exit_key="arc:resolve"),
                            claim_bearing=True,
                            evidence_fact_ids=("fact-lightweight",),
                            text_digest=digest_text(body.authored_text),
                        ),
                        V3FormulaStage(
                            stage_key="body-solution",
                            order=2,
                            formula_stage_key="solution",
                            semantic_class="BODY_CORE",
                            authored_text=body.authored_text,
                            entry_key="arc:resolve",
                            exit_key="arc:resolve",
                            bridge_contract=V3BridgeContract(entry_key="arc:resolve", exit_key="arc:resolve"),
                            claim_bearing=True,
                            evidence_fact_ids=("fact-lightweight",),
                            text_digest=digest_text(body.authored_text),
                        ),
                        V3FormulaStage(
                            stage_key="cta",
                            order=3,
                            formula_stage_key="cta",
                            semantic_class="CTA",
                            authored_text=cta.authored_text,
                            entry_key="arc:resolve",
                            exit_key="arc:end",
                            bridge_contract=V3BridgeContract(entry_key="arc:resolve", exit_key="arc:end"),
                            claim_bearing=True,
                            evidence_fact_ids=("fact-lightweight",),
                            text_digest=digest_text(cta.authored_text),
                        ),
                    ),
                    expected_stage_keys=("problem", "agitate", "solution", "cta"),
                )
                assert bridge.valid
                assert duration_gate.valid
                valid += 1
    assert attempted == 54
    assert valid == 47
    assert bridge_count == 4
    assert duplicate_count == 2
    assert evidence_count == 1


def test_exact_duplicate_revision_and_digest_contracts_are_deterministic():
    first = _context("PAS", master_id="master-one")["master"]
    second = _context("PAS", master_id="master-two")["master"]
    assert ExactDuplicateValidator.fingerprint(first) == ExactDuplicateValidator.fingerprint(second)
    assert ExactDuplicateValidator.validate(first).valid is True
    duplicate = ExactDuplicateValidator.validate(
        second, existing_fingerprints=(ExactDuplicateValidator.fingerprint(first),)
    )
    assert "EXACT_DUPLICATE" in duplicate.issue_codes
    assert RevisionImmutabilityValidator.validate(
        previous_status="APPROVED",
        previous_entity_id="master-one",
        previous_revision=1,
        candidate_entity_id="master-one",
        candidate_revision=1,
        supersedes=None,
        content_changed=True,
    ).valid is False
    assert RevisionImmutabilityValidator.validate(
        previous_status="APPROVED",
        previous_entity_id="master-one",
        previous_revision=1,
        candidate_entity_id="master-one",
        candidate_revision=2,
        supersedes=V3RevisionRef(entity_id="master-one", revision=1),
        content_changed=True,
    ).valid is True
    payload_left = {"a": 1, "b": ["same", 2]}
    payload_right = {"b": ["same", 2], "a": 1}
    assert DeterministicDigestValidator.validate_same_input(payload_left, payload_right).valid
    expected = DeterministicDigestValidator.compute(payload_left)
    assert DeterministicDigestValidator.validate(payload_right, expected).valid
    assert DeterministicDigestValidator.validate(payload_right, "0" * 64).valid is False


def test_v3_validator_module_has_no_database_or_provider_dependency():
    source = inspect.getsource(__import__("agent.services.storyboard_landbank_v3_validators", fromlist=["x"]))
    assert "get_db" not in source
    assert "make_video" not in source
    assert "httpx" not in source
    assert "playwright" not in source
