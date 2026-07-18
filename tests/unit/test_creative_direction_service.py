"""Round 1 Creative Direction authority and resolver contracts."""
from __future__ import annotations

import pytest

from agent.models.creative_direction import CreativeMode
from agent.services.creative_direction_service import (
    CreativeDirectionError,
    resolve_creative_direction,
)


def test_all_supported_modes_are_structured_and_materially_distinct():
    directions = [resolve_creative_direction(mode, product={"category": "Beauty"}) for mode in CreativeMode]

    assert {direction.mode for direction in directions} == set(CreativeMode)
    assert len({direction.composition_direction for direction in directions}) == len(CreativeMode)
    assert len({direction.human_presence_policy for direction in directions}) >= 4
    assert all(direction.authority_version == "creative-direction-modes-v1" for direction in directions)
    assert all(direction.representation_policy_version == "malaysian-representation-policy-v1" for direction in directions)


def test_unknown_mode_fails_closed():
    with pytest.raises(CreativeDirectionError, match="UNSUPPORTED_CREATIVE_MODE"):
        resolve_creative_direction("UNSAFE_MODE")


def test_existing_category_authority_is_reused_without_new_taxonomy():
    direction = resolve_creative_direction(
        CreativeMode.UGC_AUTHENTIC,
        product={"category": "Food & Beverages"},
    )

    assert "kitchen" in direction.category_context["background"]
    assert direction.canonical_cluster == "Food & Beverage"
    assert direction.scene_template_ids
    assert direction.avatar_vocabulary_source == "avatar_registry_vocab.json"
    assert "CATEGORY_SCENE_MODEL_MAP.yaml" in direction.authority_sources
    assert "creative_category_cluster_map.json" in direction.authority_sources


def test_model_ambassador_policy_rejects_identity_inference_rules():
    direction = resolve_creative_direction(CreativeMode.MODEL_AMBASSADOR)
    negatives = " ".join(direction.negative_rules).lower()

    assert "identity inference" in negatives
    assert "religious attire inference" in negatives
    assert "skin-tone descriptors" in negatives
