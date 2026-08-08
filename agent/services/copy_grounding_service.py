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

from agent.authority import claim_boundary
from agent.services import copy_angle_derivation
from agent.authority.copy_family_grounding import (
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
from agent.services.poster_design_system import font_readiness, resolve_design_route


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(x) for x in value if _clean(x)]
    return []


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = _clean(text).casefold()
    return any(term in lowered for term in terms)


_VISUAL_RAW_CONCERN_TERMS = (
    "sakit",
    "kembung",
    "berangin",
    "gatal",
    "sengal",
    "kebas",
    "lenguh",
    "resdung",
    "selesema",
    "gigitan",
    "bayi",
    "anak",
    "anak susah tidur",
    "susah tidur",
    "sukar tidur",
    "loya",
    "mabuk",
    "bengkak",
    "cramp",
    "pinggang",
    "lebam",
    "hidung tersumbat",
    "perut",
    "otot",
)


def _safe_persona_phrase(values: list[str], blocked_terms: list[str]) -> str:
    """Return one approved, non-raw-concern phrase without inventing a rewrite."""

    blocked = tuple(
        term.casefold()
        for term in [*blocked_terms, *_VISUAL_RAW_CONCERN_TERMS]
        if _clean(term)
    )
    for value in values:
        phrase = _clean(value)
        if phrase and not _contains_any(phrase, blocked):
            return phrase
    return ""


def _provenance_for(grounding: CopyGrounding, field: str, fallback: str = "MISSING") -> str:
    return _clean(grounding.field_provenance.get(field)) or fallback


def _copy_word_count(copy_layout: dict[str, str] | None) -> int:
    if not copy_layout:
        return 1
    headline = _clean(
        copy_layout.get("headline")
        or copy_layout.get("primary_message")
        or copy_layout.get("hook")
    )
    words = len(headline.split())
    return 1 if words <= 4 else 2 if words <= 8 else 3


def _build_art_direction(
    product: dict[str, Any],
    grounding: CopyGrounding,
    *,
    selected_angle: str,
    objective: str,
    copy_layout: dict[str, str] | None,
) -> dict[str, Any]:
    """Resolve a typed visual territory from product evidence and copy shape.

    These are art-direction classifications, not customer-avatar claims. The
    audience is never inferred from size, category or product tokens here.
    """

    family = _clean(grounding.family).casefold()
    product_type = _clean(product.get("product_type") or product.get("type")).casefold()
    physics = _clean(product.get("physics_class")).casefold()
    scale = _clean(product.get("product_scale")).casefold()
    evidence = " ".join(
        [
            family,
            _clean(product.get("category")).casefold(),
            _clean(product.get("subcategory")).casefold(),
            _clean(product.get("product_display_name")).casefold(),
            " ".join(_clean_list(grounding.metaphor_silos)).casefold(),
        ]
    )
    heritage = _contains_any(
        evidence,
        ("heritage", "warisan", "tradisi", "tradisional", "herbal", "herba"),
    )
    beauty = _contains_any(evidence, ("beauty", "personal care", "penjagaan diri"))
    compact = scale == "small_object" or _contains_any(
        evidence, ("minyak", "roll-on", "pocket", "travel", "25ml", "25 ml")
    )

    if heritage:
        layout_family = "HERITAGE_EDITORIAL"
        territory = "heritage craft translated through a restrained modern editorial grid"
        tension = "tactile heritage cues against clean contemporary product clarity"
        type_contrast = "characterful display serif with a disciplined humanist sans"
        negative_space = "leave quiet breathing room around the heritage cue; keep ornament subordinate to label"
        anti_cliche = [
            "no generic palace, royal crest or fake historical seal",
            "no ornamental frame that competes with the registered label",
        ]
    elif beauty:
        layout_family = "ROUTINE_EDITORIAL"
        territory = "quiet personal-care editorial with material and finish doing the selling"
        tension = "soft tactile atmosphere against crisp product silhouette and readable copy"
        type_contrast = "refined display face with a neutral high-legibility sans"
        negative_space = "use calm asymmetrical breathing room; keep the product silhouette clean"
        anti_cliche = [
            "no generic spa leaves, water splash or ungrounded ingredient props",
            "no before-and-after transformation language or imagery",
        ]
    elif compact:
        layout_family = "COMPACT_STANDBY"
        territory = "intimate pocket-scale product story with a decisive first-read hook"
        tension = "small physical format against confident, never oversized, visual presence"
        type_contrast = "strong compact sans headline with a warm readable sans support"
        negative_space = "reserve a clear pocket of negative space for the short hook and a compact action cue"
        anti_cliche = [
            "no giant bottle enlargement, floating packshot or scale illusion",
            "no random family scene or symptom tableau without an approved reference",
        ]
    else:
        layout_family = "PRODUCT_HERO_SCULPTURE"
        territory = "literal product-hero composition shaped by the registered silhouette and material"
        tension = "physical product clarity against one restrained atmospheric cue"
        type_contrast = "confident display sans with a neutral readable sans support"
        negative_space = "reserve negative space according to copy length, not a fixed poster template"
        anti_cliche = [
            "no generic premium gradient, stock lifestyle tableau or decorative clutter",
            "no invented use scene, ingredient or transformation",
        ]

    angle = _clean(selected_angle)
    objective_text = _clean(objective).casefold()
    headline_personality = (
        f"{_clean(grounding.buyer_persona.tone) or 'approved buyer tone'}; "
        f"specific to the approved angle '{angle or 'approved angle strategy'}'; no vague superlatives"
    )
    product_anchor = (
        f"registered silhouette={physics or product_type or 'UNSPECIFIED'}; "
        f"catalog scale class={scale or 'UNVERIFIED'}; preserve authored geometry and never infer dimensions"
    )
    copy_anchor = (
        "headline -> support -> approved proof chips -> CTA; "
        f"headline line budget={_copy_word_count(copy_layout)}; line breaks must preserve supplied wording"
    )
    if any(token in objective_text for token in ("catalog", "marketplace", "exact")):
        cta_treatment = "compact high-contrast action label with quiet commerce confidence"
    else:
        cta_treatment = "clear action cue with editorial restraint; never a discount sticker or urgency gimmick"

    codes = [
        f"family={_clean(grounding.family) or 'UNSPECIFIED'}",
        f"product_type={_clean(product_type) or 'UNSPECIFIED'}",
    ]
    if physics:
        codes.append(f"physics_class={physics}")
    if grounding.metaphor_silos:
        codes.append("approved_metaphor_silos=" + ",".join(grounding.metaphor_silos[:3]))

    copy_chars = sum(
        len(_clean(copy_layout.get(key)))
        for key in ("headline", "primary_message", "hook", "support", "subhook", "cta")
        if copy_layout and copy_layout.get(key)
    )
    design = resolve_design_route(
        product,
        objective=objective,
        selected_angle=angle,
        copy_chars=copy_chars,
        headline_lines=_copy_word_count(copy_layout),
        audience=_clean(grounding.buyer_persona.audience),
    )
    route_data = font_readiness(design["design_route"])

    return {
        "creative_territory": territory,
        "layout_family": layout_family,
        "visual_tension": tension,
        "product_anchor": product_anchor,
        "copy_anchor": copy_anchor,
        "headline_personality": headline_personality,
        "headline_line_budget": _copy_word_count(copy_layout),
        "type_contrast": type_contrast,
        "cta_treatment": cta_treatment,
        "negative_space_strategy": negative_space,
        "brand_visual_codes": codes,
        "anti_cliche_rules": anti_cliche,
        "design_route": design["design_route"],
        "layout_variant": design["layout_variant"],
        "type_pairing_id": design["type_pairing_id"],
        "color_strategy": design["color_strategy"],
        "proof_treatment": design["proof_treatment"],
        "malaysian_context_route": design["malaysian_context_route"],
        "font_license": design["font_license"],
        "font_readiness_status": route_data["status"],
    }


def build_safe_campaign_context(
    product: dict[str, Any],
    grounding: CopyGrounding,
    *,
    operator_direction: str = "",
    objective: str = "",
    copy_layout: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Transform product intelligence into a provider-safe campaign brief.

    Persona pains, fears and symptom language are upstream intelligence, not
    poster copy. Only fields authored in the approved snapshot may personalize
    the brief; framework defaults are never presented as this product's avatar.
    Product facts remain limited to approved USPs and are never invented here.
    """

    knowledge = grounding.product_knowledge
    persona = grounding.buyer_persona
    guardrails = grounding.claim_guardrails
    blocked = [*_clean_list(guardrails.banned_terms), *_clean_list(guardrails.blocked_claims)]
    has_approved_snapshot = grounding.source == GROUNDING_APPROVED_SNAPSHOT
    audience = _clean(persona.audience) if has_approved_snapshot else ""
    desire = _safe_persona_phrase(persona.desires, blocked) if has_approved_snapshot else ""
    objection = _safe_persona_phrase(persona.objections, blocked) if has_approved_snapshot else ""
    trigger = _safe_persona_phrase(persona.triggers, blocked) if has_approved_snapshot else ""
    tone = _clean(persona.tone) if has_approved_snapshot else ""
    selected_angle = (
        _safe_persona_phrase([operator_direction], blocked)
        if has_approved_snapshot
        else ""
    )
    approved_angle = (
        _safe_persona_phrase(grounding.angle_strategies, blocked)
        if has_approved_snapshot
        else ""
    )
    safe_angle_parts = [
        part
        for part in (
            f"approved strategy: {approved_angle}" if approved_angle else "",
            f"selected direction: {selected_angle}" if selected_angle else "",
        )
        if part
    ]
    safe_angle = "; ".join(safe_angle_parts)
    approved_facts: list[str] = []
    for fact in (_clean_list(knowledge.usps) if has_approved_snapshot else []):
        if any(term.casefold() in fact.casefold() for term in blocked if term):
            continue
        if fact.casefold() not in {item.casefold() for item in approved_facts}:
            approved_facts.append(fact)
        if len(approved_facts) == 5:
            break

    provenance = {
        "buyer_persona.audience": _provenance_for(grounding, "buyer_persona.audience"),
        "buyer_persona.desires": _provenance_for(grounding, "buyer_persona.desires"),
        "buyer_persona.objections": _provenance_for(grounding, "buyer_persona.objections"),
        "buyer_persona.triggers": _provenance_for(grounding, "buyer_persona.triggers"),
        "buyer_persona.tone": _provenance_for(grounding, "buyer_persona.tone"),
        "angle_strategies": _provenance_for(grounding, "angle_strategies"),
        "product_knowledge.usps": _provenance_for(grounding, "product_knowledge.usps"),
    }
    missing: list[str] = []
    required_fields = {
        "buyer_persona.audience": audience,
        "buyer_persona.desires": desire,
        "buyer_persona.objections": objection,
        "buyer_persona.triggers": trigger,
        "buyer_persona.tone": tone,
        "angle_strategies": approved_angle,
        "product_knowledge.usps": approved_facts,
    }
    if grounding.source != GROUNDING_APPROVED_SNAPSHOT:
        missing.append("approved snapshot")
    for field, value in required_fields.items():
        provenance_value = provenance[field]
        if (not value) or (
            not provenance_value.startswith("APPROVED_SNAPSHOT")
        ):
            missing.append(field)

    art_direction = _build_art_direction(
        product,
        grounding,
        selected_angle=selected_angle,
        objective=objective,
        copy_layout=copy_layout,
    )

    return {
        "intelligence_status": "READY" if not missing else "INCOMPLETE",
        "grounding_source": _clean(grounding.source) or "MINIMAL",
        "product_family": _clean(grounding.family),
        "formula": _clean(grounding.copy_formula),
        "audience": audience,
        "desire": desire,
        "objection": objection,
        "trigger": trigger,
        "safe_angle": safe_angle,
        "tone": tone,
        "approved_facts": approved_facts,
        "missing_fields": missing,
        "field_provenance": provenance,
        "art_direction": art_direction,
    }


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
        banned_terms=claim_boundary.banned_terms_for_brief(is_stealth),
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
        field_provenance={
            "buyer_persona.audience": "FRAMEWORK_FAMILY.avatar.audience",
            "buyer_persona.desires": "FRAMEWORK_FAMILY.avatar.desires",
            "buyer_persona.objections": "FRAMEWORK_FAMILY.avatar.objections",
            "buyer_persona.triggers": "FRAMEWORK_FAMILY.avatar.triggers",
            "buyer_persona.tone": "FRAMEWORK_FAMILY.avatar.tone",
            "angle_strategies": "FRAMEWORK_FAMILY.angle_strategies",
            "product_knowledge.usps": "MISSING_APPROVED_SNAPSHOT",
        },
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


def _family_angle_templates() -> list[frozenset[str]]:
    """Every angle list the framework families hand out, as comparable sets."""
    from agent.authority.copy_family_grounding import COPY_FAMILY_GROUNDING

    out: list[frozenset[str]] = []
    for entry in (COPY_FAMILY_GROUNDING or {}).values():
        angles = (entry or {}).get("angle_strategies") or []
        if angles:
            out.append(frozenset(str(a).strip().casefold() for a in angles if str(a).strip()))
    return out


def _is_family_template(angles: list[str]) -> bool:
    """True when a snapshot's stored angles are verbatim a FAMILY template.

    Legacy contamination marker. Nothing in the current codebase writes angles,
    yet all 30 approved snapshots carried one of 7 family templates (measured
    2026-07-24) — a herbal colic oil sharing its angle list with a hair clipper.
    Matching exactly (not fuzzily) keeps this conservative: a deliberately
    authored angle list is never mistaken for contamination.
    """
    if not angles:
        return False
    got = frozenset(a.strip().casefold() for a in angles if a.strip())
    return any(got == template for template in _family_angle_templates())


def _resolve_snapshot_angles(snap: Any, persona: Any) -> list[str]:
    """Angle axis for an approved snapshot, most-trusted source first.

    1. Angles written by the A2 derivation (`angle_source` stamped) — trusted.
    2. Stored angles that are NOT a family template — a deliberate choice.
    3. Live derivation from this snapshot's OWN approved persona. This repairs
       legacy snapshots without mutating them: approved rows are immutable, and
       the persona it derives from is itself already approved, so no unreviewed
       data enters the pipeline.
    4. Stored angles / caller's framework fallback (today's behaviour).
    """
    strategy = getattr(snap, "copy_strategy_summary_json", {})
    strategy = strategy if isinstance(strategy, dict) else {}
    stored = _angles_from_strategy(strategy)

    if strategy.get("angle_source") == "DERIVED_FROM_APPROVED_PERSONA" and stored:
        return stored
    if stored and not _is_family_template(stored):
        return stored

    derivation = copy_angle_derivation.derive_angles(
        getattr(snap, "buyer_persona_snapshot_json", {}) or persona
    )
    if derivation.get("derived"):
        return [a["label"] for a in derivation["angles"]]
    return stored


def _grounding_from_snapshot(product: dict[str, Any], snap: Any) -> CopyGrounding:
    """APPROVED_SNAPSHOT tier — real product knowledge + persona + claims, with
    the framework tier filling avatar / angle / silo / route gaps."""
    fw = build_framework_grounding(product)
    raw_persona = getattr(snap, "buyer_persona_snapshot_json", {})
    raw_persona = raw_persona if isinstance(raw_persona, dict) else {}
    persona = _merge_persona(raw_persona, fw.buyer_persona)
    resolved_angles = _resolve_snapshot_angles(snap, persona)
    angles = resolved_angles or fw.angle_strategies

    persona_sources = {
        "buyer_persona.audience": "audience",
        "buyer_persona.desires": "desires",
        "buyer_persona.objections": "objections",
        "buyer_persona.triggers": "triggers",
        "buyer_persona.tone": "tone",
    }
    field_provenance: dict[str, str] = {}
    for field, key in persona_sources.items():
        if raw_persona.get(key):
            field_provenance[field] = f"APPROVED_SNAPSHOT.buyer_persona_snapshot_json.{key}"
        else:
            field_provenance[field] = fw.field_provenance.get(
                field, "MISSING_APPROVED_PERSONA_FIELD"
            )

    strategy = getattr(snap, "copy_strategy_summary_json", {})
    strategy = strategy if isinstance(strategy, dict) else {}
    stored_angles = _angles_from_strategy(strategy)
    if stored_angles and not _is_family_template(stored_angles):
        field_provenance["angle_strategies"] = (
            "APPROVED_SNAPSHOT.copy_strategy_summary_json.angles"
        )
    elif resolved_angles:
        field_provenance["angle_strategies"] = (
            "APPROVED_SNAPSHOT.buyer_persona_snapshot_json->copy_angle_derivation"
        )
    else:
        field_provenance["angle_strategies"] = fw.field_provenance.get(
            "angle_strategies", "MISSING_APPROVED_ANGLE"
        )

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
        banned_terms=claim_boundary.banned_terms_for_brief(fw.is_stealth) + blocked,
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
        field_provenance={
            **field_provenance,
            "product_knowledge.usps": "APPROVED_SNAPSHOT.usp_json",
        },
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
