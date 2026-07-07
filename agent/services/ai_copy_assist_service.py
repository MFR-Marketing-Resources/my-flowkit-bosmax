"""AI Copy Assist V1 — controlled candidate Copy Set generator.

Produces REVIEWABLE candidate Copy Sets only. It grounds generation in product
truth, calls the provider adapter (disabled by default), sanitizes the output,
runs the EXISTING Copy Set claim-risk + completeness checks, enforces the EXISTING
dedupe, and persists candidates as `COPY_REVIEW_REQUIRED` — NEVER approved, never
bound into the deterministic final compiler.

Reuses `copy_set_service` primitives (normalize / dedupe / safety / completeness)
so AI candidates obey the same lifecycle as every other Copy Set. The provider's
raw prompt/response never enters the copy fields; only the clean copy crosses into
`to_compiler_copy(...)` later, and only after explicit operator approval.
"""
from __future__ import annotations

import json
from typing import Any

from agent.db import crud
from agent.services import ai_copy_provider_adapter as provider
from agent.models.copy_set import (
    SOURCE_AI_COPY_ASSIST,
    STATUS_COPY_REVIEW_REQUIRED,
    AICopyAssistRequest,
    normalize_usp_set,
    serialize_copy_set,
)
from agent.services.copy_set_service import (
    CopySetError,
    _clean,
    _dedupe_key_for,
    _normalize_fields,
    assess_copy_completeness,
    scan_copy_safety,
)
from agent.models.copy_grounding import CopyGrounding
from agent.services.copy_grounding_service import resolve_copy_grounding

# Privacy-sensitive strategy, sourced from the concepts in
# agent/authority/COPYWRITING_FRAMEWORK_UNIVERSAL.yaml (stealth_mode /
# stealth_sensitive_triggers). Guides the AI when a product routes STEALTH.
_STEALTH_STRATEGY = (
    "STEALTH / privacy-sensitive product: NEVER name the body part, medical "
    "condition, or intimate/sexual function explicitly. Sell through wrapped "
    "metaphor, ego / maruah (masculine pride & dignity) and self-confidence "
    "pressure, and everyday-routine framing. Keep every line dialogue-safe and "
    "TikTok platform-compliant. No health/medical outcomes, no performance or "
    "cure claims."
)


def _product_truth(product: dict[str, Any]) -> str:
    return _clean(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product.get("name")
    )


def _rotation_angles(req: AICopyAssistRequest, grounding: CopyGrounding) -> list[str]:
    """Distinct strategic angles to rotate across candidates so a batch covers
    DIFFERENT angles (not the same one reworded). Empty when the operator pinned
    an explicit angle (then that single angle steers every candidate)."""
    if _clean(getattr(req, "angle", "")):
        return []
    return list(grounding.angle_strategies or [])


def _build_brief(
    req: AICopyAssistRequest,
    product: dict[str, Any],
    grounding: CopyGrounding,
    target_angle: str = "",
) -> str:
    """Grounded brief for the provider: product truth + product knowledge +
    customer avatar + the assigned strategic angle + claim guardrails.

    Product FACTS (benefits/USPs) are only present when an approved snapshot
    exists — never invented. Signal fields are strategy guidance; the provider is
    told never to print codes/ids as copy."""
    g = grounding
    pk = g.product_knowledge
    persona = g.buyer_persona
    cg = g.claim_guardrails
    brief = {
        "product_name": _product_truth(product),
        "category": _clean(product.get("category")),
        "product_class": _clean(product.get("type")),
        "grounding_source": g.source,
        "family": g.family,
        "sensitivity": "STEALTH" if g.is_stealth else "",
        # ── customer avatar — the root of a real angle ──
        "avatar_audience": persona.audience,
        "avatar_desires": persona.desires,
        "avatar_fears": persona.fears,
        "avatar_pains": persona.pains,
        "avatar_objections": persona.objections,
        "avatar_triggers": persona.triggers,
        "tone": persona.tone,
        "pronoun": persona.pronoun,
        # ── product knowledge — real facts only (empty until an approved snapshot) ──
        "product_description": pk.description,
        "product_benefits": pk.benefits,
        "product_usps": pk.usps,
        "target_customer": pk.target_customer,
        # ── angle strategy ──
        "target_angle_strategy": target_angle,
        "available_angle_strategies": g.angle_strategies,
        "copy_formula_hint": g.copy_formula,
        "metaphor_silos": g.metaphor_silos,
        # ── request settings ──
        "existing_angle": _clean(product.get("copywriting_angle")),
        "platform": _clean(req.platform) or "TIKTOK",
        "language": _clean(req.language) or "BM_MS",
        "route_type": _clean(req.route_type) or g.effective_route or "DIRECT",
        "formula_family": _clean(req.formula_family) or "HSO",
        "content_style_mode": _clean(req.content_style_mode) or "UGC_IPHONE",
        "desired_angle": _clean(req.angle),
        "hook_direction": _clean(req.hook),
        "operator_notes": _clean(req.operator_notes),
        "strategy": _STEALTH_STRATEGY if g.is_stealth else "",
        # ── claim guardrails ──
        "claim_gate": cg.claim_gate,
        "claim_risk_level": cg.claim_risk_level,
        "allowed_claims": cg.allowed_claims,
        "banned_terms": cg.banned_terms,
        "instruction": (
            "Derive the angle from ONE specific buyer pain or desire in the avatar "
            "(use target_angle_strategy if given). Build hook -> subhook -> USPs -> "
            "CTA from that angle + avatar. Ground USPs in product_benefits/product_usps "
            "when present; do NOT invent product outcomes or claims. Obey banned_terms "
            "and claim_gate."
        ),
    }
    return json.dumps(
        {k: v for k, v in brief.items() if v not in ("", [], None)},
        ensure_ascii=True,
    )


def _merge_candidate_fields(
    ai: dict[str, Any], req: AICopyAssistRequest, grounding: CopyGrounding
) -> dict[str, Any]:
    """AI output populates the copy fields; an explicit operator field overrides
    the AI value for that field. Result is run through the shared normalizer.

    When the operator did not set a route, stealth products auto-route STEALTH
    (which keeps them review-gated); non-stealth products stay DIRECT as before."""
    stealth_route = grounding.effective_route if grounding.is_stealth else "DIRECT"
    fields = {
        "angle": req.angle if req.angle is not None else ai.get("angle"),
        "hook": req.hook if req.hook is not None else ai.get("hook"),
        "subhook": req.subhook if req.subhook is not None else ai.get("subhook"),
        "usp_set": normalize_usp_set(
            req.usp_set if req.usp_set is not None else ai.get("usp_set")
        ),
        "cta": req.cta if req.cta is not None else ai.get("cta"),
        "formula_family": req.formula_family or ai.get("formula_family") or "HSO",
        "route_type": req.route_type or stealth_route,
        "platform": req.platform or "TIKTOK",
        "language": req.language or "BM_MS",
    }
    return _normalize_fields(fields)


def _internal_provenance(ai: dict[str, Any]) -> dict[str, Any]:
    """Internal-only provenance. NEVER consumed by the compiler (to_compiler_copy
    reads copy fields only). Raw provider response is not stored verbatim."""
    status = provider.provider_status()
    risk_notes = ai.get("risk_notes")
    return {
        "resolver": "ai_copy_assist_service",
        "source": SOURCE_AI_COPY_ASSIST,
        "provider_lane": status.get("lane"),
        "provider_id": status.get("provider_id"),
        "rationale": _clean(ai.get("rationale"))[:500],
        "risk_notes": [ _clean(r) for r in risk_notes if _clean(r) ]
        if isinstance(risk_notes, list)
        else [],
    }


async def _generate_one(
    req: AICopyAssistRequest,
    product: dict[str, Any],
    grounding: CopyGrounding | None = None,
    target_angle: str = "",
) -> dict[str, Any]:
    if grounding is None:
        grounding = await resolve_copy_grounding(product)
    ai = provider.generate_candidate(_build_brief(req, product, grounding, target_angle))
    if not isinstance(ai, dict):
        raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID)

    fields = _merge_candidate_fields(ai, req, grounding)
    completeness = assess_copy_completeness(fields)
    safety = scan_copy_safety(fields, product_id=req.product_id)

    dedupe_key = _dedupe_key_for(req.product_id, fields)
    existing = await crud.find_copy_set_by_dedupe_key(dedupe_key)
    if existing:
        return {
            "copy_set": serialize_copy_set(existing),
            "created": False,
            "dedupe_match": True,
            "safety": safety,
            "warnings": ["DEDUPE_MATCH_EXISTING_COPY_SET"],
        }

    warnings: list[str] = []
    if not completeness["complete"]:
        warnings.append("COPY_INCOMPLETE")
    if not safety["safe"]:
        warnings.extend(safety["violations"])

    # AI-generated copy ALWAYS enters review — never DRAFT-clean, never approved.
    claim_review = {
        "completeness": completeness,
        "safety": safety,
        "route_type": fields["route_type"],
        "ai_generated": True,
    }
    row = await crud.create_copy_set(
        req.product_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"]),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        status=STATUS_COPY_REVIEW_REQUIRED,
        dedupe_key=dedupe_key,
        source=SOURCE_AI_COPY_ASSIST,
        provenance_json=json.dumps(_internal_provenance(ai)),
        claim_review_json=json.dumps(claim_review),
    )
    return {
        "copy_set": serialize_copy_set(row),
        "created": True,
        "dedupe_match": False,
        "safety": safety,
        "warnings": warnings,
    }


async def generate_ai_copy_candidate(
    request: AICopyAssistRequest | dict,
) -> dict[str, Any]:
    """Generate up to `candidate_count` reviewable candidate Copy Sets.
    Fails closed on: product not found, insufficient product truth, provider not
    configured, or invalid provider response. Never approves, never binds."""
    req = (
        request
        if isinstance(request, AICopyAssistRequest)
        else AICopyAssistRequest.model_validate(request)
    )
    product = await crud.get_product(req.product_id)
    if not product:
        raise CopySetError(
            "PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": req.product_id}
        )
    if not _product_truth(product):
        raise CopySetError(
            "PRODUCT_TRUTH_INSUFFICIENT",
            status_code=422,
            detail={"product_id": req.product_id},
        )

    # Provider adapter raises AICopyProviderNotConfigured / AICopyProviderError —
    # the router maps them to fail-closed responses.
    grounding = await resolve_copy_grounding(product)
    angles = _rotation_angles(req, grounding)
    candidates = [
        await _generate_one(
            req, product, grounding, angles[i % len(angles)] if angles else ""
        )
        for i in range(req.candidate_count)
    ]
    return {"provider": provider.provider_status(), "candidates": candidates}


async def generate_ai_copy_candidates_batch(
    request,
) -> dict[str, Any]:
    """Generate requested_count candidates in a single batch request.

    Each candidate is independently generated, deduped, safety-scanned,
    and similarity-scored against existing approved Copy Sets for the
    same product.  A copy_generation_batch ledger row records the run.

    When ``dry_run`` is True, product and provider validation runs but
    nothing is persisted (no Copy Set rows, no ledger row). The provider
    is NOT called in dry_run mode.

    ``rejected_count`` counts only candidates that could NOT be persisted
    (e.g. provider returned invalid output). Unsafe/incomplete candidates
    that ARE persisted for operator review are counted as warnings, not
    rejected.

    Fails closed on: product not found, insufficient product truth,
    provider not configured, or invalid provider response.
    """
    from agent.models.copy_set import AICopyAssistBatchRequest as BReq
    from agent.services import copy_similarity_service as sim_svc

    req = request if isinstance(request, BReq) else BReq.model_validate(request)
    product = await crud.get_product(req.product_id)
    if not product:
        raise CopySetError(
            "PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": req.product_id}
        )
    if not _product_truth(product):
        raise CopySetError(
            "PRODUCT_TRUTH_INSUFFICIENT",
            status_code=422,
            detail={"product_id": req.product_id},
        )

    threshold = 0.80 if req.dedupe_threshold is None else req.dedupe_threshold
    warnings: list[dict[str, Any]] = []

    # Comparison pool: previously approved Copy Sets + newly created
    # candidates from THIS batch (so intra-batch dedupe works).  Only
    # active (non-archived) approved sets seed the pool.
    existing_rows = await crud.list_copy_sets_for_product(req.product_id)
    comparison_pool = [
        serialize_copy_set(r)
        for r in existing_rows
        if r.get("status") == "COPY_APPROVED" and not r.get("archived")
    ]

    # Build a single-assist request.  Explicit operator overrides
    # (angle, hook) are passed through so they steer provider output.
    single_req = AICopyAssistRequest(
        product_id=req.product_id,
        platform=req.platform,
        language=req.language,
        route_type=req.route_type,
        formula_family=req.formula_family,
        content_style_mode=req.content_style_mode,
        operator_notes=req.operator_notes,
        angle=req.angle,
        hook=req.hook,
        candidate_count=1,
    )

    # ── dry_run: validate only, no provider call, no persistence ──
    if req.dry_run:
        return {
            "batch_id": None,
            "product_id": req.product_id,
            "requested_count": req.requested_count,
            "created_count": 0,
            "deduped_count": 0,
            "rejected_count": 0,
            "provider": provider.provider_status(),
            "candidates": [
                {
                    "copy_set_id": None, "status": "DRY_RUN",
                    "angle": req.angle or "", "hook": req.hook or "",
                    "subhook": "", "usp_set": [], "cta": "", "dedupe_key": "",
                    "similarity_score": None, "similar_to_copy_set_id": None,
                    "uniqueness_score": None,
                    "warnings": ["DRY_RUN_NO_PERSIST"],
                    "created": False, "dedupe_match": False,
                    "safety": {"safe": True, "violations": []},
                }
                for _ in range(req.requested_count)
            ],
            "ledger": None,
            "warnings": [{"code": "DRY_RUN", "message": "Dry run — nothing persisted."}],
            "dry_run": True,
        }

    grounding = await resolve_copy_grounding(product)
    angles = _rotation_angles(single_req, grounding)

    results: list[dict[str, Any]] = []
    created = 0
    deduped = 0
    rejected = 0
    unsafe_warnings = 0

    for i in range(req.requested_count):
        target_angle = angles[i % len(angles)] if angles else ""
        result = await _generate_one(single_req, product, grounding, target_angle)
        cs = result.get("copy_set") or {}
        is_new = result.get("created", False)
        is_dup = result.get("dedupe_match", False)
        safety = result.get("safety", {})
        candidate_warnings: list[str] = list(result.get("warnings", []))

        if is_new:
            # Compute and persist similarity metadata, then re-read the
            # updated row so response fields are populated (not stale-None).
            uni = sim_svc.compute_uniqueness_score(cs, comparison_pool)
            nearest, sim_score = sim_svc.find_nearest(cs, comparison_pool, threshold=threshold)

            updated_row = await crud.update_copy_set(
                cs["copy_set_id"],
                uniqueness_score=round(uni, 4),
                similar_to_copy_set_id=nearest.get("copy_set_id") if nearest else None,
                similarity_score=round(sim_score, 4) if nearest else None,
            )
            # Refresh cs from the persisted row
            cs = serialize_copy_set(updated_row)

            if nearest and sim_score >= threshold:
                candidate_warnings.append(
                    f"NEAR_DUPLICATE: {sim_score:.2f} similar to {nearest.get('copy_set_id', '?')}"
                )

            comparison_pool.append(cs)
            created += 1
        elif is_dup:
            deduped += 1

        # Safety: unsafe candidates ARE persisted for review (by _generate_one).
        # Count them as warnings, NOT as rejected (rejected = non-persisted).
        if not safety.get("safe", True):
            unsafe_warnings += 1
            candidate_warnings.append("COPY_UNSAFE_OR_INCOMPLETE")

        results.append({
            "copy_set_id": cs.get("copy_set_id"),
            "status": cs.get("status"),
            "angle": cs.get("angle", ""),
            "hook": cs.get("hook", ""),
            "subhook": cs.get("subhook", ""),
            "usp_set": cs.get("usp_set", []),
            "cta": cs.get("cta", ""),
            "dedupe_key": cs.get("dedupe_key", ""),
            "similarity_score": cs.get("similarity_score"),
            "similar_to_copy_set_id": cs.get("similar_to_copy_set_id"),
            "uniqueness_score": cs.get("uniqueness_score"),
            "warnings": candidate_warnings,
            "created": is_new,
            "dedupe_match": is_dup,
            "safety": safety,
        })

    # Top-level warnings
    if deduped > 0:
        warnings.append({"code": "EXACT_DEDUPE_HIT", "count": deduped,
                         "message": f"{deduped} candidate(s) matched existing Copy Sets exactly."})
    if unsafe_warnings > 0:
        warnings.append({"code": "UNSAFE_COPY_WARNING", "count": unsafe_warnings,
                         "message": f"{unsafe_warnings} candidate(s) flagged unsafe/incomplete — persisted for review."})
    if created == 0:
        warnings.append({"code": "NO_NEW_CANDIDATES",
                         "message": "All requested candidates were exact duplicates of existing Copy Sets."})

    # Persist batch ledger — capture the REAL batch_id from the DB row
    ledger_row = await crud.create_copy_generation_batch(
        product_id=req.product_id,
        requested_count=req.requested_count,
        created_count=created,
        deduped_count=deduped,
        rejected_count=rejected,
        source="AI_COPY_ASSIST",
        provider_lane=req.provider_lane or provider.provider_status().get("lane"),
        provider_model=req.provider_model or provider.provider_status().get("model_id"),
    )
    real_batch_id = ledger_row["batch_id"]

    return {
        "batch_id": real_batch_id,
        "product_id": req.product_id,
        "requested_count": req.requested_count,
        "created_count": created,
        "deduped_count": deduped,
        "rejected_count": rejected,
        "provider": provider.provider_status(),
        "candidates": results,
        "ledger": {
            "batch_id": real_batch_id,
            "source": "AI_COPY_ASSIST",
            "requested_count": req.requested_count,
            "created_count": created,
            "deduped_count": deduped,
            "rejected_count": rejected,
        },
        "warnings": warnings,
        "dry_run": False,
    }
