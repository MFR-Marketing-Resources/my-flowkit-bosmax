"""Bounded, idempotent NULL-cohort mapping backfill — MECHANISM ONLY.

DESIGN CONTRACT (BOSMAX-MAPPING-TELEMETRY-CLOSURE-01):
This module is NOT wired to any auto-running endpoint. `apply_bounded_backfill` refuses to
write unless called with `authorize=True` by an explicitly authorized caller AFTER owner
sign-off on the dry-run artifact. It exists so a later, approved step can remediate the
`mapping_status IS NULL` cohort SAFELY. It will:

  * target ONLY active products whose stored `mapping_status IS NULL` (immutable IDs);
  * NEVER touch a READY / APPROVED / NEEDS_REVIEW / BLOCKED, archived, or since-changed row;
  * NEVER overwrite an existing non-empty authority field (fill-empty-only);
  * write only the deterministic enrichment (`enrich_product`, zero AI/credits);
  * capture a complete before-snapshot and support deterministic rollback;
  * be idempotent (a now-mapped row is no longer NULL → skipped on re-run);
  * report exact changed and skipped rows with reasons.

The evaluator only emits READY / NEEDS_REVIEW / BLOCKED — never APPROVED (a human state);
this module refuses to persist an APPROVED it did not read as pre-existing.
"""
from __future__ import annotations

import json
from typing import Optional

from agent.db import crud
from agent.db.schema import get_db, _db_lock
from agent.services.product_intelligence import enrich_product

# Authority fields the mapping pipeline fills. A fill is safe only when the stored value
# is empty; a change to a non-empty stored value is an overwrite and disqualifies the row.
AUTHORITY_FIELDS = (
    "category", "subcategory", "type", "product_type", "product_type_id", "silo",
    "trigger_id", "formula", "claim_risk_level", "physics_class", "recommended_grip",
    "scene_context", "camera_style", "camera_behavior", "camera_shot",
)
# Derived status fields — computed, not authored; safe to (re)write on an eligible row.
STATUS_WRITE_FIELDS = (
    "mapping_status", "mapping_missing_fields", "mapping_confidence", "mapping_source",
    "prompt_readiness_status", "prompt_missing_fields",
)
PROTECTED_STATUSES = frozenset({"READY", "APPROVED", "NEEDS_REVIEW", "BLOCKED"})


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
        # evaluator must never manufacture APPROVED; refuse to persist it
        return {"product_id": pid, "eligible": False, "reason": "REFUSE_SYNTHETIC_APPROVED"}

    write = {}
    for f in AUTHORITY_FIELDS:
        if _norm(product.get(f)) == "" and _norm(enriched.get(f)) != "":
            write[f] = _dbval(enriched.get(f))
    for f in STATUS_WRITE_FIELDS:
        write[f] = _dbval(enriched.get(f))
    return {"product_id": pid, "eligible": True,
            "proposed_status": enriched.get("mapping_status"), "write_fields": write}


async def preview_bounded_backfill(cohort_ids: list[str]) -> dict:
    """Read-only plan: classify every id. Writes nothing."""
    eligible, skipped = [], []
    for pid in cohort_ids:
        c = await classify_row(await crud.get_product(pid))
        (eligible if c.get("eligible") else skipped).append(c)
    return {"cohort_size": len(cohort_ids), "eligible": eligible, "skipped": skipped,
            "eligible_count": len(eligible), "skipped_count": len(skipped)}


async def apply_bounded_backfill(cohort_ids: list[str], *, authorize: bool = False) -> dict:
    """Apply the bounded fill. REFUSES to write unless authorize=True.

    Even when authorized, re-validates each row at write time (guarding against state that
    changed since the dry-run) and only fills empty authority fields + derived status.
    Returns a before-snapshot enabling deterministic rollback via rollback_snapshot().
    """
    if not authorize:
        preview = await preview_bounded_backfill(cohort_ids)
        return {"authorized": False, "wrote": False,
                "message": "NOT_AUTHORIZED — dry-run only; call with authorize=True after owner sign-off.",
                **preview}

    db = await get_db()
    snapshot, changed, skipped = [], [], []
    async with _db_lock:
        for pid in cohort_ids:
            product = await crud.get_product(pid)
            c = await classify_row(product)  # re-validate at write time
            if not c.get("eligible"):
                skipped.append(c)
                continue
            snapshot.append({k: product.get(k) for k in
                             ("id", *AUTHORITY_FIELDS, *STATUS_WRITE_FIELDS)})
            await db.execute(
                "UPDATE product SET "
                + ", ".join(f"{k}=?" for k in c["write_fields"])
                + ", updated_at=? WHERE id=? AND lifecycle_status='ACTIVE' AND mapping_status IS NULL",
                [*c["write_fields"].values(), crud._now(), pid],
            )
            changed.append({"product_id": pid, "proposed_status": c["proposed_status"],
                            "wrote_fields": list(c["write_fields"].keys())})
        await db.commit()
    return {"authorized": True, "wrote": True, "changed_count": len(changed),
            "skipped_count": len(skipped), "changed": changed, "skipped": skipped,
            "before_snapshot": snapshot}


async def rollback_snapshot(before_snapshot: list[dict]) -> int:
    """Deterministically restore rows from a before_snapshot returned by an apply run."""
    db = await get_db()
    n = 0
    async with _db_lock:
        for row in before_snapshot:
            cols = [k for k in row if k != "id"]
            await db.execute(
                "UPDATE product SET " + ", ".join(f"{k}=?" for k in cols) + " WHERE id=?",
                [*(row[k] for k in cols), row["id"]],
            )
            n += 1
        await db.commit()
    return n
