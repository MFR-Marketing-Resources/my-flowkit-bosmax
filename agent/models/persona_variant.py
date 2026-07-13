"""Avatar Persona variants — config contracts (Owner Growth Pack, Phase A).

TEXT-only presenter control for T2V/HYBRID: composed persona entries flow
through the EXISTING `creator_persona` channel into the compiler's
`visual_description` injection. No image references — the per-mode reference
contracts stay untouched.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaGender(BaseModel):
    id: str
    label_ms: str
    descriptor_en: str  # e.g. "woman", "woman wearing a neatly styled hijab"


class PersonaEthnicity(BaseModel):
    id: str
    label: str
    descriptor_en: str  # respectful neutral phrasing, e.g. "Malay"


class PersonaAgeRange(BaseModel):
    id: str
    label: str
    descriptor_en: str  # e.g. "adult in their 30s"


class PersonaBundle(BaseModel):
    """Wardrobe + environment as ONE validated pair (coherence law: wardrobe is
    never selected apart from its matching environment/event)."""

    id: str
    label: str
    environment_en: str
    wardrobe_f_en: str
    wardrobe_f_hijab_en: str
    wardrobe_m_en: str
    expression_en: str = "calm, credible expression"
    allowed_genders: list[str] = Field(default_factory=lambda: ["F", "F_HIJAB", "M"])


class PersonaSeed(BaseModel):
    id: str
    label: str
    presentation: str = "visible creator"
    tone: str = "calm, credible, product-first"
    continuity_notes: str = (
        "same creator identity and wardrobe across all blocks"
    )
    visual_description: str


class PersonaVariantsConfig(BaseModel):
    schema_version: str = "persona-variants-v1"
    genders: list[PersonaGender] = Field(default_factory=list)
    ethnicities: list[PersonaEthnicity] = Field(default_factory=list)
    age_ranges: list[PersonaAgeRange] = Field(default_factory=list)
    bundles: list[PersonaBundle] = Field(default_factory=list)
    seeds: list[PersonaSeed] = Field(default_factory=list)
    visual_template_en: str = (
        "Malaysian {ethnicity} {gender} {age}, wearing {wardrobe}, "
        "in {environment}, {expression}, natural commercial grooming, "
        "modest presentable styling, consistent identity and wardrobe "
        "across all blocks."
    )
