"""Avatar Persona variant loader + deterministic composer (Phase A).

Loads agent/authority/PERSONA_VARIANTS.yaml (read-only authority, lru-cached)
and composes persona entries for every valid gender × ethnicity × age × bundle
combination plus the curated seeds. Entries feed PERSONA_REGISTRY in
prompt_compiler_runtime_config_service — the single choke point for
`normalize_creator_persona` validity, UI options, and the compiler's
`visual_description` injection. Fail-closed: a malformed authority file yields
ZERO variants (the two base personas keep working) — never a 500.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent.models.persona_variant import (
    PersonaBundle,
    PersonaVariantsConfig,
)

logger = logging.getLogger(__name__)

_AUTHORITY_PATH = Path(__file__).resolve().parents[1] / "authority" / "PERSONA_VARIANTS.yaml"

COMPOSED_ID_PREFIX = "AVX"


@lru_cache(maxsize=1)
def load_config() -> PersonaVariantsConfig:
    try:
        raw = yaml.safe_load(_AUTHORITY_PATH.read_text(encoding="utf-8")) or {}
        return PersonaVariantsConfig(**raw)
    except Exception as exc:  # noqa: BLE001 — fail closed to empty config
        logger.error("PERSONA_VARIANTS.yaml unreadable — variants disabled: %s", exc)
        return PersonaVariantsConfig()


def compose_persona_id(gender_id: str, ethnicity_id: str, age_id: str, bundle_id: str) -> str:
    return f"{COMPOSED_ID_PREFIX}_{gender_id}_{ethnicity_id}_{age_id}_{bundle_id}".upper()


def _bundle_wardrobe(bundle: PersonaBundle, gender_id: str) -> str:
    if gender_id == "F":
        return bundle.wardrobe_f_en
    if gender_id == "F_HIJAB":
        return bundle.wardrobe_f_hijab_en
    return bundle.wardrobe_m_en


def compose_visual_description(
    config: PersonaVariantsConfig,
    gender_id: str,
    ethnicity_id: str,
    age_id: str,
    bundle_id: str,
) -> str | None:
    gender = next((g for g in config.genders if g.id == gender_id), None)
    ethnicity = next((e for e in config.ethnicities if e.id == ethnicity_id), None)
    age = next((a for a in config.age_ranges if a.id == age_id), None)
    bundle = next((b for b in config.bundles if b.id == bundle_id), None)
    if not (gender and ethnicity and age and bundle):
        return None
    if gender.id not in bundle.allowed_genders:
        return None
    return config.visual_template_en.format(
        ethnicity=ethnicity.descriptor_en,
        gender=gender.descriptor_en,
        age=age.descriptor_en,
        wardrobe=_bundle_wardrobe(bundle, gender.id),
        environment=bundle.environment_en,
        expression=bundle.expression_en,
    )


@lru_cache(maxsize=1)
def load_composed_personas() -> tuple[dict[str, Any], ...]:
    """All persona entries (seeds first, then the full valid cross-product) in
    the exact PERSONA_REGISTRY dict shape. Deterministic order; duplicate ids
    are skipped with a log line."""
    config = load_config()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for seed in config.seeds:
        seed_id = seed.id.upper()
        if seed_id in seen:
            logger.warning("persona seed duplicate skipped: %s", seed_id)
            continue
        seen.add(seed_id)
        entries.append(
            {
                "id": seed_id,
                "label": seed.label,
                "presentation": seed.presentation,
                "tone": seed.tone,
                "continuity_notes": seed.continuity_notes,
                "visual_description": seed.visual_description,
            }
        )

    for gender in config.genders:
        for ethnicity in config.ethnicities:
            for age in config.age_ranges:
                for bundle in config.bundles:
                    if gender.id not in bundle.allowed_genders:
                        continue
                    persona_id = compose_persona_id(
                        gender.id, ethnicity.id, age.id, bundle.id
                    )
                    if persona_id in seen:
                        logger.warning("persona duplicate skipped: %s", persona_id)
                        continue
                    description = compose_visual_description(
                        config, gender.id, ethnicity.id, age.id, bundle.id
                    )
                    if not description:
                        continue
                    seen.add(persona_id)
                    entries.append(
                        {
                            "id": persona_id,
                            "label": (
                                f"{gender.label_ms} {ethnicity.label} {age.label} — {bundle.label}"
                            ),
                            "presentation": "visible creator",
                            "tone": "calm, credible, product-first",
                            "continuity_notes": (
                                "same creator identity and wardrobe across all blocks"
                            ),
                            "visual_description": description,
                        }
                    )
    return tuple(entries)


def presenter_profile_for_persona(persona_id: str | None) -> dict[str, Any] | None:
    """Presenter-profile override for the CANONICAL compiler.

    When the operator's creator_persona is a persona variant (seed or composed
    AVX id), return an avatar_registry-shaped profile whose `prose_override`
    carries the variant's visual description — `presenter_prose()` renders it
    verbatim instead of the seeded avatar-pool pick. Returns None for the base
    personas / unknown ids (pool behavior unchanged)."""
    wanted = str(persona_id or "").strip().upper()
    if not wanted:
        return None
    entry = next((e for e in load_composed_personas() if e["id"] == wanted), None)
    if not entry:
        return None
    return {
        "avatar_code": wanted,
        "character_name": entry["label"],
        "variant": "PERSONA_VARIANT",
        "skin_tone": "",
        "hair_style": "",
        "wardrobe": "",
        "environment": "",
        "lighting": "",
        "camera": "",
        "expression": "",
        "usage_tags": [],
        "prose_override": entry["visual_description"],
    }


def composer_vocab_for_ui() -> dict[str, Any]:
    """Compact vocabulary block for the frontend composer (descriptors included
    so the UI can preview the composed text without another round-trip)."""
    config = load_config()
    return {
        "id_prefix": COMPOSED_ID_PREFIX,
        "genders": [g.model_dump() for g in config.genders],
        "ethnicities": [e.model_dump() for e in config.ethnicities],
        "age_ranges": [a.model_dump() for a in config.age_ranges],
        "bundles": [
            {
                "id": b.id,
                "label": b.label,
                "environment_en": b.environment_en,
                "wardrobe_f_en": b.wardrobe_f_en,
                "wardrobe_f_hijab_en": b.wardrobe_f_hijab_en,
                "wardrobe_m_en": b.wardrobe_m_en,
                "expression_en": b.expression_en,
                "allowed_genders": list(b.allowed_genders),
            }
            for b in config.bundles
        ],
        "seeds": [s.id.upper() for s in config.seeds],
        "visual_template_en": config.visual_template_en,
    }
