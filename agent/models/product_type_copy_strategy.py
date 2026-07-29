"""Strict P4 generalized product-type copy preview and report contracts."""
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductTypeCopyDurationSeconds(IntEnum):
    SECONDS_8 = 8
    SECONDS_10 = 10
    SECONDS_16 = 16


class ProductTypeCopyStrategyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    copy_strategy_id: str
    duration_seconds: ProductTypeCopyDurationSeconds
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str
    scene_action: str
    source_strategy: Literal["PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"]
    blocked_reasons: list[str] = Field(default_factory=list)


class ProductTypeCopyReportProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    blocked_reasons: list[str] = Field(default_factory=list)


class ProductTypeCopyReportGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: str
    product_type_group: str
    scene_strategy_id: str
    count: int = Field(ge=0)


class ProductTypeCopyEligibleReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_products: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    eligible_by_product_type: list[ProductTypeCopyReportGroup]
    blocked_by_reason: dict[str, int]
    missing_copy_strategy_groups: list[ProductTypeCopyReportGroup]
    sample_eligible: list[ProductTypeCopyReportProduct]
    sample_blocked: list[ProductTypeCopyReportProduct]
