"""COPY-FINAL-B01 — single shared Copy-Set validity authority.

Product-level COPY_ELIGIBLE (copy_eligibility_service) answers:
  "may this product enter a copy lane at all?"

Copy-Set-level VALIDITY answers:
  "is THIS specific Copy Set a valid current approved production asset?"

Reporting, readiness, rotation, selection, binding, and package creation MUST
share this predicate. "Has any non-archived copy_set row" is NOT validity.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from agent.db import get_db
from agent.models.copy_set import STATUS_COPY_APPROVED
from agent.services.copy_eligibility_service import (
    BLOCKED,
    NEEDS_REVALIDATION,
    PI_INELIGIBLE,
    copy_eligibility,
)

# Product-level classifications (deterministic precedence).
CLASS_APPROVED_COPY_VALID = "APPROVED_COPY_VALID"
CLASS_APPROVED_COPY_STALE = "APPROVED_COPY_STALE"
CLASS_COPY_REVIEW_REQUIRED_ONLY = "COPY_REVIEW_REQUIRED_ONLY"
CLASS_DRAFT_COPY_ONLY = "DRAFT_COPY_ONLY"
CLASS_REJECTED_COPY_ONLY = "REJECTED_COPY_ONLY"
CLASS_MISSING_COPY = "MISSING_COPY"
CLASS_BLOCKED_WITH_REASON = "BLOCKED_WITH_REASON"

ACTION_PRESERVE_VALID_APPROVED = "PRESERVE_VALID_APPROVED"
ACTION_REVALIDATE_APPROVED = "REVALIDATE_APPROVED"
ACTION_REVIEW_EXISTING = "REVIEW_EXISTING"
ACTION_REPAIR_EXISTING = "REPAIR_EXISTING"
ACTION_GENERATE_MISSING = "GENERATE_MISSING"
ACTION_BLOCK_WITH_REASON = "BLOCK_WITH_REASON"
ACTION_READY = "READY"

QUARANTINE_BAD = {PI_INELIGIBLE, NEEDS_REVALIDATION, BLOCKED, "BLOCKED"}


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def pi_authority_digest(snapshot_row: dict[str, Any] | Any) -> str:
    """Stable digest of the current approved PI authority used for lineage."""
    get = snapshot_row.get if isinstance(snapshot_row, dict) else snapshot_row.__getitem__
    payload = {
        "snapshot_id": get("snapshot_id"),
        "version": get("version"),
        "claim_gate": get("claim_gate"),
        "product_description": get("product_description"),
        "benefits_json": get("benefits_json"),
        "usp_json": get("usp_json"),
        "target_customer_text": get("target_customer_text"),
        "allowed_claims_json": get("allowed_claims_json"),
        "buyer_persona_snapshot_json": get("buyer_persona_snapshot_json"),
        "copy_strategy_summary_json": get("copy_strategy_summary_json"),
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def evaluate_copy_set_validity(
    *,
    copy_set: dict[str, Any],
    product_eligible: bool,
    product_eligibility_reasons: list[str] | None,
    current_snapshot_id: str | None,
    current_snapshot_version: int | None,
    current_authority_digest: str | None,
    require_lineage_match: bool = True,
) -> dict[str, Any]:
    """Pure asset-level validity. No I/O.

    A valid production Copy Set must be:
    - COPY_APPROVED, not archived
    - not quarantined (PI_INELIGIBLE / NEEDS_REVALIDATION / BLOCKED)
    - on a currently COPY_ELIGIBLE product
    - complete + safe at last review (claim_review)
    - grounded on the current approved PI authority when lineage is known
      (missing lineage on approved sets is treated as STALE when require_lineage_match)
    """
    reasons: list[str] = []
    status = _clean(copy_set.get("status")).upper()
    archived = bool(copy_set.get("archived"))
    quar = _clean(copy_set.get("pi_eligibility_status")).upper() or None

    if status != STATUS_COPY_APPROVED:
        reasons.append(f"STATUS_NOT_APPROVED:{status or 'UNKNOWN'}")
    if archived:
        reasons.append("ARCHIVED")
    if quar in QUARANTINE_BAD:
        reasons.append(f"QUARANTINED:{quar}")
    if not product_eligible:
        reasons.append(
            "PRODUCT_INELIGIBLE:"
            + ",".join(product_eligibility_reasons or ["UNKNOWN"])
        )

    claim = copy_set.get("claim_review")
    if claim is None:
        claim = _parse_json(copy_set.get("claim_review_json")) or {}
    if not isinstance(claim, dict):
        claim = {}

    completeness = claim.get("completeness") or {}
    safety = claim.get("safety") or {}
    if completeness and completeness.get("complete") is False:
        reasons.append("INCOMPLETE")
    if safety and safety.get("safe") is False:
        reasons.append("UNSAFE")

    fv = claim.get("formula_validation") or {}
    sc = claim.get("sales_clarity") or {}
    override = claim.get("approval_override") or {}
    if fv and (not fv.get("valid", False) or fv.get("review_required")) and not override:
        # Only block when formula verdict exists and was not overridden at approval.
        if not override.get("formula_review_overridden"):
            reasons.append("FORMULA_REVIEW_OPEN")
    if sc and (not sc.get("clear", False) or sc.get("review_required")) and not override:
        if not override.get("sales_clarity_overridden"):
            reasons.append("SALES_CLARITY_OPEN")

    # Lineage / freshness against current PI authority.
    cs_snap = _clean(copy_set.get("pi_snapshot_id")) or None
    cs_ver = copy_set.get("pi_snapshot_version")
    try:
        cs_ver_i = int(cs_ver) if cs_ver is not None and str(cs_ver).strip() != "" else None
    except (TypeError, ValueError):
        cs_ver_i = None
    cs_digest = _clean(copy_set.get("pi_grounding_digest")) or None
    # Fall back to provenance_json lineage when dedicated columns empty.
    if not cs_snap or not cs_digest:
        prov = copy_set.get("provenance")
        if prov is None:
            prov = _parse_json(copy_set.get("provenance_json")) or {}
        if isinstance(prov, dict):
            lineage = prov.get("pi_lineage") or prov.get("product_intelligence") or {}
            if isinstance(lineage, dict):
                cs_snap = cs_snap or _clean(lineage.get("snapshot_id")) or None
                if cs_ver_i is None and lineage.get("version") is not None:
                    try:
                        cs_ver_i = int(lineage.get("version"))
                    except (TypeError, ValueError):
                        pass
                cs_digest = cs_digest or _clean(lineage.get("authority_digest")) or None

    stale = False
    if require_lineage_match and current_snapshot_id:
        if not cs_snap and not cs_digest:
            stale = True
            reasons.append("MISSING_PI_LINEAGE")
        else:
            if cs_snap and cs_snap != current_snapshot_id:
                stale = True
                reasons.append("PI_SNAPSHOT_MISMATCH")
            if (
                cs_ver_i is not None
                and current_snapshot_version is not None
                and cs_ver_i != int(current_snapshot_version)
            ):
                stale = True
                reasons.append("PI_VERSION_MISMATCH")
            if cs_digest and current_authority_digest and cs_digest != current_authority_digest:
                stale = True
                reasons.append("PI_DIGEST_MISMATCH")

    valid = not reasons
    return {
        "valid": valid,
        "stale": stale and not valid,
        "reasons": reasons,
        "copy_set_id": copy_set.get("copy_set_id"),
        "status": status,
        "pi_eligibility_status": quar,
        "pi_snapshot_id": cs_snap,
        "pi_snapshot_version": cs_ver_i,
        "pi_grounding_digest": cs_digest,
        "current_snapshot_id": current_snapshot_id,
        "current_snapshot_version": current_snapshot_version,
        "current_authority_digest": current_authority_digest,
    }


def classify_product_copy(
    *,
    product_eligible: bool,
    product_eligibility_reasons: list[str] | None,
    set_verdicts: list[dict[str, Any]],
    raw_sets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic product-level classification from per-set verdicts."""
    if not product_eligible:
        return {
            "classification": CLASS_BLOCKED_WITH_REASON,
            "recommended_next_action": ACTION_BLOCK_WITH_REASON,
            "valid_copy_set_id": None,
            "block_reasons": list(product_eligibility_reasons or []),
        }

    valid = [v for v in set_verdicts if v.get("valid")]
    if valid:
        return {
            "classification": CLASS_APPROVED_COPY_VALID,
            "recommended_next_action": ACTION_PRESERVE_VALID_APPROVED
            if True
            else ACTION_READY,
            "valid_copy_set_id": valid[0].get("copy_set_id"),
            "block_reasons": [],
        }

    # Stale approved (approved but failed only on lineage/quarantine revalidation)
    approved_raw = [
        s
        for s in raw_sets
        if _clean(s.get("status")).upper() == STATUS_COPY_APPROVED
        and not bool(s.get("archived"))
    ]
    if approved_raw:
        return {
            "classification": CLASS_APPROVED_COPY_STALE,
            "recommended_next_action": ACTION_REVALIDATE_APPROVED,
            "valid_copy_set_id": None,
            "block_reasons": [],
        }

    if any(
        _clean(s.get("status")).upper() == "COPY_REVIEW_REQUIRED"
        and not bool(s.get("archived"))
        for s in raw_sets
    ):
        return {
            "classification": CLASS_COPY_REVIEW_REQUIRED_ONLY,
            "recommended_next_action": ACTION_REVIEW_EXISTING,
            "valid_copy_set_id": None,
            "block_reasons": [],
        }

    if any(
        _clean(s.get("status")).upper() == "DRAFT_COPY" and not bool(s.get("archived"))
        for s in raw_sets
    ):
        return {
            "classification": CLASS_DRAFT_COPY_ONLY,
            "recommended_next_action": ACTION_REPAIR_EXISTING,
            "valid_copy_set_id": None,
            "block_reasons": [],
        }

    if raw_sets:
        return {
            "classification": CLASS_REJECTED_COPY_ONLY,
            "recommended_next_action": ACTION_GENERATE_MISSING,
            "valid_copy_set_id": None,
            "block_reasons": [],
        }

    return {
        "classification": CLASS_MISSING_COPY,
        "recommended_next_action": ACTION_GENERATE_MISSING,
        "valid_copy_set_id": None,
        "block_reasons": [],
    }


async def _latest_approved_snapshot(product_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT snapshot_id, version, claim_gate, claim_risk_level, "
        "product_description, benefits_json, usp_json, target_customer_text, "
        "allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "approved_at, created_at, status "
        "FROM product_intelligence_snapshot "
        "WHERE product_id = ? AND status = 'APPROVED' "
        "ORDER BY version DESC LIMIT 1",
        (product_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def evaluate_copy_set_id(copy_set_id: str) -> dict[str, Any]:
    """DB-backed validity for one Copy Set."""
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_set WHERE copy_set_id = ?", (copy_set_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return {
            "valid": False,
            "reasons": ["COPY_SET_NOT_FOUND"],
            "copy_set_id": copy_set_id,
        }
    cs = dict(row)
    cs["claim_review"] = _parse_json(cs.get("claim_review_json")) or {}
    cs["provenance"] = _parse_json(cs.get("provenance_json")) or {}
    elig = await copy_eligibility(str(cs["product_id"]))
    snap = await _latest_approved_snapshot(str(cs["product_id"]))
    digest = pi_authority_digest(snap) if snap else None
    return evaluate_copy_set_validity(
        copy_set=cs,
        product_eligible=bool(elig.get("eligible")),
        product_eligibility_reasons=list(elig.get("reasons") or []),
        current_snapshot_id=str(snap["snapshot_id"]) if snap else None,
        current_snapshot_version=int(snap["version"]) if snap else None,
        current_authority_digest=digest,
    )


async def product_copy_classification(product_id: str) -> dict[str, Any]:
    """Full product-level classification + per-set verdicts."""
    elig = await copy_eligibility(product_id)
    snap = await _latest_approved_snapshot(product_id)
    digest = pi_authority_digest(snap) if snap else None
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_set WHERE product_id = ? ORDER BY created_at DESC",
        (product_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    verdicts = []
    for cs in rows:
        cs["claim_review"] = _parse_json(cs.get("claim_review_json")) or {}
        cs["provenance"] = _parse_json(cs.get("provenance_json")) or {}
        v = evaluate_copy_set_validity(
            copy_set=cs,
            product_eligible=bool(elig.get("eligible")),
            product_eligibility_reasons=list(elig.get("reasons") or []),
            current_snapshot_id=str(snap["snapshot_id"]) if snap else None,
            current_snapshot_version=int(snap["version"]) if snap else None,
            current_authority_digest=digest,
        )
        verdicts.append(v)
    classified = classify_product_copy(
        product_eligible=bool(elig.get("eligible")),
        product_eligibility_reasons=list(elig.get("reasons") or []),
        set_verdicts=verdicts,
        raw_sets=rows,
    )
    # READY when valid
    if classified["classification"] == CLASS_APPROVED_COPY_VALID:
        classified["recommended_next_action"] = ACTION_READY
    by_status: dict[str, int] = {}
    by_quar: dict[str, int] = {}
    for cs in rows:
        if bool(cs.get("archived")):
            by_status["ARCHIVED"] = by_status.get("ARCHIVED", 0) + 1
        else:
            st = _clean(cs.get("status")) or "UNKNOWN"
            by_status[st] = by_status.get(st, 0) + 1
        q = _clean(cs.get("pi_eligibility_status")) or "NULL"
        by_quar[q] = by_quar.get(q, 0) + 1
    return {
        "product_id": product_id,
        "copy_eligible": bool(elig.get("eligible")),
        "copy_eligibility_reasons": list(elig.get("reasons") or []),
        "current_pi_snapshot_id": str(snap["snapshot_id"]) if snap else None,
        "current_pi_version": int(snap["version"]) if snap else None,
        "current_pi_authority_digest": digest,
        "current_claim_gate": snap["claim_gate"] if snap else None,
        "total_copy_sets": len(rows),
        "copy_sets_by_status": by_status,
        "copy_sets_by_quarantine": by_quar,
        "set_verdicts": verdicts,
        **classified,
    }


async def assert_copy_set_valid(copy_set_id: str) -> dict[str, Any]:
    """Fail-closed guard for selection/binding/execution."""
    v = await evaluate_copy_set_id(copy_set_id)
    if not v.get("valid"):
        raise ValueError(
            "COPY_SET_INVALID:" + ",".join(v.get("reasons") or ["UNKNOWN"])
        )
    return v


async def stamp_copy_set_pi_lineage(
    copy_set_id: str,
    *,
    product_id: str | None = None,
    revalidated_by: str | None = None,
    clear_quarantine: bool = True,
    decision: str = "GROUNDED",
    rationale: str = "",
) -> dict[str, Any]:
    """Write current PI lineage onto a Copy Set (approval or revalidation)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT product_id, provenance_json FROM copy_set WHERE copy_set_id = ?",
        (copy_set_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    if not row:
        raise ValueError("COPY_SET_NOT_FOUND")
    pid = product_id or str(row["product_id"])
    snap = await _latest_approved_snapshot(pid)
    if not snap:
        raise ValueError("NO_APPROVED_PI_SNAPSHOT")
    digest = pi_authority_digest(snap)
    now = _now()
    prov = _parse_json(row["provenance_json"]) or {}
    if not isinstance(prov, dict):
        prov = {}
    prov["pi_lineage"] = {
        "snapshot_id": snap["snapshot_id"],
        "version": snap["version"],
        "authority_digest": digest,
        "grounded_at": now,
        "grounding_source": "APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT",
        "revalidated_at": now if revalidated_by else prov.get("pi_lineage", {}).get("revalidated_at"),
        "revalidated_by": revalidated_by
        or (prov.get("pi_lineage") or {}).get("revalidated_by"),
        "decision": decision,
        "rationale": rationale or (prov.get("pi_lineage") or {}).get("rationale") or "",
    }
    # Prefer dedicated columns when present.
    cur = await db.execute("PRAGMA table_info(copy_set)")
    cols = {r[1] for r in await cur.fetchall()}
    await cur.close()
    sets = ["provenance_json = ?", "updated_at = ?"]
    params: list[Any] = [json.dumps(prov, ensure_ascii=False), now]
    if "pi_snapshot_id" in cols:
        sets.append("pi_snapshot_id = ?")
        params.append(snap["snapshot_id"])
    if "pi_snapshot_version" in cols:
        sets.append("pi_snapshot_version = ?")
        params.append(int(snap["version"]))
    if "pi_grounding_digest" in cols:
        sets.append("pi_grounding_digest = ?")
        params.append(digest)
    if "grounded_at" in cols:
        sets.append("grounded_at = ?")
        params.append(now)
    if revalidated_by:
        if "revalidated_at" in cols:
            sets.append("revalidated_at = ?")
            params.append(now)
        if "revalidated_by" in cols:
            sets.append("revalidated_by = ?")
            params.append(revalidated_by)
        if "revalidation_decision" in cols:
            sets.append("revalidation_decision = ?")
            params.append(decision)
    if clear_quarantine and "pi_eligibility_status" in cols:
        sets.append("pi_eligibility_status = NULL")
        sets.append("pi_ineligible_reasons = NULL")
    params.append(copy_set_id)
    await db.execute(
        f"UPDATE copy_set SET {', '.join(sets)} WHERE copy_set_id = ?",
        params,
    )
    await db.commit()
    return {
        "copy_set_id": copy_set_id,
        "pi_snapshot_id": snap["snapshot_id"],
        "pi_snapshot_version": int(snap["version"]),
        "pi_grounding_digest": digest,
        "grounded_at": now,
    }


async def mark_stale_copy_sets_for_product(
    product_id: str,
    *,
    current_snapshot_id: str,
    except_copy_set_ids: set[str] | None = None,
) -> int:
    """Fail-closed: approved sets not grounded on current snapshot → NEEDS_REVALIDATION."""
    db = await get_db()
    except_copy_set_ids = except_copy_set_ids or set()
    cur = await db.execute(
        "SELECT copy_set_id, pi_snapshot_id, provenance_json, status, archived, "
        "pi_eligibility_status FROM copy_set WHERE product_id = ?",
        (product_id,),
    )
    rows = await cur.fetchall()
    await cur.close()
    n = 0
    for r in rows:
        if str(r["status"]) != STATUS_COPY_APPROVED:
            continue
        if int(r["archived"] or 0):
            continue
        cid = str(r["copy_set_id"])
        if cid in except_copy_set_ids:
            continue
        snap_id = _clean(r["pi_snapshot_id"]) if "pi_snapshot_id" in r.keys() else ""
        if not snap_id:
            prov = _parse_json(r["provenance_json"]) or {}
            if isinstance(prov, dict):
                snap_id = _clean((prov.get("pi_lineage") or {}).get("snapshot_id"))
        if snap_id == current_snapshot_id:
            continue
        await db.execute(
            "UPDATE copy_set SET pi_eligibility_status = ?, "
            "pi_ineligible_reasons = ?, updated_at = ? WHERE copy_set_id = ?",
            (
                NEEDS_REVALIDATION,
                f"PI_SNAPSHOT_STALE:expected={current_snapshot_id},got={snap_id or 'NONE'}",
                _now(),
                cid,
            ),
        )
        n += 1
    if n:
        await db.commit()
    return n


async def copywriting_validity_coverage(
    *,
    lifecycle_status: str = "ACTIVE",
) -> dict[str, Any]:
    """Cohort rollup for reporting — ACTIVE canonical non-fixture non-alias."""
    from agent.services.reporting_service import (
        _MERGED_ALIAS_PREDICATE,
        _PRODUCT_BASE,
        _TEST_FIXTURE_PREDICATE,
        _product_filters,
        _scalar,
    )

    db = await get_db()
    where, params = _product_filters(lifecycle_status, None, None)
    real = f"{where} AND NOT {_TEST_FIXTURE_PREDICATE} AND NOT {_MERGED_ALIAS_PREDICATE}"
    total = await _scalar(db, f"SELECT COUNT(*) {_PRODUCT_BASE} WHERE 1=1{real}", params)
    cur = await db.execute(
        f"SELECT p.id AS id {_PRODUCT_BASE} WHERE 1=1{real}",
        params,
    )
    ids = [str(r["id"]) for r in await cur.fetchall()]
    await cur.close()

    buckets: dict[str, int] = {
        CLASS_APPROVED_COPY_VALID: 0,
        CLASS_APPROVED_COPY_STALE: 0,
        CLASS_COPY_REVIEW_REQUIRED_ONLY: 0,
        CLASS_DRAFT_COPY_ONLY: 0,
        CLASS_REJECTED_COPY_ONLY: 0,
        CLASS_MISSING_COPY: 0,
        CLASS_BLOCKED_WITH_REASON: 0,
    }
    for pid in ids:
        c = await product_copy_classification(pid)
        buckets[c["classification"]] = buckets.get(c["classification"], 0) + 1

    valid = buckets[CLASS_APPROVED_COPY_VALID]
    return {
        "scope": {"lifecycle_status": lifecycle_status},
        "total_products": total,
        "products_with_valid_approved_copy": valid,
        "products_without_valid_approved_copy": total - valid,
        "classification_counts": buckets,
        "coverage_pct": round(100.0 * valid / total, 1) if total else 0.0,
    }
