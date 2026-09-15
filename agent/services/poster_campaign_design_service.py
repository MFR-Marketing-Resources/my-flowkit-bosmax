"""Campaign Design Brief resolver and deterministic copy-route scorer.

The resolver reuses the existing copy-grounding and Product Truth authorities.
It never writes to the database and never invokes a provider while resolving a
brief.  Copy-route generation has one explicit provider boundary and a
zero-spend draft fallback that is never production-ready.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from agent.db import crud
from agent.models.poster_campaign_design_brief import (
    CAMPAIGN_BRIEF_REVIEW_BLOCKED,
    CAMPAIGN_BRIEF_REVIEW_READY,
    COPY_ROUTE_AI_CANDIDATE,
    COPY_ROUTE_DRAFT_FALLBACK,
    COPY_ROUTE_PRODUCTION_READY,
    CampaignCopyRoute,
    CampaignCopyRoutesResponse,
    CopyRouteScore,
    PosterCampaignDesignBrief,
)
from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.models.poster_copy_set import validate_poster_native_lengths
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services.copy_grounding_service import (
    build_safe_campaign_context,
    resolve_copy_grounding,
)
from agent.services.poster_design_system import resolve_design_route
from agent.services.poster_copy_quality_service import evaluate_poster_copy
from agent.services.product_truth_service import ProductTruthService


COPY_ROUTE_PROMPT_VERSION = "poster-campaign-copy-routes-v1"
COPY_ROUTE_PRODUCTION_THRESHOLD = 72
_UNSUPPORTED_MARKETING_TERMS = (
    "premium",
    "terbaik",
    "nombor satu",
    "no. 1",
    "dipercayai ramai",
    "paling",
    "jamin",
    "segera",
)
_GENERIC_TERMS = (
    "kini dalam botol",
    "gaya moden",
    "pilihan terbaik",
    "untuk semua",
    "sesuai untuk seisi keluarga",
)


class CampaignDesignBriefError(ValueError):
    def __init__(self, code: str, message: str = "", *, blockers: list[str] | None = None):
        super().__init__(message or code)
        self.code = code
        self.blockers = list(blockers or [])


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    return []


def _snapshot_provenance(value: str) -> bool:
    return _clean(value).startswith("APPROVED_SNAPSHOT")


def _truth_status(product: dict[str, Any]) -> str:
    try:
        profile = ProductTruthService.build_computed_profile(product)
        preview = getattr(profile, "final_output_preview", None)
        return _clean(getattr(preview, "claim_gate", "")) or "UNVERIFIED"
    except Exception:
        return "UNVERIFIED"


def _approved_claim_status(grounding: Any, snapshot: dict[str, Any] | None) -> str:
    if snapshot is None or _clean(snapshot.get("status")).upper() != "APPROVED":
        return "UNVERIFIED"
    guard = grounding.claim_guardrails
    if guard.allowed_claims or guard.claim_gate:
        return "APPROVED_SNAPSHOT_BOUND"
    return "APPROVED_SNAPSHOT_WITHOUT_EXPLICIT_CLAIM_LIST"


def _selected_angle(context: dict[str, Any], selected: str) -> str:
    value = _clean(selected)
    if value:
        return value
    safe = _clean(context.get("safe_angle"))
    if safe.startswith("approved strategy:"):
        return safe.split(";", 1)[0].split(":", 1)[-1].strip()
    return safe


def _brief_from_context(
    product: dict[str, Any],
    context: dict[str, Any],
    grounding: Any,
    snapshot: dict[str, Any] | None,
    *,
    objective: str,
    selected_angle: str,
    copy_layout: dict[str, str] | None,
) -> PosterCampaignDesignBrief:
    product_id = _clean(product.get("id") or product.get("product_id"))
    product_name = _clean(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product_id
    )
    art = context.get("art_direction") or {}
    design = resolve_design_route(
        product,
        objective=objective,
        selected_angle=selected_angle,
        copy_chars=sum(len(_clean(value)) for value in (copy_layout or {}).values()),
        headline_lines=int(art.get("headline_line_budget") or 1),
        audience=_clean(context.get("audience")),
    )
    provenance = dict(context.get("field_provenance") or {})
    provenance.update(
        {
            "product_identity.name": "PRODUCT.product_display_name_or_raw_product_title",
            "approved_snapshot_id": "APPROVED_SNAPSHOT.snapshot_id" if snapshot else "MISSING_APPROVED_SNAPSHOT",
            "approved_snapshot_version": "APPROVED_SNAPSHOT.version" if snapshot else "MISSING_APPROVED_SNAPSHOT",
            "product_truth_status": "PRODUCT_TRUTH_SERVICE.computed_profile",
            "design_route": "POSTER_TEMPLATE_TOKENS.design_routes",
        }
    )
    blockers = list(context.get("missing_fields") or [])
    if snapshot is None:
        blockers.insert(0, "approved product-intelligence snapshot")
    if _clean((snapshot or {}).get("status")).upper() != "APPROVED":
        blockers.append("snapshot status APPROVED")
    required_provenance = (
        "buyer_persona.audience",
        "buyer_persona.desires",
        "buyer_persona.objections",
        "buyer_persona.triggers",
        "buyer_persona.tone",
        "angle_strategies",
        "product_knowledge.usps",
    )
    for field in required_provenance:
        if not _snapshot_provenance(provenance.get(field, "")):
            blockers.append(f"approved provenance:{field}")
    facts = _list(context.get("approved_facts"))[:3]
    angle = _selected_angle(context, selected_angle)
    reason = facts[0] if facts else ""
    approved_claims_status = _approved_claim_status(grounding, snapshot)
    if approved_claims_status == "UNVERIFIED":
        blockers.append("approved claims boundary")
    prohibited = list(grounding.claim_guardrails.blocked_claims)
    prohibited.extend(grounding.claim_guardrails.banned_terms[:12])
    prohibited.extend(
        [
            "unsupported ingredients, dimensions, certification, price or urgency",
            "generic Malaysian shorthand detached from product ritual",
        ]
    )
    brief_status = CAMPAIGN_BRIEF_REVIEW_READY if not blockers else CAMPAIGN_BRIEF_REVIEW_BLOCKED
    return PosterCampaignDesignBrief(
        product_id=product_id,
        product_name=product_name,
        approved_snapshot_id=_clean((snapshot or {}).get("snapshot_id")),
        approved_snapshot_version=(snapshot or {}).get("version"),
        product_truth_status=_truth_status(product),
        approved_claims_status=approved_claims_status,
        audience=_clean(context.get("audience")),
        buyer_moment=_clean(context.get("trigger")),
        desire=_clean(context.get("desire")),
        objection=_clean(context.get("objection")),
        trigger=_clean(context.get("trigger")),
        selected_message_angle=angle,
        singular_proposition=angle,
        reason_to_believe=reason,
        approved_proof_points=facts,
        tone=_clean(context.get("tone")),
        creative_territory=_clean(art.get("creative_territory")),
        visual_metaphor_or_thesis=_clean(art.get("creative_territory")),
        layout_family=_clean(design.get("design_route")),
        visual_tension=_clean(art.get("visual_tension")),
        product_anchor=_clean(art.get("product_anchor")),
        copy_anchor=_clean(art.get("copy_anchor")),
        headline_personality=_clean(art.get("headline_personality")),
        headline_line_budget=int(art.get("headline_line_budget") or 1),
        type_pairing_id=_clean(design.get("type_pairing_id")),
        color_strategy=_clean(design.get("color_strategy")),
        cta_treatment=_clean(art.get("cta_treatment")),
        proof_treatment=_clean(design.get("proof_treatment")),
        malaysian_context_route=_clean(design.get("malaysian_context_route")),
        anti_cliche_rules=(list(art.get("anti_cliche_rules") or []) + list(design.get("anti_cliche_rules") or []))[:12],
        prohibited_claims_and_visuals=prohibited[:30],
        field_provenance=provenance,
        missing_field_blockers=sorted(set(_clean(item) for item in blockers if _clean(item))),
        review_status=brief_status,
        design_route=_clean(design.get("design_route")),
        layout_variant=_clean(design.get("layout_variant")),
        objective=_clean(objective),
    )


async def build_campaign_design_brief(
    product_id: str,
    *,
    objective: str = "Product Hero",
    selected_angle: str = "",
    copy_layout: dict[str, str] | None = None,
    fail_closed: bool = False,
) -> PosterCampaignDesignBrief:
    """Resolve the brief read-only from the current product and approved data."""

    product = await crud.get_product(_clean(product_id))
    if not product:
        raise CampaignDesignBriefError("PRODUCT_NOT_FOUND")
    product_dict = dict(product)
    grounding = await resolve_copy_grounding(product_dict)
    context = build_safe_campaign_context(
        product_dict,
        grounding,
        operator_direction=selected_angle,
        objective=objective,
        copy_layout=copy_layout,
    )
    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(_clean(product_id))
    brief = _brief_from_context(
        product_dict,
        context,
        grounding,
        dict(snapshot) if snapshot else None,
        objective=objective,
        selected_angle=selected_angle,
        copy_layout=copy_layout,
    )
    if fail_closed and brief.missing_field_blockers:
        raise CampaignDesignBriefError(
            "CAMPAIGN_INTELLIGENCE_INCOMPLETE",
            "; ".join(brief.missing_field_blockers),
            blockers=brief.missing_field_blockers,
        )
    return brief


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[\wÀ-ÿ']+", _clean(text).casefold()) if word]


def _contains_phrase(text: str, phrase: str) -> bool:
    return _clean(phrase).casefold() in _clean(text).casefold()


def score_campaign_copy_route(
    candidate: dict[str, Any],
    brief: PosterCampaignDesignBrief,
    *,
    existing_candidates: list[dict[str, Any]] | None = None,
) -> tuple[CopyRouteScore, list[str]]:
    """Score one candidate without an AI call or mutable state."""

    headline = _clean(candidate.get("primary_message"))
    support = _clean(candidate.get("support_message"))
    proofs = [_clean(item) for item in candidate.get("approved_proof_points") or candidate.get("proof_points") or [] if _clean(item)]
    cta = _clean(candidate.get("cta"))
    blob = " ".join([headline, support, *proofs, cta])
    blockers: list[str] = []
    length_errors = validate_poster_native_lengths(
        {
            "primary_message": headline,
            "support_message": support,
            "proof_points": proofs,
            "cta": cta,
        }
    )
    blockers.extend(f"COPY_LENGTH_INVALID:{error}" for error in length_errors)
    unsupported = [term for term in _UNSUPPORTED_MARKETING_TERMS if _contains_phrase(blob, term)]
    generic = [term for term in _GENERIC_TERMS if _contains_phrase(blob, term)]
    if unsupported:
        blockers.append("UNSUPPORTED_SUPERLATIVE:" + ",".join(unsupported))
    if generic:
        blockers.append("GENERIC_PHRASE:" + ",".join(generic))
    quality = evaluate_poster_copy(
        PosterCopyQualityRequest(
            archetype="PRODUCT_HERO",
            poster_headline=headline,
            poster_support_line=support,
            poster_chips=proofs,
            poster_cta=cta,
            max_chips=3,
        )
    )
    if any(f.severity == "BLOCK" for f in quality.findings):
        blockers.extend(sorted({f.code for f in quality.findings if f.severity == "BLOCK"}))
    product_name_tokens = set(_words(brief.product_name or brief.product_id))
    specificity = 8 if product_name_tokens and product_name_tokens & set(_words(blob)) else 4
    relevance_tokens = set(_words(" ".join([brief.audience, brief.desire, brief.buyer_moment])))
    relevance = min(10, 4 + len(relevance_tokens & set(_words(blob))))
    comprehension = 9 if headline and len(_words(headline)) <= 7 else 5
    reason = 8 if proofs or _contains_phrase(blob, brief.reason_to_believe) else 3
    tension = 7 if brief.singular_proposition and _contains_phrase(blob, brief.singular_proposition) else 4
    natural = 8 if any(word in blob.casefold() for word in ("untuk", "dengan", "dapatkan", "pilih", "kenali", "harian")) else 5
    proof_relevance = min(10, 3 + sum(2 for fact in brief.approved_proof_points if _contains_phrase(blob, fact)))
    non_redundancy = 3 if _contains_phrase(headline, support) or _contains_phrase(support, headline) else 8
    if headline and support:
        shorter = headline if len(_words(headline)) <= len(_words(support)) else support
        longer = support if shorter == headline else headline
        if len(_words(shorter)) >= 2 and _contains_phrase(longer, shorter):
            blockers.append("SUPPORT_REPEATS_HEADLINE")
    visual_fit = 9 if len(headline) <= 48 and len(support) <= 72 and len(cta) <= 24 else 3
    prior_text = " ".join(
        _clean(item.get("primary_message")) for item in (existing_candidates or [])
    )
    differentiation = 4 if prior_text and _contains_phrase(prior_text, headline) else 8
    claim_safety = 2 if unsupported else 9
    provenance = 9 if proofs and all(
        any(_contains_phrase(fact, proof) or _contains_phrase(proof, fact) for fact in brief.approved_proof_points)
        for proof in proofs
    ) else (6 if not proofs else 3)
    raw = (
        specificity * 1.0
        + relevance * 1.0
        + comprehension * 0.8
        + reason * 1.0
        + tension * 0.8
        + natural * 0.8
        + proof_relevance * 0.8
        + non_redundancy * 0.8
        + visual_fit * 0.8
        + differentiation * 0.8
        + claim_safety * 1.2
        + provenance * 1.2
    )
    total = max(0, min(100, round(raw / 1.14)))
    return CopyRouteScore(
        product_specificity=round(specificity),
        customer_relevance=round(relevance),
        immediate_comprehension=round(comprehension),
        reason_to_believe=round(reason),
        emotional_commercial_tension=round(tension),
        natural_malaysian_malay=round(natural),
        proof_relevance=round(proof_relevance),
        non_redundancy=round(non_redundancy),
        visual_fit_line_budget=round(visual_fit),
        differentiation=round(differentiation),
        claim_safety=round(claim_safety),
        approved_fact_provenance=round(provenance),
        total=total,
    ), sorted(set(blockers))


def _fallback_candidates(brief: PosterCampaignDesignBrief) -> list[dict[str, Any]]:
    name = _clean(brief.product_name or brief.product_id) or "Produk berdaftar"
    moment = _clean(brief.buyer_moment) or "pilihan anda"
    fact = brief.approved_proof_points[:1]
    return [
        {"singular_proposition": brief.singular_proposition, "primary_message": f"Kenali {name}", "support_message": f"Pilihan berasas untuk {moment}.", "proof_points": fact, "cta": "Ketahui lebih lanjut", "tone": brief.tone or "neutral"},
        {"singular_proposition": brief.singular_proposition, "primary_message": f"{name}, lebih dekat", "support_message": f"Dibina untuk detik {moment}.", "proof_points": fact, "cta": "Lihat produk", "tone": brief.tone or "neutral"},
        {"singular_proposition": brief.singular_proposition, "primary_message": f"Pilihan {name}", "support_message": "Satu idea, jelas untuk dipilih.", "proof_points": fact, "cta": "Terokai pilihan", "tone": brief.tone or "neutral"},
        {"singular_proposition": brief.singular_proposition, "primary_message": f"Bawa {name} bersama", "support_message": "Kenali produk melalui konteks sebenar.", "proof_points": fact, "cta": "Ketahui lebih lanjut", "tone": brief.tone or "neutral"},
        {"singular_proposition": brief.singular_proposition, "primary_message": f"{name}, satu sebab", "support_message": f"Berpandukan {brief.reason_to_believe or 'fakta diluluskan'}.", "proof_points": fact, "cta": "Lihat sekarang", "tone": brief.tone or "neutral"},
    ]


def _normalise_provider_candidate(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "route_id": _clean(item.get("route_id")) or f"AI_ROUTE_{index:02d}",
        "singular_proposition": _clean(item.get("singular_proposition")),
        "primary_message": _clean(item.get("primary_message")),
        "support_message": _clean(item.get("support_message")),
        "proof_points": [_clean(value) for value in item.get("proof_points") or item.get("approved_proof_points") or [] if _clean(value)],
        "cta": _clean(item.get("cta")),
        "tone": _clean(item.get("tone")),
        "intended_buyer_moment": _clean(item.get("intended_buyer_moment")),
        "reason_to_believe": _clean(item.get("reason_to_believe")),
    }


def _copy_routes_prompt(brief: PosterCampaignDesignBrief) -> str:
    facts = "; ".join(brief.approved_proof_points) or "none"
    return (
        "Return STRICT JSON only with exactly five materially distinct poster copy routes. "
        "Do not invent claims. Each route has one proposition, one headline, one complete support line, "
        "up to three approved proof points and one CTA. Natural Malaysian Malay; no generic superlatives.\n"
        f"PRODUCT_ID={brief.product_id}\nAUDIENCE={brief.audience}\nBUYER_MOMENT={brief.buyer_moment}\n"
        f"DESIRE={brief.desire}\nOBJECTION={brief.objection}\nTRIGGER={brief.trigger}\n"
        f"ANGLE={brief.selected_message_angle}\nAPPROVED_FACTS={facts}\n"
        'JSON shape: {"routes":[{"route_id":str,"singular_proposition":str,"primary_message":str,'
        '"support_message":str,"proof_points":[str],"cta":str,"tone":str,'
        '"intended_buyer_moment":str,"reason_to_believe":str}]}.'
    )


def generate_campaign_copy_routes(
    brief: PosterCampaignDesignBrief,
    *,
    invoke_provider: bool = False,
    provider_complete: Callable[[str, str], dict[str, Any]] | None = None,
) -> CampaignCopyRoutesResponse:
    """Generate/score five routes with exactly one explicit provider boundary."""

    raw_candidates: list[dict[str, Any]] = []
    operation_count = 0
    warnings: list[str] = []
    if invoke_provider:
        if not brief.missing_field_blockers:
            complete = provider_complete or ai_provider.complete_json
            operation_count = 1
            raw = complete(
                "You are a strict Malaysian e-commerce poster copy strategist. Never invent product facts.",
                _copy_routes_prompt(brief),
            )
            payload = raw.get("routes") if isinstance(raw, dict) else []
            raw_candidates = [
                _normalise_provider_candidate(item, i)
                for i, item in enumerate(payload or [], 1)
                if isinstance(item, dict)
            ][:5]
        else:
            warnings.append("COPY_ROUTE_PROVIDER_BLOCKED:CAMPAIGN_INTELLIGENCE_INCOMPLETE")
    if not raw_candidates:
        raw_candidates = _fallback_candidates(brief)
        warnings.append("DRAFT_FALLBACK_NOT_PRODUCTION")
    while len(raw_candidates) < 5:
        raw_candidates.extend(_fallback_candidates(brief)[len(raw_candidates) : len(raw_candidates) + 1])
    raw_candidates = raw_candidates[:5]

    output: list[CampaignCopyRoute] = []
    rejected: list[dict[str, Any]] = []
    for index, item in enumerate(raw_candidates, 1):
        score, reasons = score_campaign_copy_route(item, brief, existing_candidates=raw_candidates[: index - 1])
        status = COPY_ROUTE_AI_CANDIDATE if invoke_provider else COPY_ROUTE_DRAFT_FALLBACK
        if (
            invoke_provider
            and not reasons
            and score.total >= COPY_ROUTE_PRODUCTION_THRESHOLD
            and not brief.missing_field_blockers
        ):
            status = COPY_ROUTE_PRODUCTION_READY
        eligible = (
            invoke_provider
            and not reasons
            and score.total >= COPY_ROUTE_PRODUCTION_THRESHOLD
            and not brief.missing_field_blockers
        )
        route = CampaignCopyRoute(
            route_id=_clean(item.get("route_id")) or f"ROUTE_{index:02d}",
            singular_proposition=_clean(item.get("singular_proposition")) or brief.singular_proposition,
            primary_message=_clean(item.get("primary_message")),
            support_message=_clean(item.get("support_message")),
            approved_proof_points=[_clean(p) for p in item.get("proof_points") or [] if _clean(p)][:3],
            cta=_clean(item.get("cta")),
            tone=_clean(item.get("tone")) or brief.tone,
            intended_buyer_moment=_clean(item.get("intended_buyer_moment")) or brief.buyer_moment,
            reason_to_believe=_clean(item.get("reason_to_believe")) or brief.reason_to_believe,
            copy_provenance={
                "source": "AI_SINGLE_OPERATION" if invoke_provider else "DETERMINISTIC_DRAFT_FALLBACK",
                "prompt_version": COPY_ROUTE_PROMPT_VERSION,
                "brief_schema_version": brief.schema_version,
            },
            score=score,
            rejected_reasons=reasons,
            status=status,
            production_eligible=eligible,
        )
        output.append(route)
        if reasons:
            rejected.append({"route_id": route.route_id, "reasons": reasons})
    ranked = sorted(output, key=lambda item: (-item.score.total, item.route_id))
    top_three = [item.route_id for item in ranked[:3]]
    return CampaignCopyRoutesResponse(
        product_id=brief.product_id,
        candidates=output,
        top_three_route_ids=top_three,
        rejected_candidate_reasons=rejected,
        auto_selected=False,
        production_threshold=COPY_ROUTE_PRODUCTION_THRESHOLD,
        provider_operation_count=operation_count,
        hidden_retry_count=0,
        warnings=warnings,
    )
