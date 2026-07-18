"""Typed, inert Round 1 Creative Direction contract."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CreativeMode(StrEnum):
    PGC_CAMPAIGN = "PGC_CAMPAIGN"
    UGC_AUTHENTIC = "UGC_AUTHENTIC"
    MODEL_AMBASSADOR = "MODEL_AMBASSADOR"
    CLEAN_STUDIO_CATALOGUE = "CLEAN_STUDIO_CATALOGUE"
    LIFESTYLE_EDITORIAL = "LIFESTYLE_EDITORIAL"


class CreativeDirection(BaseModel):
    """Serializable authority output for a future explicit compiler handoff."""

    model_config = ConfigDict(extra="forbid")

    authority_version: str
    representation_policy_version: str
    mode: CreativeMode
    label: str
    composition_direction: str
    product_dominance: str
    lighting: str
    camera_framing: str
    props: str
    environment: str
    human_presence_policy: str
    product_interaction: str
    negative_rules: list[str] = Field(default_factory=list)
    malaysian_localisation_cues: list[str] = Field(default_factory=list)
    category_context: dict[str, str] = Field(default_factory=dict)
    canonical_cluster: str = ""
    cluster_source: str = ""
    scene_template_ids: list[str] = Field(default_factory=list)
    avatar_vocabulary_source: str = ""
    product_truth_claim_gate: str = "UNKNOWN"
    authority_sources: list[str] = Field(default_factory=list)
