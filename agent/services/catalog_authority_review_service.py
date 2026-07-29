"""Bounded structured-AI review for unresolved P5.8 catalog signatures.

The provider is advisory only. Every returned decision remains subject to an
independent deterministic review before it can enter Product Truth authority.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.services import ai_copy_provider_adapter


P58_MISSION_ID = "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
P58_MAX_PROVIDER_CALLS = 20
P58_MIN_BATCH_SIZE = 10
P58_MAX_BATCH_SIZE = 20


class CatalogAuthorityReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    source_category: str | None = None
    source_subcategory: str | None = None
    source_product_type: str | None = None
    product_names: list[str] = Field(min_length=1, max_length=20)
    approved_descriptions: list[str] = Field(default_factory=list, max_length=20)
    approved_usage: list[str] = Field(default_factory=list, max_length=20)
    current_product_type_group: str
    current_scene_strategy_id: str


class CatalogAuthorityReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    disposition: Literal[
        "MAP_EXISTING",
        "PROPOSE_NEW_TYPE",
        "INSUFFICIENT_PRODUCT_TRUTH",
        "SOURCE_CONFLICT",
    ]
    proposed_cluster: str | None = None
    proposed_product_type_group: str | None = None
    proposed_scene_strategy_id: str | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    evidence_basis: list[str] = Field(min_length=1, max_length=6)
    exact_reason: str = Field(min_length=8, max_length=500)
    safety_flags: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_mapping_shape(self) -> "CatalogAuthorityReviewDecision":
        mapped = self.disposition in {"MAP_EXISTING", "PROPOSE_NEW_TYPE"}
        proposed = (
            self.proposed_cluster,
            self.proposed_product_type_group,
            self.proposed_scene_strategy_id,
        )
        if mapped and not all(proposed):
            raise ValueError("MAPPED_DECISION_REQUIRES_COMPLETE_PROPOSAL")
        if not mapped and any(proposed):
            raise ValueError("BLOCKED_DECISION_MUST_NOT_PROPOSE_MAPPING")
        return self


class CatalogAuthorityReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: Literal[
        "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
    ]
    decisions: list[CatalogAuthorityReviewDecision] = Field(
        min_length=P58_MIN_BATCH_SIZE,
        max_length=P58_MAX_BATCH_SIZE,
    )

    @model_validator(mode="after")
    def validate_unique_signatures(self) -> "CatalogAuthorityReviewResponse":
        signature_ids = [item.signature_id for item in self.decisions]
        if len(signature_ids) != len(set(signature_ids)):
            raise ValueError("DUPLICATE_SIGNATURE_DECISION")
        return self


class CatalogAuthorityReviewLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: Literal[
        "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
    ]
    batch_signature_ids: list[str]
    request_count_before: int = Field(ge=0)
    request_count_after: int = Field(ge=1, le=P58_MAX_PROVIDER_CALLS)
    call_id: int = Field(ge=1)
    provider_id: str
    model: str
    response_status: Literal["SUCCEEDED"]
    json_parse_status: Literal["VALID"]
    decisions: list[CatalogAuthorityReviewDecision]


class CatalogAuthorityReviewAttempt(BaseModel):
    """Secret-free receipt for one bounded provider request."""

    model_config = ConfigDict(extra="forbid")

    call_number: int = Field(ge=1, le=P58_MAX_PROVIDER_CALLS)
    batch_signature_count: int = Field(
        ge=P58_MIN_BATCH_SIZE,
        le=P58_MAX_BATCH_SIZE,
    )
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    status: Literal["SUCCEEDED_VALID_RESPONSE", "FAILED_NO_VALID_RESPONSE"]
    response_status: Literal[
        "SUCCEEDED",
        "TIMEOUT",
        "TRANSPORT_ERROR",
        "INVALID_SCHEMA",
    ]
    finish_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_seconds: float = Field(gt=0)
    valid_decision_count: int = Field(ge=0)
    error_type: str | None = None
    raw_provider_output_retained: Literal[False] = False

    @model_validator(mode="after")
    def validate_attempt_outcome(self) -> "CatalogAuthorityReviewAttempt":
        if self.status == "SUCCEEDED_VALID_RESPONSE":
            if self.response_status != "SUCCEEDED":
                raise ValueError("P58_SUCCEEDED_ATTEMPT_REQUIRES_SUCCESS_STATUS")
            if self.valid_decision_count != self.batch_signature_count:
                raise ValueError("P58_SUCCEEDED_ATTEMPT_REQUIRES_ALL_DECISIONS")
            if self.error_type is not None:
                raise ValueError("P58_SUCCEEDED_ATTEMPT_CANNOT_HAVE_ERROR")
        elif self.valid_decision_count != 0:
            raise ValueError("P58_FAILED_ATTEMPT_CANNOT_HAVE_VALID_DECISIONS")
        return self


class CatalogAuthorityMissionReviewLedger(BaseModel):
    """Sanitized mission-level DeepSeek accounting and review disposition."""

    model_config = ConfigDict(extra="forbid")

    mission_id: Literal[
        "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
    ]
    configured_provider_id: str = Field(min_length=1)
    configured_model: str = Field(min_length=1)
    max_provider_calls: Literal[20] = P58_MAX_PROVIDER_CALLS
    request_count: int = Field(ge=0, le=P58_MAX_PROVIDER_CALLS)
    valid_provider_decision_count: int = Field(ge=0)
    accepted_provider_decision_count: int = Field(ge=0)
    rejected_provider_decision_count: int = Field(ge=0)
    blocked_provider_decision_count: int = Field(ge=0)
    attempts: list[CatalogAuthorityReviewAttempt] = Field(
        default_factory=list,
        max_length=P58_MAX_PROVIDER_CALLS,
    )
    raw_provider_output_retained: Literal[False] = False
    canonical_mutation_from_provider_output: Literal[False] = False

    @model_validator(mode="after")
    def validate_mission_accounting(
        self,
    ) -> "CatalogAuthorityMissionReviewLedger":
        if self.request_count != len(self.attempts):
            raise ValueError("P58_REVIEW_REQUEST_COUNT_MISMATCH")
        call_numbers = [attempt.call_number for attempt in self.attempts]
        if call_numbers != list(range(1, self.request_count + 1)):
            raise ValueError("P58_REVIEW_CALL_NUMBERS_NOT_CONTIGUOUS")
        if any(
            attempt.provider_id != self.configured_provider_id
            or attempt.model != self.configured_model
            for attempt in self.attempts
        ):
            raise ValueError("P58_REVIEW_PROVIDER_CONFIGURATION_MISMATCH")
        valid_count = sum(
            attempt.valid_decision_count for attempt in self.attempts
        )
        if valid_count != self.valid_provider_decision_count:
            raise ValueError("P58_REVIEW_VALID_DECISION_COUNT_MISMATCH")
        disposition_total = (
            self.accepted_provider_decision_count
            + self.rejected_provider_decision_count
            + self.blocked_provider_decision_count
        )
        if disposition_total != valid_count:
            raise ValueError("P58_REVIEW_DISPOSITION_COUNT_MISMATCH")
        return self


def _system_prompt() -> str:
    return (
        "You are an advisory product-taxonomy reviewer for BOSMAX P5.8. "
        "Return exactly one strict JSON object matching the supplied schema. "
        "Use only supplied source taxonomy and approved Product Truth evidence. "
        "Do not treat a broad category or marketing title alone as authority. "
        "Do not invent health, performance, savings, or efficacy claims. "
        "When evidence is mixed or insufficient, fail closed with "
        "INSUFFICIENT_PRODUCT_TRUTH or SOURCE_CONFLICT. "
        "Never propose GENERIC_FALLBACK or unknown_product_type as a covered "
        "mapping. Output one decision for every supplied signature and no extras."
    )


def _user_prompt(evidence: list[CatalogAuthorityReviewEvidence]) -> str:
    response_schema = {
        "mission_id": P58_MISSION_ID,
        "decisions": [
            {
                "signature_id": "16 lowercase hex characters",
                "disposition": (
                    "MAP_EXISTING | PROPOSE_NEW_TYPE | "
                    "INSUFFICIENT_PRODUCT_TRUTH | SOURCE_CONFLICT"
                ),
                "proposed_cluster": "snake_case string or null",
                "proposed_product_type_group": "snake_case string or null",
                "proposed_scene_strategy_id": "UPPER_SNAKE_CASE string or null",
                "confidence": "HIGH | MEDIUM | LOW",
                "evidence_basis": ["concise supplied-evidence references"],
                "exact_reason": "concise evidence-bound rationale",
                "safety_flags": ["optional concise flags"],
            }
        ],
    }
    payload = {
        "mission_id": P58_MISSION_ID,
        "response_schema": response_schema,
        "unresolved_signatures": [
            item.model_dump(mode="json") for item in evidence
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def review_catalog_authority_batch(
    evidence: list[CatalogAuthorityReviewEvidence],
) -> CatalogAuthorityReviewLedger:
    """Run one billable advisory call behind strict size and budget gates."""

    if not P58_MIN_BATCH_SIZE <= len(evidence) <= P58_MAX_BATCH_SIZE:
        raise ValueError("P58_REVIEW_BATCH_REQUIRES_10_TO_20_SIGNATURES")
    signature_ids = [item.signature_id for item in evidence]
    if len(signature_ids) != len(set(signature_ids)):
        raise ValueError("P58_REVIEW_BATCH_SIGNATURES_MUST_BE_UNIQUE")

    receipt_before = ai_copy_provider_adapter.provider_call_receipt()
    count_before = int(receipt_before["request_count_since_process_start"])
    if count_before >= P58_MAX_PROVIDER_CALLS:
        raise RuntimeError("P58_PROVIDER_CALL_BUDGET_EXHAUSTED")

    raw_response = ai_copy_provider_adapter.complete_json(
        _system_prompt(),
        _user_prompt(evidence),
    )
    reviewed = CatalogAuthorityReviewResponse.model_validate(raw_response)
    returned_ids = {item.signature_id for item in reviewed.decisions}
    if returned_ids != set(signature_ids):
        raise ValueError("P58_PROVIDER_SIGNATURE_SET_MISMATCH")

    receipt_after = ai_copy_provider_adapter.provider_call_receipt()
    count_after = int(receipt_after["request_count_since_process_start"])
    if count_after != count_before + 1 or count_after > P58_MAX_PROVIDER_CALLS:
        raise RuntimeError("P58_PROVIDER_CALL_RECEIPT_MISMATCH")
    last_call = receipt_after.get("last_call")
    if not isinstance(last_call, dict):
        raise RuntimeError("P58_PROVIDER_CALL_RECEIPT_MISSING")
    if (
        last_call.get("response_status") != "SUCCEEDED"
        or last_call.get("json_parse_status") != "VALID"
    ):
        raise RuntimeError("P58_PROVIDER_CALL_NOT_VALID")

    return CatalogAuthorityReviewLedger(
        mission_id=P58_MISSION_ID,
        batch_signature_ids=signature_ids,
        request_count_before=count_before,
        request_count_after=count_after,
        call_id=int(last_call["call_id"]),
        provider_id=str(last_call["provider_id"]),
        model=str(last_call["model"]),
        response_status="SUCCEEDED",
        json_parse_status="VALID",
        decisions=reviewed.decisions,
    )


__all__ = [
    "CatalogAuthorityReviewDecision",
    "CatalogAuthorityReviewEvidence",
    "CatalogAuthorityReviewLedger",
    "CatalogAuthorityReviewAttempt",
    "CatalogAuthorityMissionReviewLedger",
    "P58_MAX_PROVIDER_CALLS",
    "P58_MISSION_ID",
    "review_catalog_authority_batch",
]
