"""Bounded strategy-fingerprint reconciliation — SEV-1 remediation mechanism.

WHY THIS EXISTS
`product_strategy_fingerprint` is computed over identity fields (`category`,
`subcategory`, `type`, `product_type`, `product_type_id`, `silo`, names, id). Any bounded
mapping repair that fills those fields therefore changes the fingerprint, and
`_read_model_from_row` then flags `STALE_PRODUCT_FINGERPRINT` -> `REVIEW_REQUIRED` ->
`BLOCKED_REVIEW_REQUIRED`, silently dropping the product out of P4/P6 even though its
strategy binding never changed. Mission-04B hit exactly this.

WHAT IT DOES
For an explicitly supplied cohort it reconciles ONLY rows whose strategy binding is
provably identical to the stored, already-VERIFIED binding, and writes ONLY:
    product_strategy_taxonomy.product_fingerprint
    product_strategy_taxonomy.updated_at

It never re-verifies, never re-classifies, never touches the product table, never touches
the registry, and never alters review/consumer/authority/reviewer provenance. A row whose
binding drifted is REFUSED — that is a human review decision, not a repair.

SAFETY (mirrors the proven bounded-backfill contract)
  * `authorize=False` default; apply also requires the exact plan digest + a durable snapshot;
  * the digest binds product+taxonomy state, the full stored binding, registry state and the
    exact proposed write set, so any drift aborts BEFORE mutation;
  * one transaction under the canonical DB lock; `rowcount == 1` per row;
  * post-write re-read proves fingerprint match, binding untouched and provenance untouched;
  * any rowcount/verification/exception failure rolls back the WHOLE cohort;
  * `rollback_from_snapshot` is compare-and-swap over both written columns.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.services.product_strategy_taxonomy_service import (
    _strategy_binding,
    product_strategy_fingerprint,
)

# The ONLY columns this mechanism may ever write.
WRITABLE_COLUMNS: tuple[str, ...] = ("product_fingerprint", "updated_at")

# The six-field strategy binding that must be identical for a row to be reconcilable.
BINDING_FIELDS: tuple[str, ...] = (
    "cluster", "product_type_group", "matched_scene_strategy_id",
    "scene_coverage_status", "fallback_used", "specific_strategy",
)
# Provenance that must survive untouched.
PROVENANCE_FIELDS: tuple[str, ...] = (
    "materialization_status", "review_status", "consumer_status", "authority_source",
    "reviewer_id", "reviewer_note", "reviewed_at",
)

COHORT_SAFE = "SAFE_FINGERPRINT_ONLY_RECONCILIATION"
COHORT_BINDING_CHANGED = "BINDING_CHANGED_REVIEW_REQUIRED"
COHORT_REGISTRY_INVALID = "REGISTRY_INVALID_OR_INACTIVE"
COHORT_ALREADY_CURRENT = "ALREADY_CURRENT"
COHORT_PREEXISTING_BLOCKED = "PREEXISTING_BLOCKED_OR_UNVERIFIED"
COHORT_MISSING = "MISSING_OR_UNEXPECTED"


def _norm(v) -> str:
    return "" if v is None else str(v)


def _stored_binding(tax: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster": tax.get("cluster"),
        "product_type_group": tax.get("product_type_group"),
        "matched_scene_strategy_id": tax.get("matched_scene_strategy_id"),
        "scene_coverage_status": tax.get("scene_coverage_status"),
        "fallback_used": bool(tax.get("fallback_used")),
        "specific_strategy": bool(tax.get("specific_strategy")),
    }


async def _load(product_id: str) -> tuple[Optional[dict], Optional[dict], Optional[dict]]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE id=?", (product_id,))
    prow = await cur.fetchone()
    await cur.close()
    cur = await db.execute("SELECT * FROM product_strategy_taxonomy WHERE product_id=?", (product_id,))
    trow = await cur.fetchone()
    await cur.close()
    product = dict(prow) if prow else None
    tax = dict(trow) if trow else None
    reg = None
    if tax:
        cur = await db.execute(
            "SELECT * FROM product_strategy_type_registry WHERE cluster=? AND product_type_group=?",
            (tax.get("cluster"), tax.get("product_type_group")))
        rrow = await cur.fetchone()
        await cur.close()
        reg = dict(rrow) if rrow else None
    return product, tax, reg


async def classify_row(product_id: str) -> dict[str, Any]:
    """Read-only classification of one product into an exact cohort. Never writes."""
    product, tax, reg = await _load(product_id)
    if product is None or tax is None:
        return {"product_id": product_id, "cohort": COHORT_MISSING, "eligible": False,
                "reason": "PRODUCT_OR_TAXONOMY_ROW_MISSING"}

    current_fp = product_strategy_fingerprint(product)
    stored_fp = _norm(tax.get("product_fingerprint"))
    fingerprint_stale = stored_fp != current_fp

    current_binding = _strategy_binding(product)
    stored_binding = _stored_binding(tax)
    binding_changed = any(
        _norm(current_binding[f]) != _norm(stored_binding[f]) for f in BINDING_FIELDS)

    registry_ok = bool(
        reg is not None
        and reg.get("registry_status") == "ACTIVE"
        and _norm(reg.get("matched_scene_strategy_id")) == _norm(tax.get("matched_scene_strategy_id"))
        and _norm(reg.get("scene_coverage_status")) == _norm(tax.get("scene_coverage_status")))

    base = {
        "product_id": product_id,
        "stored_fingerprint": stored_fp, "current_fingerprint": current_fp,
        "fingerprint_stale": fingerprint_stale, "binding_changed": binding_changed,
        "stored_binding": stored_binding, "current_binding": current_binding,
        "registry_present": reg is not None,
        "registry_status": (reg or {}).get("registry_status"), "registry_ok": registry_ok,
        "provenance": {f: tax.get(f) for f in PROVENANCE_FIELDS},
        "product_updated_at": product.get("updated_at"),
        "taxonomy_updated_at": tax.get("updated_at"),
    }

    if not fingerprint_stale and not binding_changed:
        return {**base, "cohort": COHORT_ALREADY_CURRENT, "eligible": False,
                "reason": "NO_DRIFT_NOTHING_TO_RECONCILE"}
    if (tax.get("materialization_status") != "MATERIALIZED"
            or tax.get("review_status") != "VERIFIED"
            or tax.get("consumer_status") != "READY"):
        return {**base, "cohort": COHORT_PREEXISTING_BLOCKED, "eligible": False,
                "reason": "NOT_PREVIOUSLY_MATERIALIZED_VERIFIED_READY"}
    if binding_changed:
        return {**base, "cohort": COHORT_BINDING_CHANGED, "eligible": False,
                "reason": "STRATEGY_BINDING_CHANGED_REQUIRES_HUMAN_REVIEW"}
    if not registry_ok:
        return {**base, "cohort": COHORT_REGISTRY_INVALID, "eligible": False,
                "reason": "REGISTRY_PAIR_MISSING_INACTIVE_OR_MISMATCHED"}
    return {**base, "cohort": COHORT_SAFE, "eligible": True,
            "write_fields": {"product_fingerprint": current_fp}}


async def compute_plan_digest(product_ids: list[str]) -> str:
    """Deterministic digest binding every input the safety decision depends on."""
    h = hashlib.sha256()
    for pid in sorted(product_ids):
        product, tax, reg = await _load(pid)
        payload = {
            "product_id": pid,
            "product_updated_at": (product or {}).get("updated_at"),
            "current_fingerprint": product_strategy_fingerprint(product) if product else None,
            "stored_fingerprint": (tax or {}).get("product_fingerprint"),
            "taxonomy_updated_at": (tax or {}).get("updated_at"),
            "stored_binding": _stored_binding(tax) if tax else None,
            "provenance": {f: (tax or {}).get(f) for f in PROVENANCE_FIELDS},
            "registry": None if reg is None else {
                "registry_status": reg.get("registry_status"),
                "matched_scene_strategy_id": reg.get("matched_scene_strategy_id"),
                "scene_coverage_status": reg.get("scene_coverage_status")},
        }
        h.update(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()


async def preview_reconciliation(product_ids: list[str]) -> dict[str, Any]:
    """Read-only plan for a cohort: per-row classification + plan digest. Writes nothing."""
    rows = [await classify_row(pid) for pid in product_ids]
    eligible = [r for r in rows if r.get("eligible")]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cohort"]] = counts.get(r["cohort"], 0) + 1
    return {"cohort_size": len(product_ids), "eligible_count": len(eligible),
            "excluded_count": len(rows) - len(eligible), "cohort_counts": counts,
            "eligible": eligible, "rows": rows,
            "plan_digest": await compute_plan_digest(product_ids)}


async def verify_reconciled_row(product_id: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Re-read a row and prove the reconciliation was correct and provenance intact."""
    product, tax, _ = await _load(product_id)
    if product is None or tax is None:
        return {"product_id": product_id, "ok": False, "reason": "ROW_MISSING_AFTER_WRITE"}
    current_fp = product_strategy_fingerprint(product)
    problems = []
    if _norm(tax.get("product_fingerprint")) != current_fp:
        problems.append("FINGERPRINT_NOT_CURRENT")
    stored_binding = _stored_binding(tax)
    if any(_norm(stored_binding[f]) != _norm(expected["stored_binding"][f]) for f in BINDING_FIELDS):
        problems.append("BINDING_CHANGED")
    if any(_norm(tax.get(f)) != _norm(expected["provenance"][f]) for f in PROVENANCE_FIELDS):
        problems.append("PROVENANCE_CHANGED")
    if _strategy_binding(product) != stored_binding:
        problems.append("READ_MODEL_STILL_BINDING_STALE")
    return {"product_id": product_id, "ok": not problems, "problems": problems,
            "review_status": tax.get("review_status"), "consumer_status": tax.get("consumer_status")}


async def apply_reconciliation(
    product_ids: list[str],
    *,
    authorize: bool = False,
    expected_plan_digest: Optional[str] = None,
    snapshot_path: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically reconcile the SAFE rows of a cohort. Fail-closed. See module docstring."""
    if not authorize:
        preview = await preview_reconciliation(product_ids)
        return {"authorized": False, "wrote": False,
                "message": "NOT_AUTHORIZED — preview only; pass authorize=True + digest + snapshot.",
                **preview}
    if not expected_plan_digest:
        return {"authorized": True, "wrote": False, "aborted": "PLAN_DIGEST_REQUIRED"}
    if not snapshot_path:
        return {"authorized": True, "wrote": False, "aborted": "DURABLE_SNAPSHOT_PATH_REQUIRED"}

    db = await get_db()
    async with _db_lock:
        live_digest = await compute_plan_digest(product_ids)
        if live_digest != expected_plan_digest:
            return {"authorized": True, "wrote": False, "aborted": "PLAN_DIGEST_MISMATCH",
                    "expected_plan_digest": expected_plan_digest, "live_digest": live_digest}

        rows = [await classify_row(pid) for pid in product_ids]
        eligible = [r for r in rows if r.get("eligible")]
        excluded = [r for r in rows if not r.get("eligible")]

        applied_at = crud._now()
        snapshot_rows = [{
            "product_id": r["product_id"],
            "before": {"product_fingerprint": r["stored_fingerprint"],
                       "updated_at": r["taxonomy_updated_at"]},
            "after": {"product_fingerprint": r["current_fingerprint"], "updated_at": applied_at},
        } for r in eligible]
        Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_path).write_text(
            json.dumps({"plan_digest": expected_plan_digest, "applied_updated_at": applied_at,
                        "writable_columns": list(WRITABLE_COLUMNS), "rows": snapshot_rows},
                       indent=2, default=str), encoding="utf-8")

        changed, rowcount_failures, verify_failures = [], [], []
        try:
            for r in eligible:
                pid = r["product_id"]
                cur = await db.execute(
                    "UPDATE product_strategy_taxonomy SET product_fingerprint=?, updated_at=? "
                    "WHERE product_id=? AND product_fingerprint IS ? AND updated_at IS ?",
                    (r["current_fingerprint"], applied_at, pid,
                     r["stored_fingerprint"] or None, r["taxonomy_updated_at"]))
                if cur.rowcount != 1:
                    rowcount_failures.append({"product_id": pid, "rowcount": cur.rowcount})
                    continue
                v = await verify_reconciled_row(pid, r)
                if not v["ok"]:
                    verify_failures.append(v)
                else:
                    changed.append({"product_id": pid,
                                    "fingerprint": r["current_fingerprint"],
                                    "review_status": v["review_status"],
                                    "consumer_status": v["consumer_status"]})
            if rowcount_failures or verify_failures:
                await db.rollback()
                return {"authorized": True, "wrote": False,
                        "aborted": ("ROWCOUNT_MISMATCH" if rowcount_failures
                                    else "POST_WRITE_VERIFICATION_FAILED"),
                        "rowcount_failures": rowcount_failures,
                        "verify_failures": verify_failures,
                        "durable_snapshot": snapshot_path}
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {"authorized": True, "wrote": True, "changed_count": len(changed),
            "excluded_count": len(excluded), "changed": changed, "excluded": excluded,
            "durable_snapshot": snapshot_path, "plan_digest": expected_plan_digest,
            "applied_updated_at": applied_at}


async def rollback_from_snapshot(snapshot_path: str) -> dict[str, Any]:
    """Compare-and-swap rollback of the two reconciled columns only."""
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    db = await get_db()
    restored, skipped = [], []
    async with _db_lock:
        for row in data["rows"]:
            pid, before, after = row["product_id"], row["before"], row["after"]
            cur = await db.execute(
                "UPDATE product_strategy_taxonomy SET product_fingerprint=?, updated_at=? "
                "WHERE product_id=? AND product_fingerprint IS ? AND updated_at IS ?",
                (before["product_fingerprint"] or None, before["updated_at"], pid,
                 after["product_fingerprint"], after["updated_at"]))
            if cur.rowcount == 1:
                restored.append(pid)
            else:
                skipped.append({"product_id": pid, "reason": "CHANGED_SINCE_RECONCILIATION"})
        await db.commit()
        verify_ok = True
        for row in data["rows"]:
            if row["product_id"] in restored:
                _, tax, _ = await _load(row["product_id"])
                if _norm((tax or {}).get("product_fingerprint")) != _norm(row["before"]["product_fingerprint"]):
                    verify_ok = False
    return {"restored_count": len(restored), "skipped_cas": skipped,
            "restored": restored, "verify_ok": verify_ok}
