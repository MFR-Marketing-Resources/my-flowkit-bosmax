"""Macro Round 1 provider-free Formula-Driven Storyboard Landbank factory.

This module is intentionally upstream of V2 production.  It reads the
canonical Product Truth/evidence substrate and Formula/WPS authorities, writes
only the seven Phase 2 V3 records, and never imports a provider, media lane,
approval receipt, V2 materialization, or P6 production path.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from itertools import product as cartesian_product
from typing import Any, Iterable, Iterator, Mapping, Sequence

from agent.authority.copy_blueprint_v2_authority import (
    formula_version,
    is_production_formula,
    required_formula_stage_keys,
    strict_formula_contract,
    strict_formula_id,
)
from agent.db.schema import _db_lock, get_db
from agent.models.copy_blueprint_v2 import EvidenceFact, EvidenceRegistry, digest_evidence_text
from agent.models.storyboard_landbank_v3 import (
    V3Angle,
    V3BridgeContract,
    V3ComponentStageSegment,
    V3CopyRecipe,
    V3DurationProjection,
    V3FormulaRef,
    V3FormulaStage,
    V3MasterStoryboard,
    V3Objective,
    V3ProductTruthLineage,
    V3ProjectedStageSlice,
    V3RevisionRef,
    V3ReviewEvent,
    V3SeamState,
    V3StoryboardComponent,
    V3StorylineFamily,
    V3ValidationReceipt,
    deterministic_digest,
    deterministic_id,
    digest_text,
    exact_resolved_content_fingerprint,
    master_content_digest,
    normalized_text,
    projected_stage_allocations_digest,
    projection_content_digest,
    validation_receipt_digest,
    word_count,
)
from agent.models.storyboard_landbank_v3_round1 import (
    V3CandidateCombination,
    V3CandidatePage,
    V3CapacitySnapshot,
    V3CompileResult,
    V3EvidenceSelection,
    V3ExclusionReceipt,
    V3FormulaReadModel,
    V3LandbankPage,
)
from agent.services import canonical_prompt_compiler
from agent.services.storyboard_landbank_v3_validators import (
    BridgeContinuityValidator,
    ComponentStageValidator,
    DurationProjectionValidator,
    EvidenceLineageValidator,
    FormulaContractValidator,
    MasterStoryboardValidator,
    StorylineCompatibilityValidator,
    V3ValidationResult,
    receipt_from_result,
)


ROUND1_SOURCE = "STORYBOARD_LANDBANK_V3_ROUND1"
ROUND1_VALIDATOR_VERSION = "storyboard-landbank-v3-round1-1"
MAX_PAGE_SIZE = 500
MAX_CANDIDATE_BATCH = 250
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_TERMINAL_STATUSES = {
    "APPROVED",
    "FROZEN",
    "REJECTED",
    "BLOCKED",
    "SUPERSEDED",
    "ARCHIVED",
}
_REVISION_LINEAGE_FIELDS = {
    "schema_version",
    "product_id",
    "product_truth",
    "angle",
    "storyline_family",
    "formula",
    "objective",
    "recipe",
    "master",
    "revision",
    "supersedes",
    "created_at",
    "created_by",
    "angle_digest",
    "family_digest",
    "content_digest",
    "config_digest",
    "exact_content_digest",
    "duplicate_fingerprint",
    "exact_projection_digest",
}
_ENTITY_TABLES = {
    "ANGLE": ("angle_v3", "angle_id"),
    "STORYLINE_FAMILY": ("storyline_family_v3", "family_id"),
    "STORYBOARD_COMPONENT": ("storyboard_component_v3", "component_id"),
    "COPY_RECIPE": ("copy_recipe_v3", "recipe_id"),
    "MASTER_STORYBOARD": ("master_storyboard_v3", "master_id"),
    "DURATION_PROJECTION": ("duration_projection_v3", "projection_id"),
}
_MODEL_TYPES = (
    ("ANGLE", V3Angle),
    ("STORYLINE_FAMILY", V3StorylineFamily),
    ("STORYBOARD_COMPONENT", V3StoryboardComponent),
    ("COPY_RECIPE", V3CopyRecipe),
    ("MASTER_STORYBOARD", V3MasterStoryboard),
    ("DURATION_PROJECTION", V3DurationProjection),
)


class V3FactoryError(ValueError):
    """Stable, provider-free service error suitable for API translation."""

    def __init__(self, code: str, message: str, *, status_code: int = 409, details: Any = None):
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _ref(entity_id: str, revision: int) -> V3RevisionRef:
    return V3RevisionRef(entity_id=str(entity_id), revision=int(revision))


def _formula_ref(formula_id: str, version: str | None = None) -> V3FormulaRef:
    try:
        canonical = strict_formula_id(formula_id)
    except ValueError as exc:
        raise V3FactoryError("FORMULA_UNKNOWN", "Formula is not registered; V3 fails closed.", details=str(exc)) from exc
    expected = formula_version(canonical)
    if version is not None and version != expected:
        raise V3FactoryError(
            "FORMULA_VERSION_MISMATCH",
            "Formula version is stale or does not match the canonical registry.",
            details={"expected": expected, "received": version},
        )
    if not is_production_formula(canonical):
        raise V3FactoryError(
            "FORMULA_NOT_PRODUCTION_ELIGIBLE",
            "Only canonical formulas may compile production-eligible Round 1 candidates.",
            details={"formula_id": canonical},
        )
    return V3FormulaRef(formula_id=canonical, formula_version=expected)


def _mapping_values(contract: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = (contract.get("output_mapping") or {}).get(key)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def formula_read_model(formula_id: str) -> V3FormulaReadModel:
    """Resolve one formula directly from the checked-in canonical registry."""

    try:
        canonical = strict_formula_id(formula_id)
    except ValueError as exc:
        raise V3FactoryError("FORMULA_UNKNOWN", "Formula is not registered; V3 fails closed.", details=str(exc)) from exc
    contract = strict_formula_contract(canonical)
    ref = V3FormulaRef(formula_id=canonical, formula_version=formula_version(canonical))
    stages = tuple(required_formula_stage_keys(canonical))
    hook = _mapping_values(contract, "hook")
    cta = _mapping_values(contract, "cta")
    body = tuple(stage for stage in stages if stage not in set(hook) | set(cta))
    return V3FormulaReadModel(
        formula_id=ref.formula_id,
        formula_version=ref.formula_version,
        status=str(contract.get("definition_status") or "UNKNOWN"),
        compiler_family=str(contract.get("compiler_family") or ref.formula_id),
        ordered_required_stages=stages,
        hook_mapping=hook,
        body_core_mapping=body,
        cta_mapping=cta,
        production_eligible=is_production_formula(ref.formula_id),
        display_name=str(contract.get("display_name") or ref.formula_id),
        slots=tuple(contract.get("slots") or ()),
    )


def list_formula_read_models(*, production_only: bool = False) -> tuple[V3FormulaReadModel, ...]:
    # The registry is the authority.  This deliberately discovers its current
    # set rather than repeating formula names in the V3 layer.
    from agent.authority.copy_formula_registry import FORMULA_REGISTRY

    models = tuple(formula_read_model(formula_id) for formula_id in FORMULA_REGISTRY)
    if production_only:
        models = tuple(item for item in models if item.production_eligible)
    return models


def _receipt(
    validator: str,
    *,
    valid: bool = True,
    issue_codes: Sequence[str] = (),
) -> V3ValidationReceipt:
    base = V3ValidationReceipt(
        validator=validator,
        validator_version=ROUND1_VALIDATOR_VERSION,
        valid=bool(valid),
        issue_codes=tuple(dict.fromkeys(str(item) for item in issue_codes)),
        receipt_digest="0" * 64,
    )
    return base.model_copy(update={"receipt_digest": validation_receipt_digest(base)})


def _result_receipt(result: V3ValidationResult) -> V3ValidationReceipt:
    receipt = receipt_from_result(result)
    # Keep the stable Phase 2 validator version in the receipt; the result is
    # already deterministic and its digest is recalculated by the model helper.
    return receipt


def _component_segments(component: V3StoryboardComponent) -> tuple[V3ComponentStageSegment, ...]:
    """Read new segments, with a safe single-stage compatibility projection."""

    if component.stage_segments:
        return tuple(component.stage_segments)
    if len(component.formula_stage_keys) != 1:
        return ()
    key = component.formula_stage_keys[0]
    return (
        V3ComponentStageSegment(
            formula_stage_key=key,
            semantic_class=component.semantic_class,
            order=component.ordered_stage_coverage[0],
            authored_text=component.authored_text,
            text_digest=component.content_digest,
            entry_key=component.entry_key,
            exit_key=component.exit_key,
            bridge_contract=component.bridge_contract,
            evidence_fact_ids=component.evidence_fact_ids,
            evidence_digest=component.evidence_digest,
            claim_bearing=component.claim_bearing,
        ),
    )


def _evidence_result(
    truth: V3ProductTruthLineage,
    stage_evidence: Sequence[tuple[Sequence[str], bool]],
    registry: EvidenceRegistry,
) -> V3ValidationResult:
    issues: list[tuple[str, str]] = []
    for ids, claim_bearing in stage_evidence:
        result = EvidenceLineageValidator.validate(
            truth, ids, registry, claim_bearing=claim_bearing
        )
        issues.extend(zip(result.issue_codes, result.details))
    unique: dict[str, str] = {}
    for code, detail in issues:
        unique.setdefault(code, detail)
    payload = {
        "validator": "EvidenceLineageValidator",
        "validator_version": ROUND1_VALIDATOR_VERSION,
        "valid": not unique,
        "production_valid": not unique,
        "issue_codes": list(unique),
        "details": list(unique.values()),
    }
    return V3ValidationResult(
        validator="EvidenceLineageValidator",
        validator_version=ROUND1_VALIDATOR_VERSION,
        valid=not unique,
        production_valid=not unique,
        issue_codes=tuple(unique),
        details=tuple(unique.values()),
        receipt_digest=deterministic_digest(payload),
    )


def compile_master_storyboard(
    *,
    recipe: V3CopyRecipe,
    angle: V3Angle,
    storyline_family: V3StorylineFamily,
    hook: V3StoryboardComponent,
    body_core: V3StoryboardComponent,
    cta: V3StoryboardComponent,
    evidence_registry: EvidenceRegistry,
    created_by: str = "round1-compiler",
    source: str = ROUND1_SOURCE,
    created_at: str | None = None,
) -> V3CompileResult:
    """Compile one complete formula-native Master without authoring text."""

    components = (hook, body_core, cta)
    issues: list[str] = []
    details: list[str] = []
    if recipe.product_truth is None:
        return V3CompileResult(
            valid=False,
            issues=("TRUTH_LINEAGE_REQUIRED",),
            details=("Recipe must be bound to current approved Product Truth.",),
        )
    try:
        formula = _formula_ref(recipe.formula.formula_id, recipe.formula.formula_version)
    except V3FactoryError as exc:
        return V3CompileResult(valid=False, issues=(exc.code,), details=(str(exc),))
    if recipe.product_id != angle.product_id or recipe.product_id != storyline_family.product_id:
        issues.append("PRODUCT_MISMATCH")
    if angle.product_truth != recipe.product_truth:
        issues.append("ANGLE_TRUTH_LINEAGE_MISMATCH")
    if storyline_family.product_truth != recipe.product_truth:
        issues.append("STORYLINE_TRUTH_LINEAGE_MISMATCH")
    if angle.formula is not None and angle.formula != formula:
        issues.append("ANGLE_FORMULA_INCOMPATIBLE")
    if storyline_family.formula != formula:
        issues.append("STORYLINE_FORMULA_MISMATCH")
    if storyline_family.angle != _ref(angle.angle_id, angle.revision):
        issues.append("STORYLINE_ANGLE_MISMATCH")
    if any(
        component.product_id != recipe.product_id
        or component.product_truth != recipe.product_truth
        or component.objective != recipe.objective
        or component.angle != _ref(angle.angle_id, angle.revision)
        or component.storyline_family != _ref(storyline_family.family_id, storyline_family.revision)
        or component.formula != formula
        for component in components
    ):
        issues.append("COMPONENT_LINEAGE_MISMATCH")
    if [item.semantic_class for item in components] != ["HOOK", "BODY_CORE", "CTA"]:
        issues.append("COMPONENT_SEMANTIC_CLASS_SET_INVALID")

    required = tuple(required_formula_stage_keys(formula.formula_id))
    by_stage: dict[str, tuple[V3StoryboardComponent, V3ComponentStageSegment]] = {}
    for component in components:
        segments = _component_segments(component)
        for segment in segments:
            if segment.formula_stage_key in by_stage:
                issues.append("FORMULA_STAGE_DUPLICATE")
            by_stage[segment.formula_stage_key] = (component, segment)
    if tuple(key for key in required if key in by_stage) != required:
        issues.append("FORMULA_STAGE_COVERAGE_MISMATCH")
    if set(by_stage) != set(required):
        issues.append("MISSING_FORMULA_STAGE")
    if issues:
        return V3CompileResult(valid=False, issues=tuple(dict.fromkeys(issues)), details=tuple(details))

    stages: list[V3FormulaStage] = []
    evidence_map: dict[str, tuple[str, ...]] = {}
    evidence_inputs: list[tuple[Sequence[str], bool]] = []
    for index, stage_key in enumerate(required):
        component, segment = by_stage[stage_key]
        stage_id = f"stage:{index}:{stage_key}"
        stages.append(
            V3FormulaStage(
                stage_key=stage_id,
                order=index,
                formula_stage_key=stage_key,
                semantic_class=segment.semantic_class,
                authored_text=segment.authored_text,
                entry_key=segment.entry_key,
                exit_key=segment.exit_key,
                bridge_contract=segment.bridge_contract,
                claim_bearing=segment.claim_bearing,
                evidence_fact_ids=segment.evidence_fact_ids,
                text_digest=segment.text_digest,
                component_ref=_ref(component.component_id, component.revision),
            )
        )
        evidence_map[stage_id] = tuple(segment.evidence_fact_ids)
        evidence_inputs.append((segment.evidence_fact_ids, segment.claim_bearing))

    formula_result = FormulaContractValidator.validate(
        formula.formula_id, formula.formula_version, required
    )
    bridge_result = BridgeContinuityValidator.validate(
        stages, expected_stage_keys=required
    )
    evidence_result = _evidence_result(recipe.product_truth, evidence_inputs, evidence_registry)
    if not formula_result.valid:
        issues.extend(formula_result.issue_codes)
        details.extend(formula_result.details)
    if not bridge_result.valid:
        issues.extend(bridge_result.issue_codes)
        details.extend(bridge_result.details)
    if not evidence_result.valid:
        issues.extend(evidence_result.issue_codes)
        details.extend(evidence_result.details)
    if issues:
        return V3CompileResult(
            valid=False,
            production_eligible=formula_result.production_valid,
            issues=tuple(dict.fromkeys(issues)),
            details=tuple(dict.fromkeys(details)),
            receipts=(_result_receipt(formula_result), _result_receipt(bridge_result), _result_receipt(evidence_result)),
        )

    master = V3MasterStoryboard(
        master_id=deterministic_id(
            "master",
            {
                "recipe": [recipe.recipe_id, recipe.revision],
                "angle": [angle.angle_id, angle.revision],
                "family": [storyline_family.family_id, storyline_family.revision],
                "components": [[item.component_id, item.revision] for item in components],
            },
        ),
        revision=1,
        recipe=_ref(recipe.recipe_id, recipe.revision),
        product_id=recipe.product_id,
        product_truth=recipe.product_truth,
        objective=recipe.objective,
        angle=_ref(angle.angle_id, angle.revision),
        storyline_family=_ref(storyline_family.family_id, storyline_family.revision),
        formula=formula,
        stages=tuple(stages),
        resolved_component_refs=tuple(_ref(item.component_id, item.revision) for item in components),
        evidence_map=evidence_map,
        evidence_digest=deterministic_digest(evidence_map),
        bridge_continuity_receipt=_result_receipt(bridge_result),
        formula_validation_receipt=_result_receipt(formula_result),
        claim_safety_receipt=_result_receipt(evidence_result),
        exact_content_digest="0" * 64,
        duplicate_fingerprint="0" * 64,
        word_count=sum(word_count(stage.authored_text) for stage in stages),
        status="VALIDATED",
        source=source,
        created_at=created_at or _now(),
        created_by=created_by,
    )
    master = master.model_copy(
        update={
            "exact_content_digest": master_content_digest(master),
            "duplicate_fingerprint": exact_resolved_content_fingerprint(master),
        }
    )
    master_result = MasterStoryboardValidator.validate(
        master,
        evidence_registry=evidence_registry,
        angle=angle,
        storyline_family=storyline_family,
        components=components,
    )
    if not master_result.valid:
        return V3CompileResult(
            valid=False,
            production_eligible=master_result.production_valid,
            issues=master_result.issue_codes,
            details=master_result.details,
            receipts=(
                _result_receipt(formula_result),
                _result_receipt(bridge_result),
                _result_receipt(evidence_result),
                _result_receipt(master_result),
            ),
        )
    return V3CompileResult(
        valid=True,
        production_eligible=True,
        master=master,
        receipts=(
            _result_receipt(formula_result),
            _result_receipt(bridge_result),
            _result_receipt(evidence_result),
            _result_receipt(master_result),
        ),
    )


def _compress_ordered(text: str, budget: int) -> str | None:
    tokens = normalized_text(text).split()
    if not tokens or budget < 1:
        return None
    if len(tokens) <= budget:
        return normalized_text(text)
    # Deterministic, contract-safe compression: preserve the authored token
    # order and remove only the tail. No generated paraphrase is introduced.
    return " ".join(tokens[:budget])


def compile_duration_projection(
    master: V3MasterStoryboard,
    *,
    duration_seconds: int,
    evidence_registry: EvidenceRegistry,
    language_profile: str = "Malay",
    wps_mode: str = "SAFE",
    engine: str = "GOOGLE_FLOW",
    preferred_lane: str | None = None,
    created_by: str = "round1-compiler",
    source: str = ROUND1_SOURCE,
    created_at: str | None = None,
) -> tuple[V3DurationProjection | None, tuple[str, ...], tuple[str, ...]]:
    """Derive one duration child from Master stage text and WPS authority."""

    try:
        language = canonical_prompt_compiler.strict_language_name(language_profile)
        blocks = tuple(
            canonical_prompt_compiler.resolve_block_plan(
                engine, int(duration_seconds), preferred_lane=preferred_lane
            )
        )
        budgets = tuple(
            canonical_prompt_compiler.strict_dialogue_word_budget(
                seconds, language, wps_mode=wps_mode
            )
            for seconds in blocks
        )
    except ValueError as exc:
        return None, ("WPS_DURATION_FIT_SHORTFALL",), (str(exc),)
    if not master.stages:
        return None, ("MISSING_FORMULA_STAGE",), ("Master contains no stages",)
    if master.stages[-1].semantic_class != "CTA":
        return None, ("CTA_CLOSURE_INVALID",), ("Master final stage is not CTA",)

    cta_words = word_count(master.stages[-1].authored_text)
    if cta_words > budgets[-1]:
        return None, ("WPS_DURATION_FIT_SHORTFALL",), ("CTA exceeds the final block budget",)
    hook_words = word_count(master.stages[0].authored_text)
    if hook_words > budgets[0]:
        return None, ("WPS_DURATION_FIT_SHORTFALL",), ("HOOK exceeds the first block budget",)

    target_blocks: list[int | None] = [None] * len(master.stages)
    projected_text: list[str | None] = [None] * len(master.stages)
    transform_modes: list[str] = ["IDENTITY"] * len(master.stages)
    used = [0] * len(blocks)
    target_blocks[0] = 0
    projected_text[0] = normalized_text(master.stages[0].authored_text)
    used[0] += hook_words
    used[-1] += cta_words
    target_blocks[-1] = len(blocks) - 1
    projected_text[-1] = normalized_text(master.stages[-1].authored_text)

    body_indices = list(range(1, len(master.stages) - 1))
    last_body_block = max(0, len(blocks) - 2)  # reserve the final block for CTA
    for body_position, index in enumerate(body_indices):
        stage = master.stages[index]
        full = normalized_text(stage.authored_text)
        full_words = word_count(full)
        chosen: int | None = None
        desired_block = min(
            last_body_block,
            round((body_position + 1) * (len(blocks) - 1) / (len(body_indices) + 1)),
        )
        search_blocks = list(range(desired_block, last_body_block + 1)) + list(range(0, desired_block))
        # Prefer a block where the exact stage fits; this keeps identity as the
        # common path for 16s/24s and avoids needless compression.
        for block_index in search_blocks:
            available = budgets[block_index] - used[block_index]
            if block_index == len(blocks) - 1:
                available = budgets[block_index] - used[block_index]
            if full_words <= available:
                chosen = block_index
                break
        if chosen is None:
            for block_index in search_blocks:
                available = budgets[block_index] - used[block_index]
                if available > 0:
                    chosen = block_index
                    compressed = _compress_ordered(full, available)
                    if compressed is None:
                        break
                    projected_text[index] = compressed
                    transform_modes[index] = "COMPRESSED" if compressed != full else "IDENTITY"
                    used[block_index] += word_count(compressed)
                    break
        if chosen is None:
            return None, ("WPS_DURATION_FIT_SHORTFALL",), (f"stage={stage.formula_stage_key}",)
        target_blocks[index] = chosen
        if projected_text[index] is None:
            projected_text[index] = full
            used[chosen] += full_words

    allocations: list[V3ProjectedStageSlice] = []
    for index, stage in enumerate(master.stages):
        text = projected_text[index] or ""
        block_index = target_blocks[index]
        if block_index is None:
            return None, ("WPS_DURATION_FIT_SHORTFALL",), (stage.formula_stage_key,)
        allocations.append(
            V3ProjectedStageSlice(
                master_stage_key=stage.stage_key,
                master_formula_stage_key=stage.formula_stage_key,
                master_semantic_class=stage.semantic_class,
                master_stage_text_digest=stage.text_digest,
                projected_text=text,
                projected_text_digest=digest_text(text),
                source_evidence_fact_ids=stage.evidence_fact_ids,
                source_evidence_digest=deterministic_digest(list(stage.evidence_fact_ids)),
                target_block_indices=(block_index,),
                order=index,
                transform_mode=transform_modes[index],
                omission_state="PRESENT",
            )
        )
    allocation_tuple = tuple(allocations)
    slices = tuple(
        " ".join(
            item.projected_text
            for item in allocation_tuple
            if item.target_block_indices == (block_index,)
        ).strip()
        for block_index in range(len(blocks))
    )
    seams: list[V3SeamState] = []
    for boundary in range(len(blocks) - 1):
        left = [item for item in allocation_tuple if item.target_block_indices[0] <= boundary]
        right = [item for item in allocation_tuple if item.target_block_indices[0] > boundary]
        if not left or not right:
            continue
        outgoing = master.stages[left[-1].order].exit_key
        incoming = master.stages[right[0].order].entry_key
        seams.append(
            V3SeamState(
                block_index=boundary,
                outgoing_exit_key=outgoing,
                incoming_entry_key=incoming,
                dialogue_start_seconds=float(sum(blocks[:boundary])),
                dialogue_end_seconds=float(sum(blocks[: boundary + 1])),
            )
        )
    # The validator requires one seam per block boundary.  Empty dialogue
    # blocks still inherit the adjacent stage bridge state deterministically.
    if len(seams) != max(0, len(blocks) - 1):
        seams = []
        for boundary in range(len(blocks) - 1):
            left = [item for item in allocation_tuple if item.target_block_indices[0] <= boundary]
            right = [item for item in allocation_tuple if item.target_block_indices[0] > boundary]
            if not left or not right:
                # A boundary with no stage on one side is not a coherent
                # production projection; fail closed rather than inventing a
                # bridge token.
                return None, ("BRIDGE_SHORTFALL",), (f"empty stage boundary {boundary}",)
            seams.append(
                V3SeamState(
                    block_index=boundary,
                    outgoing_exit_key=master.stages[left[-1].order].exit_key,
                    incoming_entry_key=master.stages[right[0].order].entry_key,
                    dialogue_start_seconds=float(sum(blocks[:boundary])),
                    dialogue_end_seconds=float(sum(blocks[: boundary + 1])),
                )
            )

    projection = V3DurationProjection(
        projection_id=deterministic_id(
            "projection",
            {"master": [master.master_id, master.revision], "duration": int(duration_seconds), "language": language, "wps": wps_mode},
        ),
        revision=1,
        master=_ref(master.master_id, master.revision),
        product_id=master.product_id,
        product_truth=master.product_truth,
        target_duration_seconds=int(duration_seconds),
        engine=str(engine),
        language_profile=language,
        wps_mode=str(wps_mode).upper(),
        wps_authority_version=canonical_prompt_compiler.wps_authority_version(),
        wps_authority_digest=canonical_prompt_compiler.wps_authority_digest(),
        block_plan_seconds=blocks,
        exact_resolved_dialogue=" ".join(slices).strip(),
        per_block_slices=slices,
        per_block_word_counts=tuple(word_count(item) for item in slices),
        per_block_word_budgets=budgets,
        stage_allocations=allocation_tuple,
        stage_allocation_digest=projected_stage_allocations_digest(allocation_tuple),
        cta_block_index=len(blocks) - 1,
        cta_stage_key=master.stages[-1].stage_key,
        seam_states=tuple(seams),
        continuity_receipt=_receipt("BridgeContinuityValidator"),
        formula_arc_receipt=_receipt("MasterStoryboardValidator"),
        stage_allocation_receipt=_receipt("DurationProjectionValidator"),
        master_stage_keys=tuple(stage.stage_key for stage in master.stages),
        master_stage_text_digests=tuple(stage.text_digest for stage in master.stages),
        master_exact_content_digest=master_content_digest(master),
        exact_projection_digest="0" * 64,
        status="VALIDATED",
        source=source,
        created_at=created_at or _now(),
        created_by=created_by,
    )
    projection = projection.model_copy(update={"exact_projection_digest": projection_content_digest(projection)})
    result = DurationProjectionValidator.validate(projection, master, evidence_registry=evidence_registry)
    if not result.valid:
        return None, result.issue_codes, result.details
    projection = projection.model_copy(update={"stage_allocation_receipt": _result_receipt(result)})
    projection = projection.model_copy(update={"exact_projection_digest": projection_content_digest(projection)})
    result = DurationProjectionValidator.validate(projection, master, evidence_registry=evidence_registry)
    if not result.valid:
        return None, result.issue_codes, result.details
    return projection, (), ()


def encode_cursor(offset: int, *, seed: str) -> str:
    payload = _json({"offset": int(offset), "seed": str(seed)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, *, seed: str) -> int:
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode((cursor + padding).encode("ascii")))
        if payload.get("seed") != seed or int(payload.get("offset", -1)) < 0:
            raise ValueError
        return int(payload["offset"])
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeError):
        raise V3FactoryError("CURSOR_INVALID", "Candidate cursor is invalid for this recipe seed.", status_code=422)


def _candidate_sort_key(item: V3StoryboardComponent, *, seed: str) -> tuple[str, str, int]:
    return (deterministic_digest({"seed": seed, "content": item.content_digest}), item.component_id, item.revision)


def _entity_digest(model: Any) -> str:
    for field in (
        "angle_digest",
        "family_digest",
        "content_digest",
        "config_digest",
        "exact_content_digest",
        "exact_projection_digest",
    ):
        value = getattr(model, field, None)
        if value:
            return str(value)
    return deterministic_digest(model.model_dump(mode="json"))


def _mutation_digest(model: Any) -> str:
    """Digest the persisted mutation payload, excluding server timestamps."""

    entity_type, row = _entity_row(model)
    payload = {
        key: value
        for key, value in row.items()
        if key not in {"created_at", "created_by"}
    }
    return deterministic_digest({"entity_type": entity_type, "row": payload})


def _entity_type_for_model(model: Any) -> str:
    for entity_type, model_type in _MODEL_TYPES:
        if isinstance(model, model_type):
            return entity_type
    raise V3FactoryError("V3_ENTITY_UNKNOWN", f"Unsupported V3 model: {type(model).__name__}")


def _recompute_revision_model(current: Any, updates: Mapping[str, Any], *, actor_id: str) -> Any:
    """Validate a revision payload and recalculate all content digests."""

    entity_type = _entity_type_for_model(current)
    payload = current.model_dump(mode="json")
    payload.update(dict(updates))
    payload.update({
        "revision": int(current.revision) + 1,
        "supersedes": {"entity_id": getattr(current, _ENTITY_TABLES[entity_type][1]), "revision": current.revision},
        "created_at": _now(),
        "created_by": actor_id,
    })
    model_type = dict(_MODEL_TYPES)[entity_type]
    try:
        revised = model_type.model_validate(payload)
    except Exception as exc:
        raise V3FactoryError("V3_REVISION_INVALID", "New V3 revision failed typed validation.", status_code=422, details=str(exc)) from exc
    if isinstance(revised, V3Angle):
        revised = revised.model_copy(update={"evidence_digest": deterministic_digest(list(revised.evidence_fact_ids))})
        revised = revised.model_copy(update={"angle_digest": deterministic_digest({
            "product_id": revised.product_id, "truth": revised.product_truth.model_dump(mode="json"),
            "definition": revised.definition, "objective_compatibility": revised.objective_compatibility,
            "audience_compatibility": revised.audience_compatibility,
            "formula": revised.formula.model_dump(mode="json") if revised.formula else None,
            "evidence_fact_ids": list(revised.evidence_fact_ids),
        })})
    elif isinstance(revised, V3StorylineFamily):
        revised = revised.model_copy(update={"family_digest": deterministic_digest({
            "product_id": revised.product_id, "truth": revised.product_truth.model_dump(mode="json"),
            "angle": revised.angle.model_dump(mode="json"), "formula": revised.formula.model_dump(mode="json"),
            "objective_compatibility": revised.objective_compatibility, "reviewed_definition": revised.reviewed_definition,
            "narrative_route": revised.narrative_route, "entry_contract": revised.entry_contract,
            "exit_contract": revised.exit_contract, "proof_placement": revised.proof_placement,
            "cta_closure_intent": revised.cta_closure_intent, "evidence_requirements": revised.evidence_requirements,
        })})
    elif isinstance(revised, V3StoryboardComponent):
        segments = _component_segments(revised)
        if not segments:
            raise V3FactoryError("COMPONENT_STAGE_SEGMENTS_REQUIRED", "New multi-stage component revisions require typed stage segments.", status_code=422)
        evidence_ids: list[str] = []
        for segment in segments:
            for fact_id in segment.evidence_fact_ids:
                if fact_id not in evidence_ids:
                    evidence_ids.append(fact_id)
        bridge = V3BridgeContract(
            entry_key=segments[0].entry_key,
            exit_key=segments[-1].exit_key,
            continuity_requirements=tuple(dict.fromkeys(requirement for segment in segments for requirement in segment.bridge_contract.continuity_requirements)),
        )
        revised = revised.model_copy(update={
            "stage_segments": segments,
            "formula_stage_keys": tuple(segment.formula_stage_key for segment in segments),
            "ordered_stage_coverage": tuple(segment.order for segment in segments),
            "authored_text": " ".join(segment.authored_text for segment in segments).strip(),
            "entry_key": segments[0].entry_key, "exit_key": segments[-1].exit_key,
            "bridge_contract": bridge, "evidence_fact_ids": tuple(evidence_ids),
            "evidence_digest": deterministic_digest(evidence_ids),
            "claim_bearing": any(segment.claim_bearing for segment in segments),
            "content_digest": digest_text(" ".join(segment.authored_text for segment in segments).strip()),
            "semantic_fingerprint": deterministic_digest({
                "semantic_class": revised.semantic_class,
                "segments": [segment.model_dump(mode="json") for segment in segments],
            }),
            "word_count": word_count(" ".join(segment.authored_text for segment in segments).strip()),
        })
    elif isinstance(revised, V3CopyRecipe):
        config = revised.model_dump(mode="json")
        config.pop("config_digest", None)
        config.pop("status", None)
        config.pop("created_at", None)
        config.pop("created_by", None)
        config.pop("supersedes", None)
        revised = revised.model_copy(update={"config_digest": deterministic_digest(config)})
    elif isinstance(revised, V3MasterStoryboard):
        revised = revised.model_copy(update={
            "exact_content_digest": master_content_digest(revised),
            "duplicate_fingerprint": exact_resolved_content_fingerprint(revised),
        })
    elif isinstance(revised, V3DurationProjection):
        revised = revised.model_copy(update={"exact_projection_digest": projection_content_digest(revised)})
    return revised


def _truth_from_row(
    product_id: str,
    snapshot_id: str | None,
    snapshot_version: int | None,
    snapshot_digest: str | None,
    *,
    snapshot_status: str = "APPROVED",
) -> V3ProductTruthLineage | None:
    if not snapshot_id or snapshot_version is None or not snapshot_digest:
        return None
    return V3ProductTruthLineage(
        product_id=product_id,
        snapshot_id=snapshot_id,
        snapshot_version=int(snapshot_version),
        snapshot_digest=str(snapshot_digest),
        snapshot_status=str(snapshot_status),
    )


def _objective_from_row(row: Mapping[str, Any]) -> V3Objective:
    raw = _loads(row.get("objective_json"), {})
    if not isinstance(raw, Mapping):
        raw = {}
    objective_id = str(raw.get("objective_id") or row.get("objective_id") or "").strip()
    definition = str(raw.get("definition") or objective_id).strip()
    return V3Objective(objective_id=objective_id, definition=definition)


def _row_to_entity(entity_type: str, row: Mapping[str, Any]) -> Any:
    data = dict(row)
    entity_type = entity_type.upper()
    if entity_type == "ANGLE":
        truth = _truth_from_row(
            data["product_id"], data["product_truth_snapshot_id"],
            data["product_truth_snapshot_version"], data["product_truth_snapshot_digest"],
        )
        if truth is None:
            raise V3FactoryError("V3_ROW_INVALID", "Angle row has incomplete Product Truth lineage.")
        formula = None
        if data.get("formula_id"):
            formula = V3FormulaRef(formula_id=data["formula_id"], formula_version=data["formula_version"])
        supersedes = None
        if data.get("supersedes_angle_id"):
            supersedes = _ref(data["supersedes_angle_id"], data["supersedes_angle_revision"])
        return V3Angle(
            angle_id=data["angle_id"], revision=int(data["revision"]), product_id=data["product_id"],
            product_truth=truth, definition=data["definition"],
            objective_compatibility=_loads(data.get("objective_compatibility_json"), {}),
            audience_compatibility=_loads(data.get("audience_compatibility_json"), {}),
            evidence_fact_ids=tuple(_loads(data.get("evidence_fact_ids_json"), [])),
            evidence_digest=data["evidence_digest"], formula=formula, source=data["source"],
            status=data["status"], angle_digest=data["angle_digest"], supersedes=supersedes,
            created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "STORYLINE_FAMILY":
        truth = _truth_from_row(
            data["product_id"], data["product_truth_snapshot_id"],
            data["product_truth_snapshot_version"], data["product_truth_snapshot_digest"],
        )
        if truth is None:
            raise V3FactoryError("V3_ROW_INVALID", "Storyline family has incomplete Product Truth lineage.")
        supersedes = None
        if data.get("supersedes_family_id"):
            supersedes = _ref(data["supersedes_family_id"], data["supersedes_family_revision"])
        return V3StorylineFamily(
            family_id=data["family_id"], revision=int(data["revision"]), product_id=data["product_id"],
            product_truth=truth, angle=_ref(data["angle_id"], data["angle_revision"]),
            formula=V3FormulaRef(formula_id=data["formula_id"], formula_version=data["formula_version"]),
            objective_compatibility=_loads(data.get("objective_compatibility_json"), {}),
            reviewed_definition=data["reviewed_definition"],
            narrative_route=_loads(data.get("narrative_route_json"), {}),
            entry_contract=_loads(data.get("entry_contract_json"), {}),
            exit_contract=_loads(data.get("exit_contract_json"), {}),
            proof_placement=_loads(data.get("proof_placement_json"), {}),
            cta_closure_intent=_loads(data.get("cta_closure_intent_json"), {}),
            evidence_requirements=_loads(data.get("evidence_requirements_json"), {}),
            status=data["status"], family_digest=data["family_digest"], source=data["source"],
            supersedes=supersedes, created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "STORYBOARD_COMPONENT":
        truth = _truth_from_row(
            data["product_id"], data["product_truth_snapshot_id"],
            data["product_truth_snapshot_version"], data["product_truth_snapshot_digest"],
        )
        if truth is None:
            raise V3FactoryError("V3_ROW_INVALID", "Component has incomplete Product Truth lineage.")
        supersedes = None
        if data.get("supersedes_component_id"):
            supersedes = _ref(data["supersedes_component_id"], data["supersedes_component_revision"])
        return V3StoryboardComponent(
            component_id=data["component_id"], revision=int(data["revision"]), product_id=data["product_id"],
            product_truth=truth, objective=_objective_from_row(data),
            angle=_ref(data["angle_id"], data["angle_revision"]),
            storyline_family=_ref(data["storyline_family_id"], data["storyline_family_revision"]),
            formula=V3FormulaRef(formula_id=data["formula_id"], formula_version=data["formula_version"]),
            semantic_class=data["semantic_class"],
            formula_stage_keys=tuple(_loads(data.get("formula_stage_keys_json"), [])),
            ordered_stage_coverage=tuple(int(item) for item in _loads(data.get("ordered_stage_coverage_json"), [])),
            stage_segments=tuple(_loads(data.get("stage_segments_json"), [])),
            authored_text=data["authored_text"], entry_key=data["entry_key"], exit_key=data["exit_key"],
            bridge_contract=V3BridgeContract.model_validate(_loads(data.get("bridge_contract_json"), {})),
            evidence_fact_ids=tuple(_loads(data.get("evidence_fact_ids_json"), [])),
            evidence_digest=data["evidence_digest"], claim_bearing=bool(data["claim_bearing"]),
            content_digest=data["content_digest"], semantic_fingerprint=data.get("semantic_fingerprint"),
            word_count=int(data.get("word_count") or 0), status=data["status"], source=data["source"],
            supersedes=supersedes, created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "COPY_RECIPE":
        truth = _truth_from_row(
            data["product_id"], data.get("product_truth_snapshot_id"),
            data.get("product_truth_snapshot_version"), data.get("product_truth_snapshot_digest"),
        )
        supersedes = None
        if data.get("supersedes_recipe_id"):
            supersedes = _ref(data["supersedes_recipe_id"], data["supersedes_recipe_revision"])
        return V3CopyRecipe(
            recipe_id=data["recipe_id"], revision=int(data["revision"]), product_id=data["product_id"],
            product_truth=truth, campaign_key=data.get("campaign_key") or "",
            campaign_scope=_loads(data.get("campaign_scope_json"), {}),
            formula=V3FormulaRef(formula_id=data["formula_id"], formula_version=data["formula_version"]),
            objective=_objective_from_row(data),
            target_angles=tuple(
                _ref(item["entity_id"], item["revision"]) for item in _loads(data.get("target_angle_ids_json"), [])
                if isinstance(item, dict)
            ),
            storyline_policy=_loads(data.get("storyline_policy_json"), {}),
            component_count_targets={str(k): int(v) for k, v in _loads(data.get("component_count_targets_json"), {}).items()},
            supported_durations_seconds=tuple(int(item) for item in _loads(data.get("supported_durations_json"), [])),
            wps_mode=data.get("wps_mode") or "SAFE",
            novelty_policy=_loads(data.get("novelty_policy_json"), {}),
            exact_reuse_policy=_loads(data.get("exact_reuse_policy_json"), {}),
            review_policy=_loads(data.get("review_policy_json"), {}),
            target_capacity=_loads(data.get("target_capacity_json"), {}),
            deterministic_seed=data["deterministic_seed"], config_digest=data["config_digest"],
            status=data["status"], source=data["source"], supersedes=supersedes,
            created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "MASTER_STORYBOARD":
        truth = _truth_from_row(
            data["product_id"], data["product_truth_snapshot_id"],
            data["product_truth_snapshot_version"], data["product_truth_snapshot_digest"],
        )
        if truth is None:
            raise V3FactoryError("V3_ROW_INVALID", "Master has incomplete Product Truth lineage.")
        supersedes = None
        if data.get("supersedes_master_id"):
            supersedes = _ref(data["supersedes_master_id"], data["supersedes_master_revision"])
        return V3MasterStoryboard(
            master_id=data["master_id"], revision=int(data["revision"]),
            recipe=_ref(data["recipe_id"], data["recipe_revision"]), product_id=data["product_id"],
            product_truth=truth,
            objective=_objective_from_row(data),
            angle=_ref(data["angle_id"], data["angle_revision"]),
            storyline_family=_ref(data["storyline_family_id"], data["storyline_family_revision"]),
            formula=V3FormulaRef(formula_id=data["formula_id"], formula_version=data["formula_version"]),
            stages=tuple(_loads(data.get("ordered_stage_plan_json"), [])),
            resolved_component_refs=tuple(
                _ref(item["entity_id"], item["revision"]) for item in _loads(data.get("resolved_component_refs_json"), [])
                if isinstance(item, dict)
            ),
            evidence_map={str(k): tuple(v) for k, v in _loads(data.get("evidence_map_json"), {}).items()},
            evidence_digest=data["evidence_digest"],
            bridge_continuity_receipt=V3ValidationReceipt.model_validate(_loads(data.get("bridge_continuity_receipt_json"), {})),
            formula_validation_receipt=V3ValidationReceipt.model_validate(_loads(data.get("formula_validation_receipt_json"), {})),
            claim_safety_receipt=V3ValidationReceipt.model_validate(_loads(data.get("claim_safety_receipt_json"), {})),
            exact_content_digest=data["exact_content_digest"], duplicate_fingerprint=data["duplicate_fingerprint"],
            word_count=int(data.get("word_count") or 0), status=data["status"], source=data["source"],
            supersedes=supersedes, created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "DURATION_PROJECTION":
        truth = _truth_from_row(
            data["product_id"], data["product_truth_snapshot_id"],
            data["product_truth_snapshot_version"], data["product_truth_snapshot_digest"],
        )
        if truth is None:
            raise V3FactoryError("V3_ROW_INVALID", "Projection has incomplete Product Truth lineage.")
        supersedes = None
        if data.get("supersedes_projection_id"):
            supersedes = _ref(data["supersedes_projection_id"], data["supersedes_projection_revision"])
        placement = _loads(data.get("cta_placement_json"), {})
        return V3DurationProjection(
            projection_id=data["projection_id"], revision=int(data["revision"]),
            master=_ref(data["master_id"], data["master_revision"]), product_id=data["product_id"],
            product_truth=truth, target_duration_seconds=int(data["target_duration_seconds"]),
            engine=data["engine"], language_profile=data["language_profile"], wps_mode=data["wps_mode"],
            wps_authority_version=data["wps_authority_version"], wps_authority_digest=data["wps_authority_digest"],
            block_plan_seconds=tuple(int(item) for item in _loads(data.get("block_plan_json"), [])),
            exact_resolved_dialogue=data["exact_resolved_dialogue"],
            per_block_slices=tuple(_loads(data.get("per_block_slices_json"), [])),
            per_block_word_counts=tuple(int(item) for item in _loads(data.get("per_block_word_counts_json"), [])),
            per_block_word_budgets=tuple(int(item) for item in _loads(data.get("per_block_word_budgets_json"), [])),
            stage_allocations=tuple(_loads(data.get("stage_allocations_json"), [])),
            stage_allocation_digest=data["stage_allocation_digest"],
            cta_block_index=int(placement.get("block_index", data.get("cta_block_index") or 0)),
            cta_stage_key=str(placement.get("stage_key") or data.get("cta_stage_key") or ""),
            seam_states=tuple(_loads(data.get("seam_states_json"), [])),
            continuity_receipt=V3ValidationReceipt.model_validate(_loads(data.get("continuity_receipt_json"), {})),
            formula_arc_receipt=V3ValidationReceipt.model_validate(_loads(data.get("formula_arc_receipt_json"), {})),
            stage_allocation_receipt=V3ValidationReceipt.model_validate(_loads(data.get("stage_allocation_receipt_json"), {})),
            master_stage_keys=tuple(_loads(data.get("master_stage_keys_json"), [])),
            master_stage_text_digests=tuple(_loads(data.get("master_stage_text_digests_json"), [])),
            master_exact_content_digest=data["master_exact_content_digest"],
            exact_projection_digest=data["exact_projection_digest"], status=data["status"], source=data["source"],
            supersedes=supersedes, created_at=data["created_at"], created_by=data["created_by"],
        )
    if entity_type == "REVIEW_EVENT":
        return V3ReviewEvent.model_validate(data)
    raise V3FactoryError("V3_ENTITY_UNKNOWN", f"Unsupported V3 entity type: {entity_type}")


def _entity_row(model: Any) -> tuple[str, dict[str, Any]]:
    """Convert a frozen V3 model to the exact additive table row."""

    if isinstance(model, V3Angle):
        return "ANGLE", {
            "angle_id": model.angle_id, "revision": model.revision, "product_id": model.product_id,
            "product_truth_snapshot_id": model.product_truth.snapshot_id,
            "product_truth_snapshot_version": model.product_truth.snapshot_version,
            "product_truth_snapshot_digest": model.product_truth.snapshot_digest,
            "definition": model.definition, "objective_compatibility_json": _json(model.objective_compatibility),
            "audience_compatibility_json": _json(model.audience_compatibility),
            "evidence_fact_ids_json": _json(list(model.evidence_fact_ids)), "evidence_digest": model.evidence_digest,
            "formula_id": model.formula.formula_id if model.formula else None,
            "formula_version": model.formula.formula_version if model.formula else None,
            "source": model.source, "status": model.status, "angle_digest": model.angle_digest,
            "supersedes_angle_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_angle_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    if isinstance(model, V3StorylineFamily):
        return "STORYLINE_FAMILY", {
            "family_id": model.family_id, "revision": model.revision, "product_id": model.product_id,
            "product_truth_snapshot_id": model.product_truth.snapshot_id,
            "product_truth_snapshot_version": model.product_truth.snapshot_version,
            "product_truth_snapshot_digest": model.product_truth.snapshot_digest,
            "angle_id": model.angle.entity_id, "angle_revision": model.angle.revision,
            "formula_id": model.formula.formula_id, "formula_version": model.formula.formula_version,
            "objective_compatibility_json": _json(model.objective_compatibility),
            "reviewed_definition": model.reviewed_definition, "narrative_route_json": _json(model.narrative_route),
            "entry_contract_json": _json(model.entry_contract), "exit_contract_json": _json(model.exit_contract),
            "proof_placement_json": _json(model.proof_placement), "cta_closure_intent_json": _json(model.cta_closure_intent),
            "evidence_requirements_json": _json(model.evidence_requirements), "status": model.status,
            "family_digest": model.family_digest, "source": model.source,
            "supersedes_family_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_family_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    if isinstance(model, V3StoryboardComponent):
        return "STORYBOARD_COMPONENT", {
            "component_id": model.component_id, "revision": model.revision, "product_id": model.product_id,
            "product_truth_snapshot_id": model.product_truth.snapshot_id,
            "product_truth_snapshot_version": model.product_truth.snapshot_version,
            "product_truth_snapshot_digest": model.product_truth.snapshot_digest,
            "objective_id": model.objective.objective_id, "objective_json": _json(model.objective.model_dump(mode="json")),
            "angle_id": model.angle.entity_id, "angle_revision": model.angle.revision,
            "storyline_family_id": model.storyline_family.entity_id, "storyline_family_revision": model.storyline_family.revision,
            "formula_id": model.formula.formula_id, "formula_version": model.formula.formula_version,
            "semantic_class": model.semantic_class, "formula_stage_keys_json": _json(list(model.formula_stage_keys)),
            "ordered_stage_coverage_json": _json(list(model.ordered_stage_coverage)),
            "stage_segments_json": _json([item.model_dump(mode="json") for item in model.stage_segments]),
            "authored_text": model.authored_text, "entry_key": model.entry_key, "exit_key": model.exit_key,
            "bridge_contract_json": _json(model.bridge_contract.model_dump(mode="json")),
            "evidence_fact_ids_json": _json(list(model.evidence_fact_ids)), "evidence_digest": model.evidence_digest,
            "claim_bearing": int(model.claim_bearing), "content_digest": model.content_digest,
            "semantic_fingerprint": model.semantic_fingerprint, "word_count": model.word_count,
            "status": model.status, "source": model.source,
            "supersedes_component_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_component_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    if isinstance(model, V3CopyRecipe):
        truth = model.product_truth
        return "COPY_RECIPE", {
            "recipe_id": model.recipe_id, "revision": model.revision, "product_id": model.product_id,
            "product_truth_snapshot_id": truth.snapshot_id if truth else None,
            "product_truth_snapshot_version": truth.snapshot_version if truth else None,
            "product_truth_snapshot_digest": truth.snapshot_digest if truth else None,
            "campaign_key": model.campaign_key, "campaign_scope_json": _json(model.campaign_scope),
            "formula_id": model.formula.formula_id, "formula_version": model.formula.formula_version,
            "objective_id": model.objective.objective_id, "objective_json": _json(model.objective.model_dump(mode="json")),
            "target_angle_ids_json": _json([item.model_dump(mode="json") for item in model.target_angles]),
            "storyline_policy_json": _json(model.storyline_policy), "component_count_targets_json": _json(model.component_count_targets),
            "supported_durations_json": _json(list(model.supported_durations_seconds)), "wps_mode": model.wps_mode,
            "novelty_policy_json": _json(model.novelty_policy), "exact_reuse_policy_json": _json(model.exact_reuse_policy),
            "review_policy_json": _json(model.review_policy), "target_capacity_json": _json(model.target_capacity),
            "deterministic_seed": model.deterministic_seed, "config_digest": model.config_digest,
            "status": model.status, "source": model.source,
            "supersedes_recipe_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_recipe_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    if isinstance(model, V3MasterStoryboard):
        return "MASTER_STORYBOARD", {
            "master_id": model.master_id, "revision": model.revision,
            "recipe_id": model.recipe.entity_id, "recipe_revision": model.recipe.revision,
            "product_id": model.product_id, "product_truth_snapshot_id": model.product_truth.snapshot_id,
            "product_truth_snapshot_version": model.product_truth.snapshot_version,
            "product_truth_snapshot_digest": model.product_truth.snapshot_digest,
            "objective_id": model.objective.objective_id, "objective_json": _json(model.objective.model_dump(mode="json")),
            "angle_id": model.angle.entity_id, "angle_revision": model.angle.revision,
            "storyline_family_id": model.storyline_family.entity_id, "storyline_family_revision": model.storyline_family.revision,
            "formula_id": model.formula.formula_id, "formula_version": model.formula.formula_version,
            "ordered_stage_plan_json": _json([item.model_dump(mode="json") for item in model.stages]),
            "resolved_component_refs_json": _json([item.model_dump(mode="json") for item in model.resolved_component_refs]),
            "exact_stage_texts_json": _json([item.authored_text for item in model.stages]),
            "evidence_map_json": _json(model.evidence_map), "evidence_digest": model.evidence_digest,
            "bridge_continuity_receipt_json": _json(model.bridge_continuity_receipt.model_dump(mode="json")),
            "formula_validation_receipt_json": _json(model.formula_validation_receipt.model_dump(mode="json")),
            "claim_safety_receipt_json": _json(model.claim_safety_receipt.model_dump(mode="json")),
            "exact_content_digest": model.exact_content_digest, "duplicate_fingerprint": model.duplicate_fingerprint,
            "word_count": model.word_count, "status": model.status, "source": model.source,
            "supersedes_master_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_master_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    if isinstance(model, V3DurationProjection):
        return "DURATION_PROJECTION", {
            "projection_id": model.projection_id, "revision": model.revision,
            "master_id": model.master.entity_id, "master_revision": model.master.revision,
            "product_id": model.product_id, "product_truth_snapshot_id": model.product_truth.snapshot_id,
            "product_truth_snapshot_version": model.product_truth.snapshot_version,
            "product_truth_snapshot_digest": model.product_truth.snapshot_digest,
            "target_duration_seconds": model.target_duration_seconds, "engine": model.engine,
            "language_profile": model.language_profile, "wps_mode": model.wps_mode,
            "wps_authority_version": model.wps_authority_version, "wps_authority_digest": model.wps_authority_digest,
            "block_plan_json": _json(list(model.block_plan_seconds)), "exact_resolved_dialogue": model.exact_resolved_dialogue,
            "per_block_slices_json": _json(list(model.per_block_slices)), "per_block_word_counts_json": _json(list(model.per_block_word_counts)),
            "per_block_word_budgets_json": _json(list(model.per_block_word_budgets)),
            "stage_allocations_json": _json([item.model_dump(mode="json") for item in model.stage_allocations]),
            "stage_allocation_digest": model.stage_allocation_digest,
            "cta_placement_json": _json({"block_index": model.cta_block_index, "stage_key": model.cta_stage_key}),
            "seam_states_json": _json([item.model_dump(mode="json") for item in model.seam_states]),
            "continuity_receipt_json": _json(model.continuity_receipt.model_dump(mode="json")),
            "formula_arc_receipt_json": _json(model.formula_arc_receipt.model_dump(mode="json")),
            "stage_allocation_receipt_json": _json(model.stage_allocation_receipt.model_dump(mode="json")),
            "master_stage_keys_json": _json(list(model.master_stage_keys)),
            "master_stage_text_digests_json": _json(list(model.master_stage_text_digests)),
            "master_exact_content_digest": model.master_exact_content_digest,
            "exact_projection_digest": model.exact_projection_digest, "status": model.status, "source": model.source,
            "supersedes_projection_id": model.supersedes.entity_id if model.supersedes else None,
            "supersedes_projection_revision": model.supersedes.revision if model.supersedes else None,
            "created_at": model.created_at, "created_by": model.created_by,
        }
    raise V3FactoryError("V3_ENTITY_UNKNOWN", f"Unsupported V3 model: {type(model).__name__}")


class V3CopyFactoryRepository:
    """Bounded append/revision repository over the seven Phase 2 V3 tables."""

    async def get(self, entity_type: str, entity_id: str, revision: int | None = None) -> Any | None:
        entity_type = entity_type.upper()
        table, id_column = _ENTITY_TABLES.get(entity_type, (None, None))
        if table is None:
            raise V3FactoryError("V3_ENTITY_UNKNOWN", entity_type, status_code=422)
        db = await get_db()
        if revision is None:
            cursor = await db.execute(
                f"SELECT * FROM {table} WHERE {id_column}=? ORDER BY revision DESC LIMIT 1",
                (entity_id,),
            )
        else:
            cursor = await db.execute(
                f"SELECT * FROM {table} WHERE {id_column}=? AND revision=?",
                (entity_id, int(revision)),
            )
        row = await cursor.fetchone()
        return _row_to_entity(entity_type, dict(row)) if row else None

    async def list(
        self,
        entity_type: str,
        *,
        product_id: str | None = None,
        status: str | None = None,
        formula_id: str | None = None,
        angle_id: str | None = None,
        storyline_family_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        latest_only: bool = True,
    ) -> list[Any]:
        entity_type = entity_type.upper()
        table, id_column = _ENTITY_TABLES.get(entity_type, (None, None))
        if table is None:
            raise V3FactoryError("V3_ENTITY_UNKNOWN", entity_type, status_code=422)
        limit = min(MAX_PAGE_SIZE, max(1, int(limit)))
        offset = max(0, int(offset))
        clauses: list[str] = []
        params: list[Any] = []
        if product_id:
            clauses.append("t.product_id=?")
            params.append(product_id)
        if status:
            clauses.append("t.status=?")
            params.append(status)
        if formula_id:
            clauses.append("t.formula_id=?")
            params.append(formula_id)
        if angle_id and entity_type in {"STORYLINE_FAMILY", "STORYBOARD_COMPONENT", "MASTER_STORYBOARD"}:
            clauses.append("t.angle_id=?")
            params.append(angle_id)
        if storyline_family_id and entity_type in {"STORYBOARD_COMPONENT", "MASTER_STORYBOARD"}:
            column = "storyline_family_id"
            clauses.append(f"t.{column}=?")
            params.append(storyline_family_id)
        where = " AND ".join(clauses) or "1=1"
        if latest_only:
            query = (
                f"SELECT t.* FROM {table} t JOIN (SELECT {id_column}, MAX(revision) AS latest_revision "
                f"FROM {table} GROUP BY {id_column}) latest ON latest.{id_column}=t.{id_column} "
                f"AND latest.latest_revision=t.revision WHERE {where} "
                "ORDER BY t.created_at DESC, t." + id_column + " DESC LIMIT ? OFFSET ?"
            )
        else:
            query = f"SELECT t.* FROM {table} t WHERE {where} ORDER BY t.created_at DESC, t.{id_column} DESC LIMIT ? OFFSET ?"
        params.extend([limit + 1, offset])
        db = await get_db()
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [_row_to_entity(entity_type, dict(row)) for row in rows]

    async def _find_idempotent(self, request_id: str) -> Any | None:
        if not request_id:
            return None
        db = await get_db()
        cursor = await db.execute(
            "SELECT entity_type, entity_id, entity_revision FROM review_event_v3 "
            "WHERE request_id=? ORDER BY created_at DESC LIMIT 1",
            (request_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await self.get(row["entity_type"], row["entity_id"], int(row["entity_revision"]))

    async def insert(
        self,
        model: Any,
        *,
        actor_id: str,
        request_id: str,
        source: str,
        event_type: str = "CREATED",
        reason: str | None = None,
        from_status: str | None = None,
    ) -> Any:
        if not actor_id or not request_id or not source:
            raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id, request_id, and source are required.", status_code=422)
        if getattr(model, "status", None) == "APPROVED":
            raise V3FactoryError("ROUND1_APPROVAL_FORBIDDEN", "Macro Round 1 cannot create APPROVED V3 rows.", status_code=403)
        entity_type, row = _entity_row(model)
        table, _ = _ENTITY_TABLES[entity_type]
        async with _db_lock:
            existing = await self._find_idempotent(request_id)
            if existing is not None:
                if _mutation_digest(existing) != _mutation_digest(model):
                    raise V3FactoryError("IDEMPOTENCY_CONFLICT", "request_id was already used for another V3 payload.", status_code=409)
                return existing
            db = await get_db()
            pk_column = _ENTITY_TABLES[entity_type][1]
            revision = int(row["revision"])
            cursor = await db.execute(
                f"SELECT * FROM {table} WHERE {pk_column}=? AND revision=?",
                (row[pk_column], revision),
            )
            same = await cursor.fetchone()
            if same:
                existing_model = _row_to_entity(entity_type, dict(same))
                if _mutation_digest(existing_model) != _mutation_digest(model):
                    raise V3FactoryError("V3_REVISION_CONFLICT", "The V3 identity/revision already contains different content.")
                return existing_model
            columns = list(row)
            placeholders = ",".join("?" for _ in columns)
            await db.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                [row[column] for column in columns],
            )
            payload = {
                "entity_type": entity_type,
                "entity_id": row[pk_column],
                "entity_revision": revision,
                "entity_digest": _entity_digest(model),
            }
            event = V3ReviewEvent(
                event_id=deterministic_id("v3_event", {**payload, "request_id": request_id, "event_type": event_type}),
                entity_type=entity_type,
                entity_id=row[pk_column],
                entity_revision=revision,
                product_id=row["product_id"],
                event_type=event_type,
                from_status=from_status,
                to_status=getattr(model, "status", None),
                actor_id=actor_id,
                source=source,
                request_id=request_id,
                reason=reason,
                payload=payload,
                payload_digest=deterministic_digest(payload),
                created_at=_now(),
            )
            event_row = {
                "event_id": event.event_id, "entity_type": event.entity_type, "entity_id": event.entity_id,
                "entity_revision": event.entity_revision, "product_id": event.product_id,
                "event_type": event.event_type, "from_status": event.from_status, "to_status": event.to_status,
                "actor_id": event.actor_id, "source": event.source, "request_id": event.request_id,
                "reason": event.reason, "payload_json": _json(event.payload),
                "payload_digest": event.payload_digest, "created_at": event.created_at,
            }
            columns = list(event_row)
            await db.execute(
                f"INSERT INTO review_event_v3 ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [event_row[column] for column in columns],
            )
            await db.commit()
            return model

    async def create_revision(
        self,
        current: Any,
        *,
        updates: Mapping[str, Any],
        actor_id: str,
        request_id: str,
        source: str,
        event_type: str = "EDITED_AS_NEW_REVISION",
        reason: str | None = None,
    ) -> Any:
        if getattr(current, "status", None) in _TERMINAL_STATUSES:
            raise V3FactoryError("TERMINAL_REVISION_IMMUTABLE", "Terminal V3 rows require a new lineage and cannot be edited.", status_code=409)
        next_model = _recompute_revision_model(current, updates, actor_id=actor_id)
        return await self.insert(
            next_model,
            actor_id=actor_id,
            request_id=request_id,
            source=source,
            event_type=event_type,
            reason=reason,
            from_status=current.status,
        )

    async def transition(
        self,
        entity_type: str,
        entity_id: str,
        revision: int,
        *,
        status: str,
        actor_id: str,
        request_id: str,
        source: str,
        reason: str | None = None,
    ) -> Any:
        status = str(status).upper()
        if status == "APPROVED":
            raise V3FactoryError("ROUND1_APPROVAL_FORBIDDEN", "APPROVED status belongs to Macro Round 2; final approval is forbidden in Round 1.", status_code=403)
        current = await self.get(entity_type, entity_id, revision)
        if current is None:
            raise V3FactoryError("V3_ENTITY_NOT_FOUND", "V3 revision was not found.", status_code=404)
        if current.status in _TERMINAL_STATUSES:
            raise V3FactoryError("TERMINAL_REVISION_IMMUTABLE", "Terminal V3 rows cannot transition in place.", status_code=409)
        event_type = {
            "REVIEW_REQUIRED": "SUBMITTED_FOR_REVIEW",
            "REJECTED": "REJECTED",
            "ARCHIVED": "ARCHIVED",
            "SUPERSEDED": "SUPERSEDED",
        }.get(status, "EDITED_AS_NEW_REVISION")
        return await self.create_revision(
            current,
            updates={"status": status},
            actor_id=actor_id,
            request_id=request_id,
            source=source,
            event_type=event_type,
            reason=reason,
        )

    async def safe_delete(
        self,
        entity_type: str,
        entity_id: str,
        revision: int,
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> bool:
        entity_type = entity_type.upper()
        if entity_type not in _ENTITY_TABLES:
            raise V3FactoryError("V3_ENTITY_UNKNOWN", entity_type, status_code=422)
        if not actor_id or not request_id or not source:
            raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id, request_id, and source are required.", status_code=422)
        current = await self.get(entity_type, entity_id, revision)
        if current is None:
            return False
        if current.status != "DRAFT":
            raise V3FactoryError("DRAFT_DELETE_ONLY", "Only unreferenced DRAFT V3 rows can be deleted.", status_code=409)
        refs: list[tuple[str, tuple[Any, ...]]] = []
        if entity_type == "ANGLE":
            refs.extend([
                ("storyline_family_v3", (entity_id, revision)),
                ("storyboard_component_v3", (entity_id, revision)),
                ("master_storyboard_v3", (entity_id, revision)),
            ])
        elif entity_type == "STORYLINE_FAMILY":
            refs.extend([
                ("storyboard_component_v3", (entity_id, revision)),
                ("master_storyboard_v3", (entity_id, revision)),
            ])
        elif entity_type == "COPY_RECIPE":
            refs.append(("master_storyboard_v3", (entity_id, revision)))
        elif entity_type == "MASTER_STORYBOARD":
            refs.append(("duration_projection_v3", (entity_id, revision)))
        db = await get_db()
        entity_table, id_column = _ENTITY_TABLES[entity_type]
        supersedes_column = {
            "ANGLE": "supersedes_angle_id",
            "STORYLINE_FAMILY": "supersedes_family_id",
            "STORYBOARD_COMPONENT": "supersedes_component_id",
            "COPY_RECIPE": "supersedes_recipe_id",
            "MASTER_STORYBOARD": "supersedes_master_id",
            "DURATION_PROJECTION": "supersedes_projection_id",
        }[entity_type]
        supersedes_revision_column = supersedes_column.replace("_id", "_revision")
        if await (
            await db.execute(
                f"SELECT 1 FROM {entity_table} WHERE {supersedes_column}=? AND {supersedes_revision_column}=? LIMIT 1",
                (entity_id, revision),
            )
        ).fetchone():
            raise V3FactoryError("V3_DRAFT_REFERENCED", "The DRAFT has a superseding revision and cannot be deleted.", status_code=409)
        for table, values in refs:
            if table == "storyline_family_v3":
                query = "SELECT 1 FROM storyline_family_v3 WHERE angle_id=? AND angle_revision=? LIMIT 1"
            elif table == "storyboard_component_v3":
                if entity_type == "ANGLE":
                    query = "SELECT 1 FROM storyboard_component_v3 WHERE angle_id=? AND angle_revision=? LIMIT 1"
                elif entity_type == "STORYLINE_FAMILY":
                    query = "SELECT 1 FROM storyboard_component_v3 WHERE storyline_family_id=? AND storyline_family_revision=? LIMIT 1"
                else:
                    query = "SELECT 1 FROM storyboard_component_v3 WHERE component_id=? AND revision=? LIMIT 1"
            elif table == "master_storyboard_v3":
                if entity_type == "ANGLE":
                    query = "SELECT 1 FROM master_storyboard_v3 WHERE angle_id=? AND angle_revision=? LIMIT 1"
                elif entity_type == "STORYLINE_FAMILY":
                    query = "SELECT 1 FROM master_storyboard_v3 WHERE storyline_family_id=? AND storyline_family_revision=? LIMIT 1"
                else:
                    query = "SELECT 1 FROM master_storyboard_v3 WHERE recipe_id=? AND recipe_revision=? LIMIT 1"
            else:
                query = "SELECT 1 FROM duration_projection_v3 WHERE master_id=? AND master_revision=? LIMIT 1"
            if await (await db.execute(query, values)).fetchone():
                raise V3FactoryError("V3_DRAFT_REFERENCED", "The DRAFT is referenced by another V3 record.", status_code=409)
        async with _db_lock:
            await db.execute(
                f"DELETE FROM {entity_table} WHERE {id_column}=? AND revision=? AND status='DRAFT'",
                (entity_id, revision),
            )
            await db.commit()
        return True


class ProductTruthBundle:
    """Immutable-in-practice read bundle over current Product Truth/evidence."""

    def __init__(
        self,
        *,
        product: dict[str, Any],
        snapshot: dict[str, Any],
        lineage: V3ProductTruthLineage,
        facts: tuple[EvidenceFact, ...],
    ):
        self.product = product
        self.snapshot = snapshot
        self.lineage = lineage
        self.registry = EvidenceRegistry(facts=facts)


def _truth_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    payload = {
        key: snapshot.get(key)
        for key in (
            "snapshot_id", "version", "claim_gate", "claim_risk_level",
            "product_description", "benefits_json", "usp_json", "hook_angles_json",
            "pain_points_json", "usage_text", "target_customer_text", "allowed_claims_json",
            "blocked_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json",
            "warnings_text",
        )
    }
    return _sha256(payload)


class ProductTruthEvidenceAdapter:
    """Provider-free adapter; it never creates a fact or mutates Product Truth."""

    async def current(self, product_id: str) -> ProductTruthBundle:
        db = await get_db()
        product_row = await (await db.execute("SELECT * FROM product WHERE id=?", (product_id,))).fetchone()
        if not product_row:
            raise V3FactoryError("PRODUCT_NOT_FOUND", "Product was not found.", status_code=404)
        snapshot_row = await (
            await db.execute(
                "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
                "ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC LIMIT 1",
                (product_id,),
            )
        ).fetchone()
        if not snapshot_row:
            raise V3FactoryError("TRUTH_NOT_APPROVED", "An approved Product Truth snapshot is required.", status_code=409)
        product = dict(product_row)
        snapshot = dict(snapshot_row)
        if str(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
            raise V3FactoryError("PRODUCT_INACTIVE", "Inactive products cannot supply V3 copy.", status_code=409)
        lineage = V3ProductTruthLineage(
            product_id=product_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            snapshot_version=int(snapshot["version"]),
            snapshot_digest=_truth_snapshot_digest(snapshot),
            snapshot_status="APPROVED",
        )
        fact_cursor = await db.execute(
            "SELECT * FROM copy_evidence_fact_v2 WHERE product_id=? AND snapshot_id=? "
            "AND snapshot_version=? AND snapshot_status='APPROVED' AND approved=1 "
            "ORDER BY fact_id LIMIT 500",
            (product_id, lineage.snapshot_id, lineage.snapshot_version),
        )
        facts: list[EvidenceFact] = []
        for row in await fact_cursor.fetchall():
            data = dict(row)
            try:
                facts.append(
                    EvidenceFact(
                        snapshot_id=data["snapshot_id"], fact_id=data["fact_id"], product_id=data["product_id"],
                        fact_kind=data["fact_kind"], text=data["canonical_text"], text_digest=data["text_digest"],
                        snapshot_version=int(data["snapshot_version"]), snapshot_status=data["snapshot_status"],
                        approved=bool(data["approved"]), source_ref=data.get("source_ref"),
                    )
                )
            except Exception:
                # A malformed evidence row is unsafe to derive from; it is
                # excluded from the bounded read model and never repaired here.
                continue
        return ProductTruthBundle(product=product, snapshot=snapshot, lineage=lineage, facts=tuple(facts))

    async def revalidate(self, lineage: V3ProductTruthLineage) -> ProductTruthBundle:
        current = await self.current(lineage.product_id)
        if current.lineage != lineage:
            raise V3FactoryError(
                "STALE_PRODUCT_TRUTH",
                "The supplied V3 lineage is not the current approved Product Truth snapshot.",
                status_code=409,
                details={"expected": current.lineage.model_dump(mode="json"), "received": lineage.model_dump(mode="json")},
            )
        return current

    async def supply_read_model(self, product_id: str) -> dict[str, Any]:
        bundle = await self.current(product_id)
        return {
            "product_id": product_id,
            "lineage": bundle.lineage.model_dump(mode="json"),
            "facts": [fact.model_dump(mode="json") for fact in bundle.registry.facts],
            "fact_count": len(bundle.registry.facts),
            "provider_calls": 0,
            "mutations": 0,
        }


def _relevance_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if isinstance(value, Mapping):
            tokens.update(_relevance_tokens(*value.values()))
        elif isinstance(value, (list, tuple, set, frozenset)):
            tokens.update(_relevance_tokens(*value))
        else:
            tokens.update(token.casefold() for token in _TOKEN_RE.findall(str(value or "")) if len(token) > 2)
    return tokens


class EvidenceRelevanceService:
    """Deterministic ranking/filtering over already-approved evidence facts."""

    @staticmethod
    def rank(
        bundle: ProductTruthBundle,
        *,
        objective: V3Objective | None = None,
        angle: V3Angle | None = None,
        storyline_family: V3StorylineFamily | None = None,
        formula_id: str | None = None,
        requested_fact_ids: Sequence[str] = (),
        limit: int = 20,
        require_claim_evidence: bool = False,
    ) -> V3EvidenceSelection:
        context_terms = _relevance_tokens(
            objective.definition if objective else "",
            angle.definition if angle else "",
            storyline_family.reviewed_definition if storyline_family else "",
            storyline_family.narrative_route if storyline_family else {},
            formula_id or "",
        )
        by_id = {fact.fact_id: fact for fact in bundle.registry.facts}
        issues: list[str] = []
        if requested_fact_ids:
            missing = [fact_id for fact_id in requested_fact_ids if fact_id not in by_id]
            if missing:
                return V3EvidenceSelection(
                    outcome="EVIDENCE_SHORTFALL",
                    snapshot_id=bundle.lineage.snapshot_id,
                    snapshot_version=bundle.lineage.snapshot_version,
                    issue_codes=("EVIDENCE_FACT_MISSING",),
                    explanations={fact_id: ("Fact is absent from the current approved evidence registry.",) for fact_id in missing},
                )
            selected = [by_id[fact_id] for fact_id in requested_fact_ids]
        else:
            scored: list[tuple[float, EvidenceFact, tuple[str, ...]]] = []
            for fact in bundle.registry.facts:
                fact_terms = _relevance_tokens(fact.text, fact.fact_kind)
                overlap = sorted(context_terms & fact_terms)
                score = float(len(overlap))
                if overlap and fact.fact_kind in {"PRODUCT_ATTRIBUTE", "BENEFIT", "USP", "ALLOWED_CLAIM", "USAGE"}:
                    score += 0.25
                scored.append((score, fact, tuple(overlap)))
            scored.sort(key=lambda item: (-item[0], item[1].fact_id))
            selected = [item[1] for item in scored[: max(1, min(100, limit))] if item[0] > 0]
            if not selected:
                return V3EvidenceSelection(
                    outcome="EVIDENCE_SHORTFALL" if require_claim_evidence else "UNSAFE_TO_DERIVE",
                    snapshot_id=bundle.lineage.snapshot_id,
                    snapshot_version=bundle.lineage.snapshot_version,
                    issue_codes=("EVIDENCE_RELEVANCE_EMPTY",),
                    explanations={
                        "_context": (
                            "No approved fact was relevant to the supplied objective, Angle, Storyline, or Formula context.",
                            "The Round 1 adapter will not infer a mechanism or select an unrelated fact.",
                        )
                    },
                )
        if require_claim_evidence and not selected:
            issues.append("EVIDENCE_SHORTFALL")
        if not bundle.registry.facts:
            return V3EvidenceSelection(
                outcome="EVIDENCE_SHORTFALL" if require_claim_evidence else "UNSAFE_TO_DERIVE",
                snapshot_id=bundle.lineage.snapshot_id,
                snapshot_version=bundle.lineage.snapshot_version,
                issue_codes=("EVIDENCE_FACTS_EMPTY",),
            )
        explanations = {
            fact.fact_id: (
                "Approved fact is in the current Product Truth snapshot.",
                "Selected by deterministic context overlap and fact-kind authority ranking.",
            )
            for fact in selected
        }
        scores = {
            fact.fact_id: float(len(context_terms & _relevance_tokens(fact.text, fact.fact_kind)))
            for fact in selected
        }
        return V3EvidenceSelection(
            outcome="EVIDENCE_SHORTFALL" if issues else "ENOUGH_EVIDENCE",
            snapshot_id=bundle.lineage.snapshot_id,
            snapshot_version=bundle.lineage.snapshot_version,
            fact_ids=tuple(fact.fact_id for fact in selected),
            explanations=explanations,
            issue_codes=tuple(issues),
            score_by_fact=scores,
        )


class V3CopyFactoryService:
    """Application service for the complete provider-free Round 1 copy lane."""

    def __init__(
        self,
        *,
        repository: V3CopyFactoryRepository | None = None,
        truth_adapter: ProductTruthEvidenceAdapter | None = None,
    ):
        self.repository = repository or V3CopyFactoryRepository()
        self.truth_adapter = truth_adapter or ProductTruthEvidenceAdapter()

    async def formulas(self, *, production_only: bool = False) -> tuple[V3FormulaReadModel, ...]:
        return list_formula_read_models(production_only=production_only)

    async def product_supply(self, product_id: str) -> dict[str, Any]:
        return await self.truth_adapter.supply_read_model(product_id)

    async def rank_evidence(
        self,
        product_id: str,
        *,
        objective: V3Objective | None = None,
        angle: V3Angle | None = None,
        storyline_family: V3StorylineFamily | None = None,
        formula_id: str | None = None,
        requested_fact_ids: Sequence[str] = (),
        limit: int = 20,
        require_claim_evidence: bool = False,
    ) -> V3EvidenceSelection:
        if formula_id:
            _formula_ref(formula_id)
        bundle = await self.truth_adapter.current(product_id)
        return EvidenceRelevanceService.rank(
            bundle,
            objective=objective,
            angle=angle,
            storyline_family=storyline_family,
            formula_id=formula_id,
            requested_fact_ids=requested_fact_ids,
            limit=limit,
            require_claim_evidence=require_claim_evidence,
        )

    async def _current_truth(self, product_id: str) -> ProductTruthBundle:
        return await self.truth_adapter.current(product_id)

    async def _idempotent_existing(self, request_id: str, expected_type: type[Any]) -> Any | None:
        existing = await self.repository._find_idempotent(request_id)
        if existing is None:
            return None
        if not isinstance(existing, expected_type):
            raise V3FactoryError("IDEMPOTENCY_CONFLICT", "request_id was already used for another V3 entity type.", status_code=409)
        return existing

    async def _idempotent_model(self, request_id: str, model: Any) -> Any | None:
        existing = await self.repository._find_idempotent(request_id)
        if existing is None:
            return None
        if type(existing) is not type(model) or _mutation_digest(existing) != _mutation_digest(model):
            raise V3FactoryError("IDEMPOTENCY_CONFLICT", "request_id was already used for a different V3 mutation payload.", status_code=409)
        return existing

    @staticmethod
    def _objective(data: Mapping[str, Any]) -> V3Objective:
        raw = data.get("objective")
        if isinstance(raw, V3Objective):
            return raw
        if isinstance(raw, Mapping):
            try:
                return V3Objective.model_validate(raw)
            except Exception as exc:
                raise V3FactoryError("OBJECTIVE_INVALID", "Objective requires objective_id and definition.", status_code=422) from exc
        objective_id = normalized_text(str(data.get("objective_id") or ""))
        definition = normalized_text(str(data.get("objective_definition") or data.get("definition") or ""))
        if not objective_id or not definition:
            raise V3FactoryError("OBJECTIVE_REQUIRED", "Objective identity and definition are required.", status_code=422)
        return V3Objective(objective_id=objective_id, definition=definition)

    @staticmethod
    def _evidence_ids(data: Mapping[str, Any]) -> tuple[str, ...]:
        raw = data.get("evidence_fact_ids")
        if raw is None and isinstance(data.get("evidence"), Mapping):
            raw = data["evidence"].get("fact_ids")
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return ()
        return tuple(dict.fromkeys(normalized_text(str(item)) for item in raw if normalized_text(str(item))))

    @staticmethod
    def _ensure_no_approval(data: Mapping[str, Any]) -> None:
        if str(data.get("status") or "DRAFT").upper() == "APPROVED":
            raise V3FactoryError("ROUND1_APPROVAL_FORBIDDEN", "APPROVAL is not available in Macro Round 1; only DRAFT/reviewable records are created.", status_code=403)

    async def create_angle(
        self,
        product_id: str,
        data: Mapping[str, Any],
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> V3Angle:
        self._ensure_no_approval(data)
        bundle = await self._current_truth(product_id)
        evidence_ids = self._evidence_ids(data)
        selection = EvidenceRelevanceService.rank(
            bundle,
            formula_id=data.get("formula_id"),
            requested_fact_ids=evidence_ids,
            require_claim_evidence=True,
        )
        if selection.outcome != "ENOUGH_EVIDENCE":
            raise V3FactoryError("EVIDENCE_SHORTFALL", "Angle must be grounded in current approved evidence.", status_code=409, details=selection.model_dump(mode="json"))
        formula = None
        if data.get("formula_id"):
            formula = _formula_ref(str(data["formula_id"]), data.get("formula_version"))
        definition = normalized_text(str(data.get("definition") or ""))
        if not definition:
            raise V3FactoryError("ANGLE_DEFINITION_REQUIRED", "Angle definition is required.", status_code=422)
        objective_compatibility = data.get("objective_compatibility") or {}
        audience_compatibility = data.get("audience_compatibility") or {}
        digest_payload = {
            "product_id": product_id,
            "truth": bundle.lineage.model_dump(mode="json"),
            "definition": definition,
            "objective_compatibility": objective_compatibility,
            "audience_compatibility": audience_compatibility,
            "formula": formula.model_dump(mode="json") if formula else None,
            "evidence_fact_ids": list(evidence_ids),
        }
        angle_digest = deterministic_digest(digest_payload)
        existing = await self.repository.list("ANGLE", product_id=product_id, limit=MAX_PAGE_SIZE)
        angle = V3Angle(
            angle_id=normalized_text(str(data.get("angle_id") or "")) or deterministic_id("angle", digest_payload),
            revision=1,
            product_id=product_id,
            product_truth=bundle.lineage,
            definition=definition,
            objective_compatibility=dict(objective_compatibility),
            audience_compatibility=dict(audience_compatibility),
            evidence_fact_ids=evidence_ids,
            evidence_digest=deterministic_digest(list(evidence_ids)),
            formula=formula,
            source=source,
            status="DRAFT",
            angle_digest=angle_digest,
            created_at=_now(),
            created_by=actor_id,
        )
        existing_request = await self._idempotent_model(request_id, angle)
        if existing_request is not None:
            return existing_request
        if any(item.angle_digest == angle_digest for item in existing):
            raise V3FactoryError("DUPLICATE_ANGLE", "An exact current angle revision already exists.", status_code=409)
        return await self.repository.insert(
            angle, actor_id=actor_id, request_id=request_id, source=source
        )

    async def create_storyline_family(
        self,
        product_id: str,
        data: Mapping[str, Any],
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> V3StorylineFamily:
        self._ensure_no_approval(data)
        bundle = await self._current_truth(product_id)
        angle_id = normalized_text(str(data.get("angle_id") or ""))
        angle_revision = int(data.get("angle_revision") or 1)
        angle = await self.repository.get("ANGLE", angle_id, angle_revision)
        if not isinstance(angle, V3Angle):
            raise V3FactoryError("ANGLE_NOT_FOUND", "Storyline Family requires an existing Angle revision.", status_code=404)
        if angle.product_id != product_id:
            raise V3FactoryError("PRODUCT_MISMATCH", "Storyline Family cannot cross Product Truth products.", status_code=409)
        if angle.product_truth != bundle.lineage:
            raise V3FactoryError("STALE_PRODUCT_TRUTH", "Angle is not bound to current Product Truth.", status_code=409)
        formula = _formula_ref(str(data.get("formula_id") or (angle.formula.formula_id if angle.formula else "")), data.get("formula_version"))
        if angle.formula is not None and angle.formula != formula:
            raise V3FactoryError("ANGLE_FORMULA_INCOMPATIBLE", "Storyline formula must match the Angle formula lock.", status_code=409)
        definition = normalized_text(str(data.get("reviewed_definition") or data.get("definition") or ""))
        if not definition:
            raise V3FactoryError("STORYLINE_DEFINITION_REQUIRED", "Storyline Family definition is required.", status_code=422)
        route = data.get("narrative_route")
        if route is None:
            route = {"stage_keys": list(required_formula_stage_keys(formula.formula_id)), "order_locked": True}
        if not isinstance(route, Mapping):
            raise V3FactoryError("STORYLINE_ROUTE_INVALID", "narrative_route must be an ordered object.", status_code=422)
        evidence_requirements = data.get("evidence_requirements") or {}
        evidence_ids = self._evidence_ids(data)
        if evidence_ids:
            selection = EvidenceRelevanceService.rank(bundle, requested_fact_ids=evidence_ids, require_claim_evidence=True)
            if selection.outcome != "ENOUGH_EVIDENCE":
                raise V3FactoryError("EVIDENCE_SHORTFALL", "Storyline evidence is not current approved evidence.", status_code=409)
        digest_payload = {
            "product_id": product_id, "truth": bundle.lineage.model_dump(mode="json"),
            "angle": [angle.angle_id, angle.revision], "formula": formula.model_dump(mode="json"),
            "objective_compatibility": data.get("objective_compatibility") or {},
            "reviewed_definition": definition, "narrative_route": dict(route),
            "entry_contract": data.get("entry_contract") or {}, "exit_contract": data.get("exit_contract") or {},
            "proof_placement": data.get("proof_placement") or {},
            "cta_closure_intent": data.get("cta_closure_intent") or {},
            "evidence_requirements": evidence_requirements,
        }
        family = V3StorylineFamily(
            family_id=normalized_text(str(data.get("family_id") or "")) or deterministic_id("family", digest_payload),
            revision=1,
            product_id=product_id,
            product_truth=bundle.lineage,
            angle=_ref(angle.angle_id, angle.revision),
            formula=formula,
            objective_compatibility=dict(data.get("objective_compatibility") or {}),
            reviewed_definition=definition,
            narrative_route=dict(route),
            entry_contract=dict(data.get("entry_contract") or {}),
            exit_contract=dict(data.get("exit_contract") or {}),
            proof_placement=dict(data.get("proof_placement") or {}),
            cta_closure_intent=dict(data.get("cta_closure_intent") or {}),
            evidence_requirements=dict(evidence_requirements),
            status="DRAFT",
            family_digest=deterministic_digest(digest_payload),
            source=source,
            created_at=_now(),
            created_by=actor_id,
        )
        existing_request = await self._idempotent_model(request_id, family)
        if existing_request is not None:
            return existing_request
        existing = await self.repository.list("STORYLINE_FAMILY", product_id=product_id, limit=MAX_PAGE_SIZE)
        if any(item.family_digest == family.family_digest for item in existing):
            raise V3FactoryError("DUPLICATE_STORYLINE_FAMILY", "An exact storyline revision already exists.", status_code=409)
        return await self.repository.insert(family, actor_id=actor_id, request_id=request_id, source=source)

    @staticmethod
    def _segment_input(
        raw: Mapping[str, Any],
        *,
        semantic_class: str,
        default_order: int,
        default_evidence: tuple[str, ...],
    ) -> V3ComponentStageSegment:
        stage_key = normalized_text(str(raw.get("formula_stage_key") or raw.get("stage_key") or ""))
        text = normalized_text(str(raw.get("authored_text") or raw.get("text") or ""))
        entry_key = normalized_text(str(raw.get("entry_key") or ""))
        exit_key = normalized_text(str(raw.get("exit_key") or ""))
        bridge_raw = raw.get("bridge_contract") or raw.get("bridge") or {}
        if not isinstance(bridge_raw, Mapping):
            bridge_raw = {}
        entry_key = entry_key or normalized_text(str(bridge_raw.get("entry_key") or bridge_raw.get("entry") or ""))
        exit_key = exit_key or normalized_text(str(bridge_raw.get("exit_key") or bridge_raw.get("exit") or ""))
        if not stage_key or not text or not entry_key or not exit_key:
            raise V3FactoryError("COMPONENT_STAGE_SEGMENT_REQUIRED", "Each stage segment requires key, text, entry, and exit.", status_code=422)
        evidence = raw.get("evidence_fact_ids")
        if evidence is None:
            evidence = default_evidence
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence_ids = tuple(dict.fromkeys(normalized_text(str(item)) for item in (evidence or ()) if normalized_text(str(item))))
        claim_bearing = bool(raw.get("claim_bearing", semantic_class != "CTA"))
        try:
            return V3ComponentStageSegment(
                formula_stage_key=stage_key,
                semantic_class=raw.get("semantic_class") or semantic_class,
                order=int(raw.get("order", default_order)),
                authored_text=text,
                text_digest=digest_text(text),
                entry_key=entry_key,
                exit_key=exit_key,
                bridge_contract=V3BridgeContract(
                    entry_key=entry_key,
                    exit_key=exit_key,
                    continuity_requirements=tuple(str(item) for item in bridge_raw.get("continuity_requirements", ()) or ()),
                ),
                evidence_fact_ids=evidence_ids,
                evidence_digest=deterministic_digest(list(evidence_ids)),
                claim_bearing=claim_bearing,
            )
        except Exception as exc:
            if isinstance(exc, V3FactoryError):
                raise
            raise V3FactoryError("COMPONENT_STAGE_SEGMENT_INVALID", "Stage segment failed its typed contract.", status_code=422, details=str(exc)) from exc

    async def create_component(
        self,
        product_id: str,
        data: Mapping[str, Any],
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> V3StoryboardComponent:
        self._ensure_no_approval(data)
        bundle = await self._current_truth(product_id)
        angle = await self.repository.get("ANGLE", str(data.get("angle_id") or ""), int(data.get("angle_revision") or 1))
        family = await self.repository.get("STORYLINE_FAMILY", str(data.get("storyline_family_id") or ""), int(data.get("storyline_family_revision") or 1))
        if not isinstance(angle, V3Angle):
            raise V3FactoryError("ANGLE_NOT_FOUND", "Component requires a current Angle revision.", status_code=404)
        if not isinstance(family, V3StorylineFamily):
            raise V3FactoryError("STORYLINE_FAMILY_NOT_FOUND", "Component requires a current Storyline Family revision.", status_code=404)
        if angle.product_id != product_id or family.product_id != product_id:
            raise V3FactoryError("PRODUCT_MISMATCH", "Component cannot cross Product Truth products.", status_code=409)
        if angle.product_truth != bundle.lineage or family.product_truth != bundle.lineage:
            raise V3FactoryError("STALE_PRODUCT_TRUTH", "Component lineage is not bound to current Product Truth.", status_code=409)
        formula = _formula_ref(str(data.get("formula_id") or family.formula.formula_id), data.get("formula_version"))
        if family.formula != formula or family.angle != _ref(angle.angle_id, angle.revision):
            raise V3FactoryError("COMPONENT_LINEAGE_MISMATCH", "Component formula/Angle/Storyline lineage is incompatible.", status_code=409)
        objective = self._objective(data)
        if objective.objective_id not in set(str(item) for item in (family.objective_compatibility.get("objective_ids") or [objective.objective_id])):
            raise V3FactoryError("STORYLINE_OBJECTIVE_INCOMPATIBLE", "Objective is outside the Storyline Family compatibility set.", status_code=409)
        semantic_class = str(data.get("semantic_class") or "").upper()
        if semantic_class not in {"HOOK", "BODY_CORE", "CTA", "STAGE"}:
            raise V3FactoryError("COMPONENT_SEMANTIC_CLASS_REQUIRED", "Component semantic_class must be HOOK, BODY_CORE, or CTA.", status_code=422)
        default_evidence = self._evidence_ids(data)
        raw_segments = data.get("stage_segments") or data.get("segments")
        if raw_segments is None:
            stage_keys = data.get("formula_stage_keys") or []
            if isinstance(stage_keys, str):
                stage_keys = [stage_keys]
            if len(stage_keys) != 1:
                raise V3FactoryError("COMPONENT_STAGE_SEGMENTS_REQUIRED", "Multi-stage components require stage_segments.", status_code=422)
            raw_segments = [{
                "formula_stage_key": stage_keys[0], "authored_text": data.get("authored_text"),
                "entry_key": data.get("entry_key"), "exit_key": data.get("exit_key"),
                "bridge_contract": data.get("bridge_contract") or {}, "evidence_fact_ids": default_evidence,
                "claim_bearing": data.get("claim_bearing", semantic_class != "CTA"),
            }]
        if not isinstance(raw_segments, (list, tuple)) or not raw_segments:
            raise V3FactoryError("COMPONENT_STAGE_SEGMENTS_REQUIRED", "At least one stage segment is required.", status_code=422)
        required = tuple(required_formula_stage_keys(formula.formula_id))
        segment_values: list[V3ComponentStageSegment] = []
        for index, item in enumerate(raw_segments):
            if not isinstance(item, Mapping):
                raise V3FactoryError("COMPONENT_STAGE_SEGMENT_INVALID", "Every stage segment must be an object.", status_code=422)
            stage_key = normalized_text(str(item.get("formula_stage_key") or item.get("stage_key") or ""))
            if stage_key not in required:
                raise V3FactoryError(
                    "COMPONENT_STAGE_KEY_INVALID",
                    "Component stage is not present in the current canonical formula.",
                    status_code=422,
                    details={"stage_key": stage_key, "formula_id": formula.formula_id},
                )
            segment_values.append(
                self._segment_input(
                    item,
                    semantic_class=semantic_class,
                    default_order=required.index(stage_key),
                    default_evidence=default_evidence,
                )
            )
        segments = tuple(segment_values)
        stage_keys = tuple(item.formula_stage_key for item in segments)
        if stage_keys != tuple(sorted(stage_keys, key=required.index)) or len(stage_keys) != len(set(stage_keys)):
            raise V3FactoryError("COMPONENT_STAGE_ORDER_INVALID", "Segments must be unique and in canonical formula order.", status_code=422)
        positions = tuple(required.index(item) if item in required else -1 for item in stage_keys)
        if any(item < 0 for item in positions) or positions != tuple(range(positions[0], positions[-1] + 1)):
            raise V3FactoryError("COMPONENT_STAGE_COVERAGE_INVALID", "Component stages must be a contiguous canonical route.", status_code=422)
        if any(item.semantic_class != semantic_class for item in segments):
            raise V3FactoryError("COMPONENT_SEGMENT_SEMANTIC_CLASS_MISMATCH", "All segments must carry the component semantic class.", status_code=422)
        selection = EvidenceRelevanceService.rank(bundle, requested_fact_ids=tuple(dict.fromkeys(fact_id for item in segments for fact_id in item.evidence_fact_ids)), require_claim_evidence=any(item.claim_bearing for item in segments))
        if selection.outcome != "ENOUGH_EVIDENCE" and any(item.claim_bearing for item in segments):
            raise V3FactoryError("EVIDENCE_SHORTFALL", "Claim-bearing component stages require current approved evidence.", status_code=409, details=selection.model_dump(mode="json"))
        authored_text = " ".join(item.authored_text for item in segments).strip()
        evidence_ids: list[str] = []
        for item in segments:
            for fact_id in item.evidence_fact_ids:
                if fact_id not in evidence_ids:
                    evidence_ids.append(fact_id)
        bridge = V3BridgeContract(
            entry_key=segments[0].entry_key,
            exit_key=segments[-1].exit_key,
            continuity_requirements=tuple(dict.fromkeys(
                requirement
                for item in segments
                for requirement in item.bridge_contract.continuity_requirements
            )),
        )
        digest_payload = {
            "product_id": product_id, "truth": bundle.lineage.model_dump(mode="json"),
            "objective": objective.model_dump(mode="json"), "angle": [angle.angle_id, angle.revision],
            "family": [family.family_id, family.revision], "formula": formula.model_dump(mode="json"),
            "semantic_class": semantic_class, "segments": [item.model_dump(mode="json") for item in segments],
        }
        component = V3StoryboardComponent(
            component_id=normalized_text(str(data.get("component_id") or "")) or deterministic_id("component", digest_payload),
            revision=1,
            product_id=product_id,
            product_truth=bundle.lineage,
            objective=objective,
            angle=_ref(angle.angle_id, angle.revision),
            storyline_family=_ref(family.family_id, family.revision),
            formula=formula,
            semantic_class=semantic_class,
            formula_stage_keys=stage_keys,
            ordered_stage_coverage=positions,
            stage_segments=segments,
            authored_text=authored_text,
            entry_key=segments[0].entry_key,
            exit_key=segments[-1].exit_key,
            bridge_contract=bridge,
            evidence_fact_ids=tuple(evidence_ids),
            evidence_digest=deterministic_digest(evidence_ids),
            claim_bearing=any(item.claim_bearing for item in segments),
            content_digest=digest_text(authored_text),
            semantic_fingerprint=deterministic_digest({
                "semantic_class": semantic_class,
                "segments": [item.model_dump(mode="json") for item in segments],
            }),
            word_count=word_count(authored_text),
            status="DRAFT",
            source=source,
            created_at=_now(),
            created_by=actor_id,
        )
        validation = ComponentStageValidator.validate(component)
        if not validation.valid:
            raise V3FactoryError("COMPONENT_INVALID", "Component failed the formula-stage validator.", status_code=422, details=validation.model_dump(mode="json"))
        existing_request = await self._idempotent_model(request_id, component)
        if existing_request is not None:
            return existing_request
        existing = await self.repository.list("STORYBOARD_COMPONENT", product_id=product_id, limit=MAX_PAGE_SIZE)
        if any(
            item.content_digest == component.content_digest
            and item.semantic_fingerprint == component.semantic_fingerprint
            and item.semantic_class == component.semantic_class
            and item.angle == component.angle
            and item.storyline_family == component.storyline_family
            for item in existing
        ):
            raise V3FactoryError("DUPLICATE_COMPONENT", "An exact component content revision already exists.", status_code=409)
        return await self.repository.insert(component, actor_id=actor_id, request_id=request_id, source=source)

    @staticmethod
    def _revision_refs(raw: Any) -> tuple[V3RevisionRef, ...]:
        if raw is None:
            return ()
        if isinstance(raw, str):
            raw = [raw]
        refs: list[V3RevisionRef] = []
        for item in raw if isinstance(raw, (list, tuple)) else ():
            if isinstance(item, Mapping):
                entity_id = normalized_text(str(item.get("entity_id") or item.get("id") or ""))
                revision = int(item.get("revision") or 1)
            else:
                entity_id = normalized_text(str(item))
                revision = 1
            if entity_id:
                refs.append(_ref(entity_id, revision))
        return tuple(refs)

    async def create_recipe(
        self,
        product_id: str,
        data: Mapping[str, Any],
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> V3CopyRecipe:
        self._ensure_no_approval(data)
        bundle = await self._current_truth(product_id)
        formula = _formula_ref(str(data.get("formula_id") or ""), data.get("formula_version"))
        objective = self._objective(data)
        preset = str(data.get("preset") or "CUSTOM").upper()
        preset_targets: dict[str, dict[str, int]] = {
            "QUICK_TEST": {"HOOK": 1, "BODY_CORE": 1, "CTA": 1},
            "FAST54": {"HOOK": 6, "BODY_CORE": 3, "CTA": 3},
            "MULTI_ANGLE": {"HOOK": 3, "BODY_CORE": 2, "CTA": 2},
            "SCALE": {"HOOK": 100, "BODY_CORE": 10, "CTA": 10},
        }
        targets_raw = data.get("component_count_targets") or preset_targets.get(preset) or {}
        targets = {str(key).upper(): max(0, int(value)) for key, value in dict(targets_raw).items()}
        if not all(key in targets for key in ("HOOK", "BODY_CORE", "CTA")):
            raise V3FactoryError("RECIPE_COMPONENT_TARGETS_REQUIRED", "Recipe requires HOOK, BODY_CORE, and CTA counts.", status_code=422)
        durations_raw = data.get("supported_durations_seconds") or ((8, 16, 24) if preset in {"FAST54", "MULTI_ANGLE", "SCALE"} else (8,))
        if isinstance(durations_raw, int):
            durations_raw = [durations_raw]
        durations = tuple(dict.fromkeys(int(item) for item in durations_raw))
        if not durations or any(item <= 0 for item in durations):
            raise V3FactoryError("RECIPE_DURATION_REQUIRED", "Recipe requires at least one positive duration.", status_code=422)
        target_angles = self._revision_refs(data.get("target_angles") or data.get("target_angle_ids"))
        for target_angle in target_angles:
            angle = await self.repository.get("ANGLE", target_angle.entity_id, target_angle.revision)
            if not isinstance(angle, V3Angle):
                raise V3FactoryError("ANGLE_NOT_FOUND", "Recipe target angle was not found.", status_code=404)
            if angle.product_id != product_id:
                raise V3FactoryError("PRODUCT_MISMATCH", "Recipe target angles cannot cross products.", status_code=409)
            if angle.product_truth != bundle.lineage:
                raise V3FactoryError("STALE_PRODUCT_TRUTH", "Recipe target angle is not bound to current Product Truth.", status_code=409)
        target_capacity_raw = dict(data.get("target_capacity") or {})
        theoretical_target = targets["HOOK"] * targets["BODY_CORE"] * targets["CTA"]
        requested_raw = target_capacity_raw.get(
            "requested_capacity",
            data.get("requested_capacity", theoretical_target),
        )
        requested_capacity = int(requested_raw)
        if requested_capacity < 0:
            raise V3FactoryError("RECIPE_CAPACITY_INVALID", "requested_capacity cannot be negative.", status_code=422)
        seed = normalized_text(str(data.get("deterministic_seed") or ""))
        config_payload = {
            "product_id": product_id,
            "truth": bundle.lineage.model_dump(mode="json"),
            "campaign_key": normalized_text(str(data.get("campaign_key") or "")),
            "campaign_scope": data.get("campaign_scope") or {},
            "formula": formula.model_dump(mode="json"),
            "objective": objective.model_dump(mode="json"),
            "target_angles": [item.model_dump(mode="json") for item in target_angles],
            "storyline_policy": data.get("storyline_policy") or {},
            "component_count_targets": targets,
            "supported_durations_seconds": list(durations),
            "wps_mode": str(data.get("wps_mode") or "SAFE").upper(),
            "novelty_policy": data.get("novelty_policy") or {},
            "exact_reuse_policy": data.get("exact_reuse_policy") or {"exact_reuse_within_recipe": "BLOCK"},
            "review_policy": data.get("review_policy") or {"final_approval_available": False},
            "target_capacity": {**target_capacity_raw, "requested_capacity": requested_capacity},
            "preset": preset,
        }
        config_digest = deterministic_digest(config_payload)
        seed = seed or config_digest[:24]
        recipe = V3CopyRecipe(
            recipe_id=normalized_text(str(data.get("recipe_id") or "")) or deterministic_id("recipe", config_payload),
            revision=1,
            product_id=product_id,
            product_truth=bundle.lineage,
            campaign_key=config_payload["campaign_key"],
            campaign_scope=dict(config_payload["campaign_scope"]),
            formula=formula,
            objective=objective,
            target_angles=target_angles,
            storyline_policy=dict(config_payload["storyline_policy"]),
            component_count_targets=targets,
            supported_durations_seconds=durations,
            wps_mode=config_payload["wps_mode"],
            novelty_policy=dict(config_payload["novelty_policy"]),
            exact_reuse_policy=dict(config_payload["exact_reuse_policy"]),
            review_policy=dict(config_payload["review_policy"]),
            target_capacity={**target_capacity_raw, "requested_capacity": requested_capacity, "theoretical_capacity": theoretical_target, "approved_capacity": 0, "executable_capacity": 0},
            deterministic_seed=seed,
            config_digest=config_digest,
            status="DRAFT",
            source=source,
            created_at=_now(),
            created_by=actor_id,
        )
        existing_request = await self._idempotent_model(request_id, recipe)
        if existing_request is not None:
            return existing_request
        existing = await self.repository.list("COPY_RECIPE", product_id=product_id, limit=MAX_PAGE_SIZE)
        if any(item.config_digest == config_digest for item in existing):
            raise V3FactoryError("DUPLICATE_RECIPE", "An exact recipe configuration already exists.", status_code=409)
        return await self.repository.insert(recipe, actor_id=actor_id, request_id=request_id, source=source)

    async def get_entity(self, entity_type: str, entity_id: str, revision: int | None = None) -> Any | None:
        return await self.repository.get(entity_type, entity_id, revision)

    async def list_entities(self, entity_type: str, **filters: Any) -> list[Any]:
        rows = await self.repository.list(entity_type, **filters)
        return rows[: int(filters.get("limit", 100))]

    async def validate_entity(self, entity_type: str, entity_id: str, revision: int | None = None) -> dict[str, Any]:
        entity = await self.repository.get(entity_type, entity_id, revision)
        if entity is None:
            raise V3FactoryError("V3_ENTITY_NOT_FOUND", "V3 entity was not found.", status_code=404)
        issues: list[str] = []
        details: list[str] = []
        if hasattr(entity, "product_truth"):
            try:
                current = await self.truth_adapter.current(entity.product_id)
                if entity.product_truth is not None and entity.product_truth != current.lineage:
                    issues.append("STALE_PRODUCT_TRUTH")
            except V3FactoryError as exc:
                issues.append(exc.code)
                details.append(str(exc))
        if isinstance(entity, V3Angle):
            if entity.formula:
                try:
                    _formula_ref(entity.formula.formula_id, entity.formula.formula_version)
                except V3FactoryError as exc:
                    issues.append(exc.code)
                    details.append(str(exc))
        elif isinstance(entity, V3StoryboardComponent):
            result = ComponentStageValidator.validate(entity)
            issues.extend(result.issue_codes)
            details.extend(result.details)
        elif isinstance(entity, V3StorylineFamily):
            try:
                _formula_ref(entity.formula.formula_id, entity.formula.formula_version)
            except V3FactoryError as exc:
                issues.append(exc.code)
                details.append(str(exc))
        elif isinstance(entity, V3MasterStoryboard):
            angle = await self.repository.get("ANGLE", entity.angle.entity_id, entity.angle.revision)
            family = await self.repository.get("STORYLINE_FAMILY", entity.storyline_family.entity_id, entity.storyline_family.revision)
            components: list[V3StoryboardComponent] = []
            for ref in entity.resolved_component_refs:
                component = await self.repository.get("STORYBOARD_COMPONENT", ref.entity_id, ref.revision)
                if isinstance(component, V3StoryboardComponent):
                    components.append(component)
            registry = (await self.truth_adapter.current(entity.product_id)).registry
            if isinstance(angle, V3Angle) and isinstance(family, V3StorylineFamily):
                result = MasterStoryboardValidator.validate(entity, evidence_registry=registry, angle=angle, storyline_family=family, components=components)
                issues.extend(result.issue_codes)
                details.extend(result.details)
        elif isinstance(entity, V3DurationProjection):
            master = await self.repository.get("MASTER_STORYBOARD", entity.master.entity_id, entity.master.revision)
            if isinstance(master, V3MasterStoryboard):
                registry = (await self.truth_adapter.current(entity.product_id)).registry
                result = DurationProjectionValidator.validate(entity, master, evidence_registry=registry)
                issues.extend(result.issue_codes)
                details.extend(result.details)
        return {
            "entity_type": entity_type.upper(),
            "entity_id": entity_id,
            "revision": entity.revision,
            "valid": not issues,
            # Round 1 may structurally validate a compiled Master/Projection,
            # but it cannot turn any durable row into an approved/executable
            # production asset.  Keep the read contract explicit instead of
            # relying on a precedence-sensitive boolean expression.
            "production_eligible": bool(
                not issues
                and isinstance(entity, (V3MasterStoryboard, V3DurationProjection))
                and entity.status == "VALIDATED"
            ),
            "issue_codes": tuple(dict.fromkeys(issues)),
            "details": tuple(dict.fromkeys(details)),
            "provider_calls": 0,
        }

    async def create_revision(
        self, entity_type: str, entity_id: str, revision: int, updates: Mapping[str, Any], *, actor_id: str, request_id: str, source: str = ROUND1_SOURCE
    ) -> Any:
        current = await self.repository.get(entity_type, entity_id, revision)
        if current is None:
            raise V3FactoryError("V3_ENTITY_NOT_FOUND", "V3 entity was not found.", status_code=404)
        forbidden = sorted(_REVISION_LINEAGE_FIELDS.intersection(str(key) for key in updates))
        if forbidden:
            raise V3FactoryError(
                "V3_LINEAGE_IMMUTABLE",
                "A V3 revision cannot rewrite product, truth, formula, or parent lineage.",
                status_code=409,
                details={"fields": forbidden},
            )
        if "status" in updates and str(updates["status"]).upper() == "APPROVED":
            raise V3FactoryError("ROUND1_APPROVAL_FORBIDDEN", "Round 1 cannot promote a V3 row to APPROVED.", status_code=403)
        if getattr(current, "product_truth", None) is not None:
            await self.truth_adapter.revalidate(current.product_truth)
        return await self.repository.create_revision(current, updates=updates, actor_id=actor_id, request_id=request_id, source=source)

    async def transition(
        self, entity_type: str, entity_id: str, revision: int, status: str, *, actor_id: str, request_id: str, reason: str | None = None, source: str = ROUND1_SOURCE
    ) -> Any:
        current = await self.repository.get(entity_type, entity_id, revision)
        if current is not None and getattr(current, "product_truth", None) is not None:
            await self.truth_adapter.revalidate(current.product_truth)
        return await self.repository.transition(entity_type, entity_id, revision, status=status, actor_id=actor_id, request_id=request_id, source=source, reason=reason)

    async def delete_draft(
        self,
        entity_type: str,
        entity_id: str,
        revision: int,
        *,
        actor_id: str,
        request_id: str,
        source: str = ROUND1_SOURCE,
    ) -> bool:
        if not actor_id or not request_id:
            raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id and request_id are required.", status_code=422)
        return await self.repository.safe_delete(entity_type, entity_id, revision, actor_id=actor_id, request_id=request_id, source=source)

    @staticmethod
    def _candidate_id(recipe: V3CopyRecipe, angle: V3Angle, family: V3StorylineFamily, hook: V3StoryboardComponent, body: V3StoryboardComponent, cta: V3StoryboardComponent) -> str:
        return deterministic_id(
            "candidate",
            {
                "recipe": [recipe.recipe_id, recipe.revision, recipe.config_digest],
                "angle": [angle.angle_id, angle.revision],
                "family": [family.family_id, family.revision],
                "hook": [hook.component_id, hook.revision, hook.content_digest],
                "body_core": [body.component_id, body.revision, body.content_digest],
                "cta": [cta.component_id, cta.revision, cta.content_digest],
            },
        )

    async def _candidate_sets(
        self, recipe: V3CopyRecipe
    ) -> tuple[list[tuple[V3Angle, V3StorylineFamily, list[V3StoryboardComponent], list[V3StoryboardComponent], list[V3StoryboardComponent]]], int, tuple[str, ...]]:
        angles: list[V3Angle] = []
        if recipe.target_angles:
            for ref in recipe.target_angles:
                angle = await self.repository.get("ANGLE", ref.entity_id, ref.revision)
                if isinstance(angle, V3Angle):
                    angles.append(angle)
        else:
            angles = [item for item in await self.repository.list("ANGLE", product_id=recipe.product_id, limit=MAX_PAGE_SIZE) if item.status not in _TERMINAL_STATUSES]
        sets: list[tuple[V3Angle, V3StorylineFamily, list[V3StoryboardComponent], list[V3StoryboardComponent], list[V3StoryboardComponent]]] = []
        reasons: list[str] = []
        target = {str(key).upper(): int(value) for key, value in recipe.component_count_targets.items()}
        for angle in sorted(angles, key=lambda item: (item.angle_id, item.revision)):
            families = [
                item
                for item in await self.repository.list("STORYLINE_FAMILY", product_id=recipe.product_id, angle_id=angle.angle_id, formula_id=recipe.formula.formula_id, limit=MAX_PAGE_SIZE)
                if item.angle == _ref(angle.angle_id, angle.revision) and item.formula == recipe.formula and item.status not in _TERMINAL_STATUSES
            ]
            if not families:
                reasons.append("MISSING_STORYLINE_FAMILY")
            for family in sorted(families, key=lambda item: (item.family_id, item.revision)):
                all_components = [
                    item
                    for item in await self.repository.list("STORYBOARD_COMPONENT", product_id=recipe.product_id, formula_id=recipe.formula.formula_id, storyline_family_id=family.family_id, limit=MAX_PAGE_SIZE)
                    if item.angle == _ref(angle.angle_id, angle.revision)
                    and item.storyline_family == _ref(family.family_id, family.revision)
                    and item.formula == recipe.formula
                    and item.status not in _TERMINAL_STATUSES
                ]
                groups = {
                    semantic: sorted(
                        [item for item in all_components if item.semantic_class == semantic],
                        key=lambda item: _candidate_sort_key(item, seed=recipe.deterministic_seed),
                    )[: max(0, target.get(semantic, 0))]
                    for semantic in ("HOOK", "BODY_CORE", "CTA")
                }
                for semantic, code in (("HOOK", "MISSING_HOOK_VARIETY"), ("BODY_CORE", "MISSING_BODY_CORE_ROUTE"), ("CTA", "MISSING_CTA_VARIETY")):
                    if not groups[semantic]:
                        reasons.append(code)
                if all(groups[semantic] for semantic in ("HOOK", "BODY_CORE", "CTA")):
                    sets.append((angle, family, groups["HOOK"], groups["BODY_CORE"], groups["CTA"]))
        theoretical = sum(len(hooks) * len(bodies) * len(ctas) for _, _, hooks, bodies, ctas in sets)
        return sets, theoretical, tuple(dict.fromkeys(reasons))

    async def enumerate_candidates(
        self,
        recipe_id: str,
        *,
        revision: int | None = None,
        limit: int = 50,
        cursor: str | None = None,
        durations: Sequence[int] | None = None,
        compile: bool = True,
        existing_fingerprints: Iterable[str] = (),
    ) -> V3CandidatePage:
        recipe = await self.repository.get("COPY_RECIPE", recipe_id, revision)
        if not isinstance(recipe, V3CopyRecipe):
            raise V3FactoryError("RECIPE_NOT_FOUND", "Copy Recipe was not found.", status_code=404)
        if recipe.product_truth is None:
            raise V3FactoryError("TRUTH_LINEAGE_REQUIRED", "Recipe must be Product Truth-bound before enumeration.", status_code=409)
        bundle = await self.truth_adapter.revalidate(recipe.product_truth)
        sets, theoretical, setup_reasons = await self._candidate_sets(recipe)
        seed = recipe.deterministic_seed
        offset = decode_cursor(cursor, seed=seed)
        limit = min(MAX_CANDIDATE_BATCH, max(1, int(limit)))
        requested_durations = tuple(int(item) for item in (durations or recipe.supported_durations_seconds or (8,)))
        selected_fingerprints = set(str(item) for item in existing_fingerprints)

        def combinations() -> Iterator[tuple[V3Angle, V3StorylineFamily, V3StoryboardComponent, V3StoryboardComponent, V3StoryboardComponent]]:
            for angle, family, hooks, bodies, ctas in sets:
                for hook, body, cta in cartesian_product(hooks, bodies, ctas):
                    yield angle, family, hook, body, cta

        candidates: list[V3CandidateCombination] = []
        exclusions: list[V3ExclusionReceipt] = []
        structural_valid = 0
        evidence_valid = 0
        duration_valid = 0
        evaluated = 0
        skipped = 0
        more = False
        iterator = combinations()
        for angle, family, hook, body, cta in iterator:
            if skipped < offset:
                skipped += 1
                continue
            if evaluated >= limit:
                more = True
                break
            evaluated += 1
            candidate_id = self._candidate_id(recipe, angle, family, hook, body, cta)
            refs = {
                "formula": recipe.formula.formula_id,
                "angle": angle.angle_id,
                "storyline": family.family_id,
                "hook": hook.component_id,
                "body_core": body.component_id,
                "cta": cta.component_id,
            }
            result = compile_master_storyboard(
                recipe=recipe,
                angle=angle,
                storyline_family=family,
                hook=hook,
                body_core=body,
                cta=cta,
                evidence_registry=bundle.registry,
                created_by="round1-enumerator",
                source=ROUND1_SOURCE,
            ) if compile else V3CompileResult(valid=True, production_eligible=True)
            if not result.valid or result.master is None:
                code = result.issues[0] if result.issues else "MASTER_VALIDATION_FAILED"
                exclusion = V3ExclusionReceipt(candidate_id=candidate_id, code=code, details=(result.details[0] if result.details else "Master compiler rejected candidate"), dimensions=refs)
                exclusions.append(exclusion)
                candidates.append(V3CandidateCombination(
                    candidate_id=candidate_id, recipe=_ref(recipe.recipe_id, recipe.revision), angle=_ref(angle.angle_id, angle.revision),
                    storyline_family=_ref(family.family_id, family.revision), hook=_ref(hook.component_id, hook.revision), body_core=_ref(body.component_id, body.revision), cta=_ref(cta.component_id, cta.revision),
                    status="EXCLUDED", exclusion_receipts=(exclusion,), validation_receipts=result.receipts,
                ))
                continue
            structural_valid += 1
            evidence_valid += 1
            fingerprint = result.master.duplicate_fingerprint
            if fingerprint in selected_fingerprints:
                exclusion = V3ExclusionReceipt(candidate_id=candidate_id, code="EXACT_DUPLICATE", details="Exact Master content fingerprint was already seen.", dimensions=refs)
                exclusions.append(exclusion)
                candidates.append(V3CandidateCombination(
                    candidate_id=candidate_id, recipe=_ref(recipe.recipe_id, recipe.revision), angle=_ref(angle.angle_id, angle.revision),
                    storyline_family=_ref(family.family_id, family.revision), hook=_ref(hook.component_id, hook.revision), body_core=_ref(body.component_id, body.revision), cta=_ref(cta.component_id, cta.revision),
                    status="EXCLUDED", master=result.master, exclusion_receipts=(exclusion,), validation_receipts=result.receipts,
                ))
                continue
            selected_fingerprints.add(fingerprint)
            projections: list[V3DurationProjection] = []
            projection_issue: tuple[str, ...] = ()
            projection_details: tuple[str, ...] = ()
            if compile:
                for duration in requested_durations:
                    projection, issue_codes, issue_details = compile_duration_projection(
                        result.master, duration_seconds=duration, evidence_registry=bundle.registry, created_by="round1-enumerator", source=ROUND1_SOURCE
                    )
                    if projection is None:
                        projection_issue = issue_codes or ("WPS_DURATION_FIT_SHORTFALL",)
                        projection_details = issue_details
                        break
                    projections.append(projection)
            if projection_issue:
                exclusion = V3ExclusionReceipt(candidate_id=candidate_id, code=projection_issue[0], details=(projection_details[0] if projection_details else "Duration projection rejected candidate"), dimensions={**refs, "durations": ",".join(str(item) for item in requested_durations)})
                exclusions.append(exclusion)
                candidates.append(V3CandidateCombination(
                    candidate_id=candidate_id, recipe=_ref(recipe.recipe_id, recipe.revision), angle=_ref(angle.angle_id, angle.revision),
                    storyline_family=_ref(family.family_id, family.revision), hook=_ref(hook.component_id, hook.revision), body_core=_ref(body.component_id, body.revision), cta=_ref(cta.component_id, cta.revision),
                    status="BLOCKED", master=result.master, projections=tuple(projections), exclusion_receipts=(exclusion,), validation_receipts=result.receipts,
                ))
                continue
            duration_valid += 1
            candidates.append(V3CandidateCombination(
                candidate_id=candidate_id, recipe=_ref(recipe.recipe_id, recipe.revision), angle=_ref(angle.angle_id, angle.revision),
                storyline_family=_ref(family.family_id, family.revision), hook=_ref(hook.component_id, hook.revision), body_core=_ref(body.component_id, body.revision), cta=_ref(cta.component_id, cta.revision),
                status="VALID", master=result.master, projections=tuple(projections), validation_receipts=result.receipts,
            ))
        if not candidates and setup_reasons:
            exclusions.extend(
                V3ExclusionReceipt(candidate_id=deterministic_id("setup_exclusion", {"recipe": recipe.recipe_id, "code": code}), code=code, details="No compatible component supply exists for the locked recipe.", dimensions={"recipe": recipe.recipe_id})
                for code in setup_reasons
            )
        return V3CandidatePage(
            requested_capacity=int(recipe.target_capacity.get("requested_capacity") or theoretical),
            theoretical_capacity=theoretical,
            structurally_valid_capacity=structural_valid,
            evidence_valid_capacity=evidence_valid,
            duration_valid_capacity=duration_valid,
            evaluated_count=evaluated,
            bounded=True,
            seed=seed,
            cursor=cursor,
            next_cursor=encode_cursor(offset + limit, seed=seed) if more else None,
            candidates=tuple(candidates),
            exclusions=tuple(exclusions),
        )

    async def capacity(
        self,
        recipe_id: str,
        *,
        revision: int | None = None,
        evaluation_limit: int = MAX_CANDIDATE_BATCH,
    ) -> V3CapacitySnapshot:
        page = await self.enumerate_candidates(recipe_id, revision=revision, limit=min(MAX_CANDIDATE_BATCH, max(1, evaluation_limit)))
        recipe = await self.repository.get("COPY_RECIPE", recipe_id, revision)
        if not isinstance(recipe, V3CopyRecipe):
            raise V3FactoryError("RECIPE_NOT_FOUND", "Copy Recipe was not found.", status_code=404)
        exclusion_counts = Counter(item.code for item in page.exclusions)
        duration_counts: dict[str, int] = {str(duration): 0 for duration in recipe.supported_durations_seconds}
        for candidate in page.candidates:
            if candidate.status != "VALID":
                continue
            for projection in candidate.projections:
                duration_counts[str(projection.target_duration_seconds)] = duration_counts.get(str(projection.target_duration_seconds), 0) + 1
        pressure: dict[str, dict[str, int]] = {
            "formula": {recipe.formula.formula_id: page.theoretical_capacity},
            "angle": {}, "storyline": {}, "hook": {}, "body_core": {}, "cta": {},
            "bridge": {}, "evidence": {}, "duplicate": {}, "durations": duration_counts,
        }
        for exclusion in page.exclusions:
            code = exclusion.code
            key = "duplicate" if "DUPLICATE" in code else "bridge" if "BRIDGE" in code else "evidence" if "EVIDENCE" in code else "durations" if "WPS" in code or "DURATION" in code else "formula" if "FORMULA" in code else "angle" if "ANGLE" in code else "storyline" if "STORYLINE" in code else "hook" if "HOOK" in code else "body_core" if "BODY" in code else "cta" if "CTA" in code else "formula"
            pressure[key][code] = pressure[key].get(code, 0) + 1
        shortfalls: list[str] = []
        if page.theoretical_capacity < page.requested_capacity:
            shortfalls.append("REQUESTED_CAPACITY_SHORTFALL")
        shortfalls.extend(code for code in ("MISSING_HOOK_VARIETY", "MISSING_BODY_CORE_ROUTE", "MISSING_CTA_VARIETY", "MISSING_STORYLINE_FAMILY") if code in exclusion_counts or page.theoretical_capacity == 0)
        shortfalls.extend(sorted(code for code in exclusion_counts if code in {"BRIDGE_SHORTFALL", "EVIDENCE_SHORTFALL", "WPS_DURATION_FIT_SHORTFALL", "EXACT_DUPLICATE", "MISSING_FORMULA_STAGE"}))
        snapshot_payload = {
            "recipe": [recipe.recipe_id, recipe.revision, recipe.config_digest],
            "requested": page.requested_capacity, "theoretical": page.theoretical_capacity,
            "structural": page.structurally_valid_capacity, "evidence": page.evidence_valid_capacity,
            "duration": page.duration_valid_capacity, "exclusions": dict(exclusion_counts),
        }
        return V3CapacitySnapshot(
            recipe=_ref(recipe.recipe_id, recipe.revision),
            requested_capacity=page.requested_capacity,
            theoretical_capacity=page.theoretical_capacity,
            structurally_valid_capacity=page.structurally_valid_capacity,
            evidence_valid_capacity=page.evidence_valid_capacity,
            duration_valid_capacity=page.duration_valid_capacity,
            reviewable_capacity=page.duration_valid_capacity,
            approved_capacity=0,
            executable_capacity=0,
            duration_counts=duration_counts,
            pressure=pressure,
            shortfall_codes=tuple(dict.fromkeys(shortfalls)),
            exclusion_counts=dict(exclusion_counts),
            evaluated_count=page.evaluated_count,
            bounded=page.bounded,
            snapshot_digest=deterministic_digest(snapshot_payload),
        )

    async def compile_master(
        self,
        recipe_id: str,
        *,
        angle_id: str,
        angle_revision: int = 1,
        storyline_family_id: str,
        storyline_family_revision: int = 1,
        hook_id: str,
        hook_revision: int = 1,
        body_core_id: str,
        body_core_revision: int = 1,
        cta_id: str,
        cta_revision: int = 1,
        persist: bool = False,
        actor_id: str | None = None,
        request_id: str | None = None,
        source: str = ROUND1_SOURCE,
    ) -> V3CompileResult:
        recipe = await self.repository.get("COPY_RECIPE", recipe_id)
        angle = await self.repository.get("ANGLE", angle_id, angle_revision)
        family = await self.repository.get("STORYLINE_FAMILY", storyline_family_id, storyline_family_revision)
        hook = await self.repository.get("STORYBOARD_COMPONENT", hook_id, hook_revision)
        body = await self.repository.get("STORYBOARD_COMPONENT", body_core_id, body_core_revision)
        cta = await self.repository.get("STORYBOARD_COMPONENT", cta_id, cta_revision)
        if not all(isinstance(item, expected) for item, expected in ((recipe, V3CopyRecipe), (angle, V3Angle), (family, V3StorylineFamily), (hook, V3StoryboardComponent), (body, V3StoryboardComponent), (cta, V3StoryboardComponent))):
            raise V3FactoryError("V3_COMPILE_INPUT_NOT_FOUND", "Recipe, Angle, Storyline, and three components are required.", status_code=404)
        assert isinstance(recipe, V3CopyRecipe)
        assert isinstance(angle, V3Angle)
        assert isinstance(family, V3StorylineFamily)
        assert isinstance(hook, V3StoryboardComponent)
        assert isinstance(body, V3StoryboardComponent)
        assert isinstance(cta, V3StoryboardComponent)
        if recipe.product_truth is None:
            raise V3FactoryError("TRUTH_LINEAGE_REQUIRED", "Recipe must be bound to current Product Truth.", status_code=409)
        bundle = await self.truth_adapter.revalidate(recipe.product_truth)
        result = compile_master_storyboard(
            recipe=recipe, angle=angle, storyline_family=family, hook=hook, body_core=body, cta=cta,
            evidence_registry=bundle.registry, created_by=actor_id or "round1-compiler", source=source,
        )
        if persist:
            if not actor_id or not request_id:
                raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id and request_id are required for persistence.", status_code=422)
            if not result.valid or result.master is None:
                return result
            persisted = await self.repository.insert(result.master, actor_id=actor_id, request_id=request_id, source=source)
            return V3CompileResult(valid=True, production_eligible=True, master=persisted, receipts=result.receipts)
        return result

    async def project_duration(
        self,
        master_id: str,
        *,
        master_revision: int = 1,
        duration_seconds: int,
        language_profile: str = "Malay",
        wps_mode: str = "SAFE",
        preferred_lane: str | None = None,
        persist: bool = False,
        actor_id: str | None = None,
        request_id: str | None = None,
        source: str = ROUND1_SOURCE,
    ) -> tuple[V3DurationProjection | None, tuple[str, ...], tuple[str, ...]]:
        master = await self.repository.get("MASTER_STORYBOARD", master_id, master_revision)
        if not isinstance(master, V3MasterStoryboard):
            raise V3FactoryError("MASTER_NOT_FOUND", "Master Storyboard was not found.", status_code=404)
        bundle = await self.truth_adapter.revalidate(master.product_truth)
        projection, issues, details = compile_duration_projection(
            master, duration_seconds=duration_seconds, evidence_registry=bundle.registry,
            language_profile=language_profile, wps_mode=wps_mode, preferred_lane=preferred_lane,
            created_by=actor_id or "round1-compiler", source=source,
        )
        if projection is not None and persist:
            if not actor_id or not request_id:
                raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id and request_id are required for persistence.", status_code=422)
            projection = await self.repository.insert(projection, actor_id=actor_id, request_id=request_id, source=source)
        return projection, issues, details

    async def component_landbank(
        self, product_id: str, *, limit: int = 100, offset: int = 0, formula_id: str | None = None, semantic_class: str | None = None, status: str | None = None
    ) -> V3LandbankPage:
        rows = await self.repository.list("STORYBOARD_COMPONENT", product_id=product_id, formula_id=formula_id, status=status, limit=min(MAX_PAGE_SIZE, int(limit)) + 1, offset=offset)
        if semantic_class:
            rows = [row for row in rows if row.semantic_class == str(semantic_class).upper()]
        has_more = len(rows) > int(limit)
        items = [
            {
                "product_id": row.product_id, "formula": row.formula.model_dump(mode="json"),
                "angle": row.angle.model_dump(mode="json"), "storyline_family": row.storyline_family.model_dump(mode="json"),
                "component_id": row.component_id, "revision": row.revision, "semantic_class": row.semantic_class,
                "stage_segments": [item.model_dump(mode="json") for item in row.stage_segments],
                "formula_stage_keys": list(row.formula_stage_keys), "status": row.status,
                "evidence_fact_ids": list(row.evidence_fact_ids), "content_digest": row.content_digest,
            }
            for row in rows[: int(limit)]
        ]
        return V3LandbankPage.from_items(items, limit=int(limit), offset=int(offset), has_more=has_more)

    async def storyboard_landbank(
        self, product_id: str, *, limit: int = 100, offset: int = 0, status: str | None = None
    ) -> V3LandbankPage:
        masters = await self.repository.list("MASTER_STORYBOARD", product_id=product_id, status=status, limit=min(MAX_PAGE_SIZE, int(limit)) + 1, offset=offset)
        has_more = len(masters) > int(limit)
        bundle = await self.truth_adapter.current(product_id)
        projection_rows = await self.repository.list("DURATION_PROJECTION", product_id=product_id, limit=MAX_PAGE_SIZE, latest_only=True)
        items: list[dict[str, Any]] = []
        for master in masters[: int(limit)]:
            projections = [
                projection.model_dump(mode="json")
                for projection in projection_rows
                if projection.master == _ref(master.master_id, master.revision)
            ]
            items.append({
                "master": master.model_dump(mode="json"), "projections": projections,
                "current_truth": master.product_truth == bundle.lineage,
                "stale": master.product_truth != bundle.lineage,
                "validation_status": master.status,
                "capacity_eligibility": "REVIEWABLE" if master.status in {"DRAFT", "REVIEW_REQUIRED", "VALIDATED"} and master.product_truth == bundle.lineage else "BLOCKED",
            })
        return V3LandbankPage.from_items(items, limit=int(limit), offset=int(offset), has_more=has_more)

    async def review_queue(
        self, product_id: str | None = None, *, statuses: Sequence[str] = ("DRAFT", "REVIEW_REQUIRED", "VALIDATED", "BLOCKED", "REJECTED"), limit: int = 100, offset: int = 0
    ) -> V3LandbankPage:
        items: list[dict[str, Any]] = []
        for entity_type in _ENTITY_TABLES:
            if len(items) >= min(MAX_PAGE_SIZE, int(limit)) + int(offset):
                break
            rows = await self.repository.list(entity_type, product_id=product_id, limit=MAX_PAGE_SIZE, latest_only=True)
            for row in rows:
                if row.status in set(statuses):
                    items.append({
                        "entity_type": entity_type, "entity_id": row.__dict__.get("angle_id") or row.__dict__.get("family_id") or row.__dict__.get("component_id") or row.__dict__.get("recipe_id") or row.__dict__.get("master_id") or row.__dict__.get("projection_id"),
                        "revision": row.revision, "status": row.status, "product_id": row.product_id,
                        "created_at": row.created_at, "source": row.source,
                        "digest": _entity_digest(row),
                    })
        items.sort(key=lambda item: (item["created_at"], item["entity_type"], item["entity_id"]), reverse=True)
        sliced = items[int(offset): int(offset) + int(limit)]
        return V3LandbankPage.from_items(sliced, limit=int(limit), offset=int(offset), has_more=len(items) > int(offset) + len(sliced))

    async def v2_seed_preview(self, product_id: str, *, blueprint_id: str | None = None, angle_id: str | None = None) -> dict[str, Any]:
        """Inspect governed V2 sources only; this operation never writes."""

        bundle = await self.truth_adapter.current(product_id)
        db = await get_db()
        blueprint_rows = []
        if blueprint_id:
            cursor = await db.execute("SELECT * FROM copy_blueprint_v2 WHERE product_id=? AND blueprint_id=? ORDER BY revision DESC LIMIT 20", (product_id, blueprint_id))
        else:
            cursor = await db.execute("SELECT * FROM copy_blueprint_v2 WHERE product_id=? ORDER BY created_at DESC, blueprint_id, revision DESC LIMIT 100", (product_id,))
        for row in await cursor.fetchall():
            data = dict(row)
            formula_ok = False
            formula_reason = None
            try:
                _formula_ref(data.get("formula_id") or "", data.get("formula_version"))
                formula_ok = True
            except V3FactoryError as exc:
                formula_reason = exc.code
            truth_ok = (
                data.get("product_truth_snapshot_id") == bundle.lineage.snapshot_id
                and int(data.get("product_truth_snapshot_version") or 0) == bundle.lineage.snapshot_version
                and data.get("product_truth_snapshot_digest") == bundle.lineage.snapshot_digest
            )
            stage_payload = _loads(data.get("stages_json"), [])
            blueprint_rows.append({
                "source_type": "V2_BLUEPRINT", "blueprint_id": data.get("blueprint_id"), "revision": int(data.get("revision") or 0),
                "status": data.get("status"), "formula_current": formula_ok, "formula_reason": formula_reason,
                "truth_current": truth_ok, "stage_count": len(stage_payload) if isinstance(stage_payload, list) else 0,
                "import_status": "SAFE_TO_IMPORT_DRAFT" if formula_ok and truth_ok and data.get("status") not in {"BLOCKED", "SUPERSEDED"} else "REVIEW_REQUIRED",
            })
        angle_rows = []
        angle_query = "SELECT * FROM copy_angle_candidate_v2 WHERE product_id=?"
        params: list[Any] = [product_id]
        if angle_id:
            angle_query += " AND angle_id=?"
            params.append(angle_id)
        angle_query += " ORDER BY created_at DESC, angle_id LIMIT 100"
        cursor = await db.execute(angle_query, params)
        for row in await cursor.fetchall():
            data = dict(row)
            try:
                _formula_ref(data.get("formula_id") or "", data.get("formula_version"))
                formula_ok = True
                formula_reason = None
            except V3FactoryError as exc:
                formula_ok = False
                formula_reason = exc.code
            truth_ok = data.get("product_truth_snapshot_id") == bundle.lineage.snapshot_id and int(data.get("product_truth_snapshot_version") or 0) == bundle.lineage.snapshot_version and data.get("product_truth_snapshot_digest") == bundle.lineage.snapshot_digest
            angle_rows.append({
                "source_type": "V2_ANGLE_CANDIDATE", "angle_id": data.get("angle_id"), "formula_current": formula_ok,
                "formula_reason": formula_reason, "truth_current": truth_ok,
                "import_status": "SAFE_TO_IMPORT_DRAFT" if formula_ok and truth_ok else "REVIEW_REQUIRED",
            })
        return {"product_id": product_id, "blueprints": blueprint_rows, "angles": angle_rows, "provider_calls": 0, "mutations": 0, "legacy_copyset_considered": False}

    async def import_v2_angle_draft(
        self,
        product_id: str,
        angle_id: str,
        *,
        actor_id: str,
        request_id: str,
        source: str = "V2_ANGLE_SEED_ADAPTER",
    ) -> V3Angle:
        """Explicitly import one governed V2 angle candidate as a V3 DRAFT."""

        existing_request = await self._idempotent_existing(request_id, V3Angle)
        if existing_request is not None:
            return existing_request
        bundle = await self._current_truth(product_id)
        db = await get_db()
        row = await (await db.execute("SELECT * FROM copy_angle_candidate_v2 WHERE product_id=? AND angle_id=?", (product_id, angle_id))).fetchone()
        if not row:
            raise V3FactoryError("V2_ANGLE_NOT_FOUND", "V2 angle candidate was not found.", status_code=404)
        data = dict(row)
        if data.get("product_truth_snapshot_id") != bundle.lineage.snapshot_id or int(data.get("product_truth_snapshot_version") or 0) != bundle.lineage.snapshot_version or data.get("product_truth_snapshot_digest") != bundle.lineage.snapshot_digest:
            raise V3FactoryError("STALE_PRODUCT_TRUTH", "V2 angle is not bound to current Product Truth.", status_code=409)
        formula = _formula_ref(data.get("formula_id") or "", data.get("formula_version"))
        evidence = _loads(data.get("evidence_fact_ids_json"), [])
        return await self.create_angle(
            product_id,
            {
                "angle_id": f"v3-angle-from-v2-{angle_id}",
                "definition": data.get("definition") or "",
                "formula_id": formula.formula_id,
                "formula_version": formula.formula_version,
                "objective_id": data.get("objective") or "v2-objective",
                "objective_definition": data.get("objective") or "V2 governed objective",
                "evidence_fact_ids": evidence,
            },
            actor_id=actor_id,
            request_id=request_id,
            source=f"{source}:{angle_id}",
        )

    async def import_v2_blueprint_draft(
        self,
        product_id: str,
        blueprint_id: str,
        revision: int,
        *,
        actor_id: str,
        request_id: str,
        source: str = "V2_BLUEPRINT_SEED_ADAPTER",
    ) -> dict[str, Any]:
        """Derive DRAFT Angle/Family/Components from ordered V2 FormulaStages."""

        if not actor_id or not request_id:
            raise V3FactoryError("MUTATION_RECEIPT_REQUIRED", "actor_id and request_id are required.", status_code=422)
        bundle = await self._current_truth(product_id)
        db = await get_db()
        row = await (await db.execute("SELECT * FROM copy_blueprint_v2 WHERE product_id=? AND blueprint_id=? AND revision=?", (product_id, blueprint_id, revision))).fetchone()
        if not row:
            raise V3FactoryError("V2_BLUEPRINT_NOT_FOUND", "V2 Blueprint was not found.", status_code=404)
        data = dict(row)
        if data.get("status") in {"BLOCKED", "SUPERSEDED"}:
            raise V3FactoryError("V2_SEED_UNSAFE", "Blocked or superseded V2 sources cannot seed V3.", status_code=409)
        if data.get("product_truth_snapshot_id") != bundle.lineage.snapshot_id or int(data.get("product_truth_snapshot_version") or 0) != bundle.lineage.snapshot_version or data.get("product_truth_snapshot_digest") != bundle.lineage.snapshot_digest:
            raise V3FactoryError("STALE_PRODUCT_TRUTH", "V2 Blueprint is not bound to current Product Truth.", status_code=409)
        formula = _formula_ref(data.get("formula_id") or "", data.get("formula_version"))
        stages = _loads(data.get("stages_json"), [])
        if not isinstance(stages, list) or not stages:
            raise V3FactoryError("V2_SEED_STAGE_REQUIRED", "V2 Blueprint has no ordered FormulaStages.", status_code=409)
        required = tuple(required_formula_stage_keys(formula.formula_id))
        keys = tuple(str(item.get("formula_stage_key") or "") for item in stages if isinstance(item, Mapping))
        if keys != required:
            raise V3FactoryError("V2_SEED_FORMULA_STAGE_MISMATCH", "V2 FormulaStages do not match current canonical formula order.", status_code=409, details={"expected": required, "received": keys})
        contract = strict_formula_contract(formula.formula_id)
        hook_keys = set(_mapping_values(contract, "hook"))
        cta_keys = set(_mapping_values(contract, "cta"))
        body_keys = set(required) - hook_keys - cta_keys
        angle_raw = _loads(data.get("angle_json"), {})
        angle_definition = normalized_text(str(angle_raw.get("definition") or angle_raw.get("angle_definition") or ""))
        if not angle_definition:
            raise V3FactoryError("V2_SEED_ANGLE_UNSAFE", "V2 Blueprint has no safe strategic Angle definition.", status_code=409)
        evidence_ids: list[str] = []
        for item in stages:
            for ref in item.get("fact_refs") or item.get("evidence_fact_ids") or []:
                fact_id = ref.get("fact_id") if isinstance(ref, Mapping) else ref
                if fact_id and str(fact_id) not in evidence_ids:
                    evidence_ids.append(str(fact_id))
        angle = await self.create_angle(
            product_id,
            {
                "angle_id": f"v3-angle-from-v2-{blueprint_id}",
                "definition": angle_definition,
                "formula_id": formula.formula_id,
                "formula_version": formula.formula_version,
                "objective_id": str((_loads(data.get("objective_json"), {}) or {}).get("objective_id") or "v2-objective"),
                "objective_definition": str((_loads(data.get("objective_json"), {}) or {}).get("definition") or "V2 governed objective"),
                "evidence_fact_ids": evidence_ids,
            },
            actor_id=actor_id,
            request_id=f"{request_id}:angle",
            source=f"{source}:{blueprint_id}:{revision}",
        )
        bridge_missing = []
        for item in stages:
            bridge_value = _loads(item.get("bridge"), {}) if isinstance(item.get("bridge"), str) else (item.get("bridge") or {})
            entry_value = item.get("entry_key") or bridge_value.get("entry") or bridge_value.get("entry_key")
            exit_value = item.get("exit_key") or bridge_value.get("exit") or bridge_value.get("exit_key")
            if not entry_value or not exit_value:
                bridge_missing.append(item.get("formula_stage_key"))
        if bridge_missing:
            # Preserve the distinction between a safely representable V2 seed
            # and a route that needs a human review; never invent bridge keys.
            raise V3FactoryError("V2_SEED_REVIEW_REQUIRED", "V2 stage bridge lineage is incomplete; no semantic family was invented.", status_code=409, details={"stages": bridge_missing})
        family = await self.create_storyline_family(
            product_id,
            {
                "angle_id": angle.angle_id, "angle_revision": angle.revision,
                "formula_id": formula.formula_id, "formula_version": formula.formula_version,
                "reviewed_definition": angle_definition,
                "narrative_route": {"stage_keys": list(required), "source_v2_blueprint": {"blueprint_id": blueprint_id, "revision": revision}, "bridge_lineage": True},
                "evidence_fact_ids": evidence_ids,
            },
            actor_id=actor_id,
            request_id=f"{request_id}:family",
            source=f"{source}:{blueprint_id}:{revision}",
        )
        created_components: list[V3StoryboardComponent] = []
        for semantic_class, allowed_keys in (("HOOK", hook_keys), ("BODY_CORE", body_keys), ("CTA", cta_keys)):
            segment_inputs: list[dict[str, Any]] = []
            for index, item in enumerate(stages):
                if item.get("formula_stage_key") not in allowed_keys:
                    continue
                bridge_raw = item.get("bridge") or {}
                if isinstance(bridge_raw, str):
                    bridge_raw = _loads(bridge_raw, {})
                refs = item.get("fact_refs") or item.get("evidence_fact_ids") or []
                fact_ids = [ref.get("fact_id") if isinstance(ref, Mapping) else str(ref) for ref in refs]
                segment_inputs.append({
                    "formula_stage_key": item.get("formula_stage_key"), "order": index,
                    "authored_text": item.get("authored_text") or item.get("text") or "",
                    "entry_key": item.get("entry_key") or bridge_raw.get("entry") or bridge_raw.get("entry_key"),
                    "exit_key": item.get("exit_key") or bridge_raw.get("exit") or bridge_raw.get("exit_key"),
                    "bridge_contract": bridge_raw, "evidence_fact_ids": fact_ids,
                    "claim_bearing": bool(item.get("claim_bearing", semantic_class != "CTA")),
                })
            created_components.append(
                await self.create_component(
                    product_id,
                    {
                        "angle_id": angle.angle_id, "angle_revision": angle.revision,
                        "storyline_family_id": family.family_id, "storyline_family_revision": family.revision,
                        "formula_id": formula.formula_id, "formula_version": formula.formula_version,
                        "objective_id": str((_loads(data.get("objective_json"), {}) or {}).get("objective_id") or "v2-objective"),
                        "objective_definition": str((_loads(data.get("objective_json"), {}) or {}).get("definition") or "V2 governed objective"),
                        "semantic_class": semantic_class, "stage_segments": segment_inputs,
                        "component_id": f"v3-component-from-v2-{blueprint_id}-{semantic_class.lower()}",
                    },
                    actor_id=actor_id,
                    request_id=f"{request_id}:component:{semantic_class}",
                    source=f"{source}:{blueprint_id}:{revision}",
                )
            )
        return {
            "status": "DRAFT",
            "source": source,
            "v2_blueprint": {"blueprint_id": blueprint_id, "revision": revision},
            "angle": angle.model_dump(mode="json"),
            "storyline_family": family.model_dump(mode="json"),
            "components": [item.model_dump(mode="json") for item in created_components],
            "provider_calls": 0,
            "media_calls": 0,
            "approval": False,
        }


# Backwards-friendly aliases for service discovery in tests and future API
# integration.  They all point at the same single provider-free authority.
StoryboardLandbankV3FactoryService = V3CopyFactoryService
V3FactoryRepository = V3CopyFactoryRepository


__all__ = [
    "ROUND1_SOURCE",
    "V3FactoryError",
    "V3CopyFactoryRepository",
    "V3FactoryRepository",
    "ProductTruthEvidenceAdapter",
    "EvidenceRelevanceService",
    "formula_read_model",
    "list_formula_read_models",
    "compile_master_storyboard",
    "compile_duration_projection",
    "V3CopyFactoryService",
    "StoryboardLandbankV3FactoryService",
    "encode_cursor",
    "decode_cursor",
]
