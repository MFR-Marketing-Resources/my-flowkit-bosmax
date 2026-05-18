from __future__ import annotations

from typing import Any


I2V_SLOT_RECIPES: dict[str, dict[str, Any]] = {
    "PRODUCT_HELD_BY_CHARACTER_IN_SCENE": {
        "recipe_id": "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
        "label": "Product Held By Character In Scene",
        "purpose": "Product is primary. Character demonstrates it. Scene context defines environment.",
        "required_roles": [
            "product_reference",
            "character_reference",
            "scene_context_reference",
        ],
        "optional_roles": ["style_reference"],
        "engine_slot_mapping": {
            "subject": "product_reference",
            "scene": "character_reference",
            "style": "scene_context_reference",
        },
    },
    "CHARACTER_FIRST_PRODUCT_DEMO": {
        "recipe_id": "CHARACTER_FIRST_PRODUCT_DEMO",
        "label": "Character First Product Demo",
        "purpose": "Character is primary. Product becomes the demonstration object.",
        "required_roles": [
            "product_reference",
            "character_reference",
            "scene_context_reference",
        ],
        "optional_roles": ["style_reference"],
        "engine_slot_mapping": {
            "subject": "character_reference",
            "scene": "product_reference",
            "style": "scene_context_reference",
        },
    },
    "STYLE_MOOD_DOMINANT_PRODUCT_SPOT": {
        "recipe_id": "STYLE_MOOD_DOMINANT_PRODUCT_SPOT",
        "label": "Style Mood Dominant Product Spot",
        "purpose": "Product remains primary while scene context and style mood dominate direction.",
        "required_roles": [
            "product_reference",
            "scene_context_reference",
            "style_reference",
        ],
        "optional_roles": ["character_reference"],
        "engine_slot_mapping": {
            "subject": "product_reference",
            "scene": "scene_context_reference",
            "style": "style_reference",
        },
    },
}


def get_i2v_slot_recipe(recipe_id: str) -> dict[str, Any]:
    if recipe_id not in I2V_SLOT_RECIPES:
        raise ValueError("UNSUPPORTED_I2V_RECIPE")
    return I2V_SLOT_RECIPES[recipe_id]


def list_i2v_slot_recipes() -> list[dict[str, Any]]:
    return list(I2V_SLOT_RECIPES.values())
