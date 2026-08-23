"""Pure, provider-free validators for Formula-Driven Storyboard Landbank V3.

The validators operate on frozen V3 value objects and the already-approved V2
formula/evidence authorities.  They deliberately do not open the database,
call a provider, author copy, approve a revision, or materialize V2/P6 data.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
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
    V3RouteIdentity,
    V3StoryboardComponent,
    V3StorylineFamily,
    V3ValidationReceipt,
    deterministic_digest,
    digest_text,
    exact_resolved_content_fingerprint,
    master_content_digest,
    normalized_text,
    projected_stage_allocations_digest,
    projection_content_digest,
    route_key_for_fact_ids,
    validation_receipt_digest,
    word_count,
)
from agent.services import canonical_prompt_compiler


V3_VALIDATOR_VERSION = "storyboard-landbank-v3-validator-1"
_IMMUTABLE_STATUSES = {
    "APPROVED",
    "FROZEN",
    "REJECTED",
    "BLOCKED",
    "SUPERSEDED",
    "ARCHIVED",
}
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


def _ordered_token_subsequence(projected: str, source: str) -> bool:
    """Prove same-language compression without a semantic/provider comparison."""

    source_tokens = normalized_text(source).split()
    projected_tokens = normalized_text(projected).split()
    if not projected_tokens or len(projected_tokens) >= len(source_tokens):
        return False
    source_index = 0
    for token in projected_tokens:
        try:
            source_index = source_tokens.index(token, source_index) + 1
        except ValueError:
            return False
    return True


# Product Description and Target Customer are useful grounding context, but
# they do not identify a use-case route.  A route must be anchored by a more
# specific approved fact (benefit, allowed claim, USP, pain point, usage, or a
# product-specific authority kind).
_GENERIC_ROUTE_FACT_KINDS = {"PRODUCT_DESCRIPTION", "TARGET_CUSTOMER"}

# This is deliberately a small governed vocabulary, not a sentiment or
# language-quality heuristic.  A modifier is unsafe only when it appears in
# authored claim-bearing text and is absent from every cited approved fact.
_CLAIM_MODIFIERS: tuple[tuple[str, str], ...] = (
    ("TEMPORAL_IMMEDIACY", "serta-merta"),
    ("TEMPORAL_IMMEDIACY", "segera"),
    ("TEMPORAL_IMMEDIACY", "terus"),
    ("TEMPORAL_IMMEDIACY", "instant"),
    ("TEMPORAL_IMMEDIACY", "immediate"),
    ("GUARANTEE", "dijamin"),
    ("GUARANTEE", "jaminan"),
    ("GUARANTEE", "guaranteed"),
    ("GUARANTEE", "guarantee"),
    ("INTENSITY_OR_MAGNITUDE", "paling"),
    ("INTENSITY_OR_MAGNITUDE", "100%"),
    ("INTENSITY_OR_MAGNITUDE", "completely"),
    ("PERMANENCE", "kekal"),
    ("PERMANENCE", "selamanya"),
    ("PERMANENCE", "permanent"),
)


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", normalized_text(text).casefold()))


def _route_fact_ids(
    fact_ids: Sequence[str],
    *,
    product_truth: V3ProductTruthLineage,
    evidence_registry: EvidenceRegistry | None,
) -> tuple[str, ...]:
    if evidence_registry is None:
        return ()
    result: list[str] = []
    for fact_id in fact_ids:
        fact = evidence_registry.get(product_truth.snapshot_id, str(fact_id))
        if fact is not None and fact.fact_kind.upper() not in _GENERIC_ROUTE_FACT_KINDS:
            result.append(str(fact_id))
    return tuple(dict.fromkeys(result))


def _family_route_identity(family: V3StorylineFamily) -> tuple[V3RouteIdentity | None, bool]:
    """Return (identity, malformed_metadata) for current and legacy rows."""

    if family.route_identity is not None:
        return family.route_identity, False
    route = family.narrative_route
    if not isinstance(route, Mapping):
        return None, bool(route)
    route_key = normalized_text(str(route.get("route_key") or ""))
    raw_anchors = route.get("route_anchor_fact_ids")
    if not route_key and raw_anchors is None:
        return None, False
    if isinstance(raw_anchors, str):
        raw_anchors = [raw_anchors]
    try:
        identity = V3RouteIdentity(
            route_key=route_key,
            route_anchor_fact_ids=tuple(normalized_text(str(item)) for item in (raw_anchors or ()) if normalized_text(str(item))),
        )
    except Exception:
        return None, True
    return identity, False


class ClaimModifierValidator:
    """Flag unsupported temporal, intensity, guarantee, and permanence claims."""

    name = "ClaimModifierValidator"

    @classmethod
    def validate(
        cls,
        claim_text: str,
        evidence_fact_ids: Sequence[str],
        evidence_registry: EvidenceRegistry | None,
        *,
        product_truth: V3ProductTruthLineage | None = None,
    ) -> V3ValidationResult:
        if not normalized_text(claim_text) or evidence_registry is None or product_truth is None:
            return _result(cls.name)
        cited_text = " ".join(
            fact.text
            for fact_id in evidence_fact_ids
            if (fact := evidence_registry.get(product_truth.snapshot_id, str(fact_id))) is not None
        ).casefold()
        issues: list[tuple[str, str]] = []
        for category, phrase in _CLAIM_MODIFIERS:
            if _contains_phrase(claim_text, phrase) and not _contains_phrase(cited_text, phrase):
                issues.append(
                    (
                        "CLAIM_MODIFIER_UNSUPPORTED",
                        f"{category} modifier {phrase!r} is absent from cited approved evidence",
                    )
                )
        return _result(cls.name, issues)


class StorylineRouteCompatibilityValidator:
    """Enforce one coherent evidence-anchored route per Storyline Family."""

    name = "StorylineRouteCompatibilityValidator"

    @classmethod
    def validate(
        cls,
        storyline_family: V3StorylineFamily,
        components: Sequence[V3StoryboardComponent],
        *,
        evidence_registry: EvidenceRegistry | None,
    ) -> V3ValidationResult:
        issues: list[tuple[str, str]] = []
        identity, malformed = _family_route_identity(storyline_family)
        if malformed:
            issues.append(("STORYLINE_ROUTE_IDENTITY_INVALID", "Storyline Family route identity is malformed or non-deterministic"))
        anchor_ids = set(identity.route_anchor_fact_ids) if identity is not None else set()
        if identity is not None:
            if identity.route_key != route_key_for_fact_ids(list(identity.route_anchor_fact_ids)):
                issues.append(("STORYLINE_ROUTE_KEY_INVALID", "route_key is not derived from route_anchor_fact_ids"))
            if evidence_registry is None:
                issues.append(("ROUTE_EVIDENCE_REGISTRY_REQUIRED", "route identity requires current approved evidence"))
            else:
                for fact_id in identity.route_anchor_fact_ids:
                    fact = evidence_registry.get(storyline_family.product_truth.snapshot_id, fact_id)
                    if fact is None:
                        issues.append(("ROUTE_ANCHOR_FACT_MISSING", fact_id))
                    elif fact.fact_kind.upper() in _GENERIC_ROUTE_FACT_KINDS:
                        issues.append(("ROUTE_ANCHOR_GENERIC_FACT_FORBIDDEN", fact_id))

        hooks = [item for item in components if item.semantic_class == "HOOK"]
        bodies = [item for item in components if item.semantic_class == "BODY_CORE"]
        claim_route_components = [
            item for item in components
            if item.claim_bearing and item.semantic_class in {"HOOK", "BODY_CORE", "CTA"}
        ]
        route_ids_by_component = {
            item.component_id: set(
                _route_fact_ids(
                    item.evidence_fact_ids,
                    product_truth=storyline_family.product_truth,
                    evidence_registry=evidence_registry,
                )
            )
            for item in claim_route_components
        }
        for component in claim_route_components:
            route_ids = route_ids_by_component[component.component_id]
            if not route_ids:
                issues.append(
                    (
                        "ROUTE_USE_CASE_EVIDENCE_REQUIRED",
                        f"{component.component_id} has no non-generic route evidence",
                    )
                )
            elif anchor_ids and not route_ids.intersection(anchor_ids):
                issues.append(
                    (
                        "ROUTE_COMPONENT_ANCHOR_MISMATCH",
                        f"{component.component_id} does not cite the Storyline Family route anchor",
                    )
                )

        if not anchor_ids:
            # Legacy families without an explicit identity remain readable, but
            # their candidate composition is now constrained by the same
            # evidence intersection law.  Generic Product Description overlap
            # was removed above, so it cannot bridge unrelated use cases.
            for hook in hooks:
                hook_ids = set(
                    _route_fact_ids(
                        hook.evidence_fact_ids,
                        product_truth=storyline_family.product_truth,
                        evidence_registry=evidence_registry,
                    )
                )
                for body in bodies:
                    body_ids = set(
                        _route_fact_ids(
                            body.evidence_fact_ids,
                            product_truth=storyline_family.product_truth,
                            evidence_registry=evidence_registry,
                        )
                    )
                    if not hook_ids or not body_ids or not hook_ids.intersection(body_ids):
                        issues.append(
                            (
                                "ROUTE_HOOK_BODY_INCOMPATIBLE",
                                f"hook={hook.component_id}; body={body.component_id} do not share a route anchor",
                            )
                        )
        return _result(cls.name, issues)


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

        # Round 1 source-of-truth law: multi-stage components must carry one
        # exact typed segment per formula stage.  A missing segment list is
        # tolerated only for the old Phase 2 single-stage rows so historical
        # validator fixtures and legacy read models remain compatible.
        segments = tuple(component.stage_segments)
        if not segments:
            # Pre-existing Phase 2 validated fixtures/rows are retained as a
            # read-compatible legacy shape.  Round 1 authoring is stricter:
            # every new mutable component, especially DRAFT, must carry the
            # lossless segment source of truth.
            if len(stage_keys) > 1 and component.status in {"DRAFT", "REVIEW_REQUIRED"}:
                issues.append(
                    (
                        "COMPONENT_STAGE_SEGMENTS_REQUIRED",
                        "multi-stage components require lossless ordered stage segments",
                    )
                )
        else:
            segment_keys = tuple(segment.formula_stage_key for segment in segments)
            segment_orders = tuple(segment.order for segment in segments)
            if segment_keys != stage_keys:
                issues.append(
                    (
                        "COMPONENT_STAGE_SEGMENT_COVERAGE_MISMATCH",
                        "stage segments must exactly cover formula_stage_keys",
                    )
                )
            if segment_orders != tuple(component.ordered_stage_coverage):
                issues.append(
                    (
                        "COMPONENT_STAGE_SEGMENT_ORDER_MISMATCH",
                        "stage segment order must match canonical formula coverage",
                    )
                )
            if len(segment_keys) != len(set(segment_keys)):
                issues.append(("COMPONENT_STAGE_SEGMENT_DUPLICATE", "stage segments must be unique"))
            aggregate_text = " ".join(segment.authored_text for segment in segments).strip()
            if normalized_text(component.authored_text) != aggregate_text:
                issues.append(
                    (
                        "COMPONENT_HIDDEN_TEXT_OUTSIDE_SEGMENTS",
                        "aggregate authored_text must be derived exactly from stage segments",
                    )
                )
            if component.entry_key != segments[0].entry_key:
                issues.append(("COMPONENT_SEGMENT_ENTRY_MISMATCH", "component entry differs from first segment"))
            if component.exit_key != segments[-1].exit_key:
                issues.append(("COMPONENT_SEGMENT_EXIT_MISMATCH", "component exit differs from last segment"))
            flattened_evidence: list[str] = []
            for segment in segments:
                if segment.semantic_class != component.semantic_class:
                    issues.append(
                        (
                            "COMPONENT_SEGMENT_SEMANTIC_CLASS_MISMATCH",
                            segment.formula_stage_key,
                        )
                    )
                for fact_id in segment.evidence_fact_ids:
                    if fact_id not in flattened_evidence:
                        flattened_evidence.append(fact_id)
            if tuple(flattened_evidence) != tuple(component.evidence_fact_ids):
                issues.append(
                    (
                        "COMPONENT_SEGMENT_EVIDENCE_MISMATCH",
                        "component evidence must be the ordered union of segment evidence",
                    )
                )

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
        claim_text: str | None = None,
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
        if claim_bearing and claim_text:
            modifier_result = ClaimModifierValidator.validate(
                claim_text,
                evidence_fact_ids,
                registry,
                product_truth=product_truth,
            )
            issues.extend(zip(modifier_result.issue_codes, modifier_result.details))
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
        if storyline_family is not None and components:
            route_result = StorylineRouteCompatibilityValidator.validate(
                storyline_family,
                components,
                evidence_registry=evidence_registry,
            )
            issues.extend(zip(route_result.issue_codes, route_result.details))

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
                claim_text=stage.authored_text,
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
        *,
        evidence_registry: EvidenceRegistry | None = None,
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

        # The projection is a child of the Master, not an independent copy
        # authority. Every allocation must identify exactly one real Master
        # stage, preserve its order and digest, stay within its evidence
        # lineage, and use an explicit deterministic transform contract.
        master_stages = tuple(master.stages)
        master_stage_by_key = {stage.stage_key: stage for stage in master_stages}
        allocations = tuple(projection.stage_allocations)
        if projection.stage_allocation_digest != projected_stage_allocations_digest(allocations):
            issues.append(
                (
                    "PROJECTION_STAGE_ALLOCATION_DIGEST_MISMATCH",
                    "stage allocation digest is not exact",
                )
            )
        allocation_keys = tuple(item.master_stage_key for item in allocations)
        expected_stage_keys = tuple(stage.stage_key for stage in master_stages)
        allocation_orders = tuple(item.order for item in allocations)
        if allocation_orders != tuple(range(len(allocations))):
            issues.append(("PROJECTION_STAGE_ORDER_MISMATCH", repr(allocation_orders)))
        if allocation_keys != expected_stage_keys:
            if len(allocation_keys) == len(expected_stage_keys) and set(allocation_keys) == set(
                expected_stage_keys
            ):
                issues.append(("PROJECTION_STAGE_ORDER_MISMATCH", repr(allocation_keys)))
            else:
                issues.append(("PROJECTION_STAGE_COVERAGE_MISMATCH", repr(allocation_keys)))

        registry_required = projection.status in _RECEIPT_REQUIRED_STATUSES
        if registry_required and evidence_registry is None:
            issues.append(
                (
                    "PROJECTION_EVIDENCE_REGISTRY_REQUIRED",
                    "VALIDATED projections require the current approved evidence registry",
                )
            )
        for allocation in allocations:
            stage = master_stage_by_key.get(allocation.master_stage_key)
            if stage is None:
                issues.append(
                    (
                        "PROJECTION_UNKNOWN_MASTER_STAGE",
                        allocation.master_stage_key,
                    )
                )
                continue
            if allocation.transform_mode not in {"IDENTITY", "COMPRESSED", "MERGED_ADJACENT"}:
                issues.append(("PROJECTION_TRANSFORM_MODE_INVALID", allocation.master_stage_key))
            if allocation.omission_state not in {"PRESENT", "OMITTED"}:
                issues.append(("PROJECTION_OMISSION_STATE_INVALID", allocation.master_stage_key))
            if allocation.master_formula_stage_key != stage.formula_stage_key:
                issues.append(
                    (
                        "PROJECTION_MASTER_FORMULA_STAGE_MISMATCH",
                        allocation.master_stage_key,
                    )
                )
            if allocation.master_semantic_class != stage.semantic_class:
                issues.append(
                    (
                        "PROJECTION_MASTER_STAGE_SEMANTIC_MISMATCH",
                        allocation.master_stage_key,
                    )
                )
            if allocation.master_stage_text_digest != stage.text_digest:
                issues.append(
                    (
                        "PROJECTION_MASTER_STAGE_DIGEST_MISMATCH",
                        allocation.master_stage_key,
                    )
                )
            if stage.text_digest != digest_text(stage.authored_text):
                issues.append(
                    (
                        "PROJECTION_MASTER_STAGE_TEXT_DIGEST_INVALID",
                        allocation.master_stage_key,
                    )
                )
            if allocation.projected_text_digest != digest_text(allocation.projected_text):
                issues.append(
                    (
                        "PROJECTION_PROJECTED_TEXT_DIGEST_MISMATCH",
                        allocation.master_stage_key,
                    )
                )
            if allocation.source_evidence_digest != _evidence_ids_digest(
                allocation.source_evidence_fact_ids
            ):
                issues.append(
                    (
                        "PROJECTION_SOURCE_EVIDENCE_DIGEST_MISMATCH",
                        allocation.master_stage_key,
                    )
                )
            if not set(allocation.source_evidence_fact_ids).issubset(
                set(stage.evidence_fact_ids)
            ):
                issues.append(
                    (
                        "PROJECTION_EVIDENCE_OUTSIDE_MASTER",
                        allocation.master_stage_key,
                    )
                )
            if evidence_registry is not None:
                evidence_result = EvidenceLineageValidator.validate(
                    master.product_truth,
                    allocation.source_evidence_fact_ids,
                    evidence_registry,
                    claim_bearing=stage.claim_bearing,
                    claim_text=allocation.projected_text,
                )
                issues.extend(zip(evidence_result.issue_codes, evidence_result.details))

            if tuple(sorted(set(allocation.target_block_indices))) != allocation.target_block_indices:
                issues.append(
                    (
                        "PROJECTION_TARGET_BLOCK_ORDER_INVALID",
                        allocation.master_stage_key,
                    )
                )
            if any(index < 0 for index in allocation.target_block_indices):
                issues.append(
                    (
                        "PROJECTION_TARGET_BLOCK_UNKNOWN",
                        allocation.master_stage_key,
                    )
                )
            if len(allocation.target_block_indices) != 1:
                issues.append(
                    (
                        "PROJECTION_MULTIBLOCK_ALLOCATION_UNSUPPORTED",
                        allocation.master_stage_key,
                    )
                )
            elif allocation.target_block_indices[0] >= len(expected_blocks):
                issues.append(
                    (
                        "PROJECTION_TARGET_BLOCK_UNKNOWN",
                        allocation.master_stage_key,
                    )
                )

            if allocation.omission_state == "OMITTED":
                if allocation.projected_text:
                    issues.append(
                        (
                            "PROJECTION_OMISSION_TEXT_PRESENT",
                            allocation.master_stage_key,
                        )
                    )
                if allocation.projected_text_digest != digest_text(""):
                    issues.append(
                        (
                            "PROJECTION_OMISSION_DIGEST_MISMATCH",
                            allocation.master_stage_key,
                        )
                    )
                if stage.semantic_class in {"HOOK", "CTA"}:
                    issues.append(
                        (
                            "PROJECTION_REQUIRED_STAGE_OMITTED",
                            allocation.master_stage_key,
                        )
                    )
                continue

            if not allocation.projected_text:
                issues.append(("PROJECTION_PROJECTED_TEXT_REQUIRED", allocation.master_stage_key))
            if allocation.transform_mode == "IDENTITY":
                if normalized_text(allocation.projected_text) != normalized_text(stage.authored_text):
                    issues.append(
                        (
                            "PROJECTION_IDENTITY_DERIVATION_INVALID",
                            allocation.master_stage_key,
                        )
                    )
            elif allocation.transform_mode == "COMPRESSED":
                # DETERMINISTIC compression must be an ordered token subsequence of
                # the Master stage (mechanical truncation).  A governed AI_ASSISTED
                # derivative is a natural semantic rewrite bound to the SAME Master
                # stage, so the subsequence law is relaxed for it — every other gate
                # (WPS fit, formula order, CTA-final, evidence, lineage/digests) and
                # mandatory human semantic review still apply.
                if projection.derivation_source != "AI_ASSISTED" and not _ordered_token_subsequence(allocation.projected_text, stage.authored_text):
                    issues.append(
                        (
                            "PROJECTION_COMPRESSED_DERIVATION_INVALID",
                            allocation.master_stage_key,
                        )
                    )
                if stage.claim_bearing and projection.derivation_source != "AI_ASSISTED":
                    issues.append(
                        (
                            "CLAIM_STAGE_UNSAFE_DETERMINISTIC_COMPRESSION",
                            f"claim-bearing stage {allocation.master_stage_key} requires a governed semantic rewrite",
                        )
                    )
                if stage.claim_bearing or normalized_text(stage.authored_text)[-1:] in ".?!…":
                    if normalized_text(allocation.projected_text)[-1:] not in ".?!…":
                        issues.append(
                            (
                                "PROJECTION_SEMANTIC_FRAGMENT_INVALID",
                                f"compressed stage {allocation.master_stage_key} is not a complete sentence",
                            )
                        )
            elif allocation.transform_mode == "MERGED_ADJACENT":
                issues.append(
                    (
                        "PROJECTION_MERGED_ADJACENT_UNSUPPORTED",
                        "Phase 2 requires an explicit one-stage allocation for merged text",
                    )
                )

        present_allocations = tuple(
            item for item in allocations if item.omission_state == "PRESENT"
        )
        present_semantic_classes = {item.master_semantic_class for item in present_allocations}
        if not {"HOOK", "BODY_CORE", "CTA"}.issubset(present_semantic_classes):
            issues.append(
                (
                    "PROJECTION_SEMANTIC_CLASSES_INCOMPLETE",
                    repr(sorted(present_semantic_classes)),
                )
            )
        if not master_stages or master_stages[-1].semantic_class != "CTA":
            issues.append(("FORMULA_ARC_SEMANTIC_CLASSES_INCOMPLETE", "master has no final CTA stage"))
        cta_allocations = tuple(
            item for item in present_allocations if item.master_semantic_class == "CTA"
        )
        if len(cta_allocations) != 1 or not master_stages:
            issues.append(("PROJECTION_CTA_SOURCE_INVALID", "projection must allocate one Master CTA"))
        else:
            cta_allocation = cta_allocations[0]
            final_stage = master_stages[-1]
            if cta_allocation.master_stage_key != final_stage.stage_key:
                issues.append(("PROJECTION_CTA_SOURCE_INVALID", "CTA is not sourced from final Master CTA"))
            if cta_allocation.target_block_indices != (len(expected_blocks) - 1,):
                issues.append(("CTA_NOT_FINAL_BLOCK", "Master CTA allocation must land in final block"))

        expected_allocation_slices = tuple(
            " ".join(
                normalized_text(item.projected_text)
                for item in allocations
                if item.omission_state == "PRESENT"
                and len(item.target_block_indices) == 1
                and item.target_block_indices[0] == block_index
            ).strip()
            for block_index in range(len(expected_blocks))
        )
        if projection.per_block_slices != expected_allocation_slices:
            issues.append(
                (
                    "PROJECTION_BLOCK_SLICE_ALLOCATION_MISMATCH",
                    "block slices are not reconstructed from stage allocations",
                )
            )
        expected_dialogue = " ".join(expected_allocation_slices).strip()
        if normalized_text(projection.exact_resolved_dialogue) != expected_dialogue:
            issues.append(
                (
                    "PROJECTION_DIALOGUE_MASTER_DERIVATION_MISMATCH",
                    "exact dialogue is not reconstructed from derived Master stage text",
                )
            )
        if normalized_text(projection.exact_resolved_dialogue) != " ".join(
            normalized_text(item.projected_text)
            for item in present_allocations
        ).strip():
            issues.append(
                (
                    "PROJECTION_DIALOGUE_STAGE_ORDER_MISMATCH",
                    "exact dialogue stage order differs from allocation order",
                )
            )
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
            ("stage_allocation", projection.stage_allocation_receipt),
        ):
            receipt_issue = _receipt_issue(receipt_name, receipt)
            if receipt_issue:
                issues.append(receipt_issue)
        if projection.status in _RECEIPT_REQUIRED_STATUSES and projection.stage_allocation_receipt.validator != cls.name:
            issues.append(
                (
                    "PROJECTION_STAGE_ALLOCATION_RECEIPT_INVALID",
                    "validated projection requires a DurationProjectionValidator allocation receipt",
                )
            )
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


class V3CandidateGateResult(BaseModel):
    """Provider/DB-free receipt envelope for one computed FAST54 candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    valid: bool
    issue_codes: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    receipts: tuple[V3ValidationResult, ...] = ()
    gate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateGateEvaluator:
    """Evaluate actual candidate data and retain every validator receipt."""

    name = "CandidateGateEvaluator"

    @classmethod
    def evaluate(
        cls,
        candidate_id: str,
        *,
        master: V3MasterStoryboard,
        components: Sequence[V3StoryboardComponent] = (),
        evidence_registry: EvidenceRegistry | None = None,
        projection: V3DurationProjection | None = None,
        existing_fingerprints: Iterable[str] = (),
        angle: V3Angle | None = None,
        storyline_family: V3StorylineFamily | None = None,
    ) -> V3CandidateGateResult:
        receipts: list[V3ValidationResult] = []
        if components:
            for component in components:
                receipts.append(ComponentStageValidator.validate(component))
            receipts.append(StorylineCompatibilityValidator.validate_component_set(components))
        receipts.append(
            MasterStoryboardValidator.validate(
                master,
                evidence_registry=evidence_registry,
                angle=angle,
                storyline_family=storyline_family,
                components=components,
            )
        )
        receipts.append(
            ExactDuplicateValidator.validate(
                master,
                existing_fingerprints=existing_fingerprints,
            )
        )
        if projection is not None:
            receipts.append(
                DurationProjectionValidator.validate(
                    projection,
                    master,
                    evidence_registry=evidence_registry,
                )
            )

        issue_codes: list[str] = []
        details: list[str] = []
        for receipt in receipts:
            for code, detail in zip(receipt.issue_codes, receipt.details):
                if code not in issue_codes:
                    issue_codes.append(code)
                    details.append(detail)
        valid = not issue_codes
        payload = {
            "candidate_id": candidate_id,
            "valid": valid,
            "issue_codes": issue_codes,
            "details": details,
            "receipts": [receipt.model_dump(mode="json") for receipt in receipts],
        }
        result = V3CandidateGateResult(
            candidate_id=candidate_id,
            valid=valid,
            issue_codes=tuple(issue_codes),
            details=tuple(details),
            receipts=tuple(receipts),
            gate_digest="0" * 64,
        )
        return result.model_copy(update={"gate_digest": deterministic_digest(payload)})


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
    "ClaimModifierValidator",
    "FormulaContractValidator",
    "StorylineCompatibilityValidator",
    "StorylineRouteCompatibilityValidator",
    "ComponentStageValidator",
    "BridgeContinuityValidator",
    "EvidenceLineageValidator",
    "MasterStoryboardValidator",
    "DurationProjectionValidator",
    "ExactDuplicateValidator",
    "V3CandidateGateResult",
    "CandidateGateEvaluator",
    "RevisionImmutabilityValidator",
    "DeterministicDigestValidator",
]
