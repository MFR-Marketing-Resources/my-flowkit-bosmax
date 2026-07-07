"""Response models for the Poster / Creative Cockpit builder-settings SSOT.

This is a READ-ONLY settings contract. It carries the canonical poster-dimension
option lists plus a composed view of the pre-existing settings SSOTs (image-gen
models/aspects/counts, copy-signal routes, AI provider status). The same payload
feeds the read-only Creative Cockpit page AND the Poster Builder dropdowns so the
two never drift.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SettingOption(BaseModel):
    """One selectable option for a poster dimension.

    ``id`` is a stable machine key; ``label`` is what the operator sees AND what
    the poster draft carries (dropdown ``value=label``) so the existing
    prompt-draft / copy-recommendation contract stays byte-identical.
    """

    id: str
    label: str
    description: str = ""
    default: bool = False


class FlowMirrorImageModel(BaseModel):
    key: str
    label: str
    pending: bool = False


class FlowMirrorDefaults(BaseModel):
    aspect_ratio: str
    count: int
    image_model: str


class FlowMirrorSettings(BaseModel):
    aspect_ratios: list[str]
    counts: list[int]
    image_models: list[FlowMirrorImageModel]
    defaults: FlowMirrorDefaults
    source: str = "models.json"


class CopyComponentsStatus(BaseModel):
    """Availability status for copy components. Copy sets / landbank / kits are
    product-scoped and are fetched per product elsewhere; this global settings
    surface only reports what routing + data sources exist."""

    routes: list[str]
    copy_sets_scope: str = "product"
    copy_sets_endpoint: str = "/api/copy-sets/product/{product_id}"
    landbank_products: int = 0
    source: str = "copy_signals+landbank"


class AIProviderStatusSummary(BaseModel):
    """Compact, secret-free AI provider summary for the text_assist copy lane."""

    lane: str
    configured: bool
    status: str  # "configured" | "unavailable"
    provider_id: str | None = None
    model_id: str | None = None
    execution_enabled: bool = False
    source: str = "ai_provider"


class PosterBuilderSettingsResponse(BaseModel):
    poster_objectives: list[SettingOption]
    poster_types: list[SettingOption]
    languages: list[SettingOption]
    visual_routes: list[SettingOption]
    human_presence_modes: list[SettingOption]
    text_density_options: list[SettingOption]
    flow_mirror: FlowMirrorSettings
    copy_components: CopyComponentsStatus
    ai_provider: AIProviderStatusSummary
    # Per-section provenance so the cockpit can show where each value came from.
    sources: dict[str, str] = Field(default_factory=dict)
