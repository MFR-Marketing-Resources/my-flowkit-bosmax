"""Bounded, idempotent, transactional NULL-cohort mapping backfill — MECHANISM ONLY.

DESIGN CONTRACT (BOSMAX-MAPPING-TELEMETRY-CLOSURE):
NOT wired to any auto-running endpoint. `apply_bounded_backfill` refuses to write unless
called with `authorize=True` AND a matching `expected_plan_digest` AND a durable
`snapshot_path`, by an explicitly authorized caller after owner sign-off. Even then it:

  * targets ONLY active products whose stored `mapping_status IS NULL` (immutable IDs);
  * NEVER touches READY / APPROVED / NEEDS_REVIEW / BLOCKED, archived, since-changed rows;
  * NEVER overwrites an existing non-empty authority field (fill-empty-only);
  * refuses if the live cohort digest != the plan digest (state changed since planning);
  * writes a COMPLETE durable before-snapshot (every changeable column + updated_at + the
    exact values written) to disk BEFORE any mutation;
  * runs atomically, checks `rowcount == 1` per write (never reports a phantom change);
  * RE-READS each written row and recomputes readiness from stored state — if the persisted
    `mapping_status`/`prompt_readiness_status` is NOT reproducible from stored state, it
    ROLLS BACK and fails closed (no false readiness can be persisted). This holds regardless
    of `enrich_product` idempotency;
  * supports compare-and-swap `rollback_from_snapshot` that never clobbers a legitimate
    change made after the backfill.

The evaluator only emits READY / NEEDS_REVIEW / BLOCKED — never APPROVED (a human state);
this module refuses to persist an APPROVED it did not read as pre-existing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.services.product_intelligence import enrich_product

AUTHORITY_FIELDS = (
    "category", "subcategory", "type", "product_type", "product_type_id", "silo",
    "trigger_id", "formula", "claim_risk_level", "physics_class", "recommended_grip",
    "scene_context", "camera_style", "camera_behavior", "camera_shot",
)
STATUS_WRITE_FIELDS = (
    "mapping_status", "mapping_missing_fields", "mapping_confidence", "mapping_source",
    "prompt_readiness_status", "prompt_missing_fields",
)
# Every column captured in the durable before-snapshot (incl. updated_at) so rollback can
# restore the exact prior row.
SNAPSHOT_FIELDS = ("id", *AUTHORITY_FIELDS, *STATUS_WRITE_FIELDS, "updated_at")
PROTECTED_STATUSES = frozenset({"READY", "APPROVED", "NEEDS_REVIEW", "BLOCKED"})
# Cached statuses that MUST be reproducible from stored state (cache-consistency invariant).
_REPRODUCIBLE_STATUS = ("mapping_status", "prompt_readiness_status")


def _norm(v) -> str:
    return "" if v is None else str(v)


def _dbval(v):
    """JSON-encode list/dict values for TEXT columns; pass scalars through."""
    return json.dumps(v) if isinstance(v, (list, dict)) else v


async def classify_row(product: Optional[dict]) -> dict:
    """Read-only eligibility decision for one product. Never writes."""
    if not product:
        return {"eligible": False, "reason": "NOT_FOUND"}
    pid = product.get("id")
    if product.get("lifecycle_status") != "ACTIVE":
        return {"product_id": pid, "eligible": False, "reason": "NOT_ACTIVE"}
    if product.get("mapping_status") is not None:
        return {"product_id": pid, "eligible": False,
                "reason": f"MAPPING_NOT_NULL:{product.get('mapping_status')}"}

    enriched = await enrich_product(product, persist=False)
    overwrite = [
        f for f in AUTHORITY_FIELDS
        if _norm(product.get(f)) != "" and _norm(product.get(f)) != _norm(enriched.get(f))
    ]
    if overwrite:
        return {"product_id": pid, "eligible": False,
                "reason": "WOULD_OVERWRITE_EXISTING", "fields": overwrite}
    if enriched.get("mapping_status") == "APPROVED":
        return {"product_id": pid, "eligible": False, "reason": "REFUSE_SYNTHETIC_APPROVED"}

    write = {}
    for f in AUTHORITY_FIELDS:
        if _norm(product.get(f)) == "" and _norm(enriched.get(f)) != "":
            write[f] = _dbval(enriched.get(f))
    for f in STATUS_WRITE_FIELDS:
        write[f] = _dbval(enriched.get(f))
    return {"product_id": pid, "eligible": True,
            "proposed_status": enriched.get("mapping_status"), "write_fields": write}


async def compute_cohort_digest(cohort_ids: list[str]) -> str:
    """Deterministic digest of the cohort's current (id, mapping_status, updated_at). An
    authorized run must match the digest captured at plan time, else the cohort changed and
    we fail closed."""
    db_products = [await crud.get_product(pid) for pid in sorted(cohort_ids)]
    h = hashlib.sha256()
    for pid, p in zip(sorted(cohort_ids), db_products):
        h.update(repr((pid,
                       None if not p else p.get("mapping_status"),
                       None if not p else p.get("updated_at"))).encode("utf-8"))
    return h.hexdigest()


async def preview_bounded_backfill(cohort_ids: list[str]) -> dict:
    """Read-only plan: classify every id + a plan digest. Writes nothing."""
    eligible, skipped = [], []
    for pid in cohort_ids:
        c = await classify_row(await crud.get_product(pid))
        (eligible if c.get("eligible") else skipped).append(c)
    return {"cohort_size": len(cohort_ids), "eligible": eligible, "skipped": skipped,
            "eligible_count": len(eligible), "skipped_count": len(skipped),
            "plan_digest": await compute_cohort_digest(cohort_ids)}


async def _reproducible(product_after: dict) -> tuple[bool, dict]:
    """The persisted reproducible statuses must equal a fresh enrich of the stored row."""
    recomputed = await enrich_product(product_after, persist=False)
    mismatch = {
        f: {"stored": product_after.get(f), "recomputed": recomputed.get(f)}
        for f in _REPRODUCIBLE_STATUS
        if _norm(product_after.get(f)) != _norm(recomputed.get(f))
    }
    return (not mismatch), mismatch


async def apply_bounded_backfill(
    cohort_ids: list[str],
    *,
    authorize: bool = False,
    expected_plan_digest: Optional[str] = None,
    snapshot_path: Optional[str] = None,
) -> dict:
    """Apply the bounded fill. Fail-closed on any safety gate. See module docstring."""
    if not authorize:
        preview = await preview_bounded_backfill(cohort_ids)
        return {"authorized": False, "wrote": False,
                "message": "NOT_AUTHORIZED — dry-run only; call with authorize=True + digest + snapshot after owner sign-off.",
                **preview}
    if not expected_plan_digest:
        return {"authorized": True, "wrote": False, "aborted": "PLAN_DIGEST_REQUIRED"}
    if not snapshot_path:
        return {"authorized": True, "wrote": False, "aborted": "DURABLE_SNAPSHOT_PATH_REQUIRED"}

    db = await get_db()
    async with _db_lock:
        live_digest = await compute_cohort_digest(cohort_ids)
        if live_digest != expected_plan_digest:
            return {"authorized": True, "wrote": False, "aborted": "COHORT_DIGEST_MISMATCH",
                    "expected_plan_digest": expected_plan_digest, "live_digest": live_digest}

        eligible, skipped, snapshot_rows = [], [], []
        for pid in cohort_ids:
            product = await crud.get_product(pid)
            c = await classify_row(product)
            if not c.get("eligible"):
                skipped.append(c)
                continue
            eligible.append((pid, c))
            snapshot_rows.append({"before": {k: product.get(k) for k in SNAPSHOT_FIELDS},
                                  "wrote": {k: c["write_fields"][k] for k in c["write_fields"]}})

        # durable before-snapshot on disk BEFORE any mutation
        Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_path).write_text(
            json.dumps({"plan_digest": expected_plan_digest, "rows": snapshot_rows}, indent=2),
            encoding="utf-8")

        changed, invariant_failures = [], []
        try:
            for pid, c in eligible:
                cur = await db.execute(
                    "UPDATE product SET " + ", ".join(f"{k}=?" for k in c["write_fields"])
                    + ", updated_at=? WHERE id=? AND lifecycle_status='ACTIVE' AND mapping_status IS NULL",
                    [*c["write_fields"].values(), crud._now(), pid])
                if cur.rowcount != 1:
                    skipped.append({"product_id": pid, "eligible": False,
                                    "reason": f"ROWCOUNT_{cur.rowcount}_NOT_1"})
                    continue
                after = await crud.get_product(pid)  # sees the uncommitted write on this conn
                ok, mismatch = await _reproducible(after)
                if not ok:
                    invariant_failures.append({"product_id": pid, "mismatch": mismatch})
                else:
                    changed.append({"product_id": pid,
                                    "wrote_fields": list(c["write_fields"].keys()),
                                    "reproducible_status": {f: after.get(f) for f in _REPRODUCIBLE_STATUS}})
            if invariant_failures:
                await db.rollback()
                return {"authorized": True, "wrote": False,
                        "aborted": "READINESS_INVARIANT_VIOLATION",
                        "invariant_failures": invariant_failures,
                        "durable_snapshot": snapshot_path}
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {"authorized": True, "wrote": True, "changed_count": len(changed),
            "skipped_count": len(skipped), "changed": changed, "skipped": skipped,
            "durable_snapshot": snapshot_path, "plan_digest": expected_plan_digest}


async def rollback_from_snapshot(snapshot_path: str) -> dict:
    """Compare-and-swap rollback from a durable snapshot. Restores each row's before-values
    ONLY if it still holds exactly what the backfill wrote — so it never clobbers a
    legitimate change made after the backfill. Re-reads to verify."""
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    db = await get_db()
    restored, skipped_cas = [], []
    async with _db_lock:
        for row in data["rows"]:
            before, wrote = row["before"], row["wrote"]
            pid = before["id"]
            cols = [k for k in before if k != "id"]
            # CAS: only restore if every written field still equals what we wrote.
            cas = " AND ".join(f"{k}=?" for k in wrote)
            cur = await db.execute(
                "UPDATE product SET " + ", ".join(f"{k}=?" for k in cols)
                + f" WHERE id=? AND {cas}",
                [*(before[k] for k in cols), pid, *(wrote[k] for k in wrote)])
            if cur.rowcount == 1:
                restored.append(pid)
            else:
                skipped_cas.append({"product_id": pid, "reason": "CHANGED_SINCE_BACKFILL"})
        await db.commit()
        # verify restoration
        verify_ok = True
        for row in data["rows"]:
            if row["before"]["id"] in restored:
                cur_row = await crud.get_product(row["before"]["id"])
                if _norm(cur_row.get("mapping_status")) != _norm(row["before"].get("mapping_status")):
                    verify_ok = False
    return {"restored_count": len(restored), "skipped_cas": skipped_cas,
            "restored": restored, "verify_ok": verify_ok}
