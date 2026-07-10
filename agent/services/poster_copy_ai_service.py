"""AI Poster Copy Assistant (POSTER_BUILDER_V2).

Objective recommendations → angle recommendations → poster-native copy
directions → single-field regeneration, all grounded in product truth via the
shared copy-grounding resolver and transported over the operator-configured
`text_assist` provider lane (ai_copy_provider_adapter — provider/model agnostic,
fails closed when unconfigured).

POSTER-NATIVE by contract: the brief and the output schema carry NO video
concepts (no duration, WPS, dialogue timeline, story beats, shot sequence or
CTA timing). Poster copy is spatial: one selling idea, a first-read primary
message, one short support line, tight proof points, a short CTA.

Spend discipline: AI calls fire only on explicit operator actions; every
recommender has a deterministic no-spend fallback so an unconfigured lane never
blocks the workflow.
"""
from __future__ import annotations

import re
from typing import Any

from agent.db import crud
from agent.models.poster_copy_set import (
    MAX_PROOF_POINTS,
    POSTER_NATIVE_LIMITS,
    PROVENANCE_AI,
    PROVENANCE_FALLBACK,
)
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import poster_recipe_service
from agent.services.copy_grounding_service import resolve_copy_grounding
from agent.services.poster_copy_set_service import run_poster_copy_gate, PosterCopySetError

POSTER_COPY_PROMPT_VERSION = "poster-copy-ai-v1"

# Copy fields the AI may write / regenerate.
AI_COPY_FIELDS = ("primary_message", "support_message", "proof_points", "cta", "disclaimer")

_SYSTEM_PROMPT = (
    "You are an expert Bahasa Melayu e-commerce POSTER copywriter for Malaysian "
    "social commerce. A poster is read SPATIALLY in under three seconds — it is "
    "NOT a video script, story, or dialogue. Rules: ONE clear selling idea; a "
    "punchy first-read primary message; at most one short support line; up to "
    "three tight factual proof points; a short imperative CTA. Natural, warm, "
    "persuasive Malay (or the requested language) — never stiff translationese. "
    "NEVER invent product facts, ingredients, numbers, prices, discounts or "
    "certifications. NEVER use medical / symptom / relief / treatment / disease "
    "wording (no ubat, rawat, sembuh, legakan, lega, kembung, sakit, simptom, "
    "penyakit, cure, treat, heal, relief). Respect every character limit "
    "exactly. Return STRICT JSON ONLY — no markdown, no commentary."
)


class PosterCopyAIError(Exception):
    def __init__(self, code: str, message: str = "", *, status_code: int = 422):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _provenance_model() -> str:
    status = ai_provider.provider_status()
    provider = _norm(status.get("provider_id"))
    model = _norm(status.get("model_id"))
    return f"{provider}:{model}" if provider or model else ""


def _clip(text: str, limit: int) -> str:
    text = _norm(text)
    return text if len(text) <= limit else text[:limit].rstrip()


# ─── Grounded brief ───────────────────────────────────────────────────────────

def _grounding_block(grounding: Any, product: dict[str, Any]) -> str:
    name = _norm(product.get("product_display_name")) or _norm(
        product.get("raw_product_title")
    )
    pk = grounding.product_knowledge
    persona = grounding.buyer_persona
    guard = grounding.claim_guardrails
    lines = [
        f"PRODUCT (locked, never substitute): {name}",
        f"Category: {_norm(product.get('category')) or '—'} / "
        f"{_norm(product.get('subcategory')) or _norm(product.get('type')) or '—'}",
        f"Grounding source: {grounding.source}",
    ]
    if pk.description:
        lines.append(f"Approved description: {pk.description}")
    if pk.benefits:
        lines.append("Approved benefits (ONLY these may be referenced): "
                     + "; ".join(pk.benefits[:6]))
    if pk.usps:
        lines.append("Approved USPs: " + "; ".join(pk.usps[:6]))
    if not pk.benefits and not pk.usps:
        lines.append(
            "NO verified product facts are available. Do NOT state any benefit, "
            "ingredient, specification, number or outcome — use neutral routine/"
            "convenience/heritage/portability angles only."
        )
    if persona.audience:
        lines.append(f"Audience: {persona.audience}")
    if persona.desires:
        lines.append("Audience desires: " + "; ".join(persona.desires[:4]))
    if guard.blocked_claims:
        lines.append("BLOCKED claims (never use): " + "; ".join(guard.blocked_claims[:8]))
    if guard.banned_terms:
        lines.append("BANNED terms (never use): " + "; ".join(guard.banned_terms[:12]))
    return "\n".join(lines)


def _limits_block(archetype_fields: dict[str, Any]) -> str:
    return (
        f"LIMITS (characters, hard): primary_message<={POSTER_NATIVE_LIMITS['primary_message']}, "
        f"support_message<={POSTER_NATIVE_LIMITS['support_message']}, "
        f"each proof_point<={POSTER_NATIVE_LIMITS['proof_point']} (max "
        f"{archetype_fields['max_proof_points']}), cta<={POSTER_NATIVE_LIMITS['cta']}, "
        f"disclaimer<={POSTER_NATIVE_LIMITS['disclaimer']}. "
        + ("support_message is NOT used by this archetype — return an empty string for it. "
           if not archetype_fields["supports_support_message"] else "")
    )


def archetype_field_contract(archetype: str) -> dict[str, Any]:
    """Archetype-dependent field requirements derived from the recipe zone map."""
    recipe = None
    for r in poster_recipe_service.list_recipes():
        if r.archetype == archetype or r.recipe_id == archetype:
            recipe = r
            break
    if recipe is None:
        return {
            "recipe_id": "",
            "archetype": archetype,
            "supports_support_message": True,
            "max_proof_points": MAX_PROOF_POINTS,
            "selling_angles": [],
            "non_price_only": False,
        }
    source_fields = {z.source_field for z in recipe.zones if z.source_field}
    return {
        "recipe_id": recipe.recipe_id,
        "archetype": recipe.archetype,
        "supports_support_message": "subhook" in source_fields,
        "max_proof_points": min(
            recipe.max_chips or MAX_PROOF_POINTS,
            len([f for f in source_fields if f.startswith("usp_")]) or MAX_PROOF_POINTS,
        ),
        "selling_angles": list(recipe.main_selling_angles),
        "non_price_only": recipe.archetype == "OFFER",
    }


# ─── Objective recommendations ────────────────────────────────────────────────

_SIZE_TOKENS = ("5ml", "10ml", "15ml", "roll-on", "roll on", "mini", "pocket", "travel")
_HERITAGE_TOKENS = ("warisan", "tradisi", "traditional", "herba", "herbal", "turun-temurun")


def _deterministic_objective_ranking(product: dict[str, Any]) -> list[dict[str, str]]:
    """Rank the launch archetypes for this product from deterministic signals."""
    title = " ".join(
        _norm(product.get(k)).lower()
        for k in ("raw_product_title", "product_display_name", "category", "subcategory", "type")
    )
    risk_high = _norm(product.get("claim_risk_level")).upper() == "HIGH"
    scores: dict[str, float] = {
        "PRODUCT_HERO": 3.0,
        "ROUTINE_USE": 2.0,
        "HERITAGE_TRUST": 1.0,
        "PORTABILITY": 1.0,
        "PROBLEM_AWARE_SAFE": 0.5,
        "OFFER": 0.5,
    }
    reasons: dict[str, str] = {
        "PRODUCT_HERO": "Strong default: premium product-first poster.",
        "ROUTINE_USE": "Everyday routine framing is safe and relatable.",
        "HERITAGE_TRUST": "Trust/heritage framing.",
        "PORTABILITY": "Size/portability proof.",
        "PROBLEM_AWARE_SAFE": "Context/mood without any claim.",
        "OFFER": "Non-price promotional push.",
    }
    if any(t in title for t in _SIZE_TOKENS):
        scores["PORTABILITY"] += 3.0
        reasons["PORTABILITY"] = "Compact size detected — scale/portability proof fits this product."
    if any(t in title for t in _HERITAGE_TOKENS):
        scores["HERITAGE_TRUST"] += 3.0
        reasons["HERITAGE_TRUST"] = "Traditional/heritage cues detected in the product identity."
    if risk_high:
        # Claim-safe framing must OUTRANK every other boost for high-risk
        # products — the safest archetype is the recommendation, full stop.
        scores["PROBLEM_AWARE_SAFE"] += 6.0
        scores["ROUTINE_USE"] += 1.5
        reasons["PROBLEM_AWARE_SAFE"] = (
            "High claim risk — mood/context framing avoids any medical wording."
        )
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    by_archetype = {
        r.archetype: r for r in poster_recipe_service.list_recipes()
    }
    out = []
    for archetype, _score in ranked:
        recipe = by_archetype.get(archetype)
        if recipe is None:
            continue
        out.append(
            {
                "archetype": archetype,
                "recipe_id": recipe.recipe_id,
                "objective": recipe.label,
                "reason": reasons[archetype],
                "source": "DETERMINISTIC",
            }
        )
    return out


async def recommend_objectives(
    product_id: str, *, refresh_ai: bool = False
) -> dict[str, Any]:
    product = await crud.get_product(_norm(product_id))
    if not product:
        raise PosterCopyAIError("PRODUCT_NOT_FOUND", status_code=404)
    base = _deterministic_objective_ranking(dict(product))
    warnings: list[str] = []
    if refresh_ai and ai_provider.is_configured():
        try:
            grounding = await resolve_copy_grounding(dict(product))
            user = (
                _grounding_block(grounding, dict(product))
                + "\n\nTASK: Rank these poster archetypes for THIS product, best "
                "first, with a one-line Malay reason each: "
                + ", ".join(x["archetype"] for x in base)
                + '. Return JSON {"recommendations": [{"archetype": str, "reason": str}]}.'
            )
            raw = ai_provider.complete_json(_SYSTEM_PROMPT, user)
            ai_items = raw.get("recommendations") or []
            ai_order = [
                _norm(x.get("archetype")).upper()
                for x in ai_items
                if isinstance(x, dict)
            ]
            ai_reason = {
                _norm(x.get("archetype")).upper(): _norm(x.get("reason"))
                for x in ai_items
                if isinstance(x, dict)
            }
            known = {x["archetype"]: x for x in base}
            reranked = [known[a] for a in ai_order if a in known]
            for item in reranked:
                reason = ai_reason.get(item["archetype"])
                if reason:
                    item["reason"] = reason
                    item["source"] = "AI"
            remaining = [x for x in base if x not in reranked]
            base = reranked + remaining
        except ai_provider.AICopyProviderError as exc:
            warnings.append(f"AI objective ranking unavailable: {exc.code or exc}")
    elif refresh_ai:
        warnings.append("AI provider not configured — deterministic ranking only.")
    return {
        "product_id": product_id,
        "recommendations": base,
        "ai_provider_status": ai_provider.provider_status(),
        "prompt_version": POSTER_COPY_PROMPT_VERSION,
        "warnings": warnings,
    }


# ─── Angle recommendations ────────────────────────────────────────────────────

async def recommend_angles(
    product_id: str, archetype: str, *, refresh_ai: bool = False
) -> dict[str, Any]:
    product = await crud.get_product(_norm(product_id))
    if not product:
        raise PosterCopyAIError("PRODUCT_NOT_FOUND", status_code=404)
    contract = archetype_field_contract(_norm(archetype))
    angles: list[dict[str, str]] = [
        {"angle": a, "rationale": "Archetype selling angle (curated).", "source": "RECIPE"}
        for a in contract["selling_angles"]
    ]
    warnings: list[str] = []
    if refresh_ai and ai_provider.is_configured():
        try:
            grounding = await resolve_copy_grounding(dict(product))
            user = (
                _grounding_block(grounding, dict(product))
                + f"\n\nArchetype: {contract['archetype']}."
                + "\nTASK: Propose up to 4 additional SAFE selling angles for a "
                "poster of this archetype (short noun phrases, Malay, no medical "
                'wording, no prices). Return JSON {"angles": [{"angle": str, '
                '"rationale": str}]}.'
            )
            raw = ai_provider.complete_json(_SYSTEM_PROMPT, user)
            seen = {a["angle"].lower() for a in angles}
            for item in raw.get("angles") or []:
                if not isinstance(item, dict):
                    continue
                angle = _clip(item.get("angle"), 60)
                if not angle or angle.lower() in seen:
                    continue
                seen.add(angle.lower())
                angles.append(
                    {
                        "angle": angle,
                        "rationale": _clip(item.get("rationale"), 160),
                        "source": "AI",
                    }
                )
        except ai_provider.AICopyProviderError as exc:
            warnings.append(f"AI angles unavailable: {exc.code or exc}")
    elif refresh_ai:
        warnings.append("AI provider not configured — curated angles only.")
    return {
        "product_id": product_id,
        "archetype": contract["archetype"],
        "angles": angles[:8],
        "ai_provider_status": ai_provider.provider_status(),
        "prompt_version": POSTER_COPY_PROMPT_VERSION,
        "warnings": warnings,
    }


# ─── Copy directions ─────────────────────────────────────────────────────────

def _direction_is_safe(direction: dict[str, Any], archetype: str) -> bool:
    """Strict gate a candidate must pass to be shown at all."""
    try:
        run_poster_copy_gate(
            {
                "archetype": archetype,
                "language": direction.get("language") or "ms",
                "primary_message": direction.get("primary_message"),
                "support_message": direction.get("support_message"),
                "proof_points": direction.get("proof_points") or [],
                "cta": direction.get("cta"),
                "disclaimer": direction.get("disclaimer"),
            },
            strict=True,
        )
        return True
    except PosterCopySetError:
        return False


def _grounded_fallback_points(grounding: Any, limit: int) -> list[str]:
    """Proof points a fallback may state: ONLY approved benefits/USPs."""
    points: list[str] = []
    pk = getattr(grounding, "product_knowledge", None)
    for src in ((getattr(pk, "benefits", None) or []),
                (getattr(pk, "usps", None) or [])):
        for p in src:
            p = _clip(p, POSTER_NATIVE_LIMITS["proof_point"])
            if p and p.lower() not in {x.lower() for x in points}:
                points.append(p)
            if len(points) >= limit:
                return points
    return points


def _fallback_directions(
    product: dict[str, Any],
    contract: dict[str, Any],
    angle: str,
    language: str,
    grounding: Any = None,
) -> list[dict[str, Any]]:
    """Deterministic, no-spend poster directions.

    TRUTH RULE: a fallback fires exactly when NO AI grounding ran, so it may
    not fabricate ANY verifiable fact and may not IMPLY one either — no
    popularity ("dipercayai ramai"), scarcity ("stok terhad"), logistics
    ("penghantaran pantas"), routine/usage suitability ("untuk rutin anda",
    "rutin harian"), family suitability, quality/authenticity ("kualiti
    terjaga", "kemasan asli"), heritage, ingredients or results. The operator's
    ``angle`` is NOT injected verbatim — an unvalidated angle can smuggle any of
    those claims. Proof points come ONLY from approved grounding (benefits/USPs);
    with no approved intelligence the chips stay empty and the copy is limited to
    PRODUCT DISCOVERY language around the product name (Kenali / Lihat / Terokai
    / Ketahui lebih lanjut).
    """
    name = _norm(product.get("product_display_name")) or _norm(
        product.get("raw_product_title")
    ) or "Produk"
    short = name if len(name) <= 30 else name[:30].rstrip()
    grounded_points = _grounded_fallback_points(
        grounding, contract["max_proof_points"]
    ) if grounding is not None else []
    supports = contract["supports_support_message"]
    templates = [
        {
            "primary_message": _clip(f"Kenali {short}", 48),
            "support_message": _clip(f"Ketahui lebih lanjut tentang {short}.", 72)
            if supports else "",
            "proof_points": list(grounded_points),
            "cta": "Ketahui lebih lanjut",
            "disclaimer": "",
            "tone": "neutral",
        },
        {
            "primary_message": _clip(short, 48),
            "support_message": "Lihat produk." if supports else "",
            "proof_points": list(grounded_points),
            "cta": "Lihat produk",
            "disclaimer": "",
            "tone": "neutral",
        },
        {
            "primary_message": _clip(f"Terokai {short}", 48),
            "support_message": "Terokai pilihan." if supports else "",
            "proof_points": list(grounded_points),
            "cta": "Terokai pilihan",
            "disclaimer": "",
            "tone": "neutral",
        },
    ]
    out = []
    for t in templates:
        t["language"] = language
        t["field_provenance"] = {k: PROVENANCE_FALLBACK for k in AI_COPY_FIELDS}
        if _direction_is_safe(t, contract["archetype"]):
            out.append(t)
    return out


async def generate_directions(
    product_id: str,
    archetype: str,
    angle: str,
    *,
    tone: str = "",
    language: str = "ms",
    count: int = 3,
) -> dict[str, Any]:
    product = await crud.get_product(_norm(product_id))
    if not product:
        raise PosterCopyAIError("PRODUCT_NOT_FOUND", status_code=404)
    contract = archetype_field_contract(_norm(archetype))
    count = max(1, min(int(count or 3), 5))
    warnings: list[str] = []
    directions: list[dict[str, Any]] = []

    if ai_provider.is_configured():
        try:
            grounding = await resolve_copy_grounding(dict(product))
            offer_rule = (
                "This is a NON-PRICE promotional poster: NEVER mention prices, "
                "percentages, discounts or vouchers. "
                if contract["non_price_only"]
                else ""
            )
            user = (
                _grounding_block(grounding, dict(product))
                + f"\n\nArchetype: {contract['archetype']}. Selling angle: {angle}."
                + (f" Tone: {tone}." if tone else "")
                + f" Language: {language}."
                + "\n" + _limits_block(contract) + offer_rule
                + f"\nTASK: Write {count} DISTINCT poster copy directions for this "
                "angle. Each direction = one selling idea. Return JSON "
                '{"directions": [{"primary_message": str, "support_message": str, '
                '"proof_points": [str], "cta": str, "disclaimer": str, "tone": str}]}.'
            )
            raw = ai_provider.complete_json(_SYSTEM_PROMPT, user)
            for i, item in enumerate((raw.get("directions") or [])[: count + 2]):
                if not isinstance(item, dict):
                    continue
                candidate = {
                    "primary_message": _clip(item.get("primary_message"),
                                             POSTER_NATIVE_LIMITS["primary_message"]),
                    "support_message": (
                        _clip(item.get("support_message"),
                              POSTER_NATIVE_LIMITS["support_message"])
                        if contract["supports_support_message"] else ""
                    ),
                    "proof_points": [
                        _clip(p, POSTER_NATIVE_LIMITS["proof_point"])
                        for p in (item.get("proof_points") or [])[: contract["max_proof_points"]]
                        if _norm(p)
                    ],
                    "cta": _clip(item.get("cta"), POSTER_NATIVE_LIMITS["cta"]),
                    "disclaimer": _clip(item.get("disclaimer"),
                                        POSTER_NATIVE_LIMITS["disclaimer"]),
                    "tone": _clip(item.get("tone"), 30) or tone,
                    "language": language,
                    "field_provenance": {k: PROVENANCE_AI for k in AI_COPY_FIELDS},
                }
                if not candidate["primary_message"] or not candidate["cta"]:
                    warnings.append(f"AI direction {i + 1} incomplete — dropped.")
                    continue
                if not _direction_is_safe(candidate, contract["archetype"]):
                    warnings.append(f"AI direction {i + 1} failed the safety gate — dropped.")
                    continue
                directions.append(candidate)
                if len(directions) >= count:
                    break
        except ai_provider.AICopyProviderError as exc:
            warnings.append(f"AI directions unavailable: {exc.code or exc}")
    else:
        warnings.append("AI provider not configured — deterministic fallback directions.")

    if len(directions) < count:
        fb_grounding = None
        try:
            fb_grounding = await resolve_copy_grounding(dict(product))
        except Exception:
            fb_grounding = None  # no approved intelligence → neutral, chipless fallback
        for fb in _fallback_directions(
            dict(product), contract, angle, language, fb_grounding
        ):
            if len(directions) >= count:
                break
            if not any(d["primary_message"] == fb["primary_message"] for d in directions):
                directions.append(fb)

    return {
        "product_id": product_id,
        "archetype": contract["archetype"],
        "recipe_id": contract["recipe_id"],
        "angle": angle,
        "directions": directions,
        "ai_model": _provenance_model(),
        "prompt_version": POSTER_COPY_PROMPT_VERSION,
        "ai_provider_status": ai_provider.provider_status(),
        "warnings": warnings,
    }


# ─── Single-field regeneration ────────────────────────────────────────────────

async def regenerate_field(
    product_id: str,
    archetype: str,
    angle: str,
    fields: dict[str, Any],
    field_name: str,
    *,
    language: str = "ms",
) -> dict[str, Any]:
    """Regenerate ONE copy field; every other field is locked context."""
    if field_name not in AI_COPY_FIELDS:
        raise PosterCopyAIError(
            "POSTER_FIELD_NOT_REGENERABLE",
            f"field must be one of {AI_COPY_FIELDS}",
        )
    if not ai_provider.is_configured():
        raise PosterCopyAIError(
            "POSTER_AI_NOT_CONFIGURED",
            "Configure the text-assist provider lane to regenerate fields.",
            status_code=409,
        )
    product = await crud.get_product(_norm(product_id))
    if not product:
        raise PosterCopyAIError("PRODUCT_NOT_FOUND", status_code=404)
    contract = archetype_field_contract(_norm(archetype))
    grounding = await resolve_copy_grounding(dict(product))
    locked = {
        k: fields.get(k)
        for k in AI_COPY_FIELDS
        if k != field_name and fields.get(k)
    }
    limit = POSTER_NATIVE_LIMITS[
        "proof_point" if field_name == "proof_points" else field_name
    ]
    if field_name == "proof_points":
        shape = f'{{"proof_points": [str]}} (max {contract["max_proof_points"]} items, each <={limit} chars)'
    else:
        shape = f'{{"{field_name}": str}} (<={limit} chars)'
    user = (
        _grounding_block(grounding, dict(product))
        + f"\n\nArchetype: {contract['archetype']}. Selling angle: {angle}. "
        f"Language: {language}."
        + "\nLOCKED fields (do NOT change, write something that fits them): "
        + "; ".join(f"{k}={v}" for k, v in locked.items())
        + f"\nTASK: Rewrite ONLY the field `{field_name}`. Return JSON {shape}."
    )
    try:
        raw = ai_provider.complete_json(_SYSTEM_PROMPT, user)
    except ai_provider.AICopyProviderError as exc:
        raise PosterCopyAIError(
            "POSTER_FIELD_REGEN_FAILED", str(exc.code or exc), status_code=502
        )
    if field_name == "proof_points":
        value: Any = [
            _clip(p, limit)
            for p in (raw.get("proof_points") or [])[: contract["max_proof_points"]]
            if _norm(p)
        ]
    else:
        value = _clip(raw.get(field_name), limit)
    if not value:
        raise PosterCopyAIError("POSTER_FIELD_REGEN_EMPTY", status_code=502)
    merged = dict(fields)
    merged[field_name] = value
    merged.setdefault("language", language)
    if not _direction_is_safe(merged, contract["archetype"]):
        raise PosterCopyAIError(
            "POSTER_FIELD_REGEN_UNSAFE",
            "Regenerated value failed the poster safety gate — try again.",
            status_code=422,
        )
    return {
        "field": field_name,
        "value": value,
        "provenance": PROVENANCE_AI,
        "ai_model": _provenance_model(),
        "prompt_version": POSTER_COPY_PROMPT_VERSION,
    }
