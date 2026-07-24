"""Author atomic copy components with the AI lane — Phase B2.

One call authors N components of ONE type for ONE angle. That is the whole
economic point: the LLM is paid to produce reusable PARTS, not whole copy sets,
so capacity grows multiplicatively (Phase B1) instead of one-call-per-variation.

CONTRACT (mirrors ai_copy_assist_service, deliberately)
------------------------------------------------------
* Candidates land `COMPONENT_REVIEW_REQUIRED`. **Never auto-approved** — the
  operator approval gate is the claim-safety control and this lane does not
  bypass it.
* Every component is claim-scanned INDIVIDUALLY with the same
  `scan_copy_safety` the copy lane uses, by placing the text in its real slot
  so the scanner sees it exactly as it will appear.
* Deduped on a normalised hash, so the same hook cannot re-enter a pool under
  different casing or punctuation. The DB UNIQUE index is the hard guard.
* `dry_run=True` validates product/angle/type and returns the exact brief
  WITHOUT calling the provider and WITHOUT persisting — zero token spend.
* Fail-closed: unknown product, no approved snapshot, unknown angle_key, or an
  unconfigured provider all raise instead of inventing components.

The angle is resolved by re-deriving from the snapshot's own approved persona
(Phase A), so this works identically for snapshots written by A2 and for legacy
snapshots repaired at read time — no dependency on which path produced them.
"""
from __future__ import annotations

import json
from typing import Any

from agent.db import crud
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_angle_derivation
from agent.services.copy_component_service import (
    COMPONENT_TYPES,
    CTA,
    HOOK,
    SUBHOOK,
    USP_SET,
    make_dedupe_key,
)
from agent.services.copy_set_service import scan_copy_safety

__all__ = ["author_components", "build_brief", "STATUS_REVIEW_REQUIRED", "MAX_PER_CALL"]

STATUS_REVIEW_REQUIRED = "COMPONENT_REVIEW_REQUIRED"
SOURCE = "AI_COMPONENT_AUTHOR"
MAX_PER_CALL = 12
MIN_PER_CALL = 2

# What each component type IS, in the composed copy. Kept explicit because the
# model must not blur them: a hook that is really a CTA breaks composition.
_TYPE_BRIEF: dict[str, str] = {
    HOOK: (
        "HOOK — the opening line that stops the scroll. ONE sentence or a short "
        "question. It names the pain from the angle. It must NOT sell, list "
        "features, or contain a call to action."
    ),
    SUBHOOK: (
        "SUBHOOK — one or two sentences that deepen the hook by making the pain "
        "concrete and relatable. It must NOT repeat the hook's wording, and must "
        "NOT contain a call to action or a price."
    ),
    USP_SET: (
        "USP_SET — exactly 3 short benefit statements grounded in the product's "
        "real benefits/USPs. No medical claims, no cure/treat/heal language, no "
        "invented ingredients."
    ),
    CTA: (
        "CTA — one short closing line telling the viewer what to do next. No "
        "price, no discount claim, no medical promise."
    ),
}

_SYSTEM = (
    "You are a Malay (BM) direct-response copywriter for TikTok. You write "
    "ONE component type at a time as reusable building blocks that will be "
    "recombined with other components. Never write a complete ad. Never invent "
    "product facts, ingredients, certifications or results. Never make medical "
    "claims (no cure/treat/heal/diagnose). Return STRICT JSON only."
)


def _slot_fields(component_type: str, value: Any) -> dict[str, Any]:
    """Place a component's text in its REAL copy slot so the claim scanner sees
    it exactly as it will appear in a composed copy."""
    if component_type == USP_SET:
        return {"usp_set": value if isinstance(value, list) else [str(value)]}
    return {{HOOK: "hook", SUBHOOK: "subhook", CTA: "cta"}[component_type]: str(value)}


def build_brief(
    product: dict[str, Any],
    grounding: Any,
    angle: dict[str, Any],
    component_type: str,
    count: int,
) -> tuple[str, str]:
    """(system, user) for one angle + one component type. Pure — no I/O."""
    knowledge = getattr(grounding, "product_knowledge", None)
    persona = getattr(grounding, "buyer_persona", None)
    guardrails = getattr(grounding, "claim_guardrails", None)

    payload = {
        "task": f"Write {count} DISTINCT {component_type} components.",
        "component_type_rules": _TYPE_BRIEF[component_type],
        "language": "BM_MS",
        "platform": "TIKTOK",
        "product_name": product.get("product_display_name") or product.get("raw_product_title"),
        "angle": {
            "label": angle.get("label"),
            "pain": angle.get("pain"),
            "desire": angle.get("desire"),
            "fear": angle.get("fear"),
            "trigger": angle.get("trigger"),
            "audience": angle.get("audience"),
        },
        "product_benefits": list(getattr(knowledge, "benefits", []) or []),
        "product_usps": list(getattr(knowledge, "usps", []) or []),
        "tone": getattr(persona, "tone", "") if persona else "",
        "pronoun": getattr(persona, "pronoun", "anda") if persona else "anda",
        "banned_terms": list(getattr(guardrails, "banned_terms", []) or []),
        "blocked_claims": list(getattr(guardrails, "blocked_claims", []) or []),
        "hard_rules": [
            "Every item must be usable for THIS angle only.",
            "Items must differ in idea, not just wording.",
            "No medical claims. No invented facts. No prices.",
            "Do not write a full ad — only the requested component type.",
        ],
        "output_schema": (
            '{"items": [{"text": "..."}]}' if component_type != USP_SET
            else '{"items": [{"usps": ["...", "...", "..."]}]}'
        ),
    }
    return _SYSTEM, json.dumps(payload, ensure_ascii=False, indent=2)


def _extract(raw: Any, component_type: str) -> list[Any]:
    """Provider JSON -> list of component values. Tolerant, but never invents."""
    items = (raw or {}).get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out: list[Any] = []
    for it in items:
        if component_type == USP_SET:
            usps = it.get("usps") if isinstance(it, dict) else it
            if isinstance(usps, list):
                cleaned = [str(u).strip() for u in usps if str(u).strip()]
                if cleaned:
                    out.append(cleaned)
        else:
            text = it.get("text") if isinstance(it, dict) else it
            text = str(text or "").strip()
            if text:
                out.append(text)
    return out


async def author_components(
    product_id: str,
    angle_key: str,
    component_type: str,
    count: int = 6,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Author `count` components of one type for one angle. See module docstring."""
    ctype = str(component_type or "").strip().upper()
    if ctype not in COMPONENT_TYPES:
        raise ValueError(f"UNKNOWN_COMPONENT_TYPE:{component_type}")
    n = int(count or 0)
    if n < MIN_PER_CALL or n > MAX_PER_CALL:
        raise ValueError(f"COUNT_OUT_OF_RANGE:{MIN_PER_CALL}..{MAX_PER_CALL}")

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    if not snap:
        # Without an approved persona there are no product-specific angles, so
        # components would hang off a generic family label — the exact defect
        # Phase A exists to remove.
        raise ValueError("NO_APPROVED_SNAPSHOT:author_product_intelligence_first")

    persona = snap.get("buyer_persona_snapshot_json") if isinstance(snap, dict) else None
    if isinstance(persona, str):
        try:
            persona = json.loads(persona or "{}")
        except Exception:  # noqa: BLE001
            persona = {}
    derivation = copy_angle_derivation.derive_angles(persona)
    if not derivation.get("derived"):
        raise ValueError("NO_DERIVABLE_ANGLES:" + ",".join(derivation.get("warnings") or []))

    angle = next(
        (a for a in derivation["angles"] if a["angle_key"] == str(angle_key).strip()), None
    )
    if angle is None:
        raise ValueError(
            "UNKNOWN_ANGLE_KEY:" + str(angle_key)
            + " available=" + ",".join(a["angle_key"] for a in derivation["angles"])
        )

    from agent.services.copy_grounding_service import resolve_copy_grounding

    grounding = await resolve_copy_grounding(product)
    system, user = build_brief(product, grounding, angle, ctype, n)

    if dry_run:
        return {
            "product_id": product_id, "angle_key": angle["angle_key"],
            "angle_label": angle["label"], "component_type": ctype,
            "requested_count": n, "created_count": 0, "deduped_count": 0,
            "rejected_count": 0, "dry_run": True, "items": [],
            "provider": ai_provider.provider_status(),
            "brief_preview": {"system": system, "user": user},
            "warnings": ["DRY_RUN_NO_PERSIST"],
        }

    raw = ai_provider.complete_json(system, user)  # raises when unconfigured
    values = _extract(raw, ctype)

    created, deduped, rejected = [], 0, 0
    warnings: list[str] = []
    for value in values[:n]:
        content = json.dumps(value, ensure_ascii=False) if ctype == USP_SET else str(value)
        dkey = make_dedupe_key(content)
        if await crud.find_copy_component_by_dedupe_key(product_id, ctype, dkey):
            deduped += 1
            continue
        safety = scan_copy_safety(_slot_fields(ctype, value), product_id=product_id)
        if not safety["safe"]:
            rejected += 1
            warnings.append(f"UNSAFE_SKIPPED:{','.join(safety['violations'])}")
            continue
        row = await crud.create_copy_component(
            product_id,
            angle_key=angle["angle_key"],
            angle_label=angle["label"],
            component_type=ctype,
            content=content,
            status=STATUS_REVIEW_REQUIRED,
            claim_review_json=json.dumps({"safety": safety}, ensure_ascii=False),
            dedupe_key=dkey,
            source=SOURCE,
            provenance_json=json.dumps(
                {"lane": "text_assist", "angle_key": angle["angle_key"]},
                ensure_ascii=False,
            ),
        )
        created.append(row)

    if len(values) < n:
        warnings.append(f"PROVIDER_RETURNED_FEWER:{len(values)}/{n}")

    return {
        "product_id": product_id, "angle_key": angle["angle_key"],
        "angle_label": angle["label"], "component_type": ctype,
        "requested_count": n, "created_count": len(created),
        "deduped_count": deduped, "rejected_count": rejected,
        "dry_run": False, "items": created,
        "provider": ai_provider.provider_status(),
        "warnings": warnings,
    }
