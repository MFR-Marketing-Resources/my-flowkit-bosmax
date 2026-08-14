"""Additive Copy Architecture V2 domain contracts.

The legacy ``CopySet`` remains the production authority while the V2 flag is
off.  These models are deliberately self-contained: they describe a versioned
blueprint, its evidence/approval lineage, and the execution binding without
changing the legacy database rows or compiler input shape.

The ordered ``stages`` tuple is the only authored V2 copy source of truth.
Hook/body/CTA are exposed by :meth:`CopyBlueprintV2.derived_projections` and
are never persisted as replacement source fields.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


V2_SCHEMA_VERSION = "2"
V2_FEATURE_FLAG = "COPY_BLUEPRINT_V2_ENABLED"
V2_SHADOW_FLAG = "COPY_BLUEPRINT_V2_SHADOW_MODE"
V2_BINDING_VERSION = "copy-execution-binding-v2"

BlueprintStatus = Literal[
    "DRAFT",
    "REVIEW_REQUIRED",
    "APPROVED",
    "PRODUCTION_VALID",
    "SUPERSEDED",
    "BLOCKED",
]
MediaKind = Literal["VIDEO", "IMAGE"]
CopyPolicy = Literal["REQUIRED", "NOT_REQUIRED"]
FeatureFlagStateValue = Literal["OFF", "SHADOW", "PILOT", "ON"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonicalize_evidence_text(value: str) -> str:
    """Return the wording canonicalization used only for a digest.

    A digest detects wording drift.  It is intentionally not used as a fact
    identity; ``EvidenceReference.fact_id`` is supplied by the evidence
    authority and remains stable when wording is corrected.
    """

    return " ".join(str(value or "").split()).strip()


def digest_evidence_text(value: str) -> str:
    return hashlib.sha256(canonicalize_evidence_text(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class EvidenceReference(BaseModel):
    """Stable reference to a reviewed Product Truth fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)
    fact_kind: str = Field(min_length=1)

    @field_validator("snapshot_id", "fact_id", "fact_kind")
    @classmethod
    def _trim_identifier(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("identifier must not be blank")
        return value

    @model_validator(mode="after")
    def _identity_is_not_text_digest(self) -> "EvidenceReference":
        if self.fact_id.casefold() == self.text_digest.casefold():
            raise ValueError("fact_id must be a stable semantic identity, not text_digest")
        return self


class EvidenceFact(BaseModel):
    """A reviewable fact held by the additive evidence substrate.

    ``fact_id`` is caller-supplied stable identity.  ``text_digest`` is
    calculated from the approved wording and therefore changes when wording
    changes while the fact identity does not.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    fact_kind: str = Field(min_length=1)
    text: str = Field(min_length=1)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)
    snapshot_version: int = Field(ge=1)
    snapshot_status: Literal["APPROVED", "DRAFT", "SUPERSEDED", "REJECTED"]
    approved: bool = False
    source_ref: str | None = None

    @model_validator(mode="after")
    def _digest_and_approval_contract(self) -> "EvidenceFact":
        if self.fact_id.casefold() == self.text_digest.casefold():
            raise ValueError("fact_id must not be derived from text_digest")
        if digest_evidence_text(self.text) != self.text_digest:
            raise ValueError("text_digest does not match canonical fact text")
        if self.snapshot_status == "APPROVED" and not self.approved:
            raise ValueError("approved snapshot facts must be approved")
        return self

    def reference(self) -> EvidenceReference:
        return EvidenceReference(
            snapshot_id=self.snapshot_id,
            fact_id=self.fact_id,
            text_digest=self.text_digest,
            fact_kind=self.fact_kind,
        )


class EvidenceRegistry(BaseModel):
    """Read-only, snapshot-scoped evidence view used by validation/tests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: tuple[EvidenceFact, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _unique_fact_keys(self) -> "EvidenceRegistry":
        keys = [(fact.snapshot_id, fact.fact_id) for fact in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate evidence fact identity")
        return self

    def get(self, snapshot_id: str, fact_id: str) -> EvidenceFact | None:
        for fact in self.facts:
            if fact.snapshot_id == snapshot_id and fact.fact_id == fact_id:
                return fact
        return None


class ProductTruthLineage(BaseModel):
    """Approved Product Truth snapshot lineage carried by V2 artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    snapshot_digest: str = Field(pattern=_SHA256_RE.pattern)
    snapshot_status: Literal["APPROVED", "DRAFT", "SUPERSEDED", "REJECTED"]
    approved_by: str | None = None
    approved_at: str | None = None


class Objective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class Angle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    angle_id: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class BridgeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: str = ""
    exit: str = ""
    continuity_requirements: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("entry", "exit")
    @classmethod
    def _clean_bridge_token(cls, value: str) -> str:
        return " ".join(value.split()).strip()


class StageValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool = False
    error_codes: tuple[str, ...] = Field(default_factory=tuple)


class FormulaStage(BaseModel):
    """Ordered formula-native authored stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_key: str = Field(min_length=1)
    order: int = Field(ge=0)
    authored_text: str = ""
    semantic_role: str = Field(min_length=1)
    component_ref: str | None = None
    formula_stage_key: str = Field(min_length=1)
    bridge: BridgeContract = Field(default_factory=BridgeContract)
    claim_bearing: bool = False
    fact_refs: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    validation: StageValidation = Field(default_factory=StageValidation)

    @field_validator("authored_text")
    @classmethod
    def _normalize_authored_text(cls, value: str) -> str:
        return " ".join(value.split()).strip()


class ApprovedExecutionText(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_key: str = Field(min_length=1)
    text: str = Field(min_length=1)


class StageTextDigest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_key: str = Field(min_length=1)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)


class ApprovalSnapshot(BaseModel):
    """Immutable human approval receipt for one exact blueprint revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_snapshot_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    blueprint_digest: str = Field(pattern=_SHA256_RE.pattern)
    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    product_truth_snapshot_id: str = Field(min_length=1)
    stage_text_digests: tuple[StageTextDigest, ...] = Field(default_factory=tuple)
    approved_execution_text: tuple[ApprovedExecutionText, ...] = Field(default_factory=tuple)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_stage_receipts(self) -> "ApprovalSnapshot":
        digest_keys = [item.stage_key for item in self.stage_text_digests]
        text_keys = [item.stage_key for item in self.approved_execution_text]
        if len(digest_keys) != len(set(digest_keys)) or len(text_keys) != len(set(text_keys)):
            raise ValueError("approval snapshot contains duplicate stage receipts")
        return self


class SupersessionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class ProvenanceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class DerivedCopyProjection(BaseModel):
    """Lossy presentation view; never a V2 authoring source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_version: Literal["copy-blueprint-v2"] = "copy-blueprint-v2"
    blueprint_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    hook: str = ""
    body: str = ""
    cta: str = ""


class CopyBlueprintV2(BaseModel):
    """First-class formula-native V2 copy blueprint.

    Frozen nested tuples ensure an approved artifact cannot be edited in place.
    A new revision must be created for any text, evidence, formula, or lineage
    change.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["2"] = V2_SCHEMA_VERSION
    blueprint_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    copy_set_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    status: BlueprintStatus = "DRAFT"
    formula_id: str = ""
    formula_version: str = ""
    objective: Objective
    angle: Angle
    stages: tuple[FormulaStage, ...] = Field(default_factory=tuple)
    component_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    target_duration_seconds: float | None = Field(default=None, gt=0)
    wps_profile: str | None = None
    estimated_word_count: int = Field(default=0, ge=0)
    approval_snapshot: ApprovalSnapshot | None = None
    approved_execution_text: tuple[ApprovedExecutionText, ...] = Field(default_factory=tuple)
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)
    product_truth_lineage: ProductTruthLineage
    supersedes: SupersessionRef | None = None
    created_at: str = Field(min_length=1)
    approved_at: str | None = None
    approved_by: str | None = None

    @field_validator("formula_id", "formula_version")
    @classmethod
    def _explicit_formula_fields(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @model_validator(mode="after")
    def _approval_envelope(self) -> "CopyBlueprintV2":
        approved_status = self.status in {"APPROVED", "PRODUCTION_VALID"}
        if approved_status:
            if self.approval_snapshot is None:
                raise ValueError("approved V2 blueprint requires approval_snapshot")
            if not self.approved_execution_text:
                raise ValueError("approved V2 blueprint requires approved_execution_text")
            if not self.approved_by or not self.approved_at:
                raise ValueError("approved V2 blueprint requires approver metadata")
        if self.approval_snapshot is not None:
            if self.approval_snapshot.blueprint_id != self.blueprint_id:
                raise ValueError("approval snapshot blueprint mismatch")
            if self.approval_snapshot.revision != self.revision:
                raise ValueError("approval snapshot revision mismatch")
        return self

    def _execution_text_by_stage(self) -> dict[str, str]:
        if self.approved_execution_text:
            return {item.stage_key: item.text for item in self.approved_execution_text}
        return {stage.stage_key: stage.authored_text for stage in self.stages}

    def derived_projections(self) -> DerivedCopyProjection:
        """Derive hook/body/CTA from formula stages for display only."""

        from agent.authority.copy_blueprint_v2_authority import strict_formula_contract

        contract = strict_formula_contract(self.formula_id)
        mapping = contract["output_mapping"]
        text_by_stage = self._execution_text_by_stage()
        by_formula_key = {
            stage.formula_stage_key: text_by_stage.get(stage.stage_key, "")
            for stage in self.stages
        }

        def mapped_text(key: str) -> str:
            mapped = mapping.get(key)
            if isinstance(mapped, list):
                return " ".join(by_formula_key.get(item, "") for item in mapped).strip()
            return by_formula_key.get(mapped, "") if mapped else ""

        hook_slot = mapping.get("hook")
        cta_slot = mapping.get("cta")
        excluded = set(hook_slot if isinstance(hook_slot, list) else [hook_slot])
        excluded.update(cta_slot if isinstance(cta_slot, list) else [cta_slot])
        body = " ".join(
            text_by_stage.get(stage.stage_key, "")
            for stage in self.stages
            if stage.formula_stage_key not in excluded and text_by_stage.get(stage.stage_key, "")
        ).strip()
        return DerivedCopyProjection(
            blueprint_id=self.blueprint_id,
            revision=self.revision,
            hook=mapped_text("hook"),
            body=body,
            cta=mapped_text("cta"),
        )


class EvidenceLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_ids: tuple[str, ...] = Field(default_factory=tuple)
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    references: tuple[EvidenceReference, ...] = Field(default_factory=tuple)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)


class CopyBlueprintV2FeatureFlagState(BaseModel):
    """Default-off rollout state carried by every V2 binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flag_name: str = V2_FEATURE_FLAG
    enabled: bool = False
    shadow_mode: bool = False
    scope: str = ""
    pilot_scope: tuple[str, ...] = Field(default_factory=tuple)
    state: FeatureFlagStateValue = "OFF"

    @model_validator(mode="after")
    def _state_is_consistent(self) -> "CopyBlueprintV2FeatureFlagState":
        expected = "OFF"
        if self.enabled and self.shadow_mode:
            expected = "SHADOW"
        elif self.enabled and self.scope and self.scope in self.pilot_scope:
            expected = "PILOT"
        elif self.enabled:
            expected = "ON"
        if self.state != expected:
            raise ValueError(f"feature flag state mismatch: expected {expected}")
        return self

    @classmethod
    def from_environment(cls, *, scope: str = "", pilot_scope: tuple[str, ...] = ()) -> "CopyBlueprintV2FeatureFlagState":
        enabled = os.getenv(V2_FEATURE_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}
        shadow = os.getenv(V2_SHADOW_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}
        state = "OFF"
        if enabled and shadow:
            state = "SHADOW"
        elif enabled and scope and scope in pilot_scope:
            state = "PILOT"
        elif enabled:
            state = "ON"
        return cls(
            enabled=enabled,
            shadow_mode=shadow,
            scope=scope,
            pilot_scope=pilot_scope,
            state=state,
        )


class CopyExecutionBinding(BaseModel):
    """Versioned, lineage-complete V2 execution binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(min_length=1)
    lane: str = Field(min_length=1)
    media_kind: MediaKind
    copy_policy: CopyPolicy
    blueprint_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    approval_snapshot_id: str = Field(min_length=1)
    product_truth_lineage: ProductTruthLineage
    evidence_lineage: EvidenceLineage
    compiler_binding_version: str = Field(min_length=1)
    feature_flag_state: CopyBlueprintV2FeatureFlagState
    binding_status: Literal["BOUND"] = "BOUND"
    bound_at: str = Field(min_length=1)


class AdapterContext(BaseModel):
    """Proof that an adapter did not silently bypass non-copy gates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = Field(min_length=1)
    product_truth_lineage: ProductTruthLineage
    readiness_validated: bool = False
    provenance_validated: bool = False
    safety_validated: bool = False
    # Additive Phase 3 gate. The default remains compatible with direct Phase 2
    # projection callers; the consumer resolver requires this field to be
    # explicitly supplied for COPY_REQUIRED production lanes.
    semantic_review_validated: bool = True


class VideoCopyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane: str = Field(min_length=1)
    media_kind: Literal["VIDEO"] = "VIDEO"
    copy_policy: Literal["REQUIRED"] = "REQUIRED"
    binding: CopyExecutionBinding
    derived_copy: DerivedCopyProjection
    context: AdapterContext


class ImageCopyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane: str = Field(min_length=1)
    media_kind: Literal["IMAGE"] = "IMAGE"
    copy_policy: CopyPolicy
    copy_required: bool
    binding: CopyExecutionBinding | None = None
    derived_copy: DerivedCopyProjection | None = None
    context: AdapterContext
