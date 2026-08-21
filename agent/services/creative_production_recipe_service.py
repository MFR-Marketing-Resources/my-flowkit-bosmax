"""Canonical Production Studio recipe registry and private execution adapters.

Production Studio owns the business recipe selection.  This module is the one
backend registry that translates those recipes into the already-proven
technical authorities underneath them.  The translation is deliberately
private: callers outside the adapter boundary should persist and display
``production_recipe`` only.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.models.creative_production import (
    RETIRED_PRODUCTION_LOGICAL_MODES,
    ProductionRecipe,
)


class ProductionRecipeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProductionRecipeAdapter:
    recipe: ProductionRecipe
    internal_logical_mode: str
    treatment_logical_mode: str
    avatar_required_without_treatment: bool
    canonical_authority: str


# This registry is the only backend recipe-to-authority mapping.  FACELESS and
# MONTAGE intentionally retain F2V as a private transport/treatment primitive;
# neither is exposed as a Studio business mode.
PRODUCTION_RECIPE_ADAPTERS: dict[ProductionRecipe, ProductionRecipeAdapter] = {
    ProductionRecipe.HYBRID: ProductionRecipeAdapter(
        recipe=ProductionRecipe.HYBRID,
        internal_logical_mode="HYBRID",
        treatment_logical_mode="HYBRID",
        avatar_required_without_treatment=True,
        canonical_authority="workspace_generation_package_service.create_hybrid_generation_package",
    ),
    ProductionRecipe.FACELESS: ProductionRecipeAdapter(
        recipe=ProductionRecipe.FACELESS,
        internal_logical_mode="F2V",
        treatment_logical_mode="F2V",
        avatar_required_without_treatment=False,
        canonical_authority="faceless_lane_service + workspace_execution_package_service",
    ),
    ProductionRecipe.MONTAGE: ProductionRecipeAdapter(
        recipe=ProductionRecipe.MONTAGE,
        internal_logical_mode="F2V",
        treatment_logical_mode="F2V",
        avatar_required_without_treatment=False,
        canonical_authority="montage_run_service.create_montage_discrete_run",
    ),
}


def resolve_production_recipe(
    value: ProductionRecipe | str,
) -> ProductionRecipeAdapter:
    normalized = str(value).strip().upper()
    if normalized in RETIRED_PRODUCTION_LOGICAL_MODES:
        raise ProductionRecipeError(
            "PRODUCTION_RECIPE_RETIRED",
            f"Production Studio logical mode {normalized} is retired; "
            "choose a canonical recipe.",
        )
    try:
        recipe = (
            value
            if isinstance(value, ProductionRecipe)
            else ProductionRecipe(normalized)
        )
    except (TypeError, ValueError) as exc:
        raise ProductionRecipeError(
            "PRODUCTION_RECIPE_UNSUPPORTED",
            f"Unsupported Production Studio recipe: {value!r}.",
        ) from exc
    return PRODUCTION_RECIPE_ADAPTERS[recipe]


def recipe_for_plan(plan: dict[str, object]) -> ProductionRecipeAdapter | None:
    value = plan.get("production_recipe")
    if value in (None, ""):
        return None
    try:
        return resolve_production_recipe(str(value))
    except ProductionRecipeError:
        return None


def current_production_recipe_values() -> tuple[str, ...]:
    """Stable public values for contract tests and diagnostics."""

    return tuple(recipe.value for recipe in ProductionRecipe)
