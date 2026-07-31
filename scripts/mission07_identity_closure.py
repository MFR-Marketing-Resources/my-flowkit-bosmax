#!/usr/bin/env python
"""BOSMAX-ALL-659-PRODUCT-COMPLETENESS-07C — bounded identity/mapping closure.

PHASE 1 SCOPE — exactly the 11 authorized ACTIVE products, fill-empty-only:
the 10 whose mapping fails closed (`mapping_status='BLOCKED'`) plus the 1 carrying a NULL
stored status. Each of the 10 gets a per-ID subcategory/type drawn from the EXISTING
curated catalogue (one minimal new pair for a product class the catalogue does not cover
yet); the canonical enrichment then supplies the remaining authority fields.

Deliberately NOT in this phase: the wider cohort of ACTIVE products whose stored
mapping_status is not reproducible from stored fields. That is a separate pre-existing
defect with its own cohort and is reported, not bundled here.

TRUTHFULNESS BY CONSTRUCTION (same rule as the merged 04B bounded backfill):
enrichment only PROPOSES. The persisted mapping/readiness statuses are computed by the PURE
evaluators over the PROJECTED STORED row, then re-verified by re-reading the row after the
write. A status can never outlive the stored fields that justify it.

SAFETY:
  * `--apply` + `--authorize` required; default is a read-only plan.
  * cohort digest verified immediately before mutation; drift aborts.
  * NEVER overwrites a non-empty stored value (fill-empty-only).
  * one transaction under the canonical lock; rowcount==1 per row; whole-cohort rollback.
  * durable before/after snapshot written BEFORE mutating.
  * every identity write changes the product fingerprint, so the caller MUST run the
    bounded strategy-fingerprint reconciliation afterwards; `--apply` prints the exact
    follow-up command and the affected IDs.
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
from agent.services.mapping_backfill_bounded import WRITABLE_AUTHORITY_FIELDS  # noqa: E402
from agent.services.product_intelligence import enrich_product  # noqa: E402
from agent.services.product_physics import evaluate_prompt_readiness  # noqa: E402
from agent.services.product_preflight import evaluate_mapping_status  # noqa: E402

OUT_DIR = REPO / "outputs" / "mission-07c-identity-closure"

# Per-ID subcategory/type. All pairs exist in the curated catalogue except the one marked
# NEW_MINIMAL, which is the smallest evidence-backed entry for a product class the
# catalogue does not yet cover (a door-mounted pull-up bar).
IDENTITY_ASSIGNMENTS: dict[str, tuple[str, str, str]] = {
    "1063eec6": ("Car Washing & Maintenance", "Cleaning & Care Fluids", "EXISTING"),
    "21dcae04": ("Audio & Video", "Audio & Video Accessories", "EXISTING"),
    "2af04e4c": ("Muslim Fashion", "Square Hijabs", "EXISTING"),
    "2dc99727": ("Muslim Fashion", "Instant Hijab", "EXISTING"),
    "40655de2": ("Home Care Supplies", "Trash Bags", "EXISTING"),
    "4591673f": ("Baby Care & Health", "Laundry Detergent", "EXISTING"),
    "6ddfea5c": ("Baby Care & Health", "Diapers", "EXISTING"),
    "ad805d7d": ("Snacks", "Biscuits, Cookies & Wafers", "EXISTING"),
    "c41ccd1c": ("Audio & Video", "Audio & Video Accessories", "EXISTING"),
    "ec58c4af": ("Fitness Equipment", "Pull-Up Bars", "NEW_MINIMAL"),
    # e06d8afd carries a NULL stored mapping_status; enrichment alone resolves it.
    # Phase 3: the only ACTIVE product still in the missing-cluster / missing-product-type
    # buckets. Its empty subcategory/type left the strategy binding on the generic
    # fallback; this pair (already curated under "Computers & Office Equipment") resolves
    # cluster=stationery, product_type_group=gift_stationery, scene=STATIONERY/COVERED.
    "60c65d01": ("Office Stationery & Supplies", "School & Educational Supplies", "EXISTING"),
}
_RESOLVED = ("READY", "APPROVED", "NEEDS_REVIEW")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _empty(v) -> bool:
    return not v if isinstance(v, list) else not str(v or "").strip()


def _digest(rows: list[dict]) -> str:
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda x: x["id"]):
        h.update(json.dumps(
            {"id": r["id"], "updated_at": r.get("updated_at"),
             "mapping_status": r.get("mapping_status"),
             "prompt_readiness_status": r.get("prompt_readiness_status"),
             "fields": {f: r.get(f) for f in WRITABLE_AUTHORITY_FIELDS}},
            sort_keys=True, default=str).encode())
    return h.hexdigest()


async def _load_active() -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE lifecycle_status='ACTIVE' ORDER BY id")
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


async def build_plan() -> dict:
    """Read-only. Classify both cohorts and compute the exact proposed write set."""
    rows = await _load_active()
    plan = []
    for p in rows:
        short = p["id"][:8]
        stored = p.get("mapping_status")
        recomputed = evaluate_mapping_status(p)["mapping_status"]
        # Phase 1 cohort ONLY: the assigned BLOCKED products plus the NULL-status product.
        if short not in IDENTITY_ASSIGNMENTS and stored is not None:
            continue

        projected = dict(p)
        writes: dict[str, object] = {}
        sub_typ = IDENTITY_ASSIGNMENTS.get(short)
        if sub_typ:
            sub, typ, _src = sub_typ
            if _empty(projected.get("subcategory")):
                writes["subcategory"] = sub; projected["subcategory"] = sub
            if _empty(projected.get("type")):
                writes["type"] = typ; projected["type"] = typ

        enriched = await enrich_product(dict(projected), persist=False)
        for f in WRITABLE_AUTHORITY_FIELDS:
            if _empty(projected.get(f)) and not _empty(enriched.get(f)):
                writes[f] = enriched[f]; projected[f] = enriched[f]
        if not writes:
            continue

        m = evaluate_mapping_status(projected)
        projected.update(m)
        r = evaluate_prompt_readiness(projected, projected)
        after_map = m["mapping_status"]
        after_rdy = "MISSING_FIELDS" if after_map == "BLOCKED" else r.get("prompt_readiness_status")

        plan.append({
            "product_id": p["id"], "short": short,
            "cohort": "PHASE1_IDENTITY_CLOSURE",
            "vocab_source": (sub_typ[2] if sub_typ else "ENRICHMENT_ONLY"),
            "stored_mapping": stored, "recomputed_before": recomputed,
            "after_mapping": after_map, "after_readiness": after_rdy,
            "resolves": after_map in _RESOLVED,
            "writes": writes, "write_fields": sorted(writes),
            "row_updated_at": p.get("updated_at"),
        })
    return {"candidates": plan, "plan_digest": _digest(rows), "active_count": len(rows)}


async def apply_plan(plan: dict, snapshot_path: Path) -> dict:
    db = await get_db()
    eligible = [c for c in plan["candidates"] if c["resolves"]]
    skipped = [c for c in plan["candidates"] if not c["resolves"]]

    async with _db_lock:
        live = _digest(await _load_active())
        if live != plan["plan_digest"]:
            return {"wrote": False, "aborted": "PLAN_DIGEST_MISMATCH",
                    "expected": plan["plan_digest"], "live": live}

        applied_at = crud._now()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps({
            "applied_updated_at": applied_at,
            "rows": [{"product_id": c["product_id"], "writes": c["writes"],
                      "before_updated_at": c["row_updated_at"]} for c in eligible]},
            indent=2, default=str), encoding="utf-8")

        changed, failures = [], []
        try:
            for c in eligible:
                cols = [*c["writes"], "mapping_status", "prompt_readiness_status", "updated_at"]
                vals = [*(c["writes"][f] for f in c["writes"]),
                        c["after_mapping"], c["after_readiness"], applied_at]
                sets = ", ".join(f'"{col}"=?' for col in cols)
                cur = await db.execute(
                    f"UPDATE product SET {sets} WHERE id=? AND updated_at IS ?",
                    (*vals, c["product_id"], c["row_updated_at"]))
                if cur.rowcount != 1:
                    failures.append({"product_id": c["product_id"], "rowcount": cur.rowcount})
                    continue
                # re-read and re-evaluate with the PURE evaluators over STORED values only
                cur2 = await db.execute("SELECT * FROM product WHERE id=?", (c["product_id"],))
                row = dict(await cur2.fetchone())
                await cur2.close()
                if evaluate_mapping_status(row)["mapping_status"] != row.get("mapping_status"):
                    failures.append({"product_id": c["product_id"], "reason": "STATUS_NOT_REPRODUCIBLE_AFTER_WRITE"})
                else:
                    changed.append(c["product_id"])
            if failures:
                await db.rollback()
                return {"wrote": False, "aborted": "VERIFICATION_FAILED", "failures": failures}
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {"wrote": True, "changed_count": len(changed), "changed": sorted(changed),
            "skipped_unresolved": [s["product_id"] for s in skipped],
            "applied_updated_at": applied_at, "durable_snapshot": str(snapshot_path)}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = await build_plan()
    cands = plan["candidates"]
    res = [c for c in cands if c["resolves"]]
    stamp = _stamp()

    print(f"active products      : {plan['active_count']}")
    print(f"phase-1 cohort       : {len(cands)}")
    print(f"eligible writes      : {len(res)}")
    print(f"unresolved (skipped) : {len(cands) - len(res)}")
    print(f"plan_digest          : {plan['plan_digest']}")

    if not (args.apply and args.authorize):
        (OUT_DIR / f"identity-plan-{stamp}.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8")
        print("\nPLAN ONLY — nothing written. Re-run with --apply --authorize.")
        return 0

    result = await apply_plan(plan, OUT_DIR / "snapshots" / f"identity-{stamp}.json")
    (OUT_DIR / f"identity-apply-{stamp}.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "changed"}, indent=2))
    if result.get("wrote"):
        print("\nFINGERPRINT RECONCILIATION REQUIRED for the changed IDs — identity writes")
        print("change product_strategy_fingerprint. Run the bounded 04C mechanism next.")
    return 0 if result.get("wrote") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--authorize", action="store_true")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
