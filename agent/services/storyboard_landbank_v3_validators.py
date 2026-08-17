"""Pure, provider-free validators for Formula-Driven Storyboard Landbank V3.

The validators operate on frozen V3 value objects and the already-approved V2
formula/evidence authorities.  They deliberately do not open the database,
call a provider, author copy, approve a revision, or materialize V2/P6 data.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.authority.copy_blueprint_v2_authority import (
    formula_version,
    is_production_formula,
    required_formula_stage_keys,
    strict_formula_contract,
    strict_formula_id,
)
from agent.models.copy_blueprint_v2 import EvidenceRegistry
from agent.models.storyboard_landbank_v3 import (
    V3Angle,
    V3DurationProjection,
    V3FormulaStage,
    V3MasterStoryboard,
    V3ProductTruthLineage,
    V3RevisionRef,
    V3StoryboardComponent,
    V3StorylineFamily,
    V3ValidationReceipt,
    deterministic_digest,
    digest_text,
    exact_resolved_content_fingerprint,
    master_content_digest,
    normalized_text,
    projection_content_digest,
    validation_receipt_digest,
    word_count,
)
from agent.services import canonical_prompt_compiler


V3_VALIDATOR_VERSION = "storyboard-landbank-v3-validator-1"
_IMMUTABLE_STATUSES = {"APPROVED", "FROZEN", "SUPERSEDED", "ARCHIVED"}
_RECEIPT_REQUIRED_STATUSES = {"VALIDATED", "APPROVED", "FROZEN"}


class V3ValidationResult(BaseModel):
    """Stable result envelope shared by every V3 validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: str = Field(min_length=1)
    validator_version: str = V3_VALIDATOR_VERSION
    valid: bool
    production_valid: bool
    issue_codes: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _result(
    validator: str,
    issues: Iterable[tuple[str, str] | str] = (),
    *,
    production_valid: bool | None = None,
) -> V3ValidationResult:
    codes: list[str] = []
    details: list[str] = []
    for issue in issues:
        if isinstance(issue, tuple):
            code, detail = issue
        else:
            code, detail = issue, issue
        if code not in codes:
            codes.append(code)
            details.append(detail)
    valid = not codes
    payload = {
        "validator": validator,
        "validator_version": V3_VALIDATOR_VERSION,
        "valid": valid,
        "production_valid": valid if production_valid is None else production_valid,
        "issue_codes": codes,
        "details": details,
    }
    return V3ValidationResult(
        validator=validator,
        valid=valid,
        production_valid=payload["production_valid"],
        issue_codes=tuple(codes),
        details=tuple(details),
        receipt_digest=deterministic_digest(payload),
    )


def receipt_from_result(result: V3ValidationResult) -> V3ValidationReceipt:
    """Create a deterministic V3 receipt from a pure validator result."""

    receipt = V3ValidationReceipt(
        validator=result.validator,
        validator_version=result.validator_version,
        valid=result.valid,
        issue_codes=result.issue_codes,
        receipt_digest="0" * 64,
    )
    return receipt.model_copy(update={"receipt_digest": validation_receipt_digest(receipt)})


def _authority_error_code(exc: Exception, default: str) -> str:
    message = str(exc).upper()
    if "REQUIRED" in message or "MISSING" in message:
        return f"{default}_REQUIRED"
    if "UNKNOWN" in message:
        return f"{default}_UNKNOWN"
    return default


def _ref_key(ref: V3RevisionRef) -> tuple[str, int]:
    return ref.entity_id, ref.revision


def _same_ref(left: V3RevisionRef, entity_id: str, revision: int) -> bool:
    return left.entity_id == entity_id and left.revision == revision


def _mapping_keys(contract: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = contract.get("output_mapping", {}).get(name)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _compatibility_ids(value: Mapping[str, Any]) -> set[str] | None:
    """Read common compatibility shapes without inventing a new authority."""

    for key in (
        "objective_id",
        "objective_ids",
        "allowed_objectives",
        "objectives",
    ):
        candidate = value.get(key)
        if candidate is None:
            continue
        if isinstance(candidate, str):
            return {candidate}
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return {str(item) for item in candidate}
    return None


def _evidence_ids_digest(ids: Sequence[str]) -> str:
    return deterministic_digest([str(item) for item in ids])


def _evidence_map_digest(evidence_map: Mapping[str, Sequence[str]]) -> str:
    return deterministic_digest(
        {str(key): [str(item) for item in value] for key, value in evidence_map.items()}
    )


def _receipt_is_valid(receipt: V3ValidationReceipt) -> bool:
    return (
        receipt.valid
        and not receipt.issue_codes
        and receipt.receipt_digest == validation_receipt_digest(receipt)
    )


def _receipt_issue(name: str, receipt: V3ValidationReceipt) -> tuple[str, str] | None:
    if _receipt_is_valid(receipt):
        return None
    return ("INVALID_VALIDATION_RECEIPT", f"{name} receipt is not a valid deterministic receipt")


class FormulaContractValidator:
    """Validate exact formula identity, version, stages, and eligibility."""

    name = "FormulaContractValidator"

    @classmethod
    def validate(
        cls,
        formula_id: str,
        formula_version_value: str | None,
        stage_keys: Sequence[str],
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        try:
            canonical_id = strict_formula_id(formula_id)
        except ValueError as exc:
            issues.append(
                (
                    _authority_error_code(exc, "FORMULA"),
                    f"formula_id is not canonical: {formula_id!r}",
                )
            )
            return _result(cls.name, issues, production_valid=False)

        expected_version = formula_version(canonical_id)
        if formula_version_value != expected_version:
            issues.append(
                (
                    "FORMULA_VERSION_MISMATCH",
                    f"expected {expected_version}, received {formula_version_value!r}",
                )
            )
        try:
            production = is_production_formula(canonical_id)
        except ValueError:
            production = False
        if not production:
            issues.append(("FORMULA_NOT_PRODUCTION_ELIGIBLE", canonical_id))

        required = tuple(required_formula_stage_keys(canonical_id))
        actual = tuple(str(item).strip() for item in stage_keys)
        if len(actual) != len(set(actual)):
            issues.append(("FORMULA_STAGE_DUPLICATE", "formula stage keys must be unique"))
        if actual != required:
            if set(actual) != set(required):
                missing = sorted(set(required) - set(actual))
                extra = sorted(set(actual) - set(required))
                issues.append(
                    (
                        "FORMULA_STAGE_COVERAGE_MISMATCH",
                        f"missing={missing!r}; extra={extra!r}",
                    )
                )
            else:
                issues.append(
                    (
                        "FORMULA_STAGE_ORDER_MISMATCH",
                        f"expected={required!r}; received={actual!r}",
                    )
                )
        return _result(cls.name, issues, production_valid=not issues)


class StorylineCompatibilityValidator:
    """Validate product/objective/angle/family/formula identity boundaries."""

    name = "StorylineCompatibilityValidator"

    @classmethod
    def validate(
        cls,
        subject: V3StoryboardComponent | V3MasterStoryboard,
        *,
        angle: V3Angle | None = None,
        storyline_family: V3StorylineFamily | None = None,
        component_storyline_refs: Sequence[V3RevisionRef] = (),
        allow_cross_storyline: bool = False,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        product_id = subject.product_id
        objective_id = subject.objective.objective_id
        angle_ref = subject.angle
        family_ref = subject.storyline_family
        formula = subject.formula

        if subject.product_truth.product_id != product_id:
            issues.append(("PRODUCT_TRUTH_PRODUCT_MISMATCH", "subject and Product Truth differ"))

        if angle is not None:
            if angle.product_id != product_id:
                issues.append(("ANGLE_PRODUCT_MISMATCH", "angle belongs to another product"))
            if not _same_ref(angle_ref, angle.angle_id, angle.revision):
                issues.append(("ANGLE_REVISION_MISMATCH", "subject does not reference supplied angle revision"))
            if angle.product_truth.product_id != product_id:
                issues.append(("ANGLE_TRUTH_PRODUCT_MISMATCH", "angle truth lineage differs"))
            if angle.product_truth != subject.product_truth:
                issues.append(("ANGLE_TRUTH_LINEAGE_MISMATCH", "angle truth snapshot differs"))
            if angle.formula is not None and angle.formula != formula:
                issues.append(("ANGLE_FORMULA_INCOMPATIBLE", "angle formula compatibility differs"))
            allowed = _compatibility_ids(angle.objective_compatibility)
            if allowed is not None and objective_id not in allowed:
                issues.append(("ANGLE_OBJECTIVE_INCOMPATIBLE", objective_id))

        if storyline_family is not None:
            if storyline_family.product_id != product_id:
                issues.append(("STORYLINE_PRODUCT_MISMATCH", "storyline belongs to another product"))
            if not _same_ref(family_ref, storyline_family.family_id, storyline_family.revision):
                issues.append(
                    ("STORYLINE_REVISION_MISMATCH", "subject does not reference supplied storyline revision")
                )
            if storyline_family.product_truth.product_id != product_id:
                issues.append(("STORYLINE_TRUTH_PRODUCT_MISMATCH", "storyline truth lineage differs"))
            if storyline_family.product_truth != subject.product_truth:
                issues.append(("STORYLINE_TRUTH_LINEAGE_MISMATCH", "storyline truth snapshot differs"))
            if storyline_family.angle != angle_ref:
                issues.append(("STORYLINE_ANGLE_MISMATCH", "storyline is bound to another angle revision"))
            if storyline_family.formula != formula:
                issues.append(("STORYLINE_FORMULA_MISMATCH", "storyline formula/version differs"))
            allowed = _compatibility_ids(storyline_family.objective_compatibility)
            if allowed is not None and objective_id not in allowed:
                issues.append(("STORYLINE_OBJECTIVE_INCOMPATIBLE", objective_id))

        if not allow_cross_storyline:
            if any(ref != family_ref for ref in component_storyline_refs):
                issues.append(
                    (
                        "CROSS_STORYLINE_COMPOSITION_BLOCKED",
                        "all resolved components must use one storyline family revision",
                    )
                )
        return _result(cls.name, issues)

    @classmethod
    def validate_component_set(
        cls,
        components: Sequence[V3StoryboardComponent],
        *,
        allow_cross_storyline: bool = False,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if not components:
            issues.append(("COMPONENT_SET_REQUIRED", "at least one component is required"))
            return _result(cls.name, issues)
        first = components[0]
        refs = tuple(component.storyline_family for component in components)
        if not allow_cross_storyline and any(ref != refs[0] for ref in refs[1:]):
            issues.append(("CROSS_STORYLINE_COMPOSITION_BLOCKED", "component set crosses storyline families"))
        for component in components[1:]:
            if component.product_id != first.product_id:
                issues.append(("COMPONENT_PRODUCT_MISMATCH", "component set crosses products"))
            if component.objective.objective_id != first.objective.objective_id:
                issues.append(("COMPONENT_OBJECTIVE_MISMATCH", "component set crosses objectives"))
        return _result(cls.name, issues)


class ComponentStageValidator:
    """Validate stage-native component bindings and semantic classes."""

    name = "ComponentStageValidator"

    @classmethod
    def validate(cls, component: V3StoryboardComponent) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        try:
            formula = strict_formula_contract(component.formula.formula_id)
            required = tuple(required_formula_stage_keys(component.formula.formula_id))
        except ValueError as exc:
            return _result(cls.name, [("FORMULA_CONTRACT_UNAVAILABLE", str(exc))])
        formula_result = FormulaContractValidator.validate(
            component.formula.formula_id,
            component.formula.formula_version,
            required,
        )
        issues.extend(
            (code, detail)
            for code, detail in zip(formula_result.issue_codes, formula_result.details)
        )

        stage_keys = tuple(component.formula_stage_keys)
        positions = [required.index(key) for key in stage_keys if key in required]
        if len(positions) != len(stage_keys):
            issues.append(("COMPONENT_STAGE_KEY_INVALID", "component references an unknown formula stage"))
        if positions and tuple(component.ordered_stage_coverage) != tuple(positions):
            issues.append(("COMPONENT_STAGE_COVERAGE_MISMATCH", "ordered coverage does not match formula positions"))
        if positions and tuple(positions) != tuple(range(positions[0], positions[-1] + 1)):
            issues.append(("COMPONENT_STAGE_COVERAGE_NONCONTIGUOUS", "component stage coverage must be contiguous"))

        hook_keys = set(_mapping_keys(formula, "hook"))
        cta_keys = set(_mapping_keys(formula, "cta"))
        body_keys = set(required) - hook_keys - cta_keys
        allowed_by_class = {
            "HOOK": hook_keys,
            "BODY_CORE": body_keys,
            "CTA": cta_keys,
            "STAGE": set(required),
        }
        allowed = allowed_by_class[component.semantic_class]
        if not stage_keys or not set(stage_keys).issubset(allowed):
            issues.append(
                (
                    "SEMANTIC_CLASS_MAPPING_INVALID",
                    f"{component.semantic_class} cannot bind {stage_keys!r}",
                )
            )
        if component.entry_key != component.bridge_contract.entry_key:
            issues.append(("COMPONENT_ENTRY_BRIDGE_MISMATCH", "entry_key differs from bridge contract"))
        if component.exit_key != component.bridge_contract.exit_key:
            issues.append(("COMPONENT_EXIT_BRIDGE_MISMATCH", "exit_key differs from bridge contract"))
        if component.content_digest != digest_text(component.authored_text):
            issues.append(("COMPONENT_CONTENT_DIGEST_MISMATCH", "authored text digest is not exact"))
        if component.word_count != word_count(component.authored_text):
            issues.append(("COMPONENT_WORD_COUNT_MISMATCH", "word count is not exact"))
        if component.evidence_digest != _evidence_ids_digest(component.evidence_fact_ids):
            issues.append(("COMPONENT_EVIDENCE_DIGEST_MISMATCH", "evidence digest is not exact"))
        if component.claim_bearing and not component.evidence_fact_ids:
            issues.append(("CLAIM_EVIDENCE_REQUIRED", "claim-bearing component has no evidence facts"))
        if component.product_truth.product_id != component.product_id:
            issues.append(("PRODUCT_TRUTH_PRODUCT_MISMATCH", "component truth lineage differs"))
        return _result(cls.name, issues)


class BridgeContinuityValidator:
    """Validate ordered stage bridges and adjacent continuity."""

    name = "BridgeContinuityValidator"

    @classmethod
    def validate(
        cls,
        stages: Sequence[V3FormulaStage],
        *,
        expected_stage_keys: Sequence[str] | None = None,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if not stages:
            return _result(cls.name, [("STAGES_REQUIRED", "at least one stage is required")])
        actual_orders = tuple(stage.order for stage in stages)
        if actual_orders != tuple(range(len(stages))):
            issues.append(("STAGE_ORDER_INVALID", f"received stage orders {actual_orders!r}"))
        stage_keys = tuple(stage.formula_stage_key for stage in stages)
        if len(stage_keys) != len(set(stage_keys)):
            issues.append(("STAGE_KEY_DUPLICATE", "formula stage keys must be unique"))
        if expected_stage_keys is not None and stage_keys != tuple(expected_stage_keys):
            issues.append(("STAGE_COVERAGE_MISMATCH", "storyboard stages do not cover the formula contract"))
        for stage in stages:
            if stage.entry_key != stage.bridge_contract.entry_key:
                issues.append(("STAGE_ENTRY_BRIDGE_MISMATCH", stage.stage_key))
            if stage.exit_key != stage.bridge_contract.exit_key:
                issues.append(("STAGE_EXIT_BRIDGE_MISMATCH", stage.stage_key))
            if stage.text_digest != digest_text(stage.authored_text):
                issues.append(("STAGE_TEXT_DIGEST_MISMATCH", stage.stage_key))
        for previous, current in zip(stages, stages[1:]):
            if previous.exit_key != current.entry_key:
                issues.append(
                    (
                        "BRIDGE_CONTINUITY_BROKEN",
                        f"{previous.stage_key}.exit_key != {current.stage_key}.entry_key",
                    )
                )
        return _result(cls.name, issues)


class EvidenceLineageValidator:
    """Validate evidence identity against the current approved truth snapshot."""

    name = "EvidenceLineageValidator"

    @classmethod
    def validate(
        cls,
        product_truth: V3ProductTruthLineage,
        evidence_fact_ids: Sequence[str],
        registry: EvidenceRegistry | None,
        *,
        claim_bearing: bool = False,
        required_fact_ids: Sequence[str] = (),
        evidence_refs: Sequence[Any] = (),
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if product_truth.snapshot_status != "APPROVED":
            issues.append(("TRUTH_NOT_APPROVED", product_truth.snapshot_id))
        if claim_bearing and not evidence_fact_ids:
            issues.append(("CLAIM_EVIDENCE_REQUIRED", "claim-bearing stage has no evidence facts"))
        if len(tuple(evidence_fact_ids)) != len(set(evidence_fact_ids)):
            issues.append(("EVIDENCE_FACT_DUPLICATE", "evidence fact IDs must be unique"))
        if registry is None:
            issues.append(("EVIDENCE_REGISTRY_REQUIRED", "current evidence registry is required"))
            return _result(cls.name, issues)

        by_id = {str(item.fact_id): item for item in evidence_refs}
        for fact_id in evidence_fact_ids:
            fact = registry.get(product_truth.snapshot_id, str(fact_id))
            if fact is None:
                issues.append(("EVIDENCE_FACT_MISSING", str(fact_id)))
                continue
            if fact.product_id != product_truth.product_id:
                issues.append(("EVIDENCE_PRODUCT_MISMATCH", str(fact_id)))
            if fact.snapshot_version != product_truth.snapshot_version:
                issues.append(("EVIDENCE_SNAPSHOT_VERSION_MISMATCH", str(fact_id)))
            if fact.snapshot_status != "APPROVED" or not fact.approved:
                issues.append(("EVIDENCE_FACT_NOT_APPROVED", str(fact_id)))
            ref = by_id.get(str(fact_id))
            if ref is not None:
                if ref.snapshot_id != fact.snapshot_id or ref.text_digest != fact.text_digest:
                    issues.append(("EVIDENCE_REFERENCE_DIGEST_MISMATCH", str(fact_id)))
                if ref.fact_kind != fact.fact_kind:
                    issues.append(("EVIDENCE_REFERENCE_KIND_MISMATCH", str(fact_id)))
        missing_required = set(str(item) for item in required_fact_ids) - set(
            str(item) for item in evidence_fact_ids
        )
        if missing_required:
            issues.append(("REQUIRED_EVIDENCE_MISSING", repr(sorted(missing_required))))
        return _result(cls.name, issues)


class MasterStoryboardValidator:
    """Validate the complete formula-native Master Storyboard."""

    name = "MasterStoryboardValidator"

    @classmethod
    def validate(
        cls,
        master: V3MasterStoryboard,
        *,
        evidence_registry: EvidenceRegistry | None = None,
        angle: V3Angle | None = None,
        storyline_family: V3StorylineFamily | None = None,
        components: Sequence[V3StoryboardComponent] = (),
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if master.product_truth.product_id != master.product_id:
            issues.append(("PRODUCT_TRUTH_PRODUCT_MISMATCH", "master truth lineage differs"))
        if master.product_truth.snapshot_status != "APPROVED":
            issues.append(("TRUTH_NOT_APPROVED", master.product_truth.snapshot_id))
        formula_result = FormulaContractValidator.validate(
            master.formula.formula_id,
            master.formula.formula_version,
            [stage.formula_stage_key for stage in master.stages],
        )
        issues.extend(zip(formula_result.issue_codes, formula_result.details))
        try:
            expected_stage_keys = required_formula_stage_keys(master.formula.formula_id)
        except ValueError:
            expected_stage_keys = ()
        bridge_result = BridgeContinuityValidator.validate(
            master.stages, expected_stage_keys=expected_stage_keys
        )
        issues.extend(zip(bridge_result.issue_codes, bridge_result.details))
        storyline_result = StorylineCompatibilityValidator.validate(
            master, angle=angle, storyline_family=storyline_family
        )
        issues.extend(zip(storyline_result.issue_codes, storyline_result.details))

        if not master.resolved_component_refs:
            issues.append(("COMPONENT_REFS_REQUIRED", "master must retain resolved component revisions"))
        if components:
            component_set_result = StorylineCompatibilityValidator.validate_component_set(components)
            issues.extend(zip(component_set_result.issue_codes, component_set_result.details))
            refs = {_ref_key(ref) for ref in master.resolved_component_refs}
            actual_refs = {_ref_key(V3RevisionRef(entity_id=item.component_id, revision=item.revision)) for item in components}
            if refs != actual_refs:
                issues.append(("COMPONENT_REFS_MISMATCH", "master refs differ from supplied components"))
            for component in components:
                component_result = ComponentStageValidator.validate(component)
                issues.extend(zip(component_result.issue_codes, component_result.details))
                if component.product_id != master.product_id:
                    issues.append(("COMPONENT_PRODUCT_MISMATCH", component.component_id))
                if component.objective.objective_id != master.objective.objective_id:
                    issues.append(("COMPONENT_OBJECTIVE_MISMATCH", component.component_id))
                if component.angle != master.angle:
                    issues.append(("COMPONENT_ANGLE_MISMATCH", component.component_id))
                if component.storyline_family != master.storyline_family:
                    issues.append(("COMPONENT_STORYLINE_MISMATCH", component.component_id))
                if component.formula != master.formula:
                    issues.append(("COMPONENT_FORMULA_MISMATCH", component.component_id))

        semantic_classes = {stage.semantic_class for stage in master.stages}
        if not {"HOOK", "BODY_CORE", "CTA"}.issubset(semantic_classes):
            issues.append(("FORMULA_ARC_SEMANTIC_CLASSES_INCOMPLETE", repr(sorted(semantic_classes))))
        if not master.stages or master.stages[-1].semantic_class != "CTA":
            issues.append(("CTA_CLOSURE_INVALID", "final master stage must be CTA"))
        if master.word_count != sum(word_count(stage.authored_text) for stage in master.stages):
            issues.append(("MASTER_WORD_COUNT_MISMATCH", "master word count is not the stage sum"))
        if master.exact_content_digest != master_content_digest(master):
            issues.append(("MASTER_CONTENT_DIGEST_MISMATCH", "master content digest is not exact"))
        if master.duplicate_fingerprint != exact_resolved_content_fingerprint(master):
            issues.append(("MASTER_DUPLICATE_FINGERPRINT_MISMATCH", "duplicate fingerprint is not exact"))
        if master.evidence_digest != _evidence_map_digest(master.evidence_map):
            issues.append(("MASTER_EVIDENCE_DIGEST_MISMATCH", "evidence map digest is not exact"))
        stage_keys = {stage.stage_key for stage in master.stages}
        if set(master.evidence_map) - stage_keys:
            issues.append(("MASTER_EVIDENCE_MAP_STAGE_MISMATCH", "evidence map contains an unknown stage"))
        for stage in master.stages:
            mapped = tuple(master.evidence_map.get(stage.stage_key, ()))
            if mapped != stage.evidence_fact_ids:
                issues.append(("MASTER_STAGE_EVIDENCE_MISMATCH", stage.stage_key))
            evidence_result = EvidenceLineageValidator.validate(
                master.product_truth,
                stage.evidence_fact_ids,
                evidence_registry,
                claim_bearing=stage.claim_bearing,
            )
            issues.extend(zip(evidence_result.issue_codes, evidence_result.details))

        if master.status in _RECEIPT_REQUIRED_STATUSES:
            for receipt_name, receipt in (
                ("bridge_continuity", master.bridge_continuity_receipt),
                ("formula_validation", master.formula_validation_receipt),
                ("claim_safety", master.claim_safety_receipt),
            ):
                receipt_issue = _receipt_issue(receipt_name, receipt)
                if receipt_issue:
                    issues.append(receipt_issue)
        return _result(cls.name, issues)


class DurationProjectionValidator:
    """Validate a duration child against one exact Master and WPS authority."""

    name = "DurationProjectionValidator"

    @classmethod
    def validate(
        cls,
        projection: V3DurationProjection,
        master: V3MasterStoryboard,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if not _same_ref(projection.master, master.master_id, master.revision):
            issues.append(("PROJECTION_MASTER_MISMATCH", "projection must belong to one master revision"))
        if projection.product_id != master.product_id:
            issues.append(("PROJECTION_PRODUCT_MISMATCH", "projection product differs from master"))
        if projection.product_truth != master.product_truth:
            issues.append(("PROJECTION_TRUTH_LINEAGE_MISMATCH", "projection truth differs from master"))
        try:
            canonical_language = canonical_prompt_compiler.strict_language_name(
                projection.language_profile
            )
        except ValueError as exc:
            issues.append((_authority_error_code(exc, "LANGUAGE_PROFILE"), str(exc)))
            canonical_language = ""
        if canonical_language and projection.language_profile != canonical_language:
            issues.append(
                (
                    "LANGUAGE_PROFILE_NOT_CANONICAL",
                    f"store canonical profile {canonical_language!r}",
                )
            )
        try:
            expected_version = canonical_prompt_compiler.wps_authority_version()
            expected_digest = canonical_prompt_compiler.wps_authority_digest()
            if projection.wps_authority_version != expected_version:
                issues.append(("WPS_AUTHORITY_VERSION_MISMATCH", "projection WPS version differs"))
            if projection.wps_authority_digest != expected_digest:
                issues.append(("WPS_AUTHORITY_DIGEST_MISMATCH", "projection WPS digest differs"))
            expected_blocks = tuple(
                canonical_prompt_compiler.resolve_block_plan(
                    projection.engine, projection.target_duration_seconds
                )
            )
        except ValueError as exc:
            expected_blocks = ()
            issues.append((_authority_error_code(exc, "WPS_BLOCK_PLAN"), str(exc)))
        if projection.block_plan_seconds != expected_blocks:
            issues.append(("BLOCK_PLAN_MISMATCH", f"expected={expected_blocks!r}"))
        if len(projection.per_block_slices) != len(expected_blocks):
            issues.append(("BLOCK_SLICE_COUNT_MISMATCH", "one exact slice is required per authority block"))
        if len(projection.per_block_word_counts) != len(expected_blocks):
            issues.append(("BLOCK_WORD_COUNT_LENGTH_MISMATCH", "one word count is required per block"))
        if len(projection.per_block_word_budgets) != len(expected_blocks):
            issues.append(("BLOCK_WORD_BUDGET_LENGTH_MISMATCH", "one word budget is required per block"))
        actual_dialogue = " ".join(normalized_text(item) for item in projection.per_block_slices).strip()
        if actual_dialogue != normalized_text(projection.exact_resolved_dialogue):
            issues.append(("DIALOGUE_SLICE_CONCATENATION_MISMATCH", "exact dialogue differs from block slices"))
        if canonical_language and expected_blocks:
            expected_budgets = tuple(
                canonical_prompt_compiler.strict_dialogue_word_budget(
                    seconds,
                    canonical_language,
                    wps_mode=projection.wps_mode,
                )
                for seconds in expected_blocks
            )
            if projection.per_block_word_budgets != expected_budgets:
                issues.append(("WPS_BUDGET_MISMATCH", f"expected={expected_budgets!r}"))
        else:
            expected_budgets = ()
        actual_counts = tuple(word_count(item) for item in projection.per_block_slices)
        if projection.per_block_word_counts != actual_counts:
            issues.append(("BLOCK_WORD_COUNT_MISMATCH", f"expected={actual_counts!r}"))
        if any(count > budget for count, budget in zip(actual_counts, projection.per_block_word_budgets)):
            issues.append(("WPS_BUDGET_EXCEEDED", "a block exceeds canonical WPS budget"))
        if projection.cta_block_index != len(expected_blocks) - 1:
            issues.append(("CTA_NOT_FINAL_BLOCK", "CTA must land in the final authority block"))
        semantic_classes = {stage.semantic_class for stage in master.stages}
        if not {"HOOK", "BODY_CORE", "CTA"}.issubset(semantic_classes):
            issues.append(
                (
                    "FORMULA_ARC_SEMANTIC_CLASSES_INCOMPLETE",
                    repr(sorted(semantic_classes)),
                )
            )
        if not master.stages or master.stages[-1].semantic_class != "CTA":
            issues.append(("FORMULA_ARC_SEMANTIC_CLASSES_INCOMPLETE", "master has no final CTA stage"))
        if master.stages and projection.cta_stage_key != master.stages[-1].stage_key:
            issues.append(("CTA_STAGE_MISMATCH", "projection CTA does not point to master final stage"))
        if projection.master_stage_keys != tuple(stage.stage_key for stage in master.stages):
            issues.append(("MASTER_STAGE_KEY_LINEAGE_MISMATCH", "projection stage keys drifted"))
        if projection.master_stage_text_digests != tuple(
            stage.text_digest for stage in master.stages
        ):
            issues.append(("MASTER_STAGE_DIGEST_LINEAGE_MISMATCH", "projection stage digests drifted"))
        if projection.master_exact_content_digest != master_content_digest(master):
            issues.append(("MASTER_CONTENT_DIGEST_LINEAGE_MISMATCH", "projection parent digest drifted"))
        expected_seams = max(0, len(expected_blocks) - 1)
        if len(projection.seam_states) != expected_seams:
            issues.append(("SEAM_COUNT_MISMATCH", f"expected={expected_seams}"))
        for index, seam in enumerate(projection.seam_states):
            if seam.block_index != index:
                issues.append(("SEAM_INDEX_MISMATCH", str(index)))
            if seam.dialogue_end_seconds < seam.dialogue_start_seconds:
                issues.append(("SEAM_TIME_ORDER_INVALID", str(index)))
            if seam.outgoing_exit_key != seam.incoming_entry_key:
                issues.append(("SEAM_CONTINUITY_BROKEN", str(index)))
        for receipt_name, receipt in (
            ("continuity", projection.continuity_receipt),
            ("formula_arc", projection.formula_arc_receipt),
        ):
            receipt_issue = _receipt_issue(receipt_name, receipt)
            if receipt_issue:
                issues.append(receipt_issue)
        if projection.exact_projection_digest != projection_content_digest(projection):
            issues.append(("PROJECTION_CONTENT_DIGEST_MISMATCH", "projection digest is not exact"))
        return _result(cls.name, issues)


class ExactDuplicateValidator:
    """Block only deterministic exact resolved-content duplicates."""

    name = "ExactDuplicateValidator"

    @staticmethod
    def fingerprint(value: Any) -> str:
        if isinstance(value, V3MasterStoryboard):
            return exact_resolved_content_fingerprint(value)
        return deterministic_digest(value)

    @classmethod
    def validate(
        cls,
        value: Any,
        *,
        existing_fingerprints: Iterable[str] = (),
        supplied_digest: str | None = None,
    ) -> V3ValidationResult:
        expected = cls.fingerprint(value)
        issues: list[tuple[str, str]] = []
        if supplied_digest is None and isinstance(value, V3MasterStoryboard):
            supplied_digest = value.duplicate_fingerprint
        if supplied_digest is not None and supplied_digest != expected:
            issues.append(("EXACT_DUPLICATE_FINGERPRINT_MISMATCH", "supplied fingerprint differs"))
        if expected in set(existing_fingerprints):
            issues.append(("EXACT_DUPLICATE", expected))
        return _result(cls.name, issues)


class RevisionImmutabilityValidator:
    """Prove approved/frozen changes are represented by a new superseding revision."""

    name = "RevisionImmutabilityValidator"

    @classmethod
    def validate(
        cls,
        *,
        previous_status: str,
        previous_entity_id: str,
        previous_revision: int,
        candidate_entity_id: str,
        candidate_revision: int,
        supersedes: V3RevisionRef | None,
        content_changed: bool = True,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        if previous_status in _IMMUTABLE_STATUSES and content_changed:
            if candidate_entity_id != previous_entity_id:
                issues.append(("REVISION_ID_DRIFT", "a revision must retain the stable entity ID"))
            if candidate_revision <= previous_revision:
                issues.append(("IN_PLACE_REVISION_MUTATION", "immutable content requires a higher revision"))
            if supersedes is None or not _same_ref(supersedes, previous_entity_id, previous_revision):
                issues.append(("SUPERSESSION_REQUIRED", "new immutable revision must supersede the prior revision"))
        elif supersedes is not None and supersedes.entity_id == candidate_entity_id and supersedes.revision >= candidate_revision:
            issues.append(("SUPERSESSION_ORDER_INVALID", "superseded revision must be older"))
        return _result(cls.name, issues)


class DeterministicDigestValidator:
    """Validate stable canonical JSON digests without provider/runtime state."""

    name = "DeterministicDigestValidator"

    @staticmethod
    def compute(value: Any) -> str:
        return deterministic_digest(value)

    @classmethod
    def validate(
        cls,
        value: Any,
        expected_digest: str,
        *,
        canonical_payload: Any | None = None,
    ) -> V3ValidationResult:
        actual = deterministic_digest(value if canonical_payload is None else canonical_payload)
        issues: list[tuple[str, str]] = []
        if actual != expected_digest:
            issues.append(("DETERMINISTIC_DIGEST_MISMATCH", f"expected={expected_digest}; actual={actual}"))
        return _result(cls.name, issues)

    @classmethod
    def validate_same_input(cls, left: Any, right: Any) -> V3ValidationResult:
        left_digest = cls.compute(left)
        right_digest = cls.compute(right)
        if left_digest != right_digest:
            return _result(cls.name, [("DETERMINISTIC_DIGEST_NONDETERMINISTIC", "equivalent inputs differ")])
        return _result(cls.name)


__all__ = [
    "V3_VALIDATOR_VERSION",
    "V3ValidationResult",
    "receipt_from_result",
    "FormulaContractValidator",
    "StorylineCompatibilityValidator",
    "ComponentStageValidator",
    "BridgeContinuityValidator",
    "EvidenceLineageValidator",
    "MasterStoryboardValidator",
    "DurationProjectionValidator",
    "ExactDuplicateValidator",
    "RevisionImmutabilityValidator",
    "DeterministicDigestValidator",
]
