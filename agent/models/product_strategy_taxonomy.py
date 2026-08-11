"""Official product-strategy taxonomy contracts.

The taxonomy is stored outside Product Truth. A row is consumable only after
its deterministic or manual review gate resolves to VERIFIED.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProductStrategyCoverageStatus = Literal["COVERED", "PARTIAL", "FALLBACK_ONLY"]
ProductStrategyReviewStatus = Literal["VERIFIED", "REVIEW_REQUIRED"]
ProductStrategyConsumerStatus = Literal["READY", "BLOCKED_REVIEW_REQUIRED"]
ProductStrategyAuthoritySource = Literal["AUTO_DERIVED", "MANUAL_OVERRIDE"]
ProductStrategyMaterializationStatus = Literal[
    "PREVIEW",
    "PLACEHOLDER",
    "MATERIALIZED",
]
ProductStrategyRegistryStatus = Literal["ACTIVE", "REVIEW_REQUIRED"]
ProductStrategyRegistryAuthoritySource = Literal[
    "SYSTEM_SEED",
    "MANUAL_REGISTRATION",
]


class ProductStrategyTaxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    taxonomy_version: str
    product_fingerprint: str
    cluster: str
    product_type_group: str
    matched_scene_strategy_id: str
    scene_coverage_status: ProductStrategyCoverageStatus
    fallback_used: bool
    specific_strategy: bool
    classification_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    review_status: ProductStrategyReviewStatus
    consumer_status: ProductStrategyConsumerStatus
    authority_source: ProductStrategyAuthoritySource
    materialization_status: ProductStrategyMaterializationStatus
    review_reasons: list[str] = Field(default_factory=list)
    reviewer_id: str | None = None
    reviewer_note: str | None = None
    derived_at: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_stale: bool = False

    @model_validator(mode="after")
    def validate_consumer_gate(self) -> "ProductStrategyTaxonomy":
        if self.review_status == "VERIFIED":
            if self.authority_source != "MANUAL_OVERRIDE":
                raise ValueError("VERIFIED_TAXONOMY_REQUIRES_MANUAL_OVERRIDE")
            if self.materialization_status == "MATERIALIZED":
                if self.consumer_status != "READY":
                    raise ValueError("VERIFIED_TAXONOMY_MUST_BE_READY")
            elif self.materialization_status == "PREVIEW":
                if self.consumer_status != "BLOCKED_REVIEW_REQUIRED":
                    raise ValueError("PREVIEW_TAXONOMY_MUST_BE_BLOCKED")
            else:
                raise ValueError("VERIFIED_TAXONOMY_MUST_BE_REVIEWED_PREVIEW")
        elif self.consumer_status != "BLOCKED_REVIEW_REQUIRED":
            raise ValueError("UNVERIFIED_TAXONOMY_MUST_BE_BLOCKED")
        if self.materialization_status != "MATERIALIZED" and (
            self.consumer_status == "READY"
        ):
            raise ValueError("UNMATERIALIZED_TAXONOMY_MUST_BE_BLOCKED")
        if (
            self.scene_coverage_status == "FALLBACK_ONLY"
            and not self.fallback_used
        ):
            raise ValueError("FALLBACK_ONLY_REQUIRES_FALLBACK_USED")
        return self


class ProductStrategyTaxonomyBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    limit: int = Field(default=10_000, ge=1, le=10_000)
    confirm_apply: str | None = None


class ProductStrategyTaxonomyBackfillResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    mutation_performed: bool
    product_count: int
    planned_insert_count: int
    planned_update_count: int
    unchanged_count: int
    preserved_manual_override_count: int
    verified_count: int
    review_required_count: int
    coverage_counts: dict[str, int]
    cluster_counts: dict[str, int]
    review_reason_counts: dict[str, int]
    sample_review_required: list[ProductStrategyTaxonomy]
    confirmation_required: str | None = None


class ProductStrategyTaxonomyReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_product_fingerprint: str
    cluster: str
    product_type_group: str
    matched_scene_strategy_id: str
    scene_coverage_status: ProductStrategyCoverageStatus
    review_status: ProductStrategyReviewStatus
    reviewer_id: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)


class ProductStrategyTypeRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: str
    product_type_group: str
    display_name: str
    matched_scene_strategy_id: str
    scene_coverage_status: ProductStrategyCoverageStatus
    registry_status: ProductStrategyRegistryStatus
    auto_classification_enabled: bool
    authority_source: ProductStrategyRegistryAuthoritySource
    reviewer_id: str | None = None
    reviewer_note: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProductStrategyTypeRegistryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductStrategyTypeRegistryEntry]
    clusters: list[str]
    scene_strategy_ids: list[str]


class ProductStrategyTypeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: str
    product_type_group: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    display_name: str = Field(min_length=2, max_length=120)
    matched_scene_strategy_id: str
    scene_coverage_status: ProductStrategyCoverageStatus
    registry_status: ProductStrategyRegistryStatus = "REVIEW_REQUIRED"
    auto_classification_enabled: bool = False
    reviewer_id: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)


class ProductStrategyTypeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=2, max_length=120)
    matched_scene_strategy_id: str
    scene_coverage_status: ProductStrategyCoverageStatus
    registry_status: ProductStrategyRegistryStatus
    auto_classification_enabled: bool = False
    reviewer_id: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)


class ProductStrategyTypeRegistrySeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirm_apply: str | None = None


class ProductStrategyTypeRegistrySeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    mutation_performed: bool
    seed_count: int
    planned_insert_count: int
    planned_update_count: int
    unchanged_count: int
    preserved_manual_registration_count: int
    active_count: int
    review_required_count: int
    confirmation_required: str | None = None
