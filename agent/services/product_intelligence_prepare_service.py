"""Prepare Product for Copywriting — the upstream DeepSeek lane.

Given a product, use the configured text_assist lane to DRAFT a full copywriting
foundation (Product Knowledge + Customer Avatar + Market Problem Language +
Situation/Desire/Objection/Trigger + Claim Boundary + Recommended Formula +
Formula Breakdown), then persist it as a product_intelligence_review_draft for
operator review/approval. NEVER auto-approves — the operator promotes the draft
into an approved snapshot through the existing lifecycle.

Reuses ai_copy_provider_adapter.complete_json (generic structured-JSON seam over
the text_assist lane) and create_review_draft. The buyer_persona /
copy_strategy JSON keys match exactly what the copy-grounding resolver reads, so
once approved the copy engine is immediately grounded + formula-ready.

Provider calls spend tokens — this lane is operator-initiated. Tests mock
complete_json.
"""
from __future__ import annotations

import json
from typing import Any

from agent.authority import claim_boundary
from agent.authority.copy_formula_registry import (
    list_formulas,
    normalize_formula_id,
    recommend_formula,
)
from agent.db import crud
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewFieldProvenanceInput,
)
from agent.services import ai_copy_provider_adapter as provider
from agent.services.copy_grounding_service import resolve_copy_grounding
from agent.services.copy_set_service import CopySetError
from agent.services.product_intelligence_review_draft_service import create_review_draft

_PERSONA_KEYS = ("audience", "desires", "fears", "pains", "objections", "triggers", "tone", "pronoun")

# The fields we tag with AI provenance so review makes the AI source obvious.
_AI_PROVENANCE_FIELDS = (
    "product_description", "benefits_json", "usp_json", "target_customer_text",
    "buyer_persona_snapshot_json", "copy_strategy_summary_json",
)


def _s(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_s(v) for v in value if _s(v)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _product_name(product: dict[str, Any]) -> str:
    return _s(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product.get("name")
    )


def _build_prompt(product: dict[str, Any], grounding: Any) -> tuple[str, str]:
    formula_ids = ", ".join(f["formula_id"] for f in list_formulas())
    persona = getattr(grounding, "buyer_persona", None)
    system = (
        "You are BOSMAX's product copywriting preparation brain for the Malaysian "
        "TikTok Shop market. Given a product, produce a STRICT JSON object that "
        "prepares it for formula-driven selling copy. Return ONLY JSON with keys:\n"
        "product_knowledge: {description, benefits[], usps[], usage, ingredients, "
        "warnings, target_customer}\n"
        "customer_avatar: {audience, desires[], fears[], pains[], objections[], "
        "triggers[], tone, pronoun}\n"
        "market_problem_language: [the REAL words a buyer uses for the problem — "
        "e.g. kembung perut, perut berangin, anak susah lena, gigitan serangga, "
        "sengal, kebas, resdung. PRESERVE this language; never vague.]\n"
        "situation, desire, objection, trigger, use_context: short strings\n"
        "claim_boundary: {allowed_claims[], overclaim_notes[]}\n"
        f"recommended_formula: one of [{formula_ids}]\n"
        "formula_breakdown: {slot_id: text} for the recommended formula\n\n"
        "RULES: Ground everything in the product truth given. Preserve the "
        "customer's real problem language so a buyer instantly understands what "
        "the product is for. Control ONLY overclaim — no cure/treat/guarantee/"
        "100%/clinical/certification claims, and for sensitive products never name "
        "explicit anatomy. Do not invent certifications or clinical proof."
    )
    seed_avatar = {
        "family": getattr(grounding, "family", ""),
        "is_stealth": getattr(grounding, "is_stealth", False),
        "framework_audience": getattr(persona, "audience", ""),
        "framework_pains": list(getattr(persona, "pains", []) or []),
        "framework_triggers": list(getattr(persona, "triggers", []) or []),
        "angle_strategies": list(getattr(grounding, "angle_strategies", []) or []),
    }
    user = json.dumps(
        {
            "product_name": _product_name(product),
            "category": _s(product.get("category")),
            "product_class": _s(product.get("type")),
            "size_or_volume": _s(product.get("size_or_volume")),
            "existing_description": _s(product.get("product_description")),
            "framework_seed": seed_avatar,
        },
        ensure_ascii=True,
    )
    return system, user


def _coerce_persona(avatar: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _PERSONA_KEYS:
        val = avatar.get(key)
        if key in ("audience", "tone", "pronoun"):
            if _s(val):
                out[key] = _s(val)
        else:
            lst = _list(val)
            if lst:
                out[key] = lst
    return out


def _sanitize_claims(
    ai: dict[str, Any], pk: dict[str, Any], boundary: dict[str, Any], is_stealth: bool
) -> tuple[list[str], list[str]]:
    """NEVER persist overclaim as an allowed claim. Scan the AI draft with the
    claim boundary: keep only claim-safe allowed_claims, and move every overclaim
    (from allowed_claims or found anywhere in knowledge/benefits/usps/breakdown)
    into the blocked/overclaim notes. Market / problem language is preserved —
    claim_boundary never flags kembung perut / perut berangin / gigitan serangga /
    legakan / etc. This closes the coverage gap vs the narrower claim_safety scan."""
    raw_allowed = _list(boundary.get("allowed_claims"))
    safe_allowed: list[str] = []
    moved: list[str] = []
    for claim in raw_allowed:
        if claim_boundary.assess_claim_boundary(claim, is_stealth)["safe"]:
            safe_allowed.append(claim)
        else:
            moved.append(claim)
    breakdown = ai.get("formula_breakdown") if isinstance(ai.get("formula_breakdown"), dict) else {}
    scan_blob = " || ".join(
        [_s(pk.get("description")), *_list(pk.get("benefits")), *_list(pk.get("usps"))]
        + [_s(v) for v in breakdown.values()]
    )
    overclaim_hits = claim_boundary.assess_claim_boundary(scan_blob, is_stealth)["overclaim_hits"]
    blocked: list[str] = []
    for item in _list(boundary.get("overclaim_notes")) + moved + overclaim_hits:
        if item and item not in blocked:
            blocked.append(item)
    return safe_allowed, blocked


def _to_create_request(
    ai: dict[str, Any], grounding: Any
) -> tuple[ProductIntelligenceReviewDraftCreateRequest, str]:
    pk = ai.get("product_knowledge") or {}
    avatar = ai.get("customer_avatar") or {}
    boundary = ai.get("claim_boundary") or {}

    persona = _coerce_persona(avatar)
    recommended = normalize_formula_id(ai.get("recommended_formula")) if ai.get("recommended_formula") else recommend_formula(
        is_stealth=getattr(grounding, "is_stealth", False),
        family=getattr(grounding, "family", ""),
    )
    copy_strategy = {
        "recommended_formula": recommended,
        "angles": _list(ai.get("angles")) or list(getattr(grounding, "angle_strategies", []) or []),
        "market_problem_language": _list(ai.get("market_problem_language")),
        "formula_breakdown": ai.get("formula_breakdown") if isinstance(ai.get("formula_breakdown"), dict) else {},
        "situation": _s(ai.get("situation")),
        "desire": _s(ai.get("desire")),
        "objection": _s(ai.get("objection")),
        "trigger": _s(ai.get("trigger")),
        "use_context": _s(ai.get("use_context")),
    }
    # Claim-boundary sanitization: overclaim is NEVER persisted as an allowed claim.
    is_stealth = bool(getattr(grounding, "is_stealth", False))
    safe_allowed, blocked_claims = _sanitize_claims(ai, pk, boundary, is_stealth)

    provenance = [
        ProductIntelligenceReviewFieldProvenanceInput(
            field_name=field,
            source_type="AI_PREPARE_LANE",
            source_lane="text_assist",
            evidence_kind="AI_DRAFT",
            extraction_method="AI_TEXT_ASSIST",
            verification_status="PENDING_REVIEW",
        )
        for field in _AI_PROVENANCE_FIELDS
    ]

    request = ProductIntelligenceReviewDraftCreateRequest(
        product_description=_s(pk.get("description")) or None,
        benefits_json=_list(pk.get("benefits")),
        usp_json=_list(pk.get("usps")),
        usage_text=_s(pk.get("usage")) or None,
        ingredients_text=_s(pk.get("ingredients")) or None,
        warnings_text=_s(pk.get("warnings")) or None,
        target_customer_text=_s(pk.get("target_customer")) or _s(avatar.get("audience")) or None,
        allowed_claims_json=safe_allowed,
        blocked_claims_json=blocked_claims,
        buyer_persona_snapshot_json=persona,
        copy_strategy_summary_json=copy_strategy,
        created_by="ai_prepare_lane",
        provenance_items=provenance,
    )
    return request, recommended


async def prepare_product_for_copywriting(product_id: str) -> dict[str, Any]:
    """Draft a full copywriting foundation for a product via the text_assist lane
    and persist it as a review draft (never approved). Fails closed on missing
    product / unconfigured provider / invalid AI JSON."""
    product = await crud.get_product(product_id)
    if not product:
        raise CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": product_id})

    grounding = await resolve_copy_grounding(product)
    system, user = _build_prompt(product, grounding)
    ai = provider.complete_json(system, user)  # raises NotConfigured / Error
    if not isinstance(ai, dict) or not ai:
        raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID)

    request, recommended = _to_create_request(ai, grounding)
    draft = await create_review_draft(product_id, request)
    boundary_report = claim_boundary.assess_claim_boundary(
        json.dumps(ai, ensure_ascii=True), is_stealth=getattr(grounding, "is_stealth", False)
    )
    return {
        "review_draft_id": draft.draft_id,
        "review_status": draft.review_status,
        "recommended_formula": recommended,
        "grounding_source": grounding.source,
        "claim_boundary": boundary_report,
        "draft": draft.model_dump(),
    }
