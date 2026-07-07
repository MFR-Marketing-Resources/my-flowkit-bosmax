"""Copy Grounding models — the structured product-knowledge + customer-avatar
context that grounds copy generation (angle → hook → subhook → USP → CTA).

Two-tier resolution (see copy_grounding_service):
  1. APPROVED_SNAPSHOT — the operator-authored product_intelligence_snapshot
     (richest: real product knowledge + persona + claims).
  2. FRAMEWORK_FAMILY — derived from the product-intelligence family via the
     curated authority (avatar dimensions + trigger library + angle families +
     claim posture) sourced from COPYWRITING_FRAMEWORK_UNIVERSAL.yaml.
  3. MINIMAL — name/category only; ungrounded (fail-closed, flagged).

Product FACTS (benefits/USPs/ingredients) are only ever taken from an approved
snapshot — never invented. The framework tier grounds the AVATAR, ANGLE STRATEGY,
TONE and CLAIM guardrails (family-level truths), not product claims.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

GROUNDING_APPROVED_SNAPSHOT = "APPROVED_SNAPSHOT"
GROUNDING_FRAMEWORK_FAMILY = "FRAMEWORK_FAMILY"
GROUNDING_MINIMAL = "MINIMAL"


class BuyerPersona(BaseModel):
    audience: str = ""
    desires: list[str] = Field(default_factory=list)
    fears: list[str] = Field(default_factory=list)
    pains: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    tone: str = ""
    pronoun: str = ""


class ProductKnowledge(BaseModel):
    description: str = ""
    benefits: list[str] = Field(default_factory=list)
    usps: list[str] = Field(default_factory=list)
    ingredients: str = ""
    target_customer: str = ""


class ClaimGuardrails(BaseModel):
    claim_gate: str = ""
    claim_risk_level: str = ""
    allowed_claims: list[str] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)
    banned_terms: list[str] = Field(default_factory=list)


class CopyGrounding(BaseModel):
    product_id: str
    grounded: bool = False
    source: str = GROUNDING_MINIMAL
    family: str = ""
    is_stealth: bool = False
    effective_route: str = "DIRECT"
    copy_formula: str = ""
    metaphor_silos: list[str] = Field(default_factory=list)
    product_knowledge: ProductKnowledge = Field(default_factory=ProductKnowledge)
    buyer_persona: BuyerPersona = Field(default_factory=BuyerPersona)
    angle_strategies: list[str] = Field(default_factory=list)
    claim_guardrails: ClaimGuardrails = Field(default_factory=ClaimGuardrails)
    missing: list[str] = Field(default_factory=list)
