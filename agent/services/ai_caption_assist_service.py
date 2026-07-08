"""AI Caption Assist — grounded, reviewable social-caption candidate generator.

Upgrades the deterministic ``social_copy_package_service.suggest_copy`` scaffold
to a real AI caption writer that REUSES the existing on-main copywriting stack —
no new provider, no new secrets:

  - ``copy_grounding_service.resolve_copy_grounding(product)`` → customer avatar +
    product knowledge + claim guardrails + stealth route (PR #258)
  - ``ai_copy_provider_adapter.complete_json(system, user)`` → the text_assist lane
    transport, DISABLED BY DEFAULT (fails closed; no hardcoded model/key)
  - ``social_copy_package_service`` platform profiles + the single claim-safe gate

It grounds a caption in THREE layers so the copy is sharp, not generic:
  1. product truth + customer avatar (angle-first),
  2. the actual creative that was generated (the Results-Hub prompt snapshot for
     the artifact) + the approved Copy Set that steered it (message consistency),
  3. platform norms (per-platform tone / caption shape / hashtag conventions).

GOVERNANCE: this is a SUGGESTION generator only. It NEVER persists a package and
NEVER approves anything — the operator still Saves (→ DRAFT, re-validated) and
Approves through the existing lifecycle. Every candidate is claim-safe scanned
before it is returned; an unsafe candidate is returned FLAGGED, never hidden.
``ai_copy_provider_adapter.complete_json`` is the single mockable seam for tests.
"""
from __future__ import annotations

import json
from typing import Any

from agent.db import crud
from agent.services import ai_copy_provider_adapter as provider
from agent.services import social_copy_package_service as scp
from agent.services.copy_grounding_service import resolve_copy_grounding

# Cap candidate fan-out — each candidate is one provider call (token spend).
_MAX_CANDIDATES = 3
_CREATIVE_SUMMARY_CHARS = 400


def _name_of(product: dict | None) -> str:
    if not product:
        return ""
    return scp._normalize(
        product.get("product_display_name")
        or product.get("raw_product_title")
        or product.get("name")
    )


async def _resolve_product_and_creative(
    *, product_id: str | None, artifact_media_id: str | None
) -> tuple[dict | None, dict | None]:
    """Resolve the product row + the durable creative snapshot. An explicit
    product_id wins; otherwise the artifact's Results-Hub record supplies the
    product_id and the creative prompt the caption should stay consistent with."""
    record = None
    pid = scp._normalize(product_id)
    if artifact_media_id:
        record = await crud.get_generation_result(artifact_media_id)
        if record and not pid:
            pid = scp._normalize(record.get("product_id"))
    product = await crud.get_product(pid) if pid else None
    return product, record


async def _approved_copy_set(product_id: str | None) -> dict | None:
    """Most-recent APPROVED Copy Set for the product (the angle/hook/USP the video
    was actually built on) so the caption echoes the creative's message."""
    if not product_id:
        return None
    try:
        rows = await crud.list_copy_sets_for_product(product_id)
    except Exception:  # noqa: BLE001 — copy-set alignment is best-effort grounding
        return None
    approved = [
        r for r in (rows or [])
        if str(r.get("status") or "") == "COPY_APPROVED" and not r.get("archived")
    ]
    return approved[0] if approved else None  # crud returns newest-first


def _copy_set_usps(copy_set: dict) -> list[str]:
    raw = copy_set.get("usp_set")
    if isinstance(raw, list):
        return [scp._normalize(x) for x in raw if scp._normalize(x)]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [scp._normalize(x) for x in parsed if scp._normalize(x)]
        except (TypeError, ValueError):
            return []
    return []


def _system_prompt(platform: str, profile: dict) -> str:
    return (
        "You are a native social-media CAPTION writer (Malay/English, natural "
        "code-switch) for a commercial UGC product pipeline. You write ONLY draft "
        "captions for HUMAN REVIEW — never final video/engine prompts, never "
        "internal metadata (ids, codes, provenance, system names). "
        f"Write for {platform.upper()}: {profile['caption_hint']} Match a "
        f"{profile['tone']} tone"
        + ("" if profile["supports_first_comment"]
           else " (this platform has no pinned/first comment slot — put everything in the caption)")
        + ". "
        "METHOD (angle-first): the brief carries a customer avatar (avatar_audience, "
        "avatar_desires, avatar_pains, avatar_fears, avatar_objections, "
        "avatar_triggers, pronoun) and product knowledge (product_benefits, "
        "product_usps, product_description). Pick ONE specific avatar pain or desire "
        "— aligned with campaign_angle / campaign_hook when present so the caption "
        "matches the video the viewer just watched (creative_summary) — and write a "
        "scroll-stopping caption from THAT angle. Match the pronoun. Ground benefit "
        "lines in product_benefits / product_usps when present; invent NO product "
        "outcomes. "
        "If sensitivity or route_type is STEALTH: privacy-sensitive product — NEVER "
        "name the body part, medical condition, or intimate/sexual function; sell "
        "through wrapped metaphor, ego / maruah (masculine pride & dignity) and "
        "everyday-routine framing; keep every line dialogue-safe. If claim_risk_level "
        "is HIGH be extra conservative. "
        "HARD SAFETY — no medical / cure / treat / heal claims, no guaranteed results, "
        "no 'no side effects' / 'safe for everyone', no before/after or "
        "clinical-authority claims; obey banned_terms. NEVER print any id or code from "
        "the brief in the copy. "
        "Return STRICT JSON ONLY (no markdown) with keys: caption (string), "
        "first_comment (string, '' if not needed), hashtags (array of strings, WITHOUT "
        "the # sign), call_to_action (string), tone (string), rationale (string), "
        "risk_notes (array of strings)."
    )


def _build_brief(
    *,
    platform: str,
    profile: dict,
    req: dict,
    grounding: Any,
    record: dict | None,
    copy_set: dict | None,
    name: str,
    target_angle: str,
    vary: bool,
    variant_index: int,
) -> str:
    persona = grounding.buyer_persona if grounding else None
    pk = grounding.product_knowledge if grounding else None
    cg = grounding.claim_guardrails if grounding else None
    creative_summary = ""
    if record:
        creative_summary = scp._normalize(record.get("final_prompt_text"))[:_CREATIVE_SUMMARY_CHARS]
    brief: dict[str, Any] = {
        "platform": platform,
        "platform_style": profile["caption_hint"],
        "platform_tone": profile["tone"],
        "supports_first_comment": profile["supports_first_comment"],
        "language": scp._normalize(req.get("language")) or "BM_MS",
        "operator_tone": scp._normalize(req.get("tone")),
        "operator_notes": scp._normalize(req.get("operator_notes")),
        "product_name": name,
        # product knowledge (real facts only — empty until an approved snapshot)
        "product_description": pk.description if pk else "",
        "product_benefits": pk.benefits if pk else [],
        "product_usps": pk.usps if pk else [],
        "target_customer": pk.target_customer if pk else "",
        # customer avatar
        "avatar_audience": persona.audience if persona else "",
        "avatar_desires": persona.desires if persona else [],
        "avatar_pains": persona.pains if persona else [],
        "avatar_fears": persona.fears if persona else [],
        "avatar_objections": persona.objections if persona else [],
        "avatar_triggers": persona.triggers if persona else [],
        "pronoun": persona.pronoun if persona else "",
        "grounding_tone": persona.tone if persona else "",
        "target_angle": target_angle,
        # message consistency with the approved creative copy
        "campaign_angle": scp._normalize(copy_set.get("angle")) if copy_set else "",
        "campaign_hook": scp._normalize(copy_set.get("hook")) if copy_set else "",
        "campaign_usps": _copy_set_usps(copy_set) if copy_set else [],
        "campaign_cta": scp._normalize(copy_set.get("cta")) if copy_set else "",
        # what the artifact actually shows
        "creative_mode": scp._normalize((record or {}).get("mode")),
        "creative_summary": creative_summary,
        "sensitivity": "STEALTH" if (grounding and grounding.is_stealth) else "",
        "route_type": grounding.effective_route if grounding else "",
        # claim guardrails
        "claim_gate": cg.claim_gate if cg else "",
        "claim_risk_level": cg.claim_risk_level if cg else "",
        "banned_terms": cg.banned_terms if cg else [],
        "allowed_claims": cg.allowed_claims if cg else [],
        "variation_instruction": (
            f"This is variant #{variant_index + 1}. Use a DISTINCTLY different hook "
            "and angle from a generic one." if vary else ""
        ),
    }
    compact = {k: v for k, v in brief.items() if v not in ("", [], None)}
    return json.dumps(compact, ensure_ascii=True)


def _user_prompt(brief_json: str) -> str:
    return (
        "Write ONE platform-native caption as STRICT JSON for this brief. Ground it "
        "in the product truth + avatar; invent no facts.\n\n" + brief_json
    )


def _parse_candidate(ai: dict, platform: str, profile: dict) -> dict[str, Any]:
    caption = scp._normalize(ai.get("caption"))
    first_comment = scp._normalize(ai.get("first_comment"))
    cta = scp._normalize(ai.get("call_to_action") or ai.get("cta"))
    tone = scp._normalize(ai.get("tone")) or profile["tone"]
    raw_tags = ai.get("hashtags")
    hashtags = scp._clean_hashtags(raw_tags if isinstance(raw_tags, list) else [])
    compliance, blockers, warnings = scp._assess_compliance(
        caption=caption,
        first_comment=first_comment,
        call_to_action=cta,
        hashtags=hashtags,
    )
    risk_notes = ai.get("risk_notes")
    return {
        "platform": platform,
        "caption": caption,
        "first_comment": first_comment,
        "hashtags": hashtags,
        "call_to_action": cta,
        "tone": tone,
        "rationale": scp._normalize(ai.get("rationale"))[:500],
        "risk_notes": [scp._normalize(r) for r in risk_notes if scp._normalize(r)]
        if isinstance(risk_notes, list) else [],
        "compliance_status": compliance,
        "blockers": blockers,
        "warnings": warnings,
    }


async def generate_caption_candidates(req: dict) -> dict[str, Any]:
    """Generate up to ``candidate_count`` grounded, reviewable caption candidates.

    Fails closed (``AICopyProviderNotConfigured``) when the text_assist lane is not
    configured — the deterministic ``suggest_copy`` scaffold remains available as
    the free fallback. Raises ``SocialCopyError`` on an unsupported platform.
    """
    platform = scp._validate_platform(str(req.get("platform") or ""))
    profile = scp.PLATFORM_PROFILES[platform]
    try:
        count = max(1, min(_MAX_CANDIDATES, int(req.get("candidate_count") or 1)))
    except (TypeError, ValueError):
        count = 1

    product, record = await _resolve_product_and_creative(
        product_id=req.get("product_id"),
        artifact_media_id=req.get("artifact_media_id"),
    )
    grounding = None
    if product:
        try:
            grounding = await resolve_copy_grounding(product)
        except Exception:  # noqa: BLE001 — degrade to ungrounded, never hard-fail here
            grounding = None
    resolved_pid = (product or {}).get("id") or (record or {}).get("product_id")
    copy_set = await _approved_copy_set(resolved_pid)
    name = _name_of(product) or scp._normalize((record or {}).get("product_name"))
    angle_strategies = list(grounding.angle_strategies) if grounding else []

    candidates: list[dict] = []
    for i in range(count):
        target_angle = (
            angle_strategies[i % len(angle_strategies)] if angle_strategies
            else (scp._normalize(copy_set.get("angle")) if copy_set else "")
        )
        brief = _build_brief(
            platform=platform, profile=profile, req=req, grounding=grounding,
            record=record, copy_set=copy_set, name=name, target_angle=target_angle,
            vary=count > 1, variant_index=i,
        )
        ai = provider.complete_json(_system_prompt(platform, profile), _user_prompt(brief))
        if not isinstance(ai, dict):
            raise provider.AICopyProviderError(provider.ERR_RESPONSE_INVALID)
        candidates.append(_parse_candidate(ai, platform, profile))

    return {
        "provider": provider.provider_status(),
        "grounding": {
            "source": grounding.source if grounding else "MINIMAL",
            "grounded": bool(grounding.grounded) if grounding else False,
            "is_stealth": bool(grounding.is_stealth) if grounding else False,
            "product_name": name or None,
            "has_campaign_copy": bool(copy_set),
        },
        "candidates": candidates,
    }
