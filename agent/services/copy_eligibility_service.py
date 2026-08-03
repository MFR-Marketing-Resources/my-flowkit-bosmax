"""PI-13 C5 / PI-FINAL-B04: COPY_ELIGIBLE fail-closed gate.

A product may enter any copywriting lane (UI/API/bulk/batch/queue/retry/package) ONLY when it is an
active, non-alias real product with an accepted, claim-safe Product Intelligence snapshot whose
copy-critical fields are ALL present. Everything else fails CLOSED. Merged aliases and residual/debt
products are never copy-eligible. This is deliberately strict: copy grounded on missing or
unverified intelligence is exactly the downstream debt PI-13 exists to prevent.

Enforcement: call `assert_copy_eligible(product_id)` at every copy/production entrypoint; it raises
ValueError("COPY_INELIGIBLE:<reason,...>") which API routers map to HTTP 409. Background lanes
(queue worker, scheduler, retry) call it too, so a product that becomes ineligible AFTER an item
was queued still cannot execute.
"""
from __future__ import annotations
from typing import Any, Optional

from agent.db import get_db

# The copy-critical contract (PI-FINAL): every field copy generation grounds on. These can never
# be satisfied by governed absence - they must be PRESENT in the latest APPROVED snapshot.
COPY_CRITICAL_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "target_customer_text",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "claim_gate",
    "claim_risk_level",
)
_MERGED_MARKER = "DUPLICATE_MERGED_TO_CANONICAL"

COPY_INELIGIBLE_PREFIX = "COPY_INELIGIBLE:"

# Stale-asset quarantine states carried on copy_set.pi_eligibility_status (nullable; NULL = clear).
PI_INELIGIBLE = "PI_INELIGIBLE"          # product currently fails the gate
NEEDS_REVALIDATION = "NEEDS_REVALIDATION"  # product recovered, asset predates the accepted snapshot
BLOCKED = "BLOCKED"                        # reserved for explicit owner/claim blocks


def evaluate_copy_eligibility(
    *,
    lifecycle_status: Optional[str],
    archived_reason: Optional[str],
    has_approved_snapshot: bool,
    claim_gate: Optional[str],
    copy_critical_present: dict[str, bool],
    claim_review_acknowledged: bool = False,
) -> dict[str, Any]:
    """Pure decision function (no DB) so it is trivially testable and identical everywhere."""
    reasons: list[str] = []
    if str(archived_reason or "").upper().startswith(_MERGED_MARKER):
        reasons.append("MERGED_ALIAS")
    if str(lifecycle_status or "ACTIVE").upper() != "ACTIVE":
        reasons.append("NOT_ACTIVE")
    if not has_approved_snapshot:
        reasons.append("NO_ACCEPTED_SNAPSHOT")
    # Claim gate must be explicitly safe. CLAIM_REVIEW_REQUIRED is acceptable ONLY
    # when the approving reviewer recorded an explicit acknowledgement (the
    # claim-floor products - catalog claim_risk_level=HIGH - and benign-context
    # downgrades can never scan CLAIM_SAFE by design; the acknowledgement IS their
    # resolved state). CLAIM_BLOCKED and unknown always fail closed.
    gate = str(claim_gate or "").upper()
    if gate != "CLAIM_SAFE" and not (
        gate == "CLAIM_REVIEW_REQUIRED" and claim_review_acknowledged
    ):
        reasons.append(f"CLAIM_NOT_SAFE:{claim_gate or 'UNKNOWN'}")
    missing = [f for f in COPY_CRITICAL_FIELDS if not copy_critical_present.get(f)]
    if missing:
        reasons.append("MISSING_COPY_CRITICAL:" + ",".join(missing))
    return {"eligible": not reasons, "reasons": reasons}


def _ne(v: Any) -> bool:
    return v is not None and str(v).strip() not in ("", "[]", "{}", "null")


async def copy_eligibility(product_id: str) -> dict[str, Any]:
    """DB-backed evaluation for a single product. Fails closed if the product does not exist.

    Copy-critical presence is read from the latest APPROVED snapshot itself - the frozen,
    versioned authority - never from the mutable review-draft table.
    """
    db = await get_db()
    cur = await db.execute(
        "SELECT lifecycle_status, archived_reason FROM product WHERE id = ?", (product_id,))
    p = await cur.fetchone(); await cur.close()
    if not p:
        return {"product_id": product_id, "eligible": False, "reasons": ["PRODUCT_NOT_FOUND"]}
    field_list = ", ".join(f"s.{f}" for f in COPY_CRITICAL_FIELDS)
    cur = await db.execute(
        f"SELECT {field_list}, s.created_from_review_draft_id FROM product_intelligence_snapshot s "
        "WHERE s.product_id = ? AND s.status = 'APPROVED' "
        "ORDER BY s.version DESC LIMIT 1", (product_id,))
    s = await cur.fetchone(); await cur.close()
    present = {f: (_ne(s[f]) if s else False) for f in COPY_CRITICAL_FIELDS}
    acknowledged = False
    if s and str(s["claim_gate"] or "").upper() == "CLAIM_REVIEW_REQUIRED" and s["created_from_review_draft_id"]:
        # The acknowledgement is written into the approving draft's reviewer_note
        # by approve_review_draft (a terminal, immutable row).
        cur = await db.execute(
            "SELECT reviewer_note FROM product_intelligence_review_draft WHERE draft_id = ?",
            (s["created_from_review_draft_id"],))
        d = await cur.fetchone(); await cur.close()
        acknowledged = bool(d and "CLAIM_REVIEW_ACKNOWLEDGED" in str(d["reviewer_note"] or ""))
    out = evaluate_copy_eligibility(
        lifecycle_status=p["lifecycle_status"], archived_reason=p["archived_reason"],
        has_approved_snapshot=bool(s), claim_gate=(s["claim_gate"] if s else None),
        copy_critical_present=present, claim_review_acknowledged=acknowledged)
    out["product_id"] = product_id
    return out


async def assert_copy_eligible(product_id: str) -> dict[str, Any]:
    """Fail-closed guard for every copy/production entrypoint.

    Raises ValueError("COPY_INELIGIBLE:<reasons>") when the product may not enter a copy lane.
    Returns the eligibility record when eligible, so callers can log it.
    """
    result = await copy_eligibility(product_id)
    if not result["eligible"]:
        raise ValueError(COPY_INELIGIBLE_PREFIX + ",".join(result["reasons"]))
    return result


async def quarantine_stale_copy_assets(*, revalidation_for_recovered: bool = True) -> dict[str, Any]:
    """Rebuild the stale-copy containment state from the LIVE eligibility truth.

    - copy sets on currently-INELIGIBLE products -> pi_eligibility_status='PI_INELIGIBLE'
      (excluded from rotation/selection/readiness/execution by the eligibility predicates).
    - copy sets on ELIGIBLE products that were quarantined before, or that were created BEFORE the
      product's current accepted snapshot -> 'NEEDS_REVALIDATION' when
      revalidation_for_recovered=True (they were generated from since-revised intelligence).
    - Nothing is deleted; rows keep full content and history.
    """
    db = await get_db()
    cur = await db.execute(
        "SELECT DISTINCT product_id FROM copy_set WHERE product_id IS NOT NULL")
    product_ids = [str(r[0]) for r in await cur.fetchall()]
    await cur.close()
    marked_ineligible = 0
    marked_revalidation = 0
    cleared = 0
    for pid in product_ids:
        record = await copy_eligibility(pid)
        if not record["eligible"]:
            reasons = ",".join(record["reasons"])
            res = await db.execute(
                "UPDATE copy_set SET pi_eligibility_status=?, pi_ineligible_reasons=? "
                "WHERE product_id=? AND (pi_eligibility_status IS NULL "
                "OR pi_eligibility_status<>? OR COALESCE(pi_ineligible_reasons,'')<>?)",
                (PI_INELIGIBLE, reasons, pid, PI_INELIGIBLE, reasons))
            marked_ineligible += max(res.rowcount or 0, 0)
            continue
        if revalidation_for_recovered:
            # product is eligible NOW: any copy asset created before the current accepted
            # snapshot (or previously quarantined) needs revalidation before reuse
            res = await db.execute(
                "UPDATE copy_set SET pi_eligibility_status=?, pi_ineligible_reasons=NULL "
                "WHERE product_id=? AND pi_eligibility_status=?",
                (NEEDS_REVALIDATION, pid, PI_INELIGIBLE))
            marked_revalidation += max(res.rowcount or 0, 0)
        else:
            res = await db.execute(
                "UPDATE copy_set SET pi_eligibility_status=NULL, pi_ineligible_reasons=NULL "
                "WHERE product_id=? AND pi_eligibility_status=?",
                (PI_INELIGIBLE, pid))
            cleared += max(res.rowcount or 0, 0)
    await db.commit()
    return {
        "products_checked": len(product_ids),
        "marked_pi_ineligible": marked_ineligible,
        "marked_needs_revalidation": marked_revalidation,
        "cleared": cleared,
    }
