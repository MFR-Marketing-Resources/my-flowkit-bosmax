"""Bounded, idempotent, transactional NULL-cohort mapping backfill — MECHANISM ONLY.

DESIGN CONTRACT (BOSMAX-MAPPING-TELEMETRY-CLOSURE):
NOT wired to any auto-running endpoint. `apply_bounded_backfill` refuses to write unless
called with `authorize=True` AND a matching `expected_plan_digest` AND a durable
`snapshot_path`, by an explicitly authorized caller after owner sign-off.

TRUTHFULNESS BY CONSTRUCTION (no false readiness):
`enrich_product` is used ONLY to PROPOSE candidate field values (planning). The persisted
`mapping_status` / `prompt_readiness_status` are NEVER copied from enrichment. They are
computed by the PURE evaluators (`evaluate_mapping_status`, `evaluate_prompt_readiness`)
over the PROJECTED stored row — i.e. only values that will actually exist in the row after
the write. After writing, each row is re-read and re-evaluated with the SAME pure
evaluators over stored values only (no enrichment anywhere in verification); any mismatch
rolls back the WHOLE transaction. A status can therefore never outlive the stored fields
that justify it.

SAFETY:
  * targets ONLY active products whose stored `mapping_status IS NULL` (immutable IDs);
  * NEVER touches READY / APPROVED / NEEDS_REVIEW / BLOCKED, archived, or since-changed rows;
  * NEVER overwrites an existing non-empty field (fill-empty-only);
  * refuses if the live cohort digest != the plan digest;
  * writes a durable before/after snapshot (exact applied values incl. `updated_at`) BEFORE
    mutating;
  * atomic: rowcount != 1, invariant mismatch or any exception rolls back the ENTIRE cohort
    (never a partial commit);
  * `rollback_from_snapshot` restores ONLY the columns the backfill actually wrote, and its
    compare-and-swap checks EVERY column it restores (plus `updated_at`), so a legitimate
    later change can never be clobbered.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.services.product_intelligence import enrich_product
from agent.services.product_physics import evaluate_prompt_readiness
from agent.services.product_preflight import evaluate_mapping_status

# Every product column the backfill may FILL (only when the stored value is empty). This
# must cover every field the pure evaluators read, otherwise a status could be persisted
# that the stored row cannot reproduce. A contract test enforces that.
WRITABLE_AUTHORITY_FIELDS: tuple[str, ...] = (
    # mapping / creative authority
    "category", "subcategory", "type", "product_type", "product_type_id", "silo",
    "trigger_id", "formula", "copywriting_angle", "claim_risk_level", "mapping_source",
    "scene_context", "camera_style", "camera_behavior", "camera_shot",
    # physics authority (evaluate_prompt_readiness reads physics_class +
    # section_5_product_physics_prompt from these stored columns)
    "physics_class", "product_scale", "hand_object_interaction", "recommended_grip",
    "handling_notes", "camera_handling_notes", "air_gap_rule", "material_behavior",
    "surface_behavior", "fragility_level", "section_5_product_physics_prompt",
    "section_5_physics_hint",
    # prompt-section hints
    "section_4_hint", "section_6_copy_hint", "section_9_overlay_hint",
)
# Derived status columns — computed from the projected stored row, never copied from enrich.
STATUS_WRITE_FIELDS: tuple[str, ...] = (
    "mapping_status", "mapping_missing_fields",
    "prompt_readiness_status", "prompt_missing_fields",
)
PROTECTED_STATUSES = frozenset({"READY", "APPROVED", "NEEDS_REVIEW", "BLOCKED"})
_REPRODUCIBLE_STATUS = ("mapping_status", "prompt_readiness_status")


def _norm(v) -> str:
    return "" if v is None else str(v)


def _dbval(v):
    """JSON-encode list/dict values for TEXT columns; pass scalars through."""
    return json.dumps(v) if isinstance(v, (list, dict)) else v


def evaluate_stored_row(row: dict[str, Any]) -> dict[str, Any]:
    """Compute mapping + prompt readiness DIRECTLY from a row's own values.

    PURE: no enrichment, no derivation, no I/O — it reads only what is (or will be) in the
    row. `evaluate_prompt_readiness` takes the same row as its `physics` argument because
    `physics_class` and `section_5_product_physics_prompt` are real stored columns.
    Replicates the documented status coupling applied at write time.
    """
    mapping = evaluate_mapping_status(row)
    readiness = evaluate_prompt_readiness(row, row)
    mapping_status = mapping["mapping_status"]
    prompt_status = readiness["prompt_readiness_status"]
    if mapping_status == "BLOCKED":
        prompt_status = "MISSING_FIELDS"
    elif mapping_status == "NEEDS_REVIEW" and prompt_status == "READY":
        prompt_status = "NEEDS_REVIEW"
    return {
        "mapping_status": mapping_status,
        "mapping_missing_fields": mapping["mapping_missing_fields"],
        "prompt_readiness_status": prompt_status,
        "prompt_missing_fields": readiness["prompt_missing_fields"],
    }


async def classify_row(product: Optional[dict]) -> dict:
    """Read-only eligibility decision + exact write-set for one product. Never writes."""
    if not product:
        return {"eligible": False, "reason": "NOT_FOUND"}
    pid = product.get("id")
    if product.get("lifecycle_status") != "ACTIVE":
        return {"product_id": pid, "eligible": False, "reason": "NOT_ACTIVE"}
    if product.get("mapping_status") is not None:
        return {"product_id": pid, "eligible": False,
                "reason": f"MAPPING_NOT_NULL:{product.get('mapping_status')}"}

    # enrichment PROPOSES candidate values only — it never decides the persisted status
    proposed = await enrich_product(product, persist=False)
    overwrite = [
        f for f in WRITABLE_AUTHORITY_FIELDS
        if _norm(product.get(f)) != "" and _norm(product.get(f)) != _norm(proposed.get(f))
    ]
    if overwrite:
        return {"product_id": pid, "eligible": False,
                "reason": "WOULD_OVERWRITE_EXISTING", "fields": overwrite}

    fills = {f: proposed.get(f) for f in WRITABLE_AUTHORITY_FIELDS
             if _norm(product.get(f)) == "" and _norm(proposed.get(f)) != ""}
    # the row exactly as it will exist after the write
    projected = {**product, **fills}
    status = evaluate_stored_row(projected)
    if status["mapping_status"] == "APPROVED":  # evaluators never emit it; belt-and-braces
        return {"product_id": pid, "eligible": False, "reason": "REFUSE_SYNTHETIC_APPROVED"}

    write = {f: _dbval(v) for f, v in fills.items()}
    for f in STATUS_WRITE_FIELDS:
        write[f] = _dbval(status[f])
    return {"product_id": pid, "eligible": True,
            "proposed_status": status["mapping_status"],
            "proposed_prompt_readiness": status["prompt_readiness_status"],
            "write_fields": write}


async def compute_cohort_digest(cohort_ids: list[str]) -> str:
    """Deterministic digest of the cohort's current (id, mapping_status, updated_at)."""
    h = hashlib.sha256()
    for pid in sorted(cohort_ids):
        p = await crud.get_product(pid)
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


async def verify_stored_row(product_id: str) -> dict:
    """Re-read a row and prove its persisted statuses are reproducible from stored values
    alone (pure evaluators, no enrichment)."""
    stored = await crud.get_product(product_id)
    recomputed = evaluate_stored_row(stored or {})
    mismatch = {f: {"stored": (stored or {}).get(f), "recomputed_from_stored": recomputed[f]}
                for f in _REPRODUCIBLE_STATUS
                if _norm((stored or {}).get(f)) != _norm(recomputed[f])}
    return {"product_id": product_id, "ok": not mismatch, "mismatch": mismatch,
            "stored_status": {f: (stored or {}).get(f) for f in _REPRODUCIBLE_STATUS}}


async def apply_bounded_backfill(
    cohort_ids: list[str],
    *,
    authorize: bool = False,
    expected_plan_digest: Optional[str] = None,
    snapshot_path: Optional[str] = None,
) -> dict:
    """Apply the bounded fill. Fail-closed and atomic. See module docstring."""
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

        eligible, skipped = [], []
        for pid in cohort_ids:
            c = await classify_row(await crud.get_product(pid))
            if c.get("eligible"):
                eligible.append((pid, c))
            else:
                skipped.append(c)

        applied_at = crud._now()
        snapshot_rows = []
        for pid, c in eligible:
            product = await crud.get_product(pid) or {}
            cols = list(c["write_fields"].keys())
            snapshot_rows.append({
                "product_id": pid,
                # ONLY the columns this backfill modifies (+ updated_at) — rollback must
                # never touch a column it did not write.
                "before": {**{k: product.get(k) for k in cols},
                           "updated_at": product.get("updated_at")},
                "after": {**dict(c["write_fields"]), "updated_at": applied_at},
            })
        Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_path).write_text(
            json.dumps({"plan_digest": expected_plan_digest, "applied_updated_at": applied_at,
                        "rows": snapshot_rows}, indent=2), encoding="utf-8")

        changed, invariant_failures, rowcount_failures = [], [], []
        try:
            for pid, c in eligible:
                cur = await db.execute(
                    "UPDATE product SET " + ", ".join(f"{k}=?" for k in c["write_fields"])
                    + ", updated_at=? WHERE id=? AND lifecycle_status='ACTIVE' AND mapping_status IS NULL",
                    [*c["write_fields"].values(), applied_at, pid])
                if cur.rowcount != 1:
                    rowcount_failures.append({"product_id": pid, "rowcount": cur.rowcount})
                    continue
                v = await verify_stored_row(pid)  # pure stored-row check on this connection
                if not v["ok"]:
                    invariant_failures.append(v)
                else:
                    changed.append({"product_id": pid,
                                    "wrote_fields": list(c["write_fields"].keys()),
                                    "stored_status": v["stored_status"]})
            if rowcount_failures or invariant_failures:
                await db.rollback()  # ATOMIC: no partial commit of the cohort
                return {"authorized": True, "wrote": False,
                        "aborted": ("ROWCOUNT_MISMATCH" if rowcount_failures
                                    else "READINESS_INVARIANT_VIOLATION"),
                        "rowcount_failures": rowcount_failures,
                        "invariant_failures": invariant_failures,
                        "durable_snapshot": snapshot_path}
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {"authorized": True, "wrote": True, "changed_count": len(changed),
            "skipped_count": len(skipped), "changed": changed, "skipped": skipped,
            "durable_snapshot": snapshot_path, "plan_digest": expected_plan_digest,
            "applied_updated_at": applied_at}


async def rollback_from_snapshot(snapshot_path: str) -> dict:
    """Compare-and-swap rollback from a durable snapshot.

    Restores ONLY the columns the backfill actually wrote, and the CAS predicate compares
    EVERY one of those columns plus `updated_at` against the exact applied after-state. Any
    later legitimate change to any of them (or to updated_at) makes the row skip — the
    change is preserved and the row is NOT reported restored.
    """
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    db = await get_db()
    restored, skipped_cas = [], []
    async with _db_lock:
        for row in data["rows"]:
            pid, before, after = row["product_id"], row["before"], row["after"]
            cols = list(before.keys())      # exactly what we wrote (+ updated_at)
            cas_cols = list(after.keys())   # CAS covers every value being restored
            cur = await db.execute(
                "UPDATE product SET " + ", ".join(f"{k}=?" for k in cols)
                + " WHERE id=? AND " + " AND ".join(f"{k} IS ?" for k in cas_cols),
                [*(before[k] for k in cols), pid, *(after[k] for k in cas_cols)])
            if cur.rowcount == 1:
                restored.append(pid)
            else:
                skipped_cas.append({"product_id": pid, "reason": "CHANGED_SINCE_BACKFILL"})
        await db.commit()
        verify_ok = True
        for row in data["rows"]:
            pid = row["product_id"]
            if pid in restored:
                cur_row = await crud.get_product(pid) or {}
                for k, v in row["before"].items():
                    if _norm(cur_row.get(k)) != _norm(v):
                        verify_ok = False
    return {"restored_count": len(restored), "skipped_cas": skipped_cas,
            "restored": restored, "verify_ok": verify_ok}
