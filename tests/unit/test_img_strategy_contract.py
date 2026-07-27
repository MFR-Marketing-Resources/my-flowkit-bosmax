"""Unit tests for non-overlapping IMG Generation Strategy Contracts (PR #498)."""
from __future__ import annotations

import pytest
from agent.services.product_visual_grounding_resolver import (
    STRATEGY_FIXED_HERO_POSTER,
    STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
    STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION,
    resolve_generation_strategy,
)


def test_strategy_a_never_uses_exact_composite_or_scene_only():
    """Strategy A must be reference-conditioned with integrated prompt."""
    strategy = resolve_generation_strategy(
        lane_id="AVATAR_PRODUCT_INTERACTION",
        product_id="6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        has_avatar=True,
        is_product_only=False,
    )
    assert strategy == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION
    assert strategy != STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE


def test_strategy_b_uses_product_only_exact_composite():
    """Strategy B must be used only for product-only hero lanes."""
    strategy = resolve_generation_strategy(
        lane_id="PRODUCT_ONLY_HERO",
        product_id="6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        has_avatar=False,
        is_product_only=True,
    )
    assert strategy == STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE


def test_strategy_c_preserves_fixed_hero_poster():
    """Strategy C must be used for Poster Builder with fixed hero visual."""
    strategy = resolve_generation_strategy(
        lane_id="POSTER_BUILDER",
        product_id="6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        is_poster=True,
    )
    assert strategy == STRATEGY_FIXED_HERO_POSTER
