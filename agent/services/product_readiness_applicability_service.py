from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable

from agent.authority import product_readiness_applicability_registry as registry
from agent.db import crud
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled
from agent.models.copy_set import STATUS_COPY_APPROVED
from agent.models.product_readiness import (
    ApplicabilityProfileListResponse,
    ApplicabilityProfileProjection,
    AssetReadinessAuthority,
    CopyReadinessAuthority,
    EvidenceProvenanceAuthority,
    EvidenceRequirementResult,
    IndexedActionApplicability,
    ProductReadinessEvaluateRequest,
    ProductReadinessProjection,
    ProductTaxonomyReadinessAuthority,
    ProductTruthReadinessAuthority,
    ReadinessBlocker,
    ReadinessLayerResult,
    ResolvedProductReadinessInput,
    SelectionReadinessAuthority,
    TreatmentReadinessAuthority,
)
from agent.services import (
    copy_grounding_service,
    copy_set_service,
    creative_asset_service,
    creative_production_plan_service,
    creative_setup_service,
    creative_treatment_service,
    product_intelligence_snapshot_service,
    product_strategy_taxonomy_service,
    video_models,
)
from agent.services.creative_treatment_service import canonical_sha256


PROJECTION_VERSION = "product-readiness-projection-v1"

_PRODUCT_TRUTH_FIELDS = (
    "snapshot_id",
    "product_id",
    "version",
    "status",
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "claim_gate",
    "claim_risk_level",
    "allowed_claims_json",
    "blocked_claims_json",
)
_PROVENANCE_FIELDS = (
    "provenance_id",
    "snapshot_id",
    "product_id",
    "field_name",
    "declared_value",
    "normalized_value",
    "source_type",
    "source_url",
    "source_lane",
    "evidence_kind",
    "extraction_method",
    "confidence_score",
    "verification_status",
    "claim_risk_flag",
    "reviewer_decision",
)
_PRODUCT_IDENTITY_FIELDS = (
    "id",
    "source",
    "source_url",
    "brand",
    "raw_product_title",
    "product_display_name",
    "product_short_name",
    "category",
    "subcategory",
    "type",
    "product_type",
    "product_type_id",
    "lifecycle_status",
)
_SELECTION_FIELDS = (
    "selection_id",
    "product_id",
    "cluster",
    "selected_avatar_code",
    "selected_avatar_codes_json",
    "selected_scene_template_id",
    "selected_scene_template_ids_json",
    "selected_camera_preset_code",
    "selected_camera_preset_codes_json",
    "selected_block_purpose",
    "selected_content_type",
    "status",
)
_ASSET_FIELDS = (
    "asset_id",
    "semantic_role",
    "source_type",
    "storage_kind",
    "media_id",
    "local_file_path",
    "remote_source_url",
    "product_id",
    "allowed_modes",
    "engine_slot_eligibility",
    "source_prompt_fingerprint",
    "approved_for_video_support",
    "product_truth_status",
    "identity_lock_status",
    "scale_truth_status",
    "claim_safety_status",
    "review_status",
    "status",
)
_REVIEWED_STATUSES = frozenset({"APPROVED", "REVIEWED_APPROVED", "VERIFIED"})
_EXPLICIT_NOT_STATED_DECISIONS = frozenset(
    {
        "NOT_STATED",
        "NOT_STATED_IN_EVIDENCE",
        "REVIEWED_NOT_STATED_IN_EVIDENCE",
    }
)
_EXPLICIT_EMPTY_CLAIMS_DECISIONS = frozenset(
    {
        "ALLOWED_CLAIMS_EMPTY_INTENTIONAL",
        "EMPTY_ALLOWED_CLAIMS_INTENTIONAL",
        "NO_ALLOWED_CLAIMS_INTENTIONAL",
    }
)
_ACTION_EVIDENCE_CODES = frozenset(
    {
        "INGREDIENTS_OR_COMPOSITION",
        "MATERIALS_OR_COMPONENTS",
        "PHYSICAL_SCALE_AND_STATE",
        "USAGE_OR_INSTRUCTIONS",
        "WARNINGS_OR_LIMITATIONS",
    }
)


class ProductReadinessError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int = 409,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def _semantic_projection(source: object, fields: Iterable[str]) -> dict[str, object]:
    if hasattr(source, "model_dump"):
        values = source.model_dump(mode="json")
    else:
        values = dict(source or {})
    return {field: values.get(field) for field in fields}


def _clean_string(value: object) -> str:
    return str(value or "").strip()


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().casefold()
        return bool(normalized) and normalized not in {
            "n/a",
            "na",
            "none",
            "not applicable",
            "not stated",
            "unknown",
        }
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _reviewed(provenance: EvidenceProvenanceAuthority) -> bool:
    status = provenance.verification_status.strip().upper()
    decision = _clean_string(provenance.reviewer_decision).upper()
    return (
        status in _REVIEWED_STATUSES
        and "REJECT" not in decision
        and "CONFLICT" not in decision
        and "CONTRADICT" not in decision
    )


def _provenance_value(provenance: EvidenceProvenanceAuthority) -> str:
    value = provenance.normalized_value
    if value is None:
        value = provenance.declared_value
    return _clean_string(value)


def _provenance_conflicts(
    provenance: list[EvidenceProvenanceAuthority],
) -> bool:
    by_field: dict[str, set[str]] = defaultdict(set)
    for item in provenance:
        status = item.verification_status.strip().upper()
        decision = _clean_string(item.reviewer_decision).upper()
        if "CONFLICT" in status or "CONTRADICT" in status:
            return True
        if "CONFLICT" in decision or "CONTRADICT" in decision:
            return True
        if _reviewed(item):
            value = _provenance_value(item)
            if value:
                by_field[item.field_name].add(value)
    return any(len(values) > 1 for values in by_field.values())


def _parses_empty_collection(value: str | None) -> bool:
    text = _clean_string(value)
    if not text:
        return True
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, (list, dict)) and not parsed


def _explicit_empty_allowed_claims(
    provenance: list[EvidenceProvenanceAuthority],
) -> bool:
    for item in provenance:
        if not _reviewed(item):
            continue
        decision = _clean_string(item.reviewer_decision).upper()
        if decision not in _EXPLICIT_EMPTY_CLAIMS_DECISIONS:
            continue
        if _parses_empty_collection(
            item.normalized_value
            if item.normalized_value is not None
            else item.declared_value
        ):
            return True
    return False


def _explicit_not_stated(
    provenance: list[EvidenceProvenanceAuthority],
) -> bool:
    return any(
        _reviewed(item)
        and _clean_string(item.reviewer_decision).upper()
        in _EXPLICIT_NOT_STATED_DECISIONS
        for item in provenance
    )


def _provenance_for_fields(
    authority: ProductTruthReadinessAuthority,
    fields: list[str],
) -> list[EvidenceProvenanceAuthority]:
    wanted = set(fields)
    return [item for item in authority.provenance if item.field_name in wanted]


def _comparable_value(value: object) -> object:
    if isinstance(value, str):
        text = value.strip().replace("\r\n", "\n").replace("\r", "\n")
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return text
    return value


def _provenance_supports_value(
    provenance: EvidenceProvenanceAuthority,
    value: object,
) -> bool:
    if not _reviewed(provenance):
        return False
    return canonical_sha256(_comparable_value(_provenance_value(provenance))) == (
        canonical_sha256(_comparable_value(value))
    )

def _evaluate_requirement(
    policy: dict[str, object],
    resolved: ResolvedProductReadinessInput,
) -> EvidenceRequirementResult:
    code = str(policy["requirement_code"])
    source_fields = [str(value) for value in policy["source_fields"]]
    applicable = bool(policy["applicable"])
    if not applicable:
        return EvidenceRequirementResult(
            requirement_code=code,
            criticality=str(policy["criticality"]),
            applicable=False,
            state="NOT_APPLICABLE",
            rule_code=str(policy["rule_code"]),
            source_fields=source_fields,
        )

    if code == "VISUAL_ASSET_IDENTITY":
        ready = not resolved.assets.missing_roles
        return EvidenceRequirementResult(
            requirement_code=code,
            criticality=str(policy["criticality"]),
            applicable=True,
            state="VERIFIED_VALUE" if ready else "UNKNOWN_REVIEW_REQUIRED",
            rule_code=str(policy["rule_code"]),
            source_fields=[],
            value_sha256=resolved.assets.authority_sha256 if ready else None,
        )

    authority = resolved.product_truth
    provenance = _provenance_for_fields(authority, source_fields)
    provenance_ids = sorted({item.provenance_id for item in provenance})
    provenance_hashes = sorted({item.provenance_sha256 for item in provenance})
    values = {
        field: authority.field_values.get(field)
        for field in source_fields
    }
    present_fields = [field for field, value in values.items() if _has_value(value)]

    state = "UNKNOWN_REVIEW_REQUIRED"
    value_sha256: str | None = None
    if authority.is_stale or _provenance_conflicts(provenance):
        state = "UNKNOWN_REVIEW_REQUIRED"
    elif (
        code == "ALLOWED_CLAIMS"
        and not present_fields
        and _explicit_empty_allowed_claims(provenance)
    ):
        state = "VERIFIED_VALUE"
        value_sha256 = canonical_sha256({"allowed_claims_json": []})
    elif present_fields:
        supported_fields = {
            field
            for field in present_fields
            if any(
                item.field_name == field
                and _provenance_supports_value(item, values[field])
                for item in provenance
            )
        }
        if supported_fields:
            state = "VERIFIED_VALUE"
            value_sha256 = canonical_sha256(
                {field: values[field] for field in sorted(supported_fields)}
            )
    elif _explicit_not_stated(provenance):
        state = "NOT_STATED_IN_EVIDENCE"

    return EvidenceRequirementResult(
        requirement_code=code,
        criticality=str(policy["criticality"]),
        applicable=True,
        state=state,
        rule_code=str(policy["rule_code"]),
        source_fields=source_fields,
        provenance_ids=provenance_ids,
        provenance_hashes=provenance_hashes,
        value_sha256=value_sha256,
    )


def _blocker(
    *,
    code: str,
    layer: str,
    message: str,
    next_action: str,
    requirement_code: str | None = None,
) -> ReadinessBlocker:
    return ReadinessBlocker(
        code=code,
        layer=layer,
        message=message,
        next_action=next_action,
        requirement_code=requirement_code,
    )


def _requirement_layer_state(
    requirements: list[EvidenceRequirementResult],
) -> tuple[str, list[str]]:
    blocker_codes: list[str] = []
    state = "READY"
    for requirement in requirements:
        if not requirement.applicable:
            continue
        if requirement.state == "NOT_STATED_IN_EVIDENCE":
            blocker_codes.append(
                f"EVIDENCE_NOT_STATED:{requirement.requirement_code}"
            )
            state = "BLOCKED"
        elif requirement.state == "UNKNOWN_REVIEW_REQUIRED":
            blocker_codes.append(
                f"EVIDENCE_REVIEW_REQUIRED:{requirement.requirement_code}"
            )
            if state != "BLOCKED":
                state = "REVIEW_REQUIRED"
    return state, blocker_codes


def _finalize_projection(
    *,
    resolved: ResolvedProductReadinessInput,
    primary_status: str,
    profile: ApplicabilityProfileProjection,
    selected_action: IndexedActionApplicability,
    requirements: list[EvidenceRequirementResult],
    layers: list[ReadinessLayerResult],
    blockers: list[ReadinessBlocker],
) -> ProductReadinessProjection:
    next_actions = list(dict.fromkeys(item.next_action for item in blockers))
    payload = {
        "projection_version": PROJECTION_VERSION,
        "product_id": resolved.context.product_id,
        "primary_status": primary_status,
        "context": resolved.context.model_dump(mode="json"),
        "context_sha256": canonical_sha256(
            resolved.context.model_dump(mode="json")
        ),
        "product_authority_sha256": resolved.product_authority_sha256,
        "taxonomy_fingerprint": resolved.taxonomy.taxonomy_fingerprint,
        "applicability_profile": profile.model_dump(mode="json"),
        "selected_action": (
            selected_action.model_dump(mode="json")
            if selected_action is not None
            else None
        ),
        "product_truth_snapshot_id": resolved.product_truth.snapshot_id,
        "product_truth_snapshot_sha256": resolved.product_truth.snapshot_sha256,
        "evidence_requirements": [
            item.model_dump(mode="json") for item in requirements
        ],
        "readiness_layers": [item.model_dump(mode="json") for item in layers],
        "blockers": [item.model_dump(mode="json") for item in blockers],
        "next_actions": next_actions,
        "approved_copy_set_ids": sorted(resolved.copy.approved_copy_set_ids),
        "approved_treatment_ids": sorted(
            resolved.treatment.approved_treatment_ids
        ),
        "selected_treatment_ids": sorted(
            resolved.treatment.selected_treatment_ids
        ),
    }
    return ProductReadinessProjection(
        **payload,
        readiness_sha256=canonical_sha256(payload),
    )


def evaluate_resolved_readiness(
    resolved: ResolvedProductReadinessInput,
) -> ProductReadinessProjection:
    profile = registry.resolve_applicability_profile(
        resolved.taxonomy.matched_scene_strategy_id
    )
    taxonomy_ready = (
        profile.supported
        and resolved.taxonomy.materialization_status == "MATERIALIZED"
        and resolved.taxonomy.review_status == "VERIFIED"
        and resolved.taxonomy.consumer_status == "READY"
        and resolved.taxonomy.specific_strategy
        and not resolved.taxonomy.fallback_used
        and not resolved.taxonomy.is_stale
        and not resolved.taxonomy.failure_code
    )
    if not taxonomy_ready:
        code = (
            resolved.taxonomy.failure_code
            or profile.unsupported_code
            or "UNSUPPORTED_PRODUCT_TAXONOMY"
        )
        blockers = [
            _blocker(
                code=code,
                layer="taxonomy",
                message="Verified, specific applicability authority is unavailable.",
                next_action=(
                    "Verify a specific product taxonomy, Scene Strategy, and "
                    "Applicability Profile; generic fallback cannot be promoted."
                ),
            )
        ]
        layers = [
            ReadinessLayerResult(
                layer="taxonomy",
                state="BLOCKED",
                blocker_codes=[code],
            )
        ]
        return _finalize_projection(
            resolved=resolved,
            primary_status="UNSUPPORTED_PRODUCT_TAXONOMY",
            profile=profile,
            selected_action=None,
            requirements=[],
            layers=layers,
            blockers=blockers,
        )

    selected_action = registry.select_indexed_action(
        profile,
        resolved.context.allowed_action_index,
    )
    if selected_action is None:
        code = "INDEXED_ACTION_UNSUPPORTED"
        blockers = [
            _blocker(
                code=code,
                layer="treatment_template",
                message="The requested action index is outside canonical authority.",
                next_action=(
                    "Select one indexed action from the verified Scene Strategy."
                ),
            )
        ]
        layers = [
            ReadinessLayerResult(layer="taxonomy", state="READY"),
            ReadinessLayerResult(
                layer="treatment_template",
                state="BLOCKED",
                blocker_codes=[code],
            ),
        ]
        return _finalize_projection(
            resolved=resolved,
            primary_status="REVIEW_REQUIRED",
            profile=profile,
            selected_action=None,
            requirements=[],
            layers=layers,
            blockers=blockers,
        )

    policies = registry.requirement_policies(
        profile=profile,
        action=selected_action,
        creative_format=resolved.context.creative_format,
        logical_mode=resolved.context.logical_mode,
    )
    requirements = [
        _evaluate_requirement(policy, resolved) for policy in policies
    ]
    blockers: list[ReadinessBlocker] = []

    for requirement in requirements:
        if not requirement.applicable:
            continue
        if requirement.requirement_code == "VISUAL_ASSET_IDENTITY":
            continue
        if requirement.state == "NOT_STATED_IN_EVIDENCE":
            blockers.append(
                _blocker(
                    code=f"EVIDENCE_NOT_STATED:{requirement.requirement_code}",
                    layer=(
                        "action_evidence"
                        if requirement.requirement_code in _ACTION_EVIDENCE_CODES
                        else "product_truth"
                    ),
                    message=(
                        "Reviewed source evidence does not state a required fact."
                    ),
                    next_action=(
                        "Supply reviewed source evidence for "
                        f"{requirement.requirement_code} without inventing a value."
                    ),
                    requirement_code=requirement.requirement_code,
                )
            )
        elif requirement.state == "UNKNOWN_REVIEW_REQUIRED":
            blockers.append(
                _blocker(
                    code=f"EVIDENCE_REVIEW_REQUIRED:{requirement.requirement_code}",
                    layer=(
                        "action_evidence"
                        if requirement.requirement_code in _ACTION_EVIDENCE_CODES
                        else "product_truth"
                    ),
                    message=(
                        "Required evidence is absent, stale, contradictory, or "
                        "not supported by reviewed provenance."
                    ),
                    next_action=(
                        "Review provenance and resolve "
                        f"{requirement.requirement_code}."
                    ),
                    requirement_code=requirement.requirement_code,
                )
            )

    claim_gate = _clean_string(resolved.product_truth.claim_gate).upper()
    if claim_gate == "CLAIM_BLOCKED":
        blockers.append(
            _blocker(
                code="CLAIM_BLOCKED",
                layer="claim_safety",
                message="The approved Product Truth claim floor blocks production.",
                next_action=(
                    "Resolve the blocked claim through the existing human review "
                    "authority."
                ),
            )
        )
    elif claim_gate != "CLAIM_SAFE":
        blockers.append(
            _blocker(
                code="CLAIM_REVIEW_REQUIRED",
                layer="claim_safety",
                message="Claim safety is not currently approved as safe.",
                next_action=(
                    "Complete the existing claim-safety acknowledgement or review."
                ),
            )
        )

    if not resolved.copy.grounding_ready:
        blockers.append(
            _blocker(
                code="COPY_GROUNDING_REQUIRED",
                layer="copy_grounding",
                message="Copy-critical grounding is not ready.",
                next_action=(
                    "Complete approved-snapshot or governed family copy grounding."
                ),
            )
        )
    if not resolved.copy.approved_copy_set_ids:
        blockers.append(
            _blocker(
                code="APPROVED_COPY_SET_REQUIRED",
                layer="copy_set",
                message="No approved Copy Set is available for this product.",
                next_action="Compose and human-approve a product-bound Copy Set.",
            )
        )

    selection_ready = resolved.selection.status == "APPROVED"
    if not selection_ready:
        blockers.append(
            _blocker(
                code="CREATIVE_SELECTION_APPROVAL_REQUIRED",
                layer="creative_selection",
                message="Creative Selection is absent or not approved.",
                next_action=(
                    "Resolve and human-approve the product Creative Selection."
                ),
            )
        )
    actor_policy = profile.actor_policy_by_format[
        resolved.context.creative_format
    ]
    if (
        selection_ready
        and actor_policy == "PRESENTER_REQUIRED"
        and not _clean_string(resolved.selection.selected_avatar_code)
    ):
        blockers.append(
            _blocker(
                code="UGC_AVATAR_SELECTION_REQUIRED",
                layer="creative_selection",
                message="UGC requires an approved presenter selection.",
                next_action=(
                    "Select and approve a product-compatible Avatar Registry entry."
                ),
            )
        )

    for role in resolved.assets.missing_roles:
        blockers.append(
            _blocker(
                code=f"VIDEO_ASSET_ROLE_REQUIRED:{role}",
                layer="visual_assets",
                message=f"No approved, resolvable {role} asset is available.",
                next_action=(
                    f"Supply and human-approve a product-bound {role} asset "
                    "eligible for the selected mode."
                ),
                requirement_code="VISUAL_ASSET_IDENTITY",
            )
        )

    template_codes: list[str] = []
    try:
        orchestration = video_models.resolve_orchestration(
            resolved.context.model_key,
            resolved.context.duration_seconds,
        )
        if orchestration["generation_mode"] != resolved.context.generation_mode:
            template_codes.append("GENERATION_MODE_OR_DURATION_MISMATCH")
    except ValueError:
        template_codes.append("MODEL_DURATION_UNSUPPORTED")
    for code in template_codes:
        blockers.append(
            _blocker(
                code=code,
                layer="treatment_template",
                message="The requested model, duration, or generation mode conflicts.",
                next_action=(
                    "Select a governed model and duration whose orchestration "
                    "matches SINGLE or EXTEND exactly."
                ),
            )
        )

    if not resolved.treatment.p6_ready:
        treatment_codes = (
            resolved.treatment.blocker_codes
            or ["APPROVED_TREATMENT_REQUIRED"]
        )
        for code in treatment_codes:
            blockers.append(
                _blocker(
                    code=code,
                    layer="treatment_instance",
                    message=(
                        "No current approved treatment passes exact P7.5/P6 "
                        "revalidation for this context."
                    ),
                    next_action=(
                        "Create, review, and approve a current treatment matching "
                        "this format, mode, model, duration, evidence, and assets."
                    ),
                )
            )

    product_truth_requirements = [
        item
        for item in requirements
        if item.requirement_code not in _ACTION_EVIDENCE_CODES
        and item.requirement_code != "VISUAL_ASSET_IDENTITY"
    ]
    action_requirements = [
        item for item in requirements if item.requirement_code in _ACTION_EVIDENCE_CODES
    ]
    product_truth_state, product_truth_codes = _requirement_layer_state(
        product_truth_requirements
    )
    action_state, action_codes = _requirement_layer_state(action_requirements)
    claim_codes = [
        item.code for item in blockers if item.layer == "claim_safety"
    ]
    copy_grounding_codes = [
        item.code for item in blockers if item.layer == "copy_grounding"
    ]
    copy_set_codes = [item.code for item in blockers if item.layer == "copy_set"]
    selection_codes = [
        item.code for item in blockers if item.layer == "creative_selection"
    ]
    asset_codes = [
        item.code for item in blockers if item.layer == "visual_assets"
    ]
    template_codes = [
        item.code for item in blockers if item.layer == "treatment_template"
    ]
    treatment_codes = [
        item.code for item in blockers if item.layer == "treatment_instance"
    ]

    layers = [
        ReadinessLayerResult(layer="taxonomy", state="READY"),
        ReadinessLayerResult(
            layer="product_truth",
            state=product_truth_state,
            blocker_codes=product_truth_codes,
        ),
        ReadinessLayerResult(
            layer="copy_grounding",
            state="BLOCKED" if copy_grounding_codes else "READY",
            blocker_codes=copy_grounding_codes,
        ),
        ReadinessLayerResult(
            layer="claim_safety",
            state="REVIEW_REQUIRED" if claim_codes else "READY",
            blocker_codes=claim_codes,
        ),
        ReadinessLayerResult(
            layer="action_evidence",
            state=action_state,
            blocker_codes=action_codes,
        ),
        ReadinessLayerResult(
            layer="copy_set",
            state="BLOCKED" if copy_set_codes else "READY",
            blocker_codes=copy_set_codes,
        ),
        ReadinessLayerResult(
            layer="creative_selection",
            state="REVIEW_REQUIRED" if selection_codes else "READY",
            blocker_codes=selection_codes,
        ),
        ReadinessLayerResult(
            layer="visual_assets",
            state=(
                "NOT_APPLICABLE"
                if not resolved.assets.required_roles
                else "BLOCKED"
                if asset_codes
                else "READY"
            ),
            blocker_codes=asset_codes,
        ),
        ReadinessLayerResult(
            layer="treatment_template",
            state="BLOCKED" if template_codes else "READY",
            blocker_codes=template_codes,
        ),
        ReadinessLayerResult(
            layer="treatment_instance",
            state="REVIEW_REQUIRED" if treatment_codes else "READY",
            blocker_codes=treatment_codes,
        ),
        ReadinessLayerResult(
            layer="p6",
            state="READY" if resolved.treatment.p6_ready else "BLOCKED",
            blocker_codes=resolved.treatment.blocker_codes,
        ),
    ]

    treatment_critical = {
        "TREATMENT_CRITICAL",
        "BOTH",
    }
    not_stated_treatment = any(
        item.applicable
        and item.requirement_code != "VISUAL_ASSET_IDENTITY"
        and item.criticality in treatment_critical
        and item.state == "NOT_STATED_IN_EVIDENCE"
        for item in requirements
    )
    unknown_critical = any(
        item.applicable
        and item.requirement_code != "VISUAL_ASSET_IDENTITY"
        and item.criticality in treatment_critical
        and item.state == "UNKNOWN_REVIEW_REQUIRED"
        for item in requirements
    )
    claim_or_review_block = bool(
        claim_codes or selection_codes or template_codes
    )
    if not_stated_treatment:
        primary_status = "EVIDENCE_REQUIRED"
    elif unknown_critical or claim_or_review_block:
        primary_status = "REVIEW_REQUIRED"
    elif copy_grounding_codes or copy_set_codes:
        primary_status = "COPY_SUPPLY_REQUIRED"
    elif asset_codes:
        primary_status = "ASSET_REQUIRED"
    elif resolved.treatment.p6_ready and not blockers:
        primary_status = "READY"
    else:
        primary_status = "REVIEW_REQUIRED"

    return _finalize_projection(
        resolved=resolved,
        primary_status=primary_status,
        profile=profile,
        selected_action=selected_action,
        requirements=requirements,
        layers=layers,
        blockers=blockers,
    )


def _provenance_authority(source: object) -> EvidenceProvenanceAuthority:
    projection = _semantic_projection(source, _PROVENANCE_FIELDS)
    return EvidenceProvenanceAuthority(
        provenance_id=str(projection["provenance_id"]),
        field_name=str(projection["field_name"]),
        declared_value=projection["declared_value"],
        normalized_value=projection["normalized_value"],
        source_type=str(projection["source_type"]),
        source_url=projection["source_url"],
        source_lane=projection["source_lane"],
        evidence_kind=str(projection["evidence_kind"]),
        extraction_method=str(projection["extraction_method"]),
        confidence_score=projection["confidence_score"],
        verification_status=str(projection["verification_status"]),
        claim_risk_flag=projection["claim_risk_flag"],
        reviewer_decision=projection["reviewer_decision"],
        provenance_sha256=canonical_sha256(projection),
    )


async def _resolve_taxonomy(
    product_id: str,
) -> ProductTaxonomyReadinessAuthority:
    try:
        taxonomy = (
            await product_strategy_taxonomy_service.require_verified_product_strategy_taxonomy(
                product_id
            )
        )
        values = taxonomy.model_dump(mode="json")
        return ProductTaxonomyReadinessAuthority(
            taxonomy_version=values["taxonomy_version"],
            taxonomy_fingerprint=values["product_fingerprint"],
            cluster=values["cluster"],
            product_type_group=values["product_type_group"],
            matched_scene_strategy_id=values["matched_scene_strategy_id"],
            scene_coverage_status=values["scene_coverage_status"],
            fallback_used=values["fallback_used"],
            specific_strategy=values["specific_strategy"],
            review_status=values["review_status"],
            consumer_status=values["consumer_status"],
            materialization_status=values["materialization_status"],
            is_stale=values["is_stale"],
        )
    except product_strategy_taxonomy_service.ProductStrategyTaxonomyError as exc:
        try:
            taxonomy = (
                await product_strategy_taxonomy_service.get_product_strategy_taxonomy_read_model(
                    product_id
                )
            )
        except Exception:
            return ProductTaxonomyReadinessAuthority(
                failure_code=str(exc) or "TAXONOMY_NOT_VERIFIED"
            )
        values = taxonomy.model_dump(mode="json")
        return ProductTaxonomyReadinessAuthority(
            taxonomy_version=values["taxonomy_version"],
            taxonomy_fingerprint=values["product_fingerprint"],
            cluster=values["cluster"],
            product_type_group=values["product_type_group"],
            matched_scene_strategy_id=values["matched_scene_strategy_id"],
            scene_coverage_status=values["scene_coverage_status"],
            fallback_used=values["fallback_used"],
            specific_strategy=values["specific_strategy"],
            review_status=values["review_status"],
            consumer_status=values["consumer_status"],
            materialization_status=values["materialization_status"],
            is_stale=values["is_stale"],
            failure_code=str(exc) or "TAXONOMY_NOT_VERIFIED",
        )


async def _resolve_product_truth(
    product: dict[str, object],
) -> ProductTruthReadinessAuthority:
    product_id = str(product["id"])
    snapshot = (
        await product_intelligence_snapshot_service.get_latest_approved_snapshot(
            product_id
        )
    )
    product_projection = _semantic_projection(product, _PRODUCT_IDENTITY_FIELDS)
    product_provenance_projection = {
        "provenance_id": f"product:{product_id}",
        "snapshot_id": snapshot.snapshot_id if snapshot else None,
        "product_id": product_id,
        "field_name": "product_identity",
        "declared_value": json.dumps(
            product_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "normalized_value": json.dumps(
            product_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "source_type": "INTERNAL_CANONICAL",
        "source_url": product.get("source_url"),
        "source_lane": product.get("source"),
        "evidence_kind": "CANONICAL_PRODUCT_ROW",
        "extraction_method": "DATABASE_READ",
        "confidence_score": 1.0,
        "verification_status": "REVIEWED_APPROVED",
        "claim_risk_flag": None,
        "reviewer_decision": "CANONICAL_PRODUCT_IDENTITY",
    }
    product_provenance = EvidenceProvenanceAuthority(
        provenance_id=f"product:{product_id}",
        field_name="product_identity",
        declared_value=product_provenance_projection["declared_value"],
        normalized_value=product_provenance_projection["normalized_value"],
        source_type="INTERNAL_CANONICAL",
        source_url=product.get("source_url"),
        source_lane=product.get("source"),
        evidence_kind="CANONICAL_PRODUCT_ROW",
        extraction_method="DATABASE_READ",
        confidence_score=1.0,
        verification_status="REVIEWED_APPROVED",
        reviewer_decision="CANONICAL_PRODUCT_IDENTITY",
        provenance_sha256=canonical_sha256(product_provenance_projection),
    )
    if snapshot is None:
        return ProductTruthReadinessAuthority(
            field_values={"product_identity": product_projection},
            provenance=[product_provenance],
        )

    provenance_rows = (
        await product_intelligence_snapshot_service.list_field_provenance(
            snapshot_id=snapshot.snapshot_id,
            product_id=product_id,
        )
    )
    snapshot_projection = _semantic_projection(snapshot, _PRODUCT_TRUTH_FIELDS)
    values = snapshot.model_dump(mode="json")
    field_values = {
        field: values.get(field)
        for field in _PRODUCT_TRUTH_FIELDS
        if field not in {"snapshot_id", "product_id", "version", "status"}
    }
    field_values["product_identity"] = product_projection
    return ProductTruthReadinessAuthority(
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=canonical_sha256(snapshot_projection),
        snapshot_status=snapshot.status,
        field_values=field_values,
        provenance=[
            product_provenance,
            *[_provenance_authority(row) for row in provenance_rows],
        ],
        claim_gate=snapshot.claim_gate,
        claim_risk_level=snapshot.claim_risk_level,
    )


async def _resolve_copy(
    product: dict[str, object],
) -> CopyReadinessAuthority:
    grounding = await copy_grounding_service.resolve_copy_grounding(product)
    # Task C — legacy copy_set runtime closure: legacy copy_set rows never satisfy
    # active copy readiness in normal runtime. Approved copy authority is V2
    # (copy_register_v2 / Copywriting Landbank). Read the retired store only under
    # explicit maintenance mode (pre-cutover recovery / historical inspection).
    copy_sets = (
        await copy_set_service.list_copy_sets(str(product["id"]))
        if legacy_copy_maintenance_enabled()
        else []
    )
    approved = sorted(
        {
            str(item["copy_set_id"])
            for item in copy_sets
            if item.get("status") == STATUS_COPY_APPROVED
        }
    )
    return CopyReadinessAuthority(
        grounding_ready=bool(grounding.grounded),
        grounding_source=grounding.source,
        approved_copy_set_ids=approved,
    )


async def _resolve_selection(
    product_id: str,
) -> SelectionReadinessAuthority:
    selection = await creative_setup_service.get_creative_selection(product_id)
    if selection is None:
        return SelectionReadinessAuthority()
    projection = _semantic_projection(selection, _SELECTION_FIELDS)
    return SelectionReadinessAuthority(
        selection_id=_clean_string(selection.get("selection_id")) or None,
        status=_clean_string(selection.get("status")) or None,
        selected_avatar_code=(
            _clean_string(selection.get("selected_avatar_code")) or None
        ),
        selected_avatar_codes=[
            str(value).strip()
            for value in (selection.get("selected_avatar_codes") or [])
            if str(value or "").strip()
        ],
        selected_scene_template_id=(
            _clean_string(selection.get("selected_scene_template_id")) or None
        ),
        selected_scene_template_ids=[
            str(value).strip()
            for value in (selection.get("selected_scene_template_ids") or [])
            if str(value or "").strip()
        ],
        selected_camera_preset_code=(
            _clean_string(selection.get("selected_camera_preset_code")) or None
        ),
        selected_camera_preset_codes=[
            str(value).strip()
            for value in (selection.get("selected_camera_preset_codes") or [])
            if str(value or "").strip()
        ],
        selection_sha256=canonical_sha256(projection),
    )


async def _resolve_assets(
    *,
    product_id: str,
    request: ProductReadinessEvaluateRequest,
    required_roles: list[str],
) -> AssetReadinessAuthority:
    allowed_mode = "F2V" if request.logical_mode == "HYBRID" else request.logical_mode
    assets = await creative_asset_service.list_creative_assets(
        status="ACTIVE",
        allowed_mode=allowed_mode,
        product_id=product_id,
        limit=500,
    )
    eligible_by_role: dict[str, list[str]] = {}
    authority_rows: list[dict[str, object]] = []
    for role in required_roles:
        eligible = []
        for asset in assets:
            if asset.semantic_role != role:
                continue
            if asset.review_status != "APPROVED":
                continue
            if not asset.approved_for_video_support:
                continue
            if not creative_asset_service._asset_has_resolvable_source(asset):
                continue
            eligible.append(asset.asset_id)
            authority_rows.append(_semantic_projection(asset, _ASSET_FIELDS))
        eligible_by_role[role] = sorted(set(eligible))
    missing_roles = [
        role for role in required_roles if not eligible_by_role.get(role)
    ]
    authority_payload = {
        "required_roles": required_roles,
        "eligible_asset_ids_by_role": eligible_by_role,
        "assets": sorted(
            authority_rows,
            key=lambda item: (str(item["semantic_role"]), str(item["asset_id"])),
        ),
    }
    return AssetReadinessAuthority(
        required_roles=required_roles,
        eligible_asset_ids_by_role=eligible_by_role,
        missing_roles=missing_roles,
        authority_sha256=canonical_sha256(authority_payload),
    )


async def _resolve_treatments(
    request: ProductReadinessEvaluateRequest,
) -> TreatmentReadinessAuthority:
    approved = await creative_treatment_service.list_treatments(
        product_id=request.product_id,
        status="APPROVED",
        variation_group_id=None,
        limit=200,
    )
    approved_ids = sorted(str(item["treatment_id"]) for item in approved)
    try:
        availability = (
            await creative_production_plan_service.resolve_treatment_availability(
                product_video_allocations=[
                    {"product_id": request.product_id, "video_count": 1}
                ],
                logical_mode=request.logical_mode,
                model_key=request.model_key,
                duration_seconds=request.duration_seconds,
                creative_format=request.creative_format,
                treatment_ids=None,
            )
        )
    except creative_production_plan_service.CreativeProductionError as exc:
        return TreatmentReadinessAuthority(
            approved_treatment_ids=approved_ids,
            blocker_codes=[exc.code],
        )
    blocker_codes = [
        str(item.get("code"))
        for item in availability.get("blockers", [])
        if item.get("code")
    ]
    for product_result in availability.get("product_results", []):
        blocker_codes.extend(
            str(item.get("code"))
            for item in product_result.get("excluded_authority", [])
            if item.get("code")
        )
    return TreatmentReadinessAuthority(
        approved_treatment_ids=approved_ids,
        selected_treatment_ids=[
            str(value)
            for value in availability.get("selected_treatment_ids", [])
        ],
        availability_sha256=availability.get("availability_sha256"),
        p6_ready=bool(availability.get("ready")),
        blocker_codes=sorted(set(blocker_codes)),
    )


async def resolve_readiness_input(
    request: ProductReadinessEvaluateRequest,
) -> ResolvedProductReadinessInput:
    product = await crud.get_product(request.product_id)
    if product is None:
        raise ProductReadinessError(
            "PRODUCT_NOT_FOUND",
            status_code=404,
            details={"product_id": request.product_id},
        )
    taxonomy = await _resolve_taxonomy(request.product_id)
    profile = registry.resolve_applicability_profile(
        taxonomy.matched_scene_strategy_id
    )
    required_roles = list(
        profile.required_asset_roles_by_mode.get(request.logical_mode, [])
    )
    product_truth = await _resolve_product_truth(product)
    copy = await _resolve_copy(product)
    selection = await _resolve_selection(request.product_id)
    assets = await _resolve_assets(
        product_id=request.product_id,
        request=request,
        required_roles=required_roles,
    )
    treatment = await _resolve_treatments(request)
    return ResolvedProductReadinessInput(
        context=request,
        product_authority_sha256=canonical_sha256(
            _semantic_projection(product, _PRODUCT_IDENTITY_FIELDS)
        ),
        taxonomy=taxonomy,
        product_truth=product_truth,
        copy=copy,
        selection=selection,
        assets=assets,
        treatment=treatment,
    )


async def evaluate_product_readiness(
    request: ProductReadinessEvaluateRequest,
) -> ProductReadinessProjection:
    resolved = await resolve_readiness_input(request)
    return evaluate_resolved_readiness(resolved)


def get_applicability_profiles() -> ApplicabilityProfileListResponse:
    profiles = registry.list_applicability_profiles()
    payload = [profile.model_dump(mode="json") for profile in profiles]
    supported = sum(1 for profile in profiles if profile.supported)
    return ApplicabilityProfileListResponse(
        profiles=profiles,
        supported_count=supported,
        unsupported_count=len(profiles) - supported,
        registry_sha256=canonical_sha256(payload),
    )
