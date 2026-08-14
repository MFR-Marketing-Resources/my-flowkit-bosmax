"""Versioned scene choreography v2 production contract.

This is the production authority for physical product interaction. Atomic
``allowed_actions`` strings are read-compatibility / audit labels only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CHOREOGRAPHY_SCHEMA_VERSION = "scene_choreography_v2"

HandRole = Literal[
    "SUPPORT_HAND",
    "ACTIVE_HAND",
    "BOTH_HANDS",
    "NONE",
    "TABLE_REST",
]
Custody = Literal[
    "SUPPORT_HAND",
    "ACTIVE_HAND",
    "BOTH_HANDS",
    "TABLE",
    "SURFACE",
    "WORN",
    "ATTACHED",
    "FRAME_STATIC",
    "RECEIVER",
    "BAG",
    "SHELF",
]
CutBoundary = Literal["NONE", "OUTGOING", "REESTABLISH"]
Classification = Literal["P0_REWRITE", "P1_REWRITE", "P2_STATIC", "BLOCK"]
ChoreographyFamily = Literal[
    "APPLY_CONTACT",
    "MATERIAL_TRANSFER",
    "SPRAY",
    "FOOD_COOK",
    "OPEN_CLOSE",
    "PROP_TRANSFER",
    "STATIC_LOCK",
    "DEVICE_CONTROL",
    "MANIPULATION",
    "HERBAL_OIL",
    "ROLL_ON",
    "BROLL_MATCH_CUT",
]


class EntityState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1)
    location: str = Field(min_length=1)
    custody: Custody
    visible: bool
    physical_state: str = Field(min_length=1)


class ChoreographyStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(ge=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    actor_role: Literal["PRESENTER", "HANDS", "PRODUCT", "ENVIRONMENT"]
    support_hand: HandRole
    active_hand: HandRole
    action_instruction: str = Field(min_length=1)
    initial_states: list[EntityState] = Field(min_length=1)
    resulting_states: list[EntityState] = Field(min_length=1)
    visibility: str = Field(min_length=1)
    camera_cut_boundary: CutBoundary = "NONE"
    continuity_rules: list[str] = Field(default_factory=list)
    is_final_lock: bool = False
    # Atomic library action indexes this step physically implements.
    # Continuity-only / final-lock steps may leave this empty.
    source_action_indexes: list[int] = Field(default_factory=list)
    # Stable machine signature of the positive physical transition.
    transition_signature: str = Field(default="", min_length=0)


class ChoreographyVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choreography_id: str = Field(min_length=1)
    schema_version: str = CHOREOGRAPHY_SCHEMA_VERSION
    strategy_id: str = Field(min_length=1)
    classification: Classification
    family: ChoreographyFamily
    scene_duration_s: float = Field(gt=0)
    scene_strategy_label: str = Field(min_length=1)
    scene_context: str = Field(min_length=1)
    camera_route: str = Field(min_length=1)
    intent_label: str = Field(min_length=1)
    compatible_contexts: list[str] = Field(min_length=1)
    compatible_camera_routes: list[str] = Field(min_length=1)
    steps: list[ChoreographyStep] = Field(min_length=1)
    final_state_lock: str = Field(min_length=1)
    production_eligible: bool = True


class ChoreographyValidationError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        strategy_id: str | None = None,
        choreography_id: str | None = None,
        step: int | None = None,
        entity: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.strategy_id = strategy_id
        self.choreography_id = choreography_id
        self.step = step
        self.entity = entity
        self.details = details or {}

    def __str__(self) -> str:
        parts = [self.code]
        if self.strategy_id:
            parts.append(f"strategy={self.strategy_id}")
        if self.choreography_id:
            parts.append(f"choreography={self.choreography_id}")
        if self.step is not None:
            parts.append(f"step={self.step}")
        if self.entity:
            parts.append(f"entity={self.entity}")
        if self.details:
            parts.append(f"details={self.details}")
        return " ".join(parts)


PLACEHOLDER_STATE_MARKERS: tuple[str, ...] = (
    "governed initial product state",
    "governed resulting product state",
)
