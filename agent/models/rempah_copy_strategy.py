"""Strict P3B rempah/seasoning copy preview contract."""
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RempahDurationSeconds(IntEnum):
    SECONDS_8 = 8
    SECONDS_10 = 10
    SECONDS_16 = 16


class RempahCopyStrategyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: Literal["food_cooking"]
    product_type_group: Literal["rempah_seasoning"]
    scene_strategy_id: Literal["SPICE_SEASONING"]
    copy_strategy_id: str
    duration_seconds: RempahDurationSeconds
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str
    scene_action: str
    blocked_reasons: list[str] = Field(default_factory=list)
