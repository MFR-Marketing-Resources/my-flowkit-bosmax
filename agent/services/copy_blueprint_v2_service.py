"""Pure V2 validation, explicit approval, revision, and binding services.

This module has no database writes, provider calls, compiler calls, or legacy
CopySet reads.  It is the additive Phase 2 domain seam.  Persistence and
consumer cutover remain later, explicitly scoped work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.authority.copy_blueprint_v2_authority import (
    MissingV2Formula,
    UnknownV2Formula,
    formula_version,
    is_production_formula,
    required_formula_stage_keys,
    strict_formula_contract,
    strict_formula_id,
)
from agent.authority.copy_lane_matrix import get_lane_descriptor
from agent.models.copy_blueprint_v2 import (
    AdapterContext,
    ApprovalSnapshot,
    ApprovedExecutionText,
    CopyBlueprintV2,
    CopyBlueprintV2FeatureFlagState,
    CopyExecutionBinding,
    EvidenceFact,
    EvidenceLineage,
    EvidenceReference,
    EvidenceRegistry,
    FormulaStage,
    ProductTruthLineage,
    ProductionReadinessProof,
    SemanticReviewProof,
    StageTextDigest,
    SupersessionRef,
    V2_BINDING_VERSION,
    digest_evidence_text,
    digest_json,
)
from agent.services import canonical_prompt_compiler as canonical
from agent.services.prompt_compiler_runtime_config_service import DEFAULT_TARGET_LANGUAGE


class CopyBlueprintV2Error(ValueError):
    """Stable fail-closed V2 error."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        self.code = code
        self.details = details
        super().__init__(message)


class V2ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    stage_key: str | None = None


class CopyBlueprintV2ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    revision: int
    valid: bool
    production_valid: bool
    formula_id: str
    formula_version: str
    error_codes: tuple[str, ...] = ()
    issues: tuple[V2ValidationIssue, ...] = ()
    derived_projection_available: bool = False
    duration_word_count: int | None = None
    duration_word_budget: int | None = None
    duration_fit: bool | None = None


def _issue(code: str, message: str, stage_key: str | None = None) -> V2ValidationIssue:
    return V2ValidationIssue(code=code, message=message, stage_key=stage_key)


def canonical_duration_word_budget(
    duration_seconds: float | None,
    *,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    wps_mode: str = "SWEET",
) -> int | None:
    """Resolve a Copy V2 duration budget from the canonical planner authority."""

    if duration_seconds is None:
        return None
    duration = float(duration_seconds)
    if not duration.is_integer():
        raise ValueError(f"COPY_V2_DURATION_AUTHORITY_UNRESOLVED:{duration_seconds}")
    return canonical.total_dialogue_word_budget(
        int(duration),
        target_language,
        wps_mode=wps_mode,
        engine="GOOGLE_FLOW",
    )


def _unique_refs(refs: list[EvidenceReference]) -> tuple[EvidenceReference, ...]:
    out: list[EvidenceReference] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.snapshot_id, ref.fact_id)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return tuple(out)


def _evidence_digest(refs: tuple[EvidenceReference, ...]) -> str:
    return digest_json([ref.model_dump(mode="json") for ref in refs])


def _blueprint_digest(blueprint: CopyBlueprintV2) -> str:
    """Digest the authored artifact before approval metadata is attached."""

    payload = blueprint.model_dump(mode="json")
    for key in ("approval_snapshot", "approved_execution_text", "approved_at", "approved_by", "status"):
        payload.pop(key, None)
    return digest_json(payload)


def _stage_text_digests(stages: tuple[FormulaStage, ...]) -> tuple[StageTextDigest, ...]:
    return tuple(
        StageTextDigest(stage_key=stage.stage_key, text_digest=digest_evidence_text(stage.authored_text))
        for stage in stages
    )


def _approved_text(stages: tuple[FormulaStage, ...]) -> tuple[ApprovedExecutionText, ...]:
    return tuple(ApprovedExecutionText(stage_key=stage.stage_key, text=stage.authored_text) for stage in stages)


def _compare_approval_artifact(blueprint: CopyBlueprintV2, issues: list[V2ValidationIssue]) -> None:
    snapshot = blueprint.approval_snapshot
    if snapshot is None:
        return
    expected_text = _approved_text(blueprint.stages)
    if tuple(blueprint.approved_execution_text) != expected_text:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "approved execution text no longer matches the authored stage artifact",
            )
        )
    if tuple(snapshot.approved_execution_text) != expected_text:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "approval snapshot text differs from the current stage artifact",
            )
        )
    if tuple(snapshot.stage_text_digests) != _stage_text_digests(blueprint.stages):
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "approval snapshot stage digests differ from the current stage artifact",
            )
        )
    if snapshot.blueprint_digest != _blueprint_digest(blueprint):
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "blueprint content no longer matches its immutable approval digest",
            )
        )
    if snapshot.formula_id != blueprint.formula_id or snapshot.formula_version != blueprint.formula_version:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "approved formula identity/version changed after approval",
            )
        )
    if snapshot.product_truth_snapshot_id != blueprint.product_truth_lineage.snapshot_id:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "approved Product Truth snapshot changed after approval",
            )
        )
    if snapshot.semantic_review != blueprint.semantic_review:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "semantic review proof no longer matches the immutable approval snapshot",
            )
        )
    if snapshot.readiness_proof != blueprint.readiness_proof:
        issues.append(
            _issue(
                "COPY_V2_APPROVAL_MUTATED",
                "production readiness proof no longer matches the immutable approval snapshot",
            )
        )


def _same_product_truth_snapshot(left: ProductTruthLineage, right: ProductTruthLineage) -> bool:
    """Return whether two lineages point at the same approved snapshot."""

    return (
        left.product_id == right.product_id
        and left.snapshot_id == right.snapshot_id
        and left.snapshot_version == right.snapshot_version
        and left.snapshot_digest == right.snapshot_digest
        and left.snapshot_status == right.snapshot_status
    )


def _authority_lineage_changed(left: ProductTruthLineage, right: ProductTruthLineage) -> bool:
    """Detect a taxonomy/strategy authority change without treating it as copy text drift."""

    return (
        left.taxonomy_authority_fingerprint != right.taxonomy_authority_fingerprint
        or left.taxonomy_authority_version != right.taxonomy_authority_version
        or left.canonical_category != right.canonical_category
        or left.canonical_subcategory != right.canonical_subcategory
        or left.canonical_type != right.canonical_type
        or left.canonical_product_type_code != right.canonical_product_type_code
        or left.canonical_copy_cluster != right.canonical_copy_cluster
        or left.strategy_taxonomy_version != right.strategy_taxonomy_version
        or left.strategy_taxonomy_fingerprint != right.strategy_taxonomy_fingerprint
        or left.bosmax_product_family != right.bosmax_product_family
    )


def validate_copy_blueprint_v2(
    blueprint: CopyBlueprintV2,
    *,
    current_product_truth: ProductTruthLineage | None = None,
    evidence_registry: EvidenceRegistry | None = None,
    require_approval: bool = False,
    require_semantic_review: bool = False,
    require_duration_target: bool = False,
    duration_word_limit: int | None = None,
    max_words_per_second: float | None = None,
) -> CopyBlueprintV2ValidationResult:
    """Validate V2 without mutating the input.

    ``valid`` means the authored contract is structurally and evidentially
    valid.  ``production_valid`` additionally requires an immutable human
    approval snapshot and current Product Truth/evidence lineage.
    """

    issues: list[V2ValidationIssue] = []
    formula_id = blueprint.formula_id
    contract = None
    try:
        formula_id = strict_formula_id(blueprint.formula_id)
        contract = strict_formula_contract(formula_id)
    except MissingV2Formula:
        issues.append(_issue("COPY_V2_FORMULA_REQUIRED", "V2 requires an explicit formula"))
    except UnknownV2Formula:
        issues.append(_issue("COPY_V2_UNKNOWN_FORMULA", f"formula is not registered: {blueprint.formula_id}"))

    if contract is not None:
        expected_version = formula_version(formula_id)
        if blueprint.formula_version != expected_version:
            issues.append(
                _issue(
                    "COPY_V2_FORMULA_VERSION_INVALID",
                    f"formula version does not match authority: expected {expected_version}",
                )
            )
        if not is_production_formula(formula_id):
            issues.append(
                _issue(
                    "COPY_V2_FORMULA_NOT_PRODUCTION_SUPPORTED",
                    "operator-review-draft formulas cannot bind production",
                )
            )

        required = required_formula_stage_keys(formula_id)
        actual_formula_keys = [stage.formula_stage_key for stage in blueprint.stages]
        actual_stage_keys = [stage.stage_key for stage in blueprint.stages]
        if len(actual_stage_keys) != len(set(actual_stage_keys)) or len(actual_formula_keys) != len(set(actual_formula_keys)):
            issues.append(_issue("COPY_V2_STAGE_DUPLICATE", "stage keys and formula stage keys must be unique"))
        if actual_formula_keys != list(required):
            missing = [key for key in required if key not in actual_formula_keys]
            extra = [key for key in actual_formula_keys if key not in required]
            if missing:
                issues.append(_issue("COPY_V2_STAGE_MISSING", f"required formula stages missing: {missing}"))
            if extra:
                issues.append(_issue("COPY_V2_STAGE_FORMULA_MISMATCH", f"unknown formula stages supplied: {extra}"))
            if not missing and not extra:
                issues.append(_issue("COPY_V2_STAGE_ORDER_INVALID", "formula stages are not in authority order"))
        expected_orders = list(range(len(blueprint.stages)))
        if [stage.order for stage in blueprint.stages] != expected_orders:
            issues.append(_issue("COPY_V2_STAGE_ORDER_INVALID", "stage order must be contiguous and deterministic"))
        for stage in blueprint.stages:
            if not stage.authored_text:
                issues.append(_issue("COPY_V2_STAGE_TEXT_MISSING", "formula stage text is required", stage.stage_key))
            if stage.formula_stage_key not in required:
                issues.append(
                    _issue(
                        "COPY_V2_STAGE_FORMULA_MISMATCH",
                        f"stage is not registered for formula {formula_id}",
                        stage.stage_key,
                    )
                )

        for index, stage in enumerate(blueprint.stages):
            if not stage.bridge.entry or not stage.bridge.exit:
                issues.append(
                    _issue(
                        "COPY_V2_BRIDGE_INVALID",
                        "every formula stage requires an explicit bridge entry and exit",
                        stage.stage_key,
                    )
                )
            if index:
                previous = blueprint.stages[index - 1]
                if previous.bridge.exit != stage.bridge.entry:
                    issues.append(
                        _issue(
                            "COPY_V2_BRIDGE_INVALID",
                            "adjacent formula stages have discontinuous bridge labels",
                            stage.stage_key,
                        )
                    )

    if current_product_truth is None:
        issues.append(_issue("COPY_V2_PRODUCT_TRUTH_LINEAGE_MISSING", "current Product Truth lineage is required"))
    elif blueprint.product_truth_lineage != current_product_truth:
        if _same_product_truth_snapshot(blueprint.product_truth_lineage, current_product_truth) and _authority_lineage_changed(
            blueprint.product_truth_lineage,
            current_product_truth,
        ):
            issues.append(
                _issue(
                    "COPY_V2_TAXONOMY_AUTHORITY_STALE",
                    "blueprint taxonomy/strategy authority lineage is missing or stale",
                )
            )
        else:
            issues.append(_issue("COPY_V2_EVIDENCE_STALE", "blueprint Product Truth lineage is stale"))
    if blueprint.product_truth_lineage.snapshot_status != "APPROVED":
        issues.append(_issue("COPY_V2_EVIDENCE_NOT_APPROVED", "blueprint Product Truth snapshot is not approved"))

    envelope_refs = {(ref.snapshot_id, ref.fact_id): ref for ref in blueprint.evidence_refs}
    all_stage_refs: list[EvidenceReference] = []
    for stage in blueprint.stages:
        all_stage_refs.extend(stage.fact_refs)
        if stage.claim_bearing and not stage.fact_refs:
            issues.append(
                _issue(
                    "COPY_V2_EVIDENCE_MISSING",
                    "claim-bearing formula stage requires evidence references",
                    stage.stage_key,
                )
            )
        for ref in stage.fact_refs:
            if (ref.snapshot_id, ref.fact_id) not in envelope_refs:
                issues.append(
                    _issue(
                        "COPY_V2_EVIDENCE_LINEAGE_MISSING",
                        "stage evidence reference is absent from the blueprint evidence envelope",
                        stage.stage_key,
                    )
                )

    if evidence_registry is None and (blueprint.evidence_refs or all_stage_refs):
        issues.append(_issue("COPY_V2_EVIDENCE_REGISTRY_UNAVAILABLE", "evidence registry is required to validate references"))
    elif evidence_registry is not None:
        for ref in blueprint.evidence_refs:
            fact = evidence_registry.get(ref.snapshot_id, ref.fact_id)
            if fact is None:
                issues.append(_issue("COPY_V2_EVIDENCE_NOT_FOUND", f"evidence fact not found: {ref.fact_id}"))
                continue
            if fact.product_id != blueprint.product_id:
                issues.append(_issue("COPY_V2_EVIDENCE_PRODUCT_MISMATCH", f"fact belongs to another product: {ref.fact_id}"))
            if current_product_truth and fact.snapshot_id != current_product_truth.snapshot_id:
                issues.append(_issue("COPY_V2_EVIDENCE_STALE", f"evidence fact uses a stale snapshot: {ref.fact_id}"))
            if fact.text_digest != ref.text_digest:
                issues.append(_issue("COPY_V2_EVIDENCE_DIGEST_MISMATCH", f"fact wording digest differs: {ref.fact_id}"))
            if fact.fact_kind != ref.fact_kind:
                issues.append(_issue("COPY_V2_EVIDENCE_KIND_MISMATCH", f"fact kind differs: {ref.fact_id}"))
            if fact.snapshot_status != "APPROVED" or not fact.approved:
                issues.append(_issue("COPY_V2_EVIDENCE_NOT_APPROVED", f"fact is not approved: {ref.fact_id}"))

    duration_word_count = sum(len(stage.authored_text.split()) for stage in blueprint.stages)
    duration_word_budget = None
    duration_fit: bool | None = None
    if blueprint.target_duration_seconds is None:
        if require_duration_target:
            issues.append(
                _issue(
                    "COPY_V2_DURATION_TARGET_REQUIRED",
                    "Production approval requires an explicit target duration.",
                )
            )
            duration_fit = False
    else:
        try:
            duration_word_budget = canonical_duration_word_budget(
                blueprint.target_duration_seconds
            )
        except (TypeError, ValueError, KeyError) as exc:
            issues.append(
                _issue(
                    "COPY_V2_DURATION_AUTHORITY_UNRESOLVED",
                    f"Canonical duration/WPS authority could not resolve the target: {exc}",
                )
            )
        else:
            duration_fit = duration_word_count <= duration_word_budget
            if not duration_fit:
                issues.append(
                    _issue(
                        "COPY_V2_DURATION_BUDGET_EXCEEDED",
                        f"copy has {duration_word_count} words; canonical budget is {duration_word_budget}",
                    )
                )

    if duration_word_limit is not None:
        if duration_word_count > duration_word_limit:
            issues.append(
                _issue(
                    "COPY_DURATION_FIT_FAILED",
                    f"approved copy has {duration_word_count} words; limit is {duration_word_limit}",
                )
            )
    if max_words_per_second is not None and blueprint.target_duration_seconds:
        if duration_word_count / blueprint.target_duration_seconds > max_words_per_second:
            issues.append(
                _issue(
                    "COPY_V2_WPS_FIT_FAILED",
                    "copy exceeds the selected words-per-second budget",
                )
            )

    _compare_approval_artifact(blueprint, issues)
    has_approval = (
        blueprint.status in {"APPROVED", "PRODUCTION_VALID"}
        and blueprint.approval_snapshot is not None
        and bool(blueprint.approved_execution_text)
        and bool(blueprint.approved_by)
        and bool(blueprint.approved_at)
    )
    if require_approval and not has_approval:
        issues.append(_issue("COPY_V2_APPROVAL_MISSING", "production binding requires explicit human approval"))
    if require_semantic_review:
        proof = blueprint.semantic_review
        if proof is None or proof.decision != "APPROVED":
            issues.append(
                _issue(
                    "COPY_V2_SEMANTIC_REVIEW_REQUIRED",
                    "production V2 copy requires an explicit approved semantic review proof",
                )
            )

    error_codes = tuple(dict.fromkeys(issue.code for issue in issues))
    structural_valid = not error_codes
    production_valid = structural_valid and has_approval
    return CopyBlueprintV2ValidationResult(
        blueprint_id=blueprint.blueprint_id,
        revision=blueprint.revision,
        valid=structural_valid,
        production_valid=production_valid,
        formula_id=formula_id,
        formula_version=blueprint.formula_version,
        error_codes=error_codes,
        issues=tuple(issues),
        derived_projection_available=contract is not None and structural_valid,
        duration_word_count=duration_word_count,
        duration_word_budget=duration_word_budget,
        duration_fit=duration_fit,
    )


def approve_copy_blueprint_v2(
    blueprint: CopyBlueprintV2,
    *,
    approved_by: str,
    current_product_truth: ProductTruthLineage,
    evidence_registry: EvidenceRegistry,
    approved_at: str | None = None,
    semantic_review: SemanticReviewProof | None = None,
    readiness_proof: ProductionReadinessProof | None = None,
    require_duration_target: bool = True,
) -> CopyBlueprintV2:
    """Perform the explicit human approval transition.

    This is never called by validation or binding automatically.  It returns a
    new frozen revision and leaves the input artifact untouched.
    """

    if not str(approved_by or "").strip():
        raise CopyBlueprintV2Error("COPY_V2_APPROVER_REQUIRED", "human approver identity is required")
    if blueprint.status in {"APPROVED", "PRODUCTION_VALID"}:
        raise CopyBlueprintV2Error("COPY_V2_ALREADY_APPROVED", "approved V2 artifacts cannot be approved in place")
    artifact_updates = {}
    if semantic_review is not None:
        artifact_updates["semantic_review"] = semantic_review
    if readiness_proof is not None:
        artifact_updates["readiness_proof"] = readiness_proof
    artifact = blueprint.model_copy(update=artifact_updates) if artifact_updates else blueprint
    if semantic_review is not None and semantic_review.decision != "APPROVED":
        raise CopyBlueprintV2Error(
            "COPY_V2_SEMANTIC_REVIEW_REQUIRED",
            "semantic review must be explicitly approved before copy approval",
        )
    if readiness_proof is not None and not all(readiness_proof.model_dump(mode="python").values()):
        raise CopyBlueprintV2Error(
            "COPY_V2_READINESS_REQUIRED",
            "All production readiness gates must be explicitly proven before approval.",
        )
    result = validate_copy_blueprint_v2(
        artifact,
        current_product_truth=current_product_truth,
        evidence_registry=evidence_registry,
        require_duration_target=require_duration_target,
    )
    if not result.valid:
        raise CopyBlueprintV2Error(
            result.error_codes[0],
            "V2 blueprint cannot be approved while validation errors remain",
            details=result.model_dump(mode="json"),
        )
    timestamp = approved_at or datetime.now(timezone.utc).isoformat()
    execution = _approved_text(artifact.stages)
    refs = _unique_refs(list(artifact.evidence_refs))
    snapshot = ApprovalSnapshot(
        approval_snapshot_id=f"approval:{artifact.blueprint_id}:{artifact.revision}:{_blueprint_digest(artifact)[:16]}",
        blueprint_id=artifact.blueprint_id,
        revision=artifact.revision,
        blueprint_digest=_blueprint_digest(artifact),
        formula_id=strict_formula_id(artifact.formula_id),
        formula_version=formula_version(artifact.formula_id),
        product_truth_snapshot_id=current_product_truth.snapshot_id,
        stage_text_digests=_stage_text_digests(artifact.stages),
        approved_execution_text=execution,
        evidence_digest=_evidence_digest(refs),
        approved_by=approved_by.strip(),
        approved_at=timestamp,
        semantic_review=artifact.semantic_review,
        readiness_proof=artifact.readiness_proof,
    )
    return artifact.model_copy(
        update={
            "status": "APPROVED",
            "approval_snapshot": snapshot,
            "approved_execution_text": execution,
            "approved_by": approved_by.strip(),
            "approved_at": timestamp,
        }
    )


def create_blueprint_revision(
    previous: CopyBlueprintV2,
    *,
    stages: tuple[FormulaStage, ...],
    evidence_refs: tuple[EvidenceReference, ...],
    product_truth_lineage: ProductTruthLineage,
    objective: Any | None = None,
    angle: Any | None = None,
    formula_id: str | None = None,
    formula_version_value: str | None = None,
    created_at: str | None = None,
) -> CopyBlueprintV2:
    """Create a new draft revision; never edits/scrubs the approved parent."""

    return previous.model_copy(
        update={
            "revision": previous.revision + 1,
            "status": "DRAFT",
            "formula_id": formula_id if formula_id is not None else previous.formula_id,
            "formula_version": formula_version_value if formula_version_value is not None else previous.formula_version,
            "objective": objective if objective is not None else previous.objective,
            "angle": angle if angle is not None else previous.angle,
            "stages": stages,
            "evidence_refs": evidence_refs,
            "product_truth_lineage": product_truth_lineage,
            "approval_snapshot": None,
            "approved_execution_text": (),
            "semantic_review": None,
            "readiness_proof": None,
            "approved_at": None,
            "approved_by": None,
            "supersedes": SupersessionRef(blueprint_id=previous.blueprint_id, revision=previous.revision),
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        }
    )


def bind_copy_blueprint_v2(
    blueprint: CopyBlueprintV2,
    *,
    lane: str,
    current_product_truth: ProductTruthLineage,
    evidence_registry: EvidenceRegistry,
    feature_flags: CopyBlueprintV2FeatureFlagState | None = None,
    compiler_binding_version: str = V2_BINDING_VERSION,
    bound_at: str | None = None,
) -> CopyExecutionBinding:
    """Create a production binding only for an explicitly enabled V2 lane."""

    descriptor = get_lane_descriptor(lane)
    if descriptor.copy_policy != "REQUIRED":
        raise CopyBlueprintV2Error(
            "COPY_V2_BINDING_NOT_REQUIRED",
            f"lane {descriptor.lane_id} is explicitly copy-free and needs no binding",
        )
    flags = feature_flags or CopyBlueprintV2FeatureFlagState.from_environment()
    if not flags.enabled or flags.state == "OFF":
        raise CopyBlueprintV2Error("COPY_V2_FEATURE_FLAG_OFF", "V2 binding is disabled by default")
    if flags.shadow_mode or flags.state == "SHADOW":
        raise CopyBlueprintV2Error("COPY_V2_SHADOW_BINDING_FORBIDDEN", "shadow validation cannot create a production binding")
    if not flags.scope:
        raise CopyBlueprintV2Error("COPY_V2_SCOPE_REQUIRED", "V2 binding scope must be explicit")

    result = validate_copy_blueprint_v2(
        blueprint,
        current_product_truth=current_product_truth,
        evidence_registry=evidence_registry,
        require_approval=True,
    )
    if not result.production_valid:
        code = result.error_codes[0] if result.error_codes else "COPY_V2_PRODUCTION_BINDING_INVALID"
        raise CopyBlueprintV2Error(
            code,
            "V2 blueprint is not production-valid and cannot bind",
            details=result.model_dump(mode="json"),
        )
    refs = _unique_refs(list(blueprint.evidence_refs))
    snapshot = blueprint.approval_snapshot
    assert snapshot is not None
    return CopyExecutionBinding(
        binding_id=f"binding:{blueprint.blueprint_id}:{blueprint.revision}:{descriptor.lane_id}:{snapshot.approval_snapshot_id}",
        lane=descriptor.lane_id,
        media_kind=descriptor.media_kind,
        copy_policy=descriptor.copy_policy,
        blueprint_id=blueprint.blueprint_id,
        revision=blueprint.revision,
        formula_id=blueprint.formula_id,
        formula_version=blueprint.formula_version,
        approval_snapshot_id=snapshot.approval_snapshot_id,
        product_truth_lineage=current_product_truth,
        evidence_lineage=EvidenceLineage(
            snapshot_ids=tuple(dict.fromkeys(ref.snapshot_id for ref in refs)),
            fact_ids=tuple(dict.fromkeys(ref.fact_id for ref in refs)),
            references=refs,
            evidence_digest=_evidence_digest(refs),
        ),
        compiler_binding_version=compiler_binding_version,
        feature_flag_state=flags,
        bound_at=bound_at or datetime.now(timezone.utc).isoformat(),
    )


def _assert_adapter_context(context: AdapterContext, product_id: str, lineage: ProductTruthLineage) -> None:
    if context.product_id != product_id:
        raise CopyBlueprintV2Error("COPY_V2_PRODUCT_MISMATCH", "adapter context product differs from blueprint binding")
    if context.product_truth_lineage != lineage:
        raise CopyBlueprintV2Error("COPY_V2_EVIDENCE_STALE", "adapter context Product Truth lineage is stale")
    for key in ("readiness_validated", "provenance_validated", "safety_validated"):
        if not getattr(context, key):
            raise CopyBlueprintV2Error(
                "COPY_V2_GATE_NOT_PROVEN",
                f"adapter requires explicit {key} proof",
            )


def project_video_copy(
    binding: CopyExecutionBinding,
    blueprint: CopyBlueprintV2,
    *,
    context: AdapterContext,
) -> Any:
    """Universal required-copy adapter for all seven video lanes."""

    descriptor = get_lane_descriptor(binding.lane)
    if descriptor.media_kind != "VIDEO" or descriptor.copy_policy != "REQUIRED":
        raise CopyBlueprintV2Error("COPY_V2_LANE_POLICY_MISMATCH", "video adapter received a non-video lane")
    _assert_adapter_context(context, blueprint.product_id, binding.product_truth_lineage)
    if binding.blueprint_id != blueprint.blueprint_id or binding.revision != blueprint.revision:
        raise CopyBlueprintV2Error("COPY_V2_BINDING_LINEAGE_INVALID", "binding does not target the selected blueprint revision")
    from agent.models.copy_blueprint_v2 import VideoCopyProjection

    return VideoCopyProjection(
        lane=descriptor.lane_id,
        binding=binding,
        derived_copy=blueprint.derived_projections(),
        context=context,
    )


def project_image_copy(
    lane: str,
    *,
    context: AdapterContext,
    binding: CopyExecutionBinding | None = None,
    blueprint: CopyBlueprintV2 | None = None,
) -> Any:
    """Universal image adapter with an explicit copy-free policy."""

    descriptor = get_lane_descriptor(lane)
    if descriptor.media_kind != "IMAGE":
        raise CopyBlueprintV2Error("COPY_V2_LANE_POLICY_MISMATCH", "image adapter received a non-image lane")
    _assert_adapter_context(context, context.product_id, context.product_truth_lineage)
    if descriptor.copy_policy == "REQUIRED":
        if binding is None or blueprint is None:
            raise CopyBlueprintV2Error("COPY_V2_PRODUCTION_BINDING_INVALID", "copy-aware image lane requires a V2 binding")
        if binding.lane != descriptor.lane_id or binding.media_kind != "IMAGE":
            raise CopyBlueprintV2Error("COPY_V2_BINDING_LINEAGE_INVALID", "image binding lane does not match adapter lane")
        if binding.blueprint_id != blueprint.blueprint_id or binding.revision != blueprint.revision:
            raise CopyBlueprintV2Error("COPY_V2_BINDING_LINEAGE_INVALID", "binding does not target the selected blueprint revision")
        from agent.models.copy_blueprint_v2 import ImageCopyProjection

        return ImageCopyProjection(
            lane=descriptor.lane_id,
            copy_policy="REQUIRED",
            copy_required=True,
            binding=binding,
            derived_copy=blueprint.derived_projections(),
            context=context,
        )
    if binding is not None or blueprint is not None:
        raise CopyBlueprintV2Error("COPY_V2_BINDING_NOT_REQUIRED", "copy-free image lane must not receive a V2 binding")
    from agent.models.copy_blueprint_v2 import ImageCopyProjection

    return ImageCopyProjection(
        lane=descriptor.lane_id,
        copy_policy="NOT_REQUIRED",
        copy_required=False,
        context=context,
    )
