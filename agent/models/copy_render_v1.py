"""Pydantic contracts for the On-Demand Copy Renderer (Round 2).

SYSTEM OWNS STRUCTURE; AI ONLY STITCHES.

The provider receives up to 5 system-selected recipes as ephemeral slots (S1..S5)
plus the formula stage keys, and returns ordered stage text per slot. It never
sees or authors DB ids, never chooses the benefit/angle/hook/body/cta/formula, and
never computes duration/WPS. `extra="forbid"` + per-string bounds keep the
worst-case 5-script envelope inside the structured-output transport ceiling; the
EXACT slot set and per-formula stage keys/order are enforced in the service (they
vary by request), not hard-coded here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# --------------------------------------------------------------------------
# System-owned constants (never sent to / authored by the AI)
# --------------------------------------------------------------------------
SUGGESTION_BATCH_SIZE = 5           # candidates per Generate/Regenerate action
MAX_FORMULA_STAGES = 6              # PAS=4 … PASTOR=6; bounds the envelope
DEFAULT_FORMULA_ID = "PAS"
DEFAULT_TARGET_LANGUAGE = "BM_MS"
DEFAULT_WPS_MODE = "SWEET"
SUPPORTED_LANES = ("HYBRID", "FACELESS")

# Lineage versions — bump to intentionally invalidate cache + stale sessions.
RENDERER_PROMPT_VERSION = "copy-render-prompt-v1"
SAFETY_POLICY_VERSION = "copy-render-safety-v1"

# Provenance authority label for the request-scoped rendered execution copy.
BENEFIT_COPY_RENDER_AUTHORITY = "BENEFIT_COPY_RENDER_V1"
BENEFIT_COPY_RENDER_SOURCE = "benefit_copy_render_v1"

# Bounded authored strings (storage/transport bounds; the real per-script limit is
# the deterministic word-budget check). Worst case 5 slots x MAX_FORMULA_STAGES x
# STAGE_TEXT_MAX_CHARS must fit OPENAI_COMPATIBLE_JSON_MAX_TOKENS=4096 — proven by
# tests/unit/test_copy_render_cache/contract.
SLOT_MAX_CHARS = 8
STAGE_KEY_MAX_CHARS = 48
STAGE_TEXT_MAX_CHARS = 360

_Slot = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SLOT_MAX_CHARS)]
_StageKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=STAGE_KEY_MAX_CHARS)]
_StageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=STAGE_TEXT_MAX_CHARS)]

Lane = Literal["HYBRID", "FACELESS"]


# --------------------------------------------------------------------------
# STRICT provider-output contract (AI stitches words only)
# --------------------------------------------------------------------------
class CopyRenderStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_key: _StageKey
    text: _StageText


class CopyRenderSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: _Slot
    stages: list[CopyRenderStage] = Field(min_length=1, max_length=MAX_FORMULA_STAGES)


class CopyRenderEnvelope(BaseModel):
    """Full stitch-call output: one suggestion per supplied slot (≤5)."""

    model_config = ConfigDict(extra="forbid")
    suggestions: list[CopyRenderSuggestion] = Field(min_length=1, max_length=SUGGESTION_BATCH_SIZE)


# --------------------------------------------------------------------------
# API request bodies
# --------------------------------------------------------------------------
class CreateCopyRenderSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1)
    benefit_id: str = Field(min_length=1)
    lane: Lane
    target_count: int = Field(ge=1, le=200)
    duration_seconds: int = Field(ge=1, le=600)
    target_language: str = Field(default=DEFAULT_TARGET_LANGUAGE, min_length=1, max_length=16)
    formula_id: str | None = Field(default=None, max_length=40)


class GenerateSuggestionsRequest(BaseModel):
    """Generate or Regenerate. `request_id` makes the paid action idempotent."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=64)


class UpdateTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_count: int = Field(ge=1, le=200)
