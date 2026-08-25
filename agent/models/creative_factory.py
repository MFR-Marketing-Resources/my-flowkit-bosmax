"""Pydantic models for the Benefit-Centric Creative Factory (Round 1).

SYSTEM OWNS STRUCTURE; AI AUTHORS WORDS.

These models define two things:

1. The STRICT, BOUNDED provider-output contract that the single STRUCTURE call
   per benefit must satisfy. The provider authors ONLY words (angle text + hook /
   body / CTA seeds). It never supplies ids, status, route/storyline, duration,
   WPS, scene, camera, or avatar. `extra="forbid"` rejects any such control or
   identity key, and the per-string ``max_length`` bounds keep the worst-case
   ``3 angles / 18 hooks / 9 bodies / 9 CTAs`` envelope inside the provider
   transport ceiling (see ``tests/unit/test_creative_factory_provider_contract``).

2. The validated API request bodies for the creative-factory router.

All database identity, lineage, digests, versions, status, timestamps and
provider receipts are assigned by BOSMAX AFTER validation — never by the AI.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# --------------------------------------------------------------------------
# Deterministic atom shape (SYSTEM-owned; never authored by or sent to the AI)
# --------------------------------------------------------------------------
ANGLES_PER_BENEFIT = 3
HOOKS_PER_ANGLE = 6
BODIES_PER_ANGLE = 3
CTAS_PER_ANGLE = 3

# A combination is a (hook, body, cta) triple within one angle.
COMBINATIONS_PER_ANGLE = HOOKS_PER_ANGLE * BODIES_PER_ANGLE * CTAS_PER_ANGLE  # 54
DEFAULT_BENEFIT_CAPACITY = ANGLES_PER_BENEFIT * COMBINATIONS_PER_ANGLE        # 162

# Per-benefit authored-atom counts (for validation + receipts).
HOOKS_PER_BENEFIT = ANGLES_PER_BENEFIT * HOOKS_PER_ANGLE   # 18
BODIES_PER_BENEFIT = ANGLES_PER_BENEFIT * BODIES_PER_ANGLE  # 9
CTAS_PER_BENEFIT = ANGLES_PER_BENEFIT * CTAS_PER_ANGLE      # 9

# --------------------------------------------------------------------------
# Bounded authored-string lengths (amendment 7: storage / transport bounds only,
# NOT duration / WPS / video timing). Kept deliberately compact; the contract-size
# test proves the maximal envelope fits the structured-output transport ceiling.
# --------------------------------------------------------------------------
ANGLE_MAX_CHARS = 200
HOOK_MAX_CHARS = 200
BODY_MAX_CHARS = 240
CTA_MAX_CHARS = 120
BENEFIT_MAX_CHARS = 300
USAGE_HINT_MAX_CHARS = 300
REVIEWER_NOTE_MAX_CHARS = 2000

_AngleText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=ANGLE_MAX_CHARS)
]
_HookText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=HOOK_MAX_CHARS)
]
_BodyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BODY_MAX_CHARS)
]
_CtaText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=CTA_MAX_CHARS)
]

BenefitStatus = Literal["DRAFT", "VERIFIED", "REVIEW_REQUIRED", "BLOCKED", "ARCHIVED"]
AtomStatus = Literal["ACTIVE", "STALE", "SUPERSEDED", "ARCHIVED"]
BuildStatus = Literal["RESERVED", "RUNNING", "COMPLETED", "FAILED"]
ReviewAction = Literal["VERIFY", "BLOCK"]


# --------------------------------------------------------------------------
# STRICT provider-output contract (AI authors words only)
# --------------------------------------------------------------------------
class CreativeAngleProposal(BaseModel):
    """One angle: a selling perspective for a benefit, plus its reusable seeds.

    Exactly ``HOOKS_PER_ANGLE`` hooks, ``BODIES_PER_ANGLE`` body cores and
    ``CTAS_PER_ANGLE`` CTA seeds. ``extra="forbid"`` rejects any provider-supplied
    identity/control key (angle_id, status, route_key, duration, scene, ...).
    """

    model_config = ConfigDict(extra="forbid")

    angle: _AngleText
    hooks: list[_HookText] = Field(min_length=HOOKS_PER_ANGLE, max_length=HOOKS_PER_ANGLE)
    bodies: list[_BodyText] = Field(min_length=BODIES_PER_ANGLE, max_length=BODIES_PER_ANGLE)
    ctas: list[_CtaText] = Field(min_length=CTAS_PER_ANGLE, max_length=CTAS_PER_ANGLE)


class CreativeBuildEnvelope(BaseModel):
    """Full STRUCTURE-call output: exactly ``ANGLES_PER_BENEFIT`` angles."""

    model_config = ConfigDict(extra="forbid")

    angles: list[CreativeAngleProposal] = Field(
        min_length=ANGLES_PER_BENEFIT, max_length=ANGLES_PER_BENEFIT
    )


# --------------------------------------------------------------------------
# API request bodies
# --------------------------------------------------------------------------
class BenefitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    benefit: str = Field(min_length=1, max_length=BENEFIT_MAX_CHARS)
    usage_hint: str | None = Field(default=None, max_length=USAGE_HINT_MAX_CHARS)


class BenefitUpdateRequest(BaseModel):
    """Partial edit. ``benefit`` keeps the stable benefit_id; a material text or
    usage change re-checks PI and stales that benefit's own atoms only."""

    model_config = ConfigDict(extra="forbid")

    benefit: str | None = Field(default=None, min_length=1, max_length=BENEFIT_MAX_CHARS)
    usage_hint: str | None = Field(default=None, max_length=USAGE_HINT_MAX_CHARS)


class BenefitReviewRequest(BaseModel):
    """Audited manual resolution of a REVIEW_REQUIRED benefit (amendment 9)."""

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    reviewer_note: str = Field(min_length=1, max_length=REVIEWER_NOTE_MAX_CHARS)


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    benefit_id: str = Field(min_length=1)


class BuildVerifiedRequest(BaseModel):
    """Governed batch build (amendment 4): must be explicitly confirmed."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    confirm: bool = False
