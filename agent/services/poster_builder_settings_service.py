"""Poster / Creative Cockpit builder-settings SSOT (read-only).

Owns the canonical poster-dimension option lists and composes the ALREADY
EXISTING settings SSOTs into one payload:

  - flow_mirror  -> ``build_image_gen_settings`` (models.json image models,
                    aspect ratios, counts) — the exact same source the IMG
                    surfaces use, not a duplicate list.
  - copy_components -> copy-signal routes + copy landbank presence.
  - ai_provider  -> text_assist lane status (masked; no secrets, no token spend).

The SAME payload feeds the read-only Creative Cockpit page and the Poster
Builder dropdowns so the two can never drift.

Contract note: each option's ``id`` is the exact string the poster draft carries
(dropdown ``value=id``). The seed defaults below intentionally match today's
draft defaults so the prompt-draft / copy-recommendation contract stays
byte-identical. This module performs NO mutation, NO persistence, NO generation.
"""
from __future__ import annotations

from agent.models.poster_builder_settings import (
    AIProviderStatusSummary,
    CopyComponentsStatus,
    FlowMirrorDefaults,
    FlowMirrorImageModel,
    FlowMirrorSettings,
    PosterBuilderSettingsResponse,
    SettingOption,
)
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_landbank_service
from agent.services.copy_signal_generator_service import SUPPORTED_ROUTES
from agent.services.img_asset_factory_service import build_image_gen_settings

# (id/wire-value, label, description, is_default). ``id`` is the exact string the
# draft submits; keep the defaults aligned with EMPTY_POSTER_DRAFT / the copy
# recommendation request defaults.
POSTER_OBJECTIVES = [
    ("Product awareness", "Product awareness", "Introduce the product and build recognition.", True),
    ("Sales conversion", "Sales conversion", "Drive purchase / click-through with a clear offer.", False),
    ("Education / how-to", "Education / how-to", "Explain how the product is used or its benefits.", False),
    ("Trust & credibility", "Trust & credibility", "Reassure with heritage, quality, and social proof.", False),
    ("Promo / offer", "Promo / offer", "Highlight a limited promotion or bundle.", False),
]

POSTER_TYPES = [
    ("Product-only hero poster", "Product-only hero poster", "Single product hero, no human.", True),
    ("Lifestyle in-use", "Lifestyle in-use", "Product shown in a real usage context.", False),
    ("Benefit callout", "Benefit callout", "Product plus 2–3 benefit call-outs.", False),
    ("Promo / price", "Promo / price", "Product plus a promotional price / offer block.", False),
    ("Comparison", "Comparison", "Before/after or vs-alternative framing (restricted-safe).", False),
]

LANGUAGES = [
    ("ms", "Malay", "Bahasa Melayu copy.", True),
    ("en", "English", "English copy.", False),
    ("zh", "Chinese", "Chinese copy.", False),
    ("ta", "Tamil", "Tamil copy.", False),
]

VISUAL_ROUTES = [
    ("Premium commercial", "Premium commercial", "Polished studio commercial look.", True),
    ("UGC authentic", "UGC authentic", "Handheld, authentic, creator-style.", False),
    ("Clean studio", "Clean studio", "Minimal studio background, product-forward.", False),
    ("Lifestyle editorial", "Lifestyle editorial", "Editorial lifestyle scene.", False),
]

HUMAN_PRESENCE_MODES = [
    ("No human / product-forward", "No human / product-forward", "No people; the product is the hero.", True),
    ("Hands only", "Hands only", "Hands interacting with the product.", False),
    ("Faceless model", "Faceless model", "Body / model without a visible face.", False),
    ("Full model / creator", "Full model / creator", "Full visible model or creator.", False),
]

TEXT_DENSITY_OPTIONS = [
    ("low", "Low", "Minimal text; headline + CTA only.", False),
    ("medium", "Medium", "Headline, subhook, a few USPs, CTA.", True),
    ("high", "High", "Denser copy layout with multiple USP lines.", False),
]


def _options(rows: list[tuple[str, str, str, bool]]) -> list[SettingOption]:
    return [
        SettingOption(id=rid, label=label, description=desc, default=is_default)
        for (rid, label, desc, is_default) in rows
    ]


def _flow_mirror() -> FlowMirrorSettings:
    igs = build_image_gen_settings()
    return FlowMirrorSettings(
        aspect_ratios=list(igs["aspect_options"]),
        counts=list(igs["count_options"]),
        image_models=[FlowMirrorImageModel(**m) for m in igs["models"]],
        defaults=FlowMirrorDefaults(
            aspect_ratio=igs["default_aspect"],
            count=igs["default_count"],
            image_model=igs["default_model"],
        ),
    )


def _copy_components() -> CopyComponentsStatus:
    try:
        landbank_products = len(copy_landbank_service.list_products())
    except Exception:
        landbank_products = 0
    return CopyComponentsStatus(
        routes=list(SUPPORTED_ROUTES),
        landbank_products=landbank_products,
    )


def _ai_provider() -> AIProviderStatusSummary:
    status = ai_provider.provider_status()
    configured = bool(status.get("configured"))
    return AIProviderStatusSummary(
        lane=str(status.get("lane") or "text_assist"),
        configured=configured,
        status="configured" if configured else "unavailable",
        provider_id=status.get("provider_id"),
        model_id=status.get("model_id"),
        execution_enabled=bool(status.get("execution_enabled")),
    )


class PosterBuilderSettingsService:
    @staticmethod
    def build_settings() -> PosterBuilderSettingsResponse:
        return PosterBuilderSettingsResponse(
            poster_objectives=_options(POSTER_OBJECTIVES),
            poster_types=_options(POSTER_TYPES),
            languages=_options(LANGUAGES),
            visual_routes=_options(VISUAL_ROUTES),
            human_presence_modes=_options(HUMAN_PRESENCE_MODES),
            text_density_options=_options(TEXT_DENSITY_OPTIONS),
            flow_mirror=_flow_mirror(),
            copy_components=_copy_components(),
            ai_provider=_ai_provider(),
            sources={
                "poster_dimensions": "config",
                "flow_mirror": "models.json",
                "copy_components": "copy_signals+landbank",
                "ai_provider": "ai_provider",
            },
        )
