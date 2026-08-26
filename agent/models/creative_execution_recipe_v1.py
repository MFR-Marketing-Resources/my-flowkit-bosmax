"""Pydantic contracts for the Creative Execution Recipe (Round 3).

SYSTEM OWNS VISUAL VARIATION SELECTION / RECIPE LINEAGE / PROMPT SNAPSHOTS.

The CreativeExecutionRecipeV1 is the durable, immutable execution unit binding
one immutable rendered-copy identity (BENEFIT_COPY_RENDER_V1) + a production
recipe (HYBRID/FACELESS/MONTAGE) + one deterministic visual-variation identity +
duration + product-truth lineage, and — after a provider-free compile — an
immutable prompt-snapshot reference to an existing workspace_execution_package.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RECIPE_SCHEMA_VERSION = "CREATIVE_EXECUTION_RECIPE_V1"
SUPPORTED_PRODUCTION_RECIPES = ("HYBRID", "FACELESS", "MONTAGE")

# A production recipe consumes a finalized rendered-copy candidate authored on the
# matching Round-2 copy lane. HYBRID is presenter-led. FACELESS and MONTAGE are
# BOTH presenter-free and consume FACELESS-lane rendered copy (avatar-exempt,
# hands/dialogue authored copy) — the mascot in MONTAGE speaks the same
# presenter-free dialogue. This reuses Round 2's HYBRID/FACELESS copy lanes with
# no new copy lane, and the production_recipe is folded into the visual fingerprint
# so MONTAGE and FACELESS variations never collide.
PRODUCTION_RECIPE_TO_COPY_LANE = {
    "HYBRID": "HYBRID",
    "FACELESS": "FACELESS",
    "MONTAGE": "FACELESS",
}

ProductionRecipe = Literal["HYBRID", "FACELESS", "MONTAGE"]


class CreateExecutionRecipesRequest(BaseModel):
    """Create ``visual_count`` execution recipes from ONE finalized rendered-copy
    candidate — the SAME immutable copy across ``visual_count`` distinct governed
    visual variations (SAME_SCRIPT_DIFF_VISUALS). Provider-free (no text/image/video
    provider call)."""

    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1)
    production_recipe: ProductionRecipe
    visual_count: int = Field(ge=1, le=50)
    duration_seconds: int | None = Field(default=None, ge=1, le=600)
    avatar_id: str | None = Field(default=None, max_length=64)
    treatment_id: str | None = Field(default=None, max_length=64)
    seed: str | None = Field(default=None, max_length=128)


class RemixExecutionRecipeRequest(BaseModel):
    """Remix: the SAME copy identity of an existing recipe, a NEW governed visual
    variation. No copy-provider call — a new recipe + new prompt snapshot only."""

    model_config = ConfigDict(extra="forbid")
    seed: str = Field(min_length=1, max_length=128)
    visual_count: int = Field(default=1, ge=1, le=50)
