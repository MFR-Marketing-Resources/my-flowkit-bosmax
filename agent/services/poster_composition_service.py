"""Canonical deterministic professional-poster composition resolver."""
from __future__ import annotations

from typing import Any


_PROFILES = {
    "PGC_CAMPAIGN": ("campaign_product_hero_v1", "right", "70-80%", "campaign key light", "optional", "bold campaign headline"),
    "UGC_AUTHENTIC": ("authentic_routine_v1", "lower-right", "55-65%", "ambient practical light", "allowed", "simple conversational headline"),
    "MODEL_AMBASSADOR": ("ambassador_split_v1", "lower-left", "55-65%", "polished advertising light", "required", "headline outside face-safe zone"),
    "CLEAN_STUDIO_CATALOGUE": ("studio_catalogue_v1", "center", "70-80%", "controlled studio light", "prohibited", "restrained high-contrast headline"),
    "LIFESTYLE_EDITORIAL": ("editorial_context_v1", "lower-right", "60-70%", "refined natural light", "allowed", "curated editorial headline"),
}


def resolve_poster_composition(*, creative_direction: Any, recipe_id: str, frame_ratio: str, fields: dict[str, str]) -> dict[str, Any]:
    """Resolve one plan; callers keep provenance separate from engine-facing text."""
    mode = str(getattr(creative_direction, "mode", "") or "")
    if not mode:
        return {}
    profile, anchor, dominance, lighting, human, hook_treatment = _PROFILES[mode]
    warnings = []
    if len(fields.get("hook", "")) > 48:
        warnings.append("HOOK_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    if len(fields.get("cta", "")) > 24:
        warnings.append("CTA_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    return {
        "schema_version": "wrna-poster-composition-v1",
        "profile_id": profile,
        "creative_mode": mode,
        "recipe_id": recipe_id,
        "canvas": {"frame_ratio": frame_ratio or "9:16", "safe_margin": "5%", "edge_exclusion": "text and CTA stay inside safe margin"},
        "reading_order": ["product", "hook", "subhook", "usp", "cta"],
        "product": {"anchor": anchor, "dominance": dominance, "label_visibility": "required", "real_world_scale": "required", "prohibited_overlaps": ["hook", "cta", "face"]},
        "copy": {"hook_zone": "upper-left", "subhook_zone": "upper-left below hook", "usp_zone": "left-middle", "cta_zone": "lower-left", "max_lines": {"hook": 3, "subhook": 3, "usp": 3, "cta": 2}},
        "typography": {"hook": hook_treatment, "subhook": "supporting", "usp": "stacked proof lines, not badges", "cta": "concise high-contrast action"},
        "scene": {"lighting": lighting, "human_presence": human, "negative_space": "protect copy zones", "background_complexity": "controlled"},
        "quality_negative_rules": ["no text covering product or face", "no floating chips", "no excessive badges", "no duplicate product crop", "no fabricated certification", "no cluttered spec-sheet layout"],
        "warnings": warnings,
    }


def render_composition_instruction(plan: dict[str, Any]) -> str:
    if not plan:
        return ""
    product = plan["product"]
    return (
        f"Professional composition: {plan['canvas']['frame_ratio']} canvas; product anchored {product['anchor']} at {product['dominance']} visual dominance, label visible and real-world scale preserved. "
        f"Reading order product then hook, subhook, USP and CTA. Keep hook upper-left, USP left-middle and CTA lower-left inside 5% safe margin. "
        f"{plan['scene']['lighting']}; {plan['typography']['hook']}; {', '.join(plan['quality_negative_rules'])}."
    )
