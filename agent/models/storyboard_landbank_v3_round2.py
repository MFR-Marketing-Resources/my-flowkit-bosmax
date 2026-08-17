"""Strict Round 2 envelopes for the V3 Copy Register and AI assistant.

These models are deliberately separate from the V2 copy authority and from the
Round 1 deterministic records.  Provider output is accepted only through the
``V3AIProviderEnvelope`` contract; approval and run receipts are immutable
provenance envelopes, never executable V2/P6 payloads.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.models.storyboard_landbank_v3 import (
    V3BridgeContract,
    V3RevisionRef,
    V3SemanticClass,
    deterministic_digest,
    digest_text,
    normalized_text,
)


_SHA256 = r"^[0-9a-f]{64}$"
AssistantMode = Literal["CREATE", "EXPAND", "FILL_CAPACITY"]
ProviderMode = Literal["LIVE_TEXT_ASSIST", "FAKE_TEST"]
ApprovalScope = Literal["INDIVIDUAL", "BATCH"]
ApprovalTarget = Literal["MASTER_STORYBOARD", "DURATION_PROJECTION"]


class V3ProviderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane: Literal["text_assist"] = "text_assist"
    status: str = Field(min_length=1)
    configured: bool = False
    provider_id: str | None = None
    model_id: str | None = None
    execution_enabled: bool = False
    provider_calls: int = Field(default=0, ge=0)
    fake_provider_allowed: bool = False


class V3AssistantGap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_class: Literal["HOOK", "BODY_CORE", "CTA"]
    current_count: int = Field(ge=0, le=500)
    target_count: int = Field(ge=0, le=500)
    gap_count: int = Field(ge=0, le=24)
    reason: str = Field(min_length=1, max_length=240)


class V3AssistantPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3.2"] = "3.2"
    plan_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    recipe: V3RevisionRef
    # The plan is a durable authoring contract, not only a count calculation.
    # Keep the locked route and truth snapshot beside the run so a reviewer can
    # reconstruct what the assistant was allowed to see and produce.
    objective: dict[str, Any] = Field(default_factory=dict)
    formula: dict[str, Any] = Field(default_factory=dict)
    angle: V3RevisionRef | None = None
    storyline_family: V3RevisionRef | None = None
    product_truth: dict[str, Any] = Field(default_factory=dict)
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    evidence_digest: str = Field(default="0" * 64, pattern=_SHA256)
    language_profile: str = Field(default="Malay", min_length=1)
    current_capacity: dict[str, int] = Field(default_factory=dict)
    mode: AssistantMode
    target_counts: dict[str, int] = Field(default_factory=dict)
    gaps: tuple[V3AssistantGap, ...] = Field(default_factory=tuple)
    target_durations_seconds: tuple[int, ...] = Field(min_length=1, max_length=3)
    wps_mode: Literal["SAFE", "SWEET"]
    provider: V3ProviderSummary
    prompt_version: str = Field(min_length=1)
    prompt_digest: str = Field(pattern=_SHA256)
    estimated_provider_calls: int = Field(ge=0, le=3)
    estimated_output_tokens: int = Field(ge=0, le=20000)
    estimated_credit_spend: int = Field(default=0, ge=0)
    max_proposals: int = Field(ge=1, le=24)
    max_provider_calls: int = Field(default=1, ge=0, le=1)
    max_output_tokens: int = Field(default=20000, ge=1, le=20000)
    max_cost: int = Field(default=0, ge=0)
    cost_status: Literal["NOT_REPORTED", "WITHIN_BUDGET", "BUDGET_EXCEEDED"] = "NOT_REPORTED"
    explicit_execute_required: Literal[True] = True
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3AICopySegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_stage_key: str = Field(min_length=1, max_length=80)
    authored_text: str = Field(min_length=8, max_length=1200)
    entry_key: str = Field(min_length=1, max_length=120)
    exit_key: str = Field(min_length=1, max_length=120)
    continuity_requirements: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    claim_bearing: bool = True

    @field_validator("authored_text", "entry_key", "exit_key")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = normalized_text(value)
        if not value:
            raise ValueError("V3_AI_TEXT_REQUIRED")
        return value


class V3AICopyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(min_length=1, max_length=120)
    semantic_class: Literal["HOOK", "BODY_CORE", "CTA"]
    angle_definition: str = Field(min_length=8, max_length=500)
    storyline_definition: str = Field(min_length=8, max_length=500)
    segments: tuple[V3AICopySegment, ...] = Field(min_length=1, max_length=8)
    rationale: str = Field(min_length=8, max_length=800)
    risk_notes: tuple[str, ...] = Field(default_factory=tuple, max_length=12)


class V3AIProviderEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["v3-copy-assistant-1"] = "v3-copy-assistant-1"
    proposals: tuple[V3AICopyProposal, ...] = Field(min_length=1, max_length=24)


class V3AIProviderReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ProviderMode
    lane: Literal["text_assist"] = "text_assist"
    provider_id: str | None = None
    model_id: str | None = None
    call_id: int | None = Field(default=None, ge=0)
    response_status: str = Field(min_length=1)
    json_parse_status: str = Field(min_length=1)
    usage: dict[str, int | float] = Field(default_factory=dict)
    prompt_digest: str = Field(pattern=_SHA256)
    output_digest: str = Field(pattern=_SHA256)


class V3QualitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hard_pass: bool
    formula_valid: bool
    evidence_valid: bool
    bridge_valid: bool
    claim_safety_valid: bool
    truth_current: bool
    wps_valid: bool
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)
    novelty_signal: Literal["NOVEL", "NEAR_DUPLICATE", "EXACT_DUPLICATE", "UNKNOWN"]
    novelty_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)


class V3AssistantRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    recipe: V3RevisionRef
    mode: AssistantMode
    status: Literal["PLANNED", "EXECUTED", "FAILED"]
    provider: V3AIProviderReceipt | None = None
    proposal_ids: tuple[str, ...] = Field(default_factory=tuple)
    component_refs: tuple[V3RevisionRef, ...] = Field(default_factory=tuple)
    master: V3RevisionRef | None = None
    projections: tuple[V3RevisionRef, ...] = Field(default_factory=tuple)
    output_digest: str | None = Field(default=None, pattern=_SHA256)
    provider_calls: int = Field(default=0, ge=0)
    credit_spend: int = Field(default=0, ge=0)
    token_usage: dict[str, int | float] = Field(default_factory=dict)
    quality: V3QualitySignal | None = None
    error_code: str | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3ApprovalChecklist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_reviewed: bool = False
    product_truth_reviewed: bool = False
    formula_reviewed: bool = False
    evidence_reviewed: bool = False
    bridge_reviewed: bool = False
    safety_reviewed: bool = False
    duration_reviewed: bool = False

    def all_passed(self) -> bool:
        return all(self.model_dump(mode="json").values())


class V3HumanApprovalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["v3-human-approval-receipt-1"] = "v3-human-approval-receipt-1"
    receipt_id: str = Field(min_length=1)
    approval_scope: ApprovalScope
    target_type: ApprovalTarget
    target_id: str = Field(min_length=1)
    target_revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    master_ref: V3RevisionRef
    projection_refs: tuple[V3RevisionRef, ...] = Field(default_factory=tuple, max_length=3)
    batch_target_refs: tuple[V3RevisionRef, ...] = Field(default_factory=tuple, max_length=24)
    exact_content_fingerprint: str = Field(pattern=_SHA256)
    projection_fingerprints: tuple[str, ...] = Field(default_factory=tuple, max_length=3)
    product_truth_snapshot_id: str = Field(min_length=1)
    product_truth_snapshot_version: int = Field(ge=1)
    product_truth_snapshot_digest: str = Field(pattern=_SHA256)
    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    evidence_digest: str = Field(pattern=_SHA256)
    wps_authority_digests: tuple[str, ...] = Field(default_factory=tuple, max_length=3)
    checklist: V3ApprovalChecklist
    approved_by: str = Field(min_length=1)
    rationale: str = Field(min_length=8, max_length=1200)
    automatic_approval: Literal[False] = False
    batch_id: str | None = None
    receipt_digest: str = Field(pattern=_SHA256)
    created_at: str = Field(min_length=1)


class V3PromptPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_digest: str = Field(pattern=_SHA256)
    system_instructions: str = Field(min_length=1)
    untrusted_truth_json: str = Field(min_length=2)
    requested_output_contract: dict[str, Any]
    provider_calls: int = 0
    credit_spend: int = 0


def approval_receipt_digest(receipt: V3HumanApprovalReceipt) -> str:
    payload = receipt.model_dump(mode="json")
    payload.pop("receipt_digest", None)
    return deterministic_digest(payload)


def proposal_text_digest(proposal: V3AICopyProposal) -> str:
    return deterministic_digest({
        "semantic_class": proposal.semantic_class,
        "segments": [
            {
                **segment.model_dump(mode="json"),
                "text_digest": digest_text(segment.authored_text),
            }
            for segment in proposal.segments
        ],
    })


__all__ = [
    "AssistantMode",
    "ProviderMode",
    "V3ProviderSummary",
    "V3AssistantGap",
    "V3AssistantPlan",
    "V3AICopySegment",
    "V3AICopyProposal",
    "V3AIProviderEnvelope",
    "V3AIProviderReceipt",
    "V3QualitySignal",
    "V3AssistantRunReceipt",
    "V3ApprovalChecklist",
    "V3HumanApprovalReceipt",
    "V3PromptPreview",
    "approval_receipt_digest",
    "proposal_text_digest",
]
