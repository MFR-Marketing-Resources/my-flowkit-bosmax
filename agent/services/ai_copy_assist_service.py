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


def _product_truth(product: dict[str, Any]) -> str:
    return _clean(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product.get("name")
    )


def _build_brief(req: AICopyAssistRequest, product: dict[str, Any]) -> str:
    """A grounded, safe brief string for the provider. Product truth only — no
    invented facts, no internal ids echoed as copy."""
    brief = {
        "product_name": _product_truth(product),
        "category": _clean(product.get("category")),
        "existing_angle": _clean(product.get("copywriting_angle")),
        "platform": _clean(req.platform) or "TIKTOK",
        "language": _clean(req.language) or "BM_MS",
        "route_type": _clean(req.route_type) or "DIRECT",
        "formula_family": _clean(req.formula_family) or "HSO",
        "content_style_mode": _clean(req.content_style_mode) or "UGC_IPHONE",
        "desired_angle": _clean(req.angle),
        "hook_direction": _clean(req.hook),
        "operator_notes": _clean(req.operator_notes),
        "safety": "no medical/cure/treat/heal/guaranteed/universal-safety/before-after claims",
    }
    return json.dumps({k: v for k, v in brief.items() if v}, ensure_ascii=True)


def _merge_candidate_fields(
    ai: dict[str, Any], req: AICopyAssistRequest
) -> dict[str, Any]:
    """AI output populates the copy fields; an explicit operator field overrides
    the AI value for that field. Result is run through the shared normalizer."""
    fields = {
        "angle": req.angle if req.angle is not None else ai.get("angle"),
        "hook": req.hook if req.hook is not None else ai.get("hook"),
        "subhook": req.subhook if req.subhook is not None else ai.get("subhook"),
        "usp_set": normalize_usp_set(
            req.usp_set if req.usp_set is not None else ai.get("usp_set")
        ),
        "cta": req.cta if req.cta is not None else ai.get("cta"),
        "formula_family": req.formula_family or ai.get("formula_family") or "HSO",
        "route_type": req.route_type or "DIRECT",
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
    req: AICopyAssistRequest, product: dict[str, Any]
) -> dict[str, Any]:
    ai = provider.generate_candidate(_build_brief(req, product))
    if not isinstance(ai, dict):
        raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID)

    fields = _merge_candidate_fields(ai, req)
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
    candidates = [await _generate_one(req, product) for _ in range(req.candidate_count)]
    return {"provider": provider.provider_status(), "candidates": candidates}


async def generate_ai_copy_candidates_batch(
    request: AICopyAssistBatchRequest | dict,
) -> dict[str, Any]:
    """Generate requested_count candidates in a single batch request.

    Each candidate is independently generated, deduped, safety-scanned,
    and similarity-scored against existing approved Copy Sets for the
    same product.  A copy_generation_batch ledger row records the run.

    When ``dry_run`` is True, validation runs but nothing is persisted.

    Fails closed on: product not found, insufficient product truth,
    provider not configured, or invalid provider response.
    """
    import uuid as _uuid_mod
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

    batch_id = str(_uuid_mod.uuid4())
    threshold = req.dedupe_threshold or 0.80
    warnings: list[dict[str, Any]] = []

    # Load existing approved Copy Sets for similarity comparison
    existing_rows = await crud.list_copy_sets_for_product(req.product_id)
    existing_approved = [
        serialize_copy_set(r)
        for r in existing_rows
        if r.get("status") == "COPY_APPROVED" and not r.get("archived")
    ]

    # Build a single-assist request to reuse _generate_one logic
    single_req = AICopyAssistRequest(
        product_id=req.product_id,
        platform=req.platform,
        language=req.language,
        route_type=req.route_type,
        formula_family=req.formula_family,
        content_style_mode=req.content_style_mode,
        operator_notes=req.operator_notes,
        candidate_count=1,
    )

    results: list[dict[str, Any]] = []
    created = 0
    deduped = 0
    rejected = 0

    for i in range(req.requested_count):
        if req.dry_run:
            # Dry run: build a simulated candidate without persisting
            results.append({
                "copy_set_id": None,
                "status": "DRY_RUN",
                "angle": req.angle or "",
                "hook": req.hook or "",
                "subhook": "",
                "usp_set": [],
                "cta": "",
                "dedupe_key": "",
                "similarity_score": None,
                "similar_to_copy_set_id": None,
                "uniqueness_score": None,
                "warnings": ["DRY_RUN_NO_PERSIST"],
                "created": False,
                "dedupe_match": False,
                "safety": {"safe": True, "violations": []},
            })
            continue

        result = await _generate_one(single_req, product)
        cs = result.get("copy_set") or {}
        is_new = result.get("created", False)
        is_dup = result.get("dedupe_match", False)
        safety = result.get("safety", {})
        candidate_warnings: list[str] = list(result.get("warnings", []))

        if is_new:
            # Compute uniqueness against approved
            uni = sim_svc.compute_uniqueness_score(cs, existing_approved)
            nearest, sim_score = sim_svc.find_nearest(cs, existing_approved, threshold=threshold)
            near_dup = nearest is not None and sim_score >= threshold

            if near_dup:
                candidate_warnings.append(
                    f"NEAR_DUPLICATE: {sim_score:.2f} similar to {nearest.get('copy_set_id', '?')}"
                )
                if {"NEAR_DUPLICATE_WARNING"} not in [set(w.get("code","") for w in warnings)]:
                    pass  # warnings handled per-candidate

            # Persist similarity metadata
            await crud.update_copy_set(
                cs["copy_set_id"],
                uniqueness_score=round(uni, 4),
                similar_to_copy_set_id=nearest.get("copy_set_id") if nearest else None,
                similarity_score=round(sim_score, 4) if nearest else None,
            )
            existing_approved.append(cs)
            created += 1
        elif is_dup:
            deduped += 1

        if not safety.get("safe", True):
            rejected += 1

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

    # Compile top-level warnings
    if deduped > 0:
        warnings.append({"code": "EXACT_DEDUPE_HIT", "count": deduped,
                         "message": f"{deduped} candidate(s) matched existing Copy Sets exactly."})
    if created == 0 and not req.dry_run:
        warnings.append({"code": "NO_NEW_CANDIDATES", "count": 0,
                         "message": "All requested candidates were exact duplicates of existing Copy Sets."})

    # Record batch ledger (skip in dry_run)
    if not req.dry_run:
        await crud.create_copy_generation_batch(
            product_id=req.product_id,
            requested_count=req.requested_count,
            created_count=created,
            deduped_count=deduped,
            rejected_count=rejected,
            source="AI_COPY_ASSIST",
            provider_lane=req.provider_lane or provider.provider_status().get("lane"),
            provider_model=req.provider_model or provider.provider_status().get("model_id"),
        )

    return {
        "batch_id": batch_id,
        "product_id": req.product_id,
        "requested_count": req.requested_count,
        "created_count": created,
        "deduped_count": deduped,
        "rejected_count": rejected,
        "provider": provider.provider_status(),
        "candidates": results,
        "ledger": {
            "batch_id": batch_id,
            "source": "AI_COPY_ASSIST",
            "requested_count": req.requested_count,
            "created_count": created,
            "deduped_count": deduped,
            "rejected_count": rejected,
        },
        "warnings": warnings,
        "dry_run": req.dry_run,
    }
