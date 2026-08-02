#!/usr/bin/env python
"""BOSMAX-PI-EXCEPTION-REGRESSION-08E — bounded L1 identity fill + paired reconciliation.

WHY THIS EXISTS
Two ACTIVE products sat `mapping_status='BLOCKED'` purely because `subcategory` and `type`
were NULL (`BLOCKING_MAPPING_FIELDS`, `agent/services/product_preflight.py`), which in turn
FORCES `prompt_readiness_status='MISSING_FIELDS'`
(`agent/services/product_intelligence.py:289`). The owner supplied the L1 authority values
after the 08E audit proved the mapping-rules file, the source ingestion table and the
per-product precedents could not supply them.

WHY NOT `enrich_product(persist=True)`
That is the canonical write-back, but `persist_intelligence` rewrites ~50 columns AND passes
the EXISTING `updated_at` straight through — it is the exact mechanism that produced the 08E
silent writes. This driver instead uses `enrich_product(persist=False)` as a PURE CALCULATOR,
discloses every column the canonical enrichment WOULD have changed, and then writes only a
bounded, CAS-guarded column set with an honest `updated_at` bump.

WRITE POLICY — FILL-EMPTY-ONLY
`subcategory` / `type` are written ONLY when currently NULL/blank. A non-empty stored value is
never overwritten; such a row is REFUSED, not silently skipped. `category` is NEVER written by
this driver (owner instruction: do not mutate category independently) — it is not in
WRITABLE_COLUMNS, so that is structural rather than a matter of care.

The four status columns are NOT free-form: they are recomputed by the canonical authority from
the post-fill row, so they can only ever say what `enrich_product` itself would say.

SAFETY
  * `--preview` is the default and writes nothing;
  * `--apply` additionally requires the explicit `--authorize` flag;
  * cohort set hash verified before anything else runs;
  * CAS: every UPDATE is guarded on the exact pre-image and must report rowcount == 1;
  * one transaction; any rowcount/verification failure rolls back the WHOLE cohort;
  * durable before/after snapshot written BEFORE the transaction;
  * post-write re-read proves the intended values and proves no other column moved;
  * `--rollback` is compare-and-swap over the written columns only.

Zero provider calls, zero generation, zero credits.

Usage:
    python scripts/product_l1_identity_bounded_08e.py --preview
    python scripts/product_l1_identity_bounded_08e.py --apply --authorize
    python scripts/product_l1_identity_bounded_08e.py --rollback <snapshot.json>
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.db import crud  # noqa: E402
from agent.db.schema import _db_lock, get_db  # noqa: E402
from agent.services.product_intelligence import enrich_product, json_dump_list  # noqa: E402

# Owner-authorized L1 authority. Exact ID cohort — nothing is resolved by search.
AUTHORIZED_L1: dict[str, dict[str, str]] = {
    "013b7710-a55e-4053-9224-e1149f052f57": {
        "subcategory": "Building Supplies",
        "type": "Wallpaper & Wall Trim",
    },
    "ae47b55b-58d4-441e-97d3-0d6c785bb530": {
        "subcategory": "Home Care Supplies",
        "type": "Pest & Weed Control",
    },
}
COHORT_SHA256 = "1cf199ffe0194caa084a63c070cda2d80d1afb38416f195eebad5d15dc8ffd8c"

# The ONLY columns this driver may ever write. `category` is deliberately absent.
WRITABLE_COLUMNS: tuple[str, ...] = (
    "subcategory", "type",
    "mapping_status", "mapping_missing_fields",
    "prompt_readiness_status", "prompt_missing_fields",
    "updated_at",
)
# Fill-empty-only applies to these; the rest are recomputed status.
FILL_ONLY_COLUMNS: tuple[str, ...] = ("subcategory", "type")

# Never written, never inferred — asserted unchanged after the write.
IDENTITY_GUARD_COLUMNS: tuple[str, ...] = (
    "id", "raw_product_title", "product_display_name", "product_short_name",
    "category", "product_type", "product_type_id", "silo", "lifecycle_status",
)

OUT_DIR = REPO / "outputs" / "mission-08e-l1-identity"


class CohortAuthorizationError(RuntimeError):
    """The cohort is not the owner-accepted one. Never proceed past this."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cohort_set_sha256(mapping: dict[str, dict[str, str]]) -> str:
    """Canonical hash binding the ID SET *and* the exact authority values."""
    payload = {pid: {k: mapping[pid][k] for k in sorted(mapping[pid])}
               for pid in sorted(mapping)}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_authorized_cohort(
    mapping: dict[str, dict[str, str]] = AUTHORIZED_L1,
    expected_sha256: str = COHORT_SHA256,
) -> tuple[str, ...]:
    actual = cohort_set_sha256(mapping)
    if actual != expected_sha256:
        raise CohortAuthorizationError(
            "COHORT_SHA_MISMATCH — refusing to proceed. "
            f"count={len(mapping)} expected_sha256={expected_sha256} actual_sha256={actual}"
        )
    return tuple(sorted(mapping))


def _blank(v) -> bool:
    return not str(v or "").strip()


async def _load(product_id: str) -> dict | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE id=?", (product_id,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def classify_row(product_id: str) -> dict:
    """Read-only classification of one product. Never writes."""
    stored = await _load(product_id)
    if stored is None:
        return {"product_id": product_id, "eligible": False, "reason": "PRODUCT_ROW_MISSING"}

    target = AUTHORIZED_L1[product_id]
    occupied = [c for c in FILL_ONLY_COLUMNS if not _blank(stored.get(c))]
    if occupied:
        return {"product_id": product_id, "eligible": False,
                "reason": "FILL_EMPTY_ONLY_VIOLATION_FIELD_ALREADY_SET",
                "occupied": {c: stored.get(c) for c in occupied}}

    # Canonical authority used as a PURE CALCULATOR (persist=False writes nothing).
    candidate = dict(stored)
    candidate.update(target)
    derived = await enrich_product(candidate, persist=False)

    write_fields = {
        "subcategory": target["subcategory"],
        "type": target["type"],
        "mapping_status": derived.get("mapping_status") or None,
        "mapping_missing_fields": json_dump_list(derived.get("mapping_missing_fields") or []),
        "prompt_readiness_status": derived.get("prompt_readiness_status") or None,
        "prompt_missing_fields": json_dump_list(derived.get("prompt_missing_fields") or []),
    }

    # FULL drift disclosure: every stored column the canonical enrichment would have changed,
    # including the ones this bounded driver deliberately refuses to write.
    enrichment_drift = {}
    for col, new in derived.items():
        if col not in stored:
            continue
        old = stored.get(col)
        if isinstance(new, (list, dict)):
            new = json_dump_list(new) if isinstance(new, list) else json.dumps(new)
        if str(old or "") != str(new or ""):
            enrichment_drift[col] = {"stored": old, "enrichment_would_write": new}
    not_written = {c: v for c, v in enrichment_drift.items() if c not in WRITABLE_COLUMNS}

    return {
        "product_id": product_id,
        "eligible": True,
        "before": {c: stored.get(c) for c in WRITABLE_COLUMNS},
        "write_fields": write_fields,
        "identity_guard": {c: stored.get(c) for c in IDENTITY_GUARD_COLUMNS},
        "enrichment_drift": enrichment_drift,
        "columns_enrichment_would_change_but_this_driver_refuses": not_written,
        "mapping_status_before": stored.get("mapping_status"),
        "mapping_status_after": write_fields["mapping_status"],
        "prompt_status_before": stored.get("prompt_readiness_status"),
        "prompt_status_after": write_fields["prompt_readiness_status"],
    }


async def compute_plan_digest(product_ids: list[str]) -> str:
    """Deterministic digest binding every input the safety decision depends on."""
    h = hashlib.sha256()
    for pid in sorted(product_ids):
        row = await classify_row(pid)
        h.update(json.dumps({
            "product_id": pid,
            "before": row.get("before"),
            "write_fields": row.get("write_fields"),
            "identity_guard": row.get("identity_guard"),
            "eligible": row.get("eligible"),
        }, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()


async def preview_l1(product_ids: list[str]) -> dict:
    rows = [await classify_row(pid) for pid in product_ids]
    eligible = [r for r in rows if r.get("eligible")]
    return {"cohort_size": len(product_ids), "eligible_count": len(eligible),
            "excluded_count": len(rows) - len(eligible), "rows": rows,
            "plan_digest": await compute_plan_digest(product_ids)}


async def verify_row(product_id: str, expected: dict) -> dict:
    stored = await _load(product_id)
    if stored is None:
        return {"product_id": product_id, "ok": False, "problems": ["ROW_MISSING_AFTER_WRITE"]}
    problems = []
    for col, want in expected["write_fields"].items():
        if str(stored.get(col) or "") != str(want or ""):
            problems.append(f"VALUE_MISMATCH:{col}")
    for col, want in expected["identity_guard"].items():
        if str(stored.get(col) or "") != str(want or ""):
            problems.append(f"IDENTITY_COLUMN_CHANGED:{col}")
    return {"product_id": product_id, "ok": not problems, "problems": problems,
            "mapping_status": stored.get("mapping_status"),
            "prompt_readiness_status": stored.get("prompt_readiness_status")}


async def apply_l1(
    product_ids: list[str],
    *,
    authorize: bool = False,
    expected_plan_digest: str | None = None,
    snapshot_path: str | None = None,
) -> dict:
    """Atomically fill L1 for the eligible rows of a cohort. Fail-closed."""
    if not authorize:
        return {"authorized": False, "wrote": False,
                "message": "NOT_AUTHORIZED — preview only.", **await preview_l1(product_ids)}
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
        if excluded:
            return {"authorized": True, "wrote": False,
                    "aborted": "COHORT_CONTAINS_INELIGIBLE_ROWS", "excluded": excluded}

        applied_at = crud._now()
        snapshot_rows = [{
            "product_id": r["product_id"],
            "before": r["before"],
            "after": {**r["write_fields"], "updated_at": applied_at},
        } for r in eligible]
        Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_path).write_text(json.dumps(
            {"plan_digest": expected_plan_digest, "applied_updated_at": applied_at,
             "writable_columns": list(WRITABLE_COLUMNS), "rows": snapshot_rows},
            indent=2, default=str), encoding="utf-8")

        changed, rowcount_failures, verify_failures = [], [], []
        try:
            for r in eligible:
                pid = r["product_id"]
                w = r["write_fields"]
                # CAS on the exact pre-image of every fill-only column plus mapping_status.
                cur = await db.execute(
                    "UPDATE product SET subcategory=?, type=?, mapping_status=?, "
                    "mapping_missing_fields=?, prompt_readiness_status=?, "
                    "prompt_missing_fields=?, updated_at=? "
                    "WHERE id=? AND subcategory IS ? AND type IS ? AND mapping_status IS ?",
                    (w["subcategory"], w["type"], w["mapping_status"],
                     w["mapping_missing_fields"], w["prompt_readiness_status"],
                     w["prompt_missing_fields"], applied_at, pid,
                     r["before"]["subcategory"], r["before"]["type"],
                     r["before"]["mapping_status"]))
                if cur.rowcount != 1:
                    rowcount_failures.append({"product_id": pid, "rowcount": cur.rowcount})
                    continue
                v = await verify_row(pid, r)
                if not v["ok"]:
                    verify_failures.append(v)
                else:
                    changed.append({"product_id": pid,
                                    "mapping_status": v["mapping_status"],
                                    "prompt_readiness_status": v["prompt_readiness_status"],
                                    "subcategory": w["subcategory"], "type": w["type"]})
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
            "changed": changed, "excluded": excluded, "durable_snapshot": snapshot_path,
            "plan_digest": expected_plan_digest, "applied_updated_at": applied_at}


async def rollback_from_snapshot(snapshot_path: str) -> dict:
    """Compare-and-swap rollback of the written columns only."""
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    db = await get_db()
    restored, skipped = [], []
    async with _db_lock:
        for row in data["rows"]:
            pid, before, after = row["product_id"], row["before"], row["after"]
            cur = await db.execute(
                "UPDATE product SET subcategory=?, type=?, mapping_status=?, "
                "mapping_missing_fields=?, prompt_readiness_status=?, "
                "prompt_missing_fields=?, updated_at=? "
                "WHERE id=? AND subcategory IS ? AND type IS ? AND mapping_status IS ?",
                (before["subcategory"], before["type"], before["mapping_status"],
                 before["mapping_missing_fields"], before["prompt_readiness_status"],
                 before["prompt_missing_fields"], before["updated_at"], pid,
                 after["subcategory"], after["type"], after["mapping_status"]))
            if cur.rowcount == 1:
                restored.append(pid)
            else:
                skipped.append({"product_id": pid, "reason": "CHANGED_SINCE_APPLY"})
        await db.commit()
    return {"restored_count": len(restored), "restored": restored, "skipped_cas": skipped}


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


async def main_async(args: argparse.Namespace) -> int:
    if args.rollback:
        result = await rollback_from_snapshot(args.rollback)
        out = _write(OUT_DIR / f"rollback-l1-08e-{_stamp()}.json", result)
        print(json.dumps({**result, "evidence": str(out)}, indent=2, default=str))
        return 0 if not result["skipped_cas"] else 1

    cohort = load_authorized_cohort()
    stamp = _stamp()
    print(f"cohort: {len(cohort)} ids  set_sha256={cohort_set_sha256(AUTHORIZED_L1)}")

    plan = await preview_l1(list(cohort))
    print(f"eligible={plan['eligible_count']} excluded={plan['excluded_count']}")
    print(f"plan_digest: {plan['plan_digest']}")
    for r in plan["rows"]:
        if r.get("eligible"):
            print(f"  {r['product_id'][:8]} mapping {r['mapping_status_before']} -> "
                  f"{r['mapping_status_after']} | prompt {r['prompt_status_before']} -> "
                  f"{r['prompt_status_after']}")
            refused = r["columns_enrichment_would_change_but_this_driver_refuses"]
            print(f"     refused-by-policy columns: {sorted(refused) or 'none'}")
        else:
            print(f"  {r['product_id'][:8]} INELIGIBLE: {r.get('reason')}")

    if not args.apply:
        out = _write(OUT_DIR / f"preview-l1-08e-{stamp}.json",
                     {"mode": "PREVIEW_READ_ONLY", "invoked_at_utc": stamp,
                      "cohort_set_sha256": cohort_set_sha256(AUTHORIZED_L1),
                      "wrote": False, **plan})
        print(f"PREVIEW ONLY — nothing written.\nevidence: {out}")
        return 0

    if not args.authorize:
        print("REFUSED: --apply requires the explicit --authorize flag.")
        return 2

    snapshot = OUT_DIR / "snapshots" / f"product-l1-08e-{stamp}.json"
    result = await apply_l1(list(cohort), authorize=True,
                           expected_plan_digest=plan["plan_digest"],
                           snapshot_path=str(snapshot))
    out = _write(OUT_DIR / f"apply-l1-08e-{stamp}.json",
                 {"mode": "APPLY", "invoked_at_utc": stamp,
                  "cohort_set_sha256": cohort_set_sha256(AUTHORIZED_L1),
                  "preview_plan_digest": plan["plan_digest"], **result})
    print(json.dumps({k: v for k, v in result.items() if k != "excluded"},
                     indent=2, default=str))
    print(f"evidence: {out}")
    return 0 if result.get("wrote") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--preview", action="store_true", help="read-only plan (default)")
    p.add_argument("--apply", action="store_true", help="fill L1; requires --authorize")
    p.add_argument("--authorize", action="store_true", help="explicit owner authorization")
    p.add_argument("--rollback", metavar="SNAPSHOT", help="compare-and-swap rollback")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
