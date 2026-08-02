"""PI-13 C5: COPY_ELIGIBLE fail-closed gate.

A product may enter any copywriting lane (UI/API/bulk/batch/queue/retry/package) ONLY when it is an
active, non-alias real product with an accepted, claim-safe Product Intelligence snapshot whose
copy-critical fields are present. Everything else fails CLOSED. Merged aliases and residual/debt
products are never copy-eligible. This is deliberately strict: copy grounded on missing or
unverified intelligence is exactly the downstream debt PI-13 exists to prevent.
"""
from __future__ import annotations
from typing import Any, Optional

from agent.db import get_db

# fields a grounded copy lane must have to say anything true about the product
COPY_CRITICAL_FIELDS = ("product_description", "benefits_json", "usp_json")
_MERGED_MARKER = "DUPLICATE_MERGED_TO_CANONICAL"


def evaluate_copy_eligibility(
    *,
    lifecycle_status: Optional[str],
    archived_reason: Optional[str],
    has_approved_snapshot: bool,
    claim_gate: Optional[str],
    copy_critical_present: dict[str, bool],
) -> dict[str, Any]:
    """Pure decision function (no DB) so it is trivially testable and identical everywhere."""
    reasons: list[str] = []
    if str(archived_reason or "").upper().startswith(_MERGED_MARKER):
        reasons.append("MERGED_ALIAS")
    if str(lifecycle_status or "ACTIVE").upper() != "ACTIVE":
        reasons.append("NOT_ACTIVE")
    if not has_approved_snapshot:
        reasons.append("NO_ACCEPTED_SNAPSHOT")
    # claim gate must be explicitly safe; blocked / review / unknown all fail closed
    if str(claim_gate or "").upper() != "CLAIM_SAFE":
        reasons.append(f"CLAIM_NOT_SAFE:{claim_gate or 'UNKNOWN'}")
    missing = [f for f in COPY_CRITICAL_FIELDS if not copy_critical_present.get(f)]
    if missing:
        reasons.append("MISSING_COPY_CRITICAL:" + ",".join(missing))
    return {"eligible": not reasons, "reasons": reasons}


async def copy_eligibility(product_id: str) -> dict[str, Any]:
    """DB-backed evaluation for a single product. Fails closed if the product does not exist."""
    db = await get_db()
    cur = await db.execute(
        "SELECT lifecycle_status, archived_reason FROM product WHERE id = ?", (product_id,))
    p = await cur.fetchone(); await cur.close()
    if not p:
        return {"product_id": product_id, "eligible": False, "reasons": ["PRODUCT_NOT_FOUND"]}
    cur = await db.execute(
        "SELECT s.claim_gate AS claim_gate, d.product_description AS pd, d.benefits_json AS bj, d.usp_json AS uj "
        "FROM product_intelligence_snapshot s "
        "LEFT JOIN product_intelligence_review_draft d ON d.draft_id = s.created_from_review_draft_id "
        "WHERE s.product_id = ? AND s.status = 'APPROVED' ORDER BY s.version DESC LIMIT 1", (product_id,))
    s = await cur.fetchone(); await cur.close()

    def _ne(v: Any) -> bool:
        return v is not None and str(v).strip() not in ("", "[]", "{}", "null")

    present = {"product_description": _ne(s["pd"]) if s else False,
               "benefits_json": _ne(s["bj"]) if s else False,
               "usp_json": _ne(s["uj"]) if s else False}
    out = evaluate_copy_eligibility(
        lifecycle_status=p["lifecycle_status"], archived_reason=p["archived_reason"],
        has_approved_snapshot=bool(s), claim_gate=(s["claim_gate"] if s else None),
        copy_critical_present=present)
    out["product_id"] = product_id
    return out
