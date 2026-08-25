"""Round 1 read models for the provider-free V3 Copy Factory.

These are deliberately read/compile envelopes rather than new persistence
authorities.  The seven Phase 2 V3 records remain the only durable V3 source;
candidate, evidence, capacity, and landbank views are bounded projections over
those records and the canonical Product Truth/evidence/formula authorities.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.models.storyboard_landbank_v3 import (
    V3DurationProjection,
    V3MasterStoryboard,
    V3RevisionRef,
    V3ValidationReceipt,
    deterministic_digest,
)


class V3FormulaReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    compiler_family: str = Field(min_length=1)
    ordered_required_stages: tuple[str, ...] = Field(min_length=1)
    hook_mapping: tuple[str, ...] = Field(default_factory=tuple)
    body_core_mapping: tuple[str, ...] = Field(default_factory=tuple)
    cta_mapping: tuple[str, ...] = Field(default_factory=tuple)
    production_eligible: bool = False
    display_name: str = ""
    slots: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


class V3EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["ENOUGH_EVIDENCE", "EVIDENCE_SHORTFALL", "UNSAFE_TO_DERIVE"]
    snapshot_id: str = ""
    snapshot_version: int | None = None
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    explanations: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)
    score_by_fact: dict[str, float] = Field(default_factory=dict)


class V3ExclusionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    details: str = ""
    dimensions: dict[str, str] = Field(default_factory=dict)


class V3CandidateDurationStatus(BaseModel):
    """Per-duration outcome for ONE semantic candidate.

    Semantic-duration decoupling: a BLOCKED duration is an independent duration
    outcome, never a semantic exclusion.  A candidate can be semantically VALID
    while one duration is BLOCKED and the others are READY.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seconds: int = Field(gt=0)
    status: Literal["READY", "REVIEW_REQUIRED", "BLOCKED"]
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)


class V3DurationCapacity(BaseModel):
    """Truthful per-duration capacity over the evaluated candidate set.

    Reports independent counts (not only a boolean) so an 8s block is visible as
    ``blocked_capacity`` without collapsing the semantic supply.  ``ready`` is the
    strict FAST54_<n>S_READY authority: full requested capacity, no block, no
    pending review — mirroring legacy ``fast54_ready`` but scoped to one duration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seconds: int = Field(gt=0)
    valid_capacity: int = Field(default=0, ge=0)
    blocked_capacity: int = Field(default=0, ge=0)
    review_required_capacity: int = Field(default=0, ge=0)
    ready: bool = False
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)


class V3CandidateCombination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    recipe: V3RevisionRef
    angle: V3RevisionRef
    storyline_family: V3RevisionRef
    hook: V3RevisionRef
    body_core: V3RevisionRef
    cta: V3RevisionRef
    status: Literal["VALID", "REVIEW_REQUIRED", "BLOCKED", "EXCLUDED"]
    master: V3MasterStoryboard | None = None
    projections: tuple[V3DurationProjection, ...] = Field(default_factory=tuple)
    # Per-duration outcomes attached to a semantically-committed candidate.  A
    # duration BLOCK lives here and never forces ``status`` to BLOCKED/EXCLUDED.
    duration_statuses: tuple[V3CandidateDurationStatus, ...] = Field(default_factory=tuple)
    validation_receipts: tuple[V3ValidationReceipt, ...] = Field(default_factory=tuple)
    exclusion_receipts: tuple[V3ExclusionReceipt, ...] = Field(default_factory=tuple)


class V3CandidatePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_capacity: int = Field(ge=0)
    theoretical_capacity: int = Field(ge=0)
    structurally_valid_capacity: int = Field(ge=0)
    evidence_valid_capacity: int = Field(ge=0)
    duration_valid_capacity: int = Field(ge=0)
    evaluated_count: int = Field(ge=0)
    bounded: bool = True
    seed: str = Field(min_length=1)
    cursor: str | None = None
    next_cursor: str | None = None
    candidates: tuple[V3CandidateCombination, ...] = Field(default_factory=tuple)
    exclusions: tuple[V3ExclusionReceipt, ...] = Field(default_factory=tuple)
    # ``theoretical_capacity`` is retained as a compatibility alias for the
    # raw Cartesian count.  Semantic capacity is the only FAST54 eligibility
    # signal; duration and review counts remain separately observable.
    theoretical_raw_capacity: int = Field(default=0, ge=0)
    semantic_valid_capacity: int = Field(default=0, ge=0)
    weak_review_required_capacity: int = Field(default=0, ge=0)
    # LEGACY authority — preserved exactly: semantic AND every duration valid AND
    # no pending review.  New consumers should read the explicit authorities below.
    fast54_ready: bool = False
    # New decoupled authorities (additive; never redefine ``fast54_ready``).
    fast54_semantic_ready: bool = False
    fast54_8s_ready: bool = False
    fast54_16s_ready: bool = False
    fast54_24s_ready: bool = False
    duration_capacities: tuple[V3DurationCapacity, ...] = Field(default_factory=tuple)


class V3CapacitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recipe: V3RevisionRef
    requested_capacity: int = Field(ge=0)
    theoretical_capacity: int = Field(ge=0)
    structurally_valid_capacity: int = Field(ge=0)
    evidence_valid_capacity: int = Field(ge=0)
    duration_valid_capacity: int = Field(ge=0)
    reviewable_capacity: int = Field(ge=0)
    approved_capacity: int = 0
    executable_capacity: int = 0
    duration_counts: dict[str, int] = Field(default_factory=dict)
    pressure: dict[str, dict[str, int]] = Field(default_factory=dict)
    shortfall_codes: tuple[str, ...] = Field(default_factory=tuple)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)
    evaluated_count: int = Field(ge=0)
    bounded: bool = True
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    theoretical_raw_capacity: int = Field(default=0, ge=0)
    semantic_valid_capacity: int = Field(default=0, ge=0)
    weak_review_required_capacity: int = Field(default=0, ge=0)
    # LEGACY authority — preserved exactly (semantic AND all durations AND no review).
    fast54_ready: bool = False
    # New decoupled authorities (additive; never redefine ``fast54_ready``).
    fast54_semantic_ready: bool = False
    fast54_8s_ready: bool = False
    fast54_16s_ready: bool = False
    fast54_24s_ready: bool = False
    duration_capacities: tuple[V3DurationCapacity, ...] = Field(default_factory=tuple)


class V3CompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    production_eligible: bool = False
    master: V3MasterStoryboard | None = None
    issues: tuple[str, ...] = Field(default_factory=tuple)
    details: tuple[str, ...] = Field(default_factory=tuple)
    receipts: tuple[V3ValidationReceipt, ...] = Field(default_factory=tuple)


class V3LandbankPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    total_returned: int = Field(ge=0)
    limit: int = Field(gt=0)
    offset: int = Field(ge=0)
    next_offset: int | None = None
    read_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_items(cls, items: list[dict[str, Any]], *, limit: int, offset: int, has_more: bool) -> "V3LandbankPage":
        return cls(
            items=tuple(items),
            total_returned=len(items),
            limit=limit,
            offset=offset,
            next_offset=offset + len(items) if has_more else None,
            read_digest=deterministic_digest(items),
        )


__all__ = [
    "V3FormulaReadModel",
    "V3EvidenceSelection",
    "V3ExclusionReceipt",
    "V3CandidateDurationStatus",
    "V3DurationCapacity",
    "V3CandidateCombination",
    "V3CandidatePage",
    "V3CapacitySnapshot",
    "V3CompileResult",
    "V3LandbankPage",
]
