"""Strict P3A lip-colour copy preview contract."""
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LipColorDurationSeconds(IntEnum):
    SECONDS_8 = 8
    SECONDS_10 = 10
    SECONDS_16 = 16


class LipColorCopyStrategyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: Literal["beauty_makeup"]
    product_type_group: Literal["lipstick_lip_tint"]
    scene_strategy_id: Literal["LIP_COLOR"]
    copy_strategy_id: str
    duration_seconds: LipColorDurationSeconds
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str
    scene_action: str
    blocked_reasons: list[str] = Field(default_factory=list)
