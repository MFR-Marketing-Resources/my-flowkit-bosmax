"""Poster recipe authority loader (PR B1).

Read-only SSOT access to agent/authority/POSTER_RECIPES.yaml. No mutation, no
persistence, no generation, no token/credit spend. Mirrors the authority-file
convention used by avatar_registry / canonical_prompt_compiler
(`_AUTHORITY_DIR = <service parent>/authority` + `yaml.safe_load`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from agent.models.poster_recipe import PosterRecipe, PosterRecipeSummary

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"
_RECIPES_FILE = _AUTHORITY_DIR / "POSTER_RECIPES.yaml"


@lru_cache(maxsize=1)
def _load_recipes() -> tuple[PosterRecipe, ...]:
    raw = yaml.safe_load(_RECIPES_FILE.read_text(encoding="utf-8")) or {}
    entries = raw.get("recipes") or []
    recipes: list[PosterRecipe] = []
    for entry in entries:
        if isinstance(entry, dict):
            recipes.append(PosterRecipe.model_validate(entry))
    return tuple(recipes)


def list_recipes() -> list[PosterRecipe]:
    """Full recipe objects (structure + zones)."""
    return list(_load_recipes())


def list_recipe_summaries() -> list[PosterRecipeSummary]:
    """Lightweight list for a recipe selector (id / archetype / label / description)."""
    return [
        PosterRecipeSummary(
            recipe_id=r.recipe_id,
            archetype=r.archetype,
            label=r.label,
            description=r.description,
        )
        for r in _load_recipes()
    ]


def get_recipe(recipe_id: str) -> PosterRecipe | None:
    """Resolve one recipe by id; None when unknown (caller fails closed)."""
    target = str(recipe_id or "").strip()
    if not target:
        return None
    for r in _load_recipes():
        if r.recipe_id == target:
            return r
    return None
