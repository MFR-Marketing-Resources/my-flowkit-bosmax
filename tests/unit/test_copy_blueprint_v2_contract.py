"""Focused Phase 2 tests for the additive V2 domain/evidence contract."""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent.authority.copy_blueprint_v2_authority import formula_version
from agent.models.copy_blueprint_v2 import (
    Angle,
    BridgeContract,
    CopyBlueprintV2,
    CopyBlueprintV2FeatureFlagState,
    EvidenceFact,
    EvidenceReference,
    EvidenceRegistry,
    FormulaStage,
    Objective,
    ProductTruthLineage,
    digest_evidence_text,
)
from agent.services.copy_blueprint_v2_service import (
    CopyBlueprintV2Error,
    approve_copy_blueprint_v2,
    bind_copy_blueprint_v2,
    create_blueprint_revision,
    validate_copy_blueprint_v2,
)


def _lineage(snapshot_id: str = "pi-snapshot-1") -> ProductTruthLineage:
    return ProductTruthLineage(
        product_id="product-1",
        snapshot_id=snapshot_id,
        snapshot_version=1,
        snapshot_digest="a" * 64,
        snapshot_status="APPROVED",
        approved_by="truth-reviewer",
        approved_at="2026-08-14T00:00:00Z",
    )


def _fact() -> EvidenceFact:
    text = "Menyerap cepat untuk rutin harian"
    return EvidenceFact(
        snapshot_id="pi-snapshot-1",
        fact_id="fact-benefit-001",
        product_id="product-1",
        fact_kind="benefit",
        text=text,
        text_digest=digest_evidence_text(text),
        snapshot_version=1,
        snapshot_status="APPROVED",
        approved=True,
        source_ref="product-intelligence:benefits[0]",
    )


def _stage(
    key: str,
    order: int,
    text: str,
    *,
    claim_bearing: bool = False,
    fact_refs: tuple[EvidenceReference, ...] = (),
) -> FormulaStage:
    previous = "OPEN" if order == 0 else f"PAS_{order - 1}"
    current = f"PAS_{order}"
    return FormulaStage(
        stage_key=key,
        order=order,
        authored_text=text,
        semantic_role=key,
        formula_stage_key=key,
        bridge=BridgeContract(
            entry=previous,
            exit=current,
            continuity_requirements=("preserve buyer continuity",),
        ),
        claim_bearing=claim_bearing,
        fact_refs=fact_refs,
    )


def _blueprint(**overrides) -> CopyBlueprintV2:
    ref = _fact().reference()
    values = {
        "blueprint_id": "bp-001",
        "product_id": "product-1",
        "copy_set_id": "v2-copy-set-001",
        "revision": 1,
        "status": "DRAFT",
        "formula_id": "PAS",
        "formula_version": formula_version("PAS"),
        "objective": Objective(objective_id="conversion", definition="Move a qualified buyer to try the product."),
        "angle": Angle(angle_id="routine-ease", definition="A simpler daily routine for a real buyer problem."),
        "stages": (
            _stage("problem", 0, "Rutin harian terasa leceh bila produk lambat menyerap."),
            _stage("agitate", 1, "Bila tertangguh, rasa malas nak teruskan rutin."),
            _stage("solution", 2, "Formula ini menyerap cepat untuk rutin harian.", claim_bearing=True, fact_refs=(ref,)),
            _stage("cta", 3, "Cuba masukkan dalam rutin kau hari ini."),
        ),
        "evidence_refs": (ref,),
        "target_duration_seconds": 8.0,
        "wps_profile": "SWEET_V1",
        "estimated_word_count": 25,
        "provenance": (("authoring", "operator-v2"),),
        "product_truth_lineage": _lineage(),
        "created_at": "2026-08-14T00:00:00Z",
    }
    # Convert the compact fixture provenance tuple into the strict model shape.
    values["provenance"] = tuple(
        {"key": key, "value": value} for key, value in values["provenance"]
    )
    values.update(overrides)
    return CopyBlueprintV2(**values)


def _registry() -> EvidenceRegistry:
    return EvidenceRegistry(facts=(_fact(),))


def _flags() -> CopyBlueprintV2FeatureFlagState:
    return CopyBlueprintV2FeatureFlagState(
        enabled=True,
        scope="phase2-test",
        pilot_scope=("phase2-test",),
        state="PILOT",
    )


def test_valid_v2_is_formula_native_and_projections_are_derived_only():
    blueprint = _blueprint()
    before = deepcopy(blueprint.model_dump(mode="json"))
    result = validate_copy_blueprint_v2(
        blueprint,
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
    )

    assert result.valid is True
    assert result.production_valid is False  # draft is not production-valid
    projection = blueprint.derived_projections()
    assert projection.source_version == "copy-blueprint-v2"
    assert projection.hook == "Rutin harian terasa leceh bila produk lambat menyerap."
    assert "Formula ini menyerap cepat" in projection.body
    assert projection.cta == "Cuba masukkan dalam rutin kau hari ini."
    assert blueprint.model_dump(mode="json") == before


def test_unknown_or_missing_formula_fails_closed_without_legacy_hso_fallback():
    unknown = _blueprint(formula_id="NOT_REGISTERED", formula_version="anything")
    missing = _blueprint(formula_id="", formula_version="")

    unknown_result = validate_copy_blueprint_v2(
        unknown, current_product_truth=_lineage(), evidence_registry=_registry()
    )
    missing_result = validate_copy_blueprint_v2(
        missing, current_product_truth=_lineage(), evidence_registry=_registry()
    )

    assert "COPY_V2_UNKNOWN_FORMULA" in unknown_result.error_codes
    assert "COPY_V2_FORMULA_REQUIRED" in missing_result.error_codes
    assert unknown_result.formula_id == "NOT_REGISTERED"
    assert "HSO" not in unknown_result.error_codes


def test_missing_stage_order_bridge_and_claim_evidence_fail_closed():
    blueprint = _blueprint(
        stages=(
            _stage("problem", 1, "Problem text"),
            _stage("problem", 2, "Duplicate text", claim_bearing=True),
        ),
        evidence_refs=(),
    )
    result = validate_copy_blueprint_v2(
        blueprint, current_product_truth=_lineage(), evidence_registry=_registry()
    )
    assert "COPY_V2_STAGE_DUPLICATE" in result.error_codes
    assert "COPY_V2_STAGE_MISSING" in result.error_codes
    assert "COPY_V2_STAGE_ORDER_INVALID" in result.error_codes


def test_evidence_identity_is_stable_while_wording_digest_changes():
    old = _fact()
    corrected_text = "Menyerap sangat cepat untuk rutin harian"
    corrected = EvidenceFact(
        snapshot_id=old.snapshot_id,
        fact_id=old.fact_id,
        product_id=old.product_id,
        fact_kind=old.fact_kind,
        text=corrected_text,
        text_digest=digest_evidence_text(corrected_text),
        snapshot_version=old.snapshot_version,
        snapshot_status="APPROVED",
        approved=True,
        source_ref=old.source_ref,
    )
    assert corrected.fact_id == old.fact_id
    assert corrected.text_digest != old.text_digest
    assert corrected.text_digest != corrected.fact_id


def test_stale_product_truth_and_digest_mismatch_block_production():
    ref = _fact().reference().model_copy(update={"text_digest": "b" * 64})
    blueprint = _blueprint(evidence_refs=(ref,))
    result = validate_copy_blueprint_v2(
        blueprint,
        current_product_truth=_lineage("pi-snapshot-2"),
        evidence_registry=_registry(),
        require_approval=True,
    )
    assert "COPY_V2_EVIDENCE_STALE" in result.error_codes
    assert "COPY_V2_EVIDENCE_DIGEST_MISMATCH" in result.error_codes
    assert result.production_valid is False


def test_explicit_approval_is_immutable_and_never_automatic():
    draft = _blueprint()
    registry = _registry()
    approved = approve_copy_blueprint_v2(
        draft,
        approved_by="operator-1",
        current_product_truth=_lineage(),
        evidence_registry=registry,
        approved_at="2026-08-14T01:00:00Z",
    )
    assert draft.status == "DRAFT"
    assert approved.status == "APPROVED"
    assert approved.approval_snapshot is not None
    assert approved.approval_snapshot.approved_by == "operator-1"
    assert approved.approved_execution_text[2].text == approved.stages[2].authored_text
    valid = validate_copy_blueprint_v2(
        approved,
        current_product_truth=_lineage(),
        evidence_registry=registry,
        require_approval=True,
    )
    assert valid.production_valid is True
    with pytest.raises(ValidationError):
        approved.status = "DRAFT"  # type: ignore[misc]

    changed_stage = approved.stages[0].model_copy(update={"authored_text": "Changed after approval"})
    forged = approved.model_copy(update={"stages": (changed_stage,) + approved.stages[1:]})
    forged_result = validate_copy_blueprint_v2(
        forged,
        current_product_truth=_lineage(),
        evidence_registry=registry,
        require_approval=True,
    )
    assert "COPY_V2_APPROVAL_MUTATED" in forged_result.error_codes


def test_revision_supersedes_approved_parent_without_editing_it():
    approved = approve_copy_blueprint_v2(
        _blueprint(),
        approved_by="operator-1",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        approved_at="2026-08-14T01:00:00Z",
    )
    new_revision = create_blueprint_revision(
        approved,
        stages=approved.stages,
        evidence_refs=approved.evidence_refs,
        product_truth_lineage=approved.product_truth_lineage,
        created_at="2026-08-14T02:00:00Z",
    )
    assert approved.status == "APPROVED"
    assert approved.approval_snapshot is not None
    assert new_revision.status == "DRAFT"
    assert new_revision.revision == 2
    assert new_revision.supersedes is not None
    assert new_revision.supersedes.revision == 1
    assert new_revision.approval_snapshot is None


def test_binding_requires_feature_flag_and_carries_complete_lineage():
    approved = approve_copy_blueprint_v2(
        _blueprint(),
        approved_by="operator-1",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        approved_at="2026-08-14T01:00:00Z",
    )
    with pytest.raises(CopyBlueprintV2Error) as disabled:
        bind_copy_blueprint_v2(
            approved,
            lane="T2V",
            current_product_truth=_lineage(),
            evidence_registry=_registry(),
        )
    assert disabled.value.code == "COPY_V2_FEATURE_FLAG_OFF"
    binding = bind_copy_blueprint_v2(
        approved,
        lane="T2V",
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        feature_flags=_flags(),
        bound_at="2026-08-14T03:00:00Z",
    )
    assert binding.blueprint_id == approved.blueprint_id
    assert binding.revision == approved.revision
    assert binding.formula_version == formula_version("PAS")
    assert binding.approval_snapshot_id == approved.approval_snapshot.approval_snapshot_id
    assert binding.evidence_lineage.fact_ids == ("fact-benefit-001",)
    assert binding.feature_flag_state.state == "PILOT"


def test_duration_fit_fails_without_rewriting_approved_text():
    blueprint = _blueprint(target_duration_seconds=1.0)
    before = blueprint.model_dump(mode="json")
    result = validate_copy_blueprint_v2(
        blueprint,
        current_product_truth=_lineage(),
        evidence_registry=_registry(),
        duration_word_limit=2,
    )
    assert "COPY_DURATION_FIT_FAILED" in result.error_codes
    assert blueprint.model_dump(mode="json") == before
