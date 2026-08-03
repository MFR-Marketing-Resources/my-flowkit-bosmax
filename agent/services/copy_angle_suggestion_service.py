"""Suggest NEW copy ANGLES (buyer pains) for a product via the DeepSeek text lane.

This is the AI half of the Copy Components "angle" control. Given a product that
already has an APPROVED product-intelligence snapshot, ask the configured
`text_assist` lane to PROPOSE candidate pains (angles) grounded in the product's
own knowledge + customer avatar, and return them for operator review.

It writes NOTHING. The operator edits the suggestions and commits them through the
existing FREE, claim-gated add-angles path
(`copy_angle_expansion_service.expand_product_angles`). Separation of concerns:

- suggest (here): spends ONE small text-token call; read-only; no DB write.
- commit (add-angles): FREE, claim-gated, operator-approved, re-approves a snapshot.

Fail-closed: an unconfigured provider raises `AICopyProviderNotConfigured` (-> 409);
a bad provider call raises `AICopyProviderError` (-> 502). Missing product/snapshot
raise `ValueError` (-> 422). Suggestions are deduped against the existing persona
pains (case/whitespace-insensitive, exactly like `expand_product_angles`) and capped
to the remaining angle slots (`MAX_ANGLES`).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agent.services import ai_copy_provider_adapter as provider
from agent.services.copy_angle_derivation import MAX_ANGLES
from agent.services.copy_grounding_service import resolve_copy_grounding

_DEFAULT_COUNT = 8


def _s(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_s(v) for v in value if _s(v)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return default


def _build_prompt(
    product: dict[str, Any],
    snap: dict[str, Any],
    persona: dict[str, Any],
    existing_pains: list[str],
    market_language: list[str],
    is_stealth: bool,
    want: int,
) -> tuple[str, str]:
    stealth_rule = (
        " This is a PRIVACY-SENSITIVE product: never name the body part, medical "
        "condition or intimate function explicitly; frame the pain through everyday "
        "situations and dignity (maruah), and keep every line dialogue-safe."
        if is_stealth
        else ""
    )
    system = (
        "You are BOSMAX's angle brain for the Malaysian TikTok Shop market. An "
        "'angle' is ONE concrete buyer PAIN / use-case in the customer's own words "
        "(e.g. 'lampin bocor waktu malam', 'perut berangin lepas menyusu', 'sengal "
        "lutut naik tangga'). Given a product's knowledge and customer avatar, "
        "propose NEW pains that are NOT already in the existing list. Return ONLY "
        'STRICT JSON: {"angles": ["<pain phrase>", ...]}.\n'
        "RULES: Ground every pain in the product truth given — invent no new facts, "
        "outcomes or ingredients. Preserve the buyer's real problem language "
        "(Malay), never vague. One short phrase per angle. Do NOT repeat any "
        "existing pain (even reworded). Do NOT write cure/treat/heal, guaranteed, "
        "'100%', clinical or certification claims." + stealth_rule
    )
    user = json.dumps(
        {
            "want_count": want,
            "product_name": _s(
                product.get("product_display_name")
                or product.get("raw_product_title")
                or product.get("name")
            ),
            "category": _s(product.get("category")),
            "product_knowledge": {
                "description": _s(snap.get("product_description")),
                "benefits": _list(_parse(snap.get("benefits_json"), [])),
                "usps": _list(_parse(snap.get("usp_json"), [])),
                "usage": _s(snap.get("usage_text")),
                "ingredients": _s(snap.get("ingredients_text")),
                "warnings": _s(snap.get("warnings_text")),
                "target_customer": _s(snap.get("target_customer_text")),
            },
            "customer_avatar": {
                "audience": _s(persona.get("audience")),
                "desires": _list(persona.get("desires")),
                "fears": _list(persona.get("fears")),
                "triggers": _list(persona.get("triggers")),
                "objections": _list(persona.get("objections")),
            },
            "market_problem_language": market_language,
            "existing_pains_do_not_repeat": existing_pains,
        },
        ensure_ascii=True,
    )
    return system, user


async def suggest_product_angles(
    product_id: str, count: int = _DEFAULT_COUNT
) -> dict[str, Any]:
    """Propose NEW candidate pains (angles) for a product. Read-only; spends one
    text-token call.

    Returns {ok, suggestions, existing_count, remaining_slots, warnings}. Raises
    ValueError("PRODUCT_NOT_FOUND" / "NO_APPROVED_SNAPSHOT"), and propagates the
    provider's AICopyProviderNotConfigured / AICopyProviderError unchanged.
    """
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    # PI-FINAL-B04: angle suggestion (and bulk_suggest, which routes through here
    # per product) is a copy lane - COPY_ELIGIBLE only.
    from agent.services.copy_eligibility_service import assert_copy_eligible
    await assert_copy_eligible(product_id)

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    if not snap:
        raise ValueError("NO_APPROVED_SNAPSHOT")

    persona = _parse(snap.get("buyer_persona_snapshot_json"), {}) or {}
    existing = _list(persona.get("pains"))
    remaining = MAX_ANGLES - len(existing)
    if remaining <= 0:
        return {
            "ok": True,
            "suggestions": [],
            "existing_count": len(existing),
            "remaining_slots": 0,
            "warnings": [f"ANGLES_FULL:{MAX_ANGLES}"],
        }

    strategy = _parse(snap.get("copy_strategy_summary_json"), {}) or {}
    market_language = _list(strategy.get("market_problem_language"))

    grounding = await resolve_copy_grounding(product)
    is_stealth = bool(getattr(grounding, "is_stealth", False))

    want = max(1, min(int(count or _DEFAULT_COUNT), remaining))
    system, user = _build_prompt(
        product, snap, persona, existing, market_language, is_stealth, want
    )
    # Offload the blocking httpx provider call so a bulk loop never starves the
    # event loop / /health (incident PR #404). Tests mock complete_json (sync) —
    # to_thread runs + awaits them, propagating returns and exceptions unchanged.
    ai = await asyncio.to_thread(provider.complete_json, system, user)  # raises NotConfigured / Error

    raw = ai.get("angles") if isinstance(ai, dict) else None
    if not isinstance(raw, list):
        raw = ai.get("pains") if isinstance(ai, dict) else None
    candidates = _list(raw)

    seen = {p.strip().lower() for p in existing}
    suggestions: list[str] = []
    for cand in candidates:
        key = cand.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(cand)
        if len(suggestions) >= remaining:
            break

    warnings: list[str] = []
    if not suggestions:
        warnings.append("NO_SUGGESTIONS")

    return {
        "ok": True,
        "suggestions": suggestions,
        "existing_count": len(existing),
        "remaining_slots": remaining,
        "warnings": warnings,
    }
