"""Copy Grounding — resolve the product-knowledge + customer-avatar context that
grounds copy generation (so angle/hook/subhook/USP/CTA are strategy-driven, not
guessed).

Two-tier resolution:
  1. APPROVED_SNAPSHOT — operator-authored product_intelligence_snapshot (richest:
     real product knowledge + persona + claims). Framework tier fills any gaps
     (family avatar / angle strategies / metaphor silos / route).
  2. FRAMEWORK_FAMILY — derived from the product-intelligence family via the
     curated authority (avatar + trigger library + angle families + claim
     posture) sourced from COPYWRITING_FRAMEWORK_UNIVERSAL.yaml.
  3. MINIMAL — unknown family + no snapshot → ungrounded (flagged, fail-closed).

Product FACTS (benefits/USPs/ingredients) are only ever read from an approved
snapshot — the framework tier NEVER invents product claims (only avatar / angle /
tone / claim-guardrails, which are family-level framework truths).
"""
from __future__ import annotations

from typing import Any

from agent.authority.copy_family_grounding import (
    FRAMEWORK_BANNED_TERMS,
    grounding_for_family,
)
from agent.models.copy_grounding import (
    GROUNDING_APPROVED_SNAPSHOT,
    GROUNDING_FRAMEWORK_FAMILY,
    GROUNDING_MINIMAL,
    BuyerPersona,
    ClaimGuardrails,
    CopyGrounding,
    ProductKnowledge,
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(x) for x in value if _clean(x)]
    return []


def build_framework_grounding(product: dict[str, Any]) -> CopyGrounding:
    """FRAMEWORK tier (sync, pure) — grounding derived from the product's family
    via the curated authority. Used when no approved snapshot exists."""
    from agent.services.product_intelligence_service import (
        inject_product_intelligence_fields,
        resolve_product_intelligence_profile,
    )

    try:
        profile = resolve_product_intelligence_profile(product)
        hydrated = inject_product_intelligence_fields(dict(product), profile)
    except Exception:
        hydrated = dict(product)

    family = _clean(hydrated.get("bosmax_product_family"))
    copy_route = _clean(hydrated.get("copy_route")).upper()
    silo = _clean(hydrated.get("silo"))
    product_type = _clean(hydrated.get("product_type")).upper()
    is_stealth = (
        product_type == "STEALTH"
        or copy_route == "STEALTH"
        or "stealth" in silo.lower()
    )
    if is_stealth:
        effective_route = "STEALTH"
    elif copy_route in ("REVIEW_REQUIRED", "DIRECT"):
        effective_route = copy_route
    else:
        effective_route = "DIRECT"

    fam = grounding_for_family(family)
    avatar = fam.get("avatar", {}) if isinstance(fam.get("avatar"), dict) else {}
    known = bool(_clean(avatar.get("audience")) or avatar.get("triggers"))

    persona = BuyerPersona(
        audience=_clean(avatar.get("audience")),
        desires=_clean_list(avatar.get("desires")),
        fears=_clean_list(avatar.get("fears")),
        pains=_clean_list(avatar.get("pains")),
        objections=_clean_list(avatar.get("objections")),
        triggers=_clean_list(avatar.get("triggers")),
        tone=_clean(avatar.get("tone")),
        pronoun=_clean(avatar.get("pronoun")),
    )
    guardrails = ClaimGuardrails(
        claim_gate=_clean(hydrated.get("claim_gate")) or _clean(fam.get("claim_posture")),
        claim_risk_level=_clean(hydrated.get("claim_risk_level")),
        allowed_claims=[],
        blocked_claims=[],
        banned_terms=list(FRAMEWORK_BANNED_TERMS),
    )
    knowledge = ProductKnowledge(target_customer=persona.audience)

    return CopyGrounding(
        product_id=_clean(product.get("id")),
        grounded=known,
        source=GROUNDING_FRAMEWORK_FAMILY if known else GROUNDING_MINIMAL,
        family=family,
        is_stealth=is_stealth,
        effective_route=effective_route,
        copy_formula=_clean(fam.get("copy_formula")),
        metaphor_silos=list(fam.get("metaphor_silos") or []),
        product_knowledge=knowledge,
        buyer_persona=persona,
        angle_strategies=list(fam.get("angle_strategies") or []),
        claim_guardrails=guardrails,
        missing=[
            "approved product-intelligence snapshot (real benefits / USPs / ingredients) — author to enrich",
        ],
    )


def _merge_persona(persona_json: Any, fallback: BuyerPersona) -> BuyerPersona:
    """Read the freeform buyer_persona_snapshot_json defensively; fall back to the
    framework family avatar for any key the operator did not author."""
    pj = persona_json if isinstance(persona_json, dict) else {}

    def s(*keys: str, default: str) -> str:
        for k in keys:
            v = pj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return default

    def lst(*keys: str, default: list[str]) -> list[str]:
        for k in keys:
            v = pj.get(k)
            if isinstance(v, list) and v:
                return _clean_list(v)
            if isinstance(v, str) and v.strip():
                return [v.strip()]
        return default

    return BuyerPersona(
        audience=s("audience", "persona", "avatar_summary", default=fallback.audience),
        desires=lst("desires", "desire_summary", default=fallback.desires),
        fears=lst("fears", default=fallback.fears),
        pains=lst("pains", "pain_stack", "pain_points", default=fallback.pains),
        objections=lst("objections", "objection_summary", default=fallback.objections),
        triggers=lst("triggers", "trigger_stack", default=fallback.triggers),
        tone=s("tone", default=fallback.tone),
        pronoun=s("pronoun", default=fallback.pronoun),
    )


def _angles_from_strategy(strategy_json: Any) -> list[str]:
    sj = strategy_json if isinstance(strategy_json, dict) else {}
    angles = sj.get("angles")
    if isinstance(angles, list) and angles:
        return _clean_list(angles)
    angle = sj.get("angle")
    if isinstance(angle, str) and angle.strip():
        return [angle.strip()]
    return []


def _grounding_from_snapshot(product: dict[str, Any], snap: Any) -> CopyGrounding:
    """APPROVED_SNAPSHOT tier — real product knowledge + persona + claims, with
    the framework tier filling avatar / angle / silo / route gaps."""
    fw = build_framework_grounding(product)
    persona = _merge_persona(getattr(snap, "buyer_persona_snapshot_json", {}), fw.buyer_persona)
    angles = _angles_from_strategy(getattr(snap, "copy_strategy_summary_json", {})) or fw.angle_strategies

    knowledge = ProductKnowledge(
        description=_clean(getattr(snap, "product_description", "")),
        benefits=_clean_list(getattr(snap, "benefits_json", [])),
        usps=_clean_list(getattr(snap, "usp_json", [])),
        ingredients=_clean(getattr(snap, "ingredients_text", "")),
        target_customer=_clean(getattr(snap, "target_customer_text", "")) or persona.audience,
    )
    blocked = _clean_list(getattr(snap, "blocked_claims_json", []))
    guardrails = ClaimGuardrails(
        claim_gate=_clean(getattr(snap, "claim_gate", "")) or fw.claim_guardrails.claim_gate,
        claim_risk_level=_clean(getattr(snap, "claim_risk_level", "")) or fw.claim_guardrails.claim_risk_level,
        allowed_claims=_clean_list(getattr(snap, "allowed_claims_json", [])),
        blocked_claims=blocked,
        banned_terms=list(FRAMEWORK_BANNED_TERMS) + blocked,
    )
    missing: list[str] = []
    if not knowledge.benefits and not knowledge.usps:
        missing.append("benefits / USPs (snapshot has none)")

    return CopyGrounding(
        product_id=fw.product_id,
        grounded=True,
        source=GROUNDING_APPROVED_SNAPSHOT,
        family=fw.family,
        is_stealth=fw.is_stealth,
        effective_route=fw.effective_route,
        copy_formula=fw.copy_formula,
        metaphor_silos=fw.metaphor_silos,
        product_knowledge=knowledge,
        buyer_persona=persona,
        angle_strategies=angles,
        claim_guardrails=guardrails,
        missing=missing,
    )


async def _safe_latest_approved(product_id: str) -> Any:
    if not product_id:
        return None
    try:
        from agent.services.product_intelligence_snapshot_service import (
            get_latest_approved_snapshot,
        )

        return await get_latest_approved_snapshot(product_id)
    except Exception:
        return None


async def resolve_copy_grounding(product: dict[str, Any]) -> CopyGrounding:
    """Resolve the copy grounding for a product: approved snapshot first, else the
    framework-family tier, else minimal (ungrounded)."""
    snap = await _safe_latest_approved(_clean(product.get("id")))
    if snap is not None:
        return _grounding_from_snapshot(product, snap)
    return build_framework_grounding(product)
