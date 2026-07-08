"""Sales Clarity QA — would a real TikTok Shop buyer understand and want this?

Independent of the formula slot check: every generated Copy Set must be able to
answer the buyer-clarity questions. Below threshold => review-required (never
auto-approved). Reuses the formula validator's slot_coverage so the two agree.
"""
from __future__ import annotations

from typing import Any

from agent.authority import claim_boundary
from agent.services.formula_validator_service import (
    _any_overlap,
    _mentions_avatar_pain,
    _s,
)

# A readable short-video copy set: enough substance, not a wall of text.
_MIN_TOTAL_CHARS = 40
_MAX_TOTAL_CHARS = 1200


def assess_sales_clarity(
    copy_fields: dict[str, Any],
    grounding: Any = None,
    formula_id: str = "",
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    persona = getattr(grounding, "buyer_persona", None)
    pk = getattr(grounding, "product_knowledge", None)

    hook = _s(copy_fields.get("hook"))
    cta = _s(copy_fields.get("cta"))
    usps = [u for u in (copy_fields.get("usp_set") or []) if _s(u)]
    all_text = " ".join([
        _s(copy_fields.get("angle")), hook, _s(copy_fields.get("subhook")),
        " ".join(usps), cta,
    ])
    total_chars = len(all_text.strip())

    facts = list(getattr(pk, "benefits", []) or []) + list(getattr(pk, "usps", []) or [])
    is_stealth = bool(getattr(grounding, "is_stealth", False))
    boundary = claim_boundary.assess_claim_boundary(all_text, is_stealth=is_stealth)

    slot_cov = (validation or {}).get("slot_coverage", {})
    slots_satisfied = bool(slot_cov) and all(slot_cov.values())

    answers = {
        # Who is the customer?
        "customer": bool(_s(getattr(persona, "audience", "")) or _s(getattr(pk, "target_customer", ""))),
        # What problem is being solved? (market language OR avatar pain — not vague)
        "problem": bool(boundary["problem_language_present"]) or _mentions_avatar_pain(all_text, grounding),
        # What situation triggers the buying need?
        "situation": _mentions_avatar_pain(all_text, grounding)
        or bool(list(getattr(persona, "triggers", []) or [])) and _mentions_trigger(all_text, persona),
        # What product knowledge supports this copy?
        "product_knowledge_support": (_any_overlap(usps, facts) if facts else bool(_s(getattr(pk, "description", "")))),
        # What formula was used + were its slots satisfied?
        "formula": bool(formula_id),
        "slots_satisfied": slots_satisfied,
        # Reason to buy now?
        "reason_to_buy_now": bool(cta) and cta.casefold() not in _GENERIC,
        # Clear enough for a real buyer?
        "tiktok_clear": bool(hook) and bool(cta) and _MIN_TOTAL_CHARS <= total_chars <= _MAX_TOTAL_CHARS and boundary["safe"],
    }
    gaps = [k for k, v in answers.items() if not v]
    score = round(sum(1 for v in answers.values() if v) / len(answers), 2)
    return {
        "clarity_score": score,
        "answers": answers,
        "gaps": gaps,
        # A copy is clear when it leaves no gap on the load-bearing questions.
        "clear": not ({"problem", "customer", "tiktok_clear", "reason_to_buy_now"} & set(gaps)),
        "review_required": bool(gaps),
    }


_GENERIC = {
    "beli sekarang", "klik sekarang", "klik link", "klik", "order sekarang",
    "shop now", "buy now", "dapatkan sekarang",
}


def _mentions_trigger(text: str, persona: Any) -> bool:
    from agent.services.formula_validator_service import _tokens

    hay = _tokens(text)
    for t in list(getattr(persona, "triggers", []) or []):
        if _tokens(t) & hay:
            return True
    return False
