"""Formula Validator — does this copy actually obey its formula + sell?

Validates a generated Copy Set against the selected formula's slot contract
(copy_formula_registry) plus grounding and the claim boundary. Fails / marks
review-required when:
  - a required formula slot is empty (PAS w/o Agitate, AIDA w/o Desire bridge,
    HSO w/o Story/Offer, ...),
  - the copy names NO real buyer problem / market language (vague, cowardly),
  - USPs are not connected to approved product facts,
  - the CTA is generic and disconnected from the buyer,
  - the copy contains OVERCLAIM (hard fail).

Never invents product claims. Purely a QA/gate over already-generated copy.
"""
from __future__ import annotations

from typing import Any

from agent.authority import claim_boundary
from agent.authority.copy_formula_registry import get_formula

_GENERIC_CTA = {
    "beli sekarang", "klik sekarang", "klik link", "klik", "order sekarang",
    "shop now", "buy now", "dapatkan sekarang", "grab now", "checkout sekarang",
}

_STOPWORDS = {
    "yang", "dan", "untuk", "dengan", "anda", "saya", "kau", "aku", "ini", "itu",
    "the", "and", "for", "with", "your", "you", "a", "to", "of", "is", "in",
    "dalam", "pada", "atau", "juga", "tanpa", "bila", "boleh", "akan", "dari",
}


def _s(value: Any) -> str:
    return str(value or "").strip()


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _s(text).casefold().replace("/", " ").split():
        tok = "".join(ch for ch in raw if ch.isalnum())
        if len(tok) >= 4 and tok not in _STOPWORDS:
            out.add(tok)
    return out


def _any_overlap(a_list: list[str], b_list: list[str]) -> bool:
    a: set[str] = set()
    for x in a_list:
        a |= _tokens(x)
    b: set[str] = set()
    for y in b_list:
        b |= _tokens(y)
    return bool(a & b)


def _reverse_slot_map(mapping: dict[str, Any]) -> dict[str, list[str]]:
    """slot_id -> every copy field that carries it (from output_mapping). A slot
    is considered covered if ANY of its mapped fields has content."""
    rev: dict[str, list[str]] = {}
    for field, slot in mapping.items():
        slots = slot if isinstance(slot, list) else [slot]
        for s in slots:
            rev.setdefault(s, []).append(field)
    return rev


def _copy_field_text(field: str, copy_fields: dict[str, Any]) -> str:
    if field == "usp":
        return " ".join(_s(u) for u in (copy_fields.get("usp_set") or []))
    return _s(copy_fields.get(field))


def _mentions_avatar_pain(text: str, grounding: Any) -> bool:
    persona = getattr(grounding, "buyer_persona", None)
    pains = list(getattr(persona, "pains", []) or []) + list(getattr(persona, "desires", []) or [])
    hay = _tokens(text)
    for p in pains:
        if _tokens(p) & hay:
            return True
    return False


def validate_formula_copy(
    formula_id: Any,
    copy_fields: dict[str, Any],
    breakdown: dict[str, Any] | None = None,
    grounding: Any = None,
) -> dict[str, Any]:
    formula = get_formula(formula_id)
    fid = formula["formula_id"]
    breakdown = breakdown or {}
    reverse = _reverse_slot_map(formula["output_mapping"])
    violations: list[dict[str, Any]] = []
    slot_coverage: dict[str, bool] = {}

    # 1. Slot coverage — from breakdown if authored, else the mapped copy field.
    for slot in formula["slots"]:
        sid = slot["slot_id"]
        text = _s(breakdown.get(sid))
        if not text:
            fields = reverse.get(sid, [])
            text = " ".join(_copy_field_text(f, copy_fields) for f in fields).strip()
        present = bool(text)
        slot_coverage[sid] = present
        if slot.get("required") and not present:
            violations.append({
                "code": f"SLOT_MISSING:{sid}", "slot": sid, "severity": "review",
                "message": f"{fid} requires '{sid}' — {slot['purpose']}",
            })

    # 2. Overclaim (hard fail).
    is_stealth = bool(getattr(grounding, "is_stealth", False))
    all_text = " ".join([
        _s(copy_fields.get("angle")), _s(copy_fields.get("hook")),
        _s(copy_fields.get("subhook")),
        " ".join(_s(u) for u in (copy_fields.get("usp_set") or [])),
        _s(copy_fields.get("cta")), " ".join(_s(v) for v in breakdown.values()),
    ])
    boundary = claim_boundary.assess_claim_boundary(all_text, is_stealth=is_stealth)
    for hit in boundary["overclaim_hits"]:
        violations.append({
            "code": "OVERCLAIM", "term": hit, "severity": "fail",
            "message": f"Overclaim '{hit}': control claims — no cure/guarantee/clinical/certification.",
        })

    # 3. Anti-cowardly: copy MUST name a real buyer problem / market language.
    problem_present = bool(boundary["problem_language_present"]) or _mentions_avatar_pain(all_text, grounding)
    if not problem_present:
        violations.append({
            "code": "NO_PROBLEM_IDENTIFIED", "severity": "review",
            "message": "Copy names no real buyer problem / market language — too vague to sell. Preserve the customer's actual problem.",
        })

    # 4. USPs must connect to approved product facts when they exist.
    pk = getattr(grounding, "product_knowledge", None)
    facts = list(getattr(pk, "benefits", []) or []) + list(getattr(pk, "usps", []) or [])
    usps = [u for u in (copy_fields.get("usp_set") or []) if _s(u)]
    if facts and usps and not _any_overlap(usps, facts):
        violations.append({
            "code": "USP_NOT_GROUNDED", "severity": "review",
            "message": "USPs do not connect to approved product facts.",
        })

    # 5. CTA quality.
    cta = _s(copy_fields.get("cta"))
    if cta and cta.casefold() in _GENERIC_CTA:
        violations.append({
            "code": "CTA_GENERIC", "severity": "review",
            "message": "CTA is generic and disconnected from the buyer situation.",
        })

    has_fail = any(v["severity"] == "fail" for v in violations)
    has_review = any(v["severity"] == "review" for v in violations)
    return {
        "formula_id": fid,
        "definition_status": formula["definition_status"],
        "valid": not has_fail,
        "review_required": has_fail or has_review,
        "slot_coverage": slot_coverage,
        "violations": violations,
    }
