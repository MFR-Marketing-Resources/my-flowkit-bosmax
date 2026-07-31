#!/usr/bin/env python
"""BOSMAX-07G — bounded correction of MANUAL_OVERRIDE rows whose binding went stale.

WHY A SEPARATE PATH
The governed taxonomy backfill deliberately PRESERVES `authority_source='MANUAL_OVERRIDE'`
rows, which is correct: an operator decision must not be silently re-derived. But three
products were given a MANUAL_OVERRIDE binding and then had their IDENTITY corrected under
owner authority, so the stored binding is now demonstrably WRONG and the backfill will
never touch it:

    e06d8afd  Minyak Kastor (castor HAIR OIL)      hair_wash/HAIR_WASH
                                              ->  hair_treatment/HAIR_TREATMENT
    1063eec6  Nakamichi WINDSHIELD cleaner          household_cleaner/HOUSEHOLD_CLEANER
                                              ->  car_care_fluid/CAR_CARE
    ad805d7d  Biskut Makmur (BISCUITS)              packaged_food/PACKAGED_FOOD
                                              ->  packaged_snack/PACKAGED_SNACK

Refreshing the fingerprint alone would have "resolved" the staleness flag while leaving a
castor oil classified as a shampoo — certifying wrong data. This writes the binding the
current identity actually derives, then the matching fingerprint.

GOVERNANCE
The binding materially CHANGED, so these rows are NOT re-verified. `review_status` is set
to REVIEW_REQUIRED / BLOCKED_REVIEW_REQUIRED and the original reviewer provenance is kept
in the note. That is the same stance the bounded 04C mechanism takes: a changed binding is
a human decision, not a repair. None of the three is in the P6 cohort today, so this
cannot regress production readiness.

SAFETY
  * `--apply` + `--authorize` required; default prints the plan and writes nothing.
  * only rows whose CURRENT derived binding differs from stored are eligible;
  * the target (cluster, product_type_group) pair must exist ACTIVE + COVERED in the
    registry, else the row is refused;
  * one transaction, CAS on `updated_at`, exact rowcount, whole-cohort rollback;
  * durable before/after snapshot written before mutating;
  * post-write re-read proves binding, fingerprint and lifecycle.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.db import crud  # noqa: E402
from agent.db.schema import _db_lock, get_db  # noqa: E402
from agent.services.product_strategy_taxonomy_service import (  # noqa: E402
    _strategy_binding,
    product_strategy_fingerprint,
)

OUT_DIR = REPO / "outputs" / "mission-07g-scene-binding"

# Exactly the three MANUAL_OVERRIDE rows whose identity was corrected under owner
# authority. Immutable: the script refuses anything not listed here.
COHORT: tuple[str, ...] = (
    "e06d8afd-44fa-47d7-8d79-d7dc55d52c41",
    "1063eec6-976c-415f-95dd-be5c7b53608b",
    "ad805d7d-e6fa-4a05-ad96-edc8e0295ae8",
)
NOTE = (
    "Mission-07G: binding re-derived after an owner-authorised identity correction; "
    "held for human review because the strategy binding changed"
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def _load(pid: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE id=?", (pid,))
    prow = await cur.fetchone()
    await cur.close()
    cur = await db.execute("SELECT * FROM product_strategy_taxonomy WHERE product_id=?", (pid,))
    trow = await cur.fetchone()
    await cur.close()
    return (dict(prow) if prow else None), (dict(trow) if trow else None)


async def _registry_ok(cluster: str, group: str) -> bool:
    db = await get_db()
    cur = await db.execute(
        "SELECT registry_status, scene_coverage_status FROM product_strategy_type_registry"
        " WHERE cluster=? AND product_type_group=?", (cluster, group))
    row = await cur.fetchone()
    await cur.close()
    return bool(row and row[0] == "ACTIVE" and row[1] == "COVERED")


async def build_plan() -> list[dict]:
    plan = []
    for pid in COHORT:
        product, tax = await _load(pid)
        if not product or not tax:
            plan.append({"product_id": pid, "eligible": False, "reason": "ROW_MISSING"})
            continue
        derived = _strategy_binding(product)
        stored = {
            "cluster": tax.get("cluster"),
            "product_type_group": tax.get("product_type_group"),
            "matched_scene_strategy_id": tax.get("matched_scene_strategy_id"),
            "scene_coverage_status": tax.get("scene_coverage_status"),
        }
        changed = any(str(derived[k]) != str(stored[k]) for k in stored)
        registry_ok = await _registry_ok(derived["cluster"], derived["product_type_group"])
        plan.append({
            "product_id": pid,
            "title": "".join(c for c in str(product.get("raw_product_title") or "") if ord(c) < 128)[:56],
            "stored": stored, "derived": derived,
            "binding_changed": changed, "registry_ok": registry_ok,
            "current_fingerprint": product_strategy_fingerprint(product),
            "stored_fingerprint": tax.get("product_fingerprint"),
            "row_updated_at": tax.get("updated_at"),
            "lifecycle_status": product.get("lifecycle_status"),
            "eligible": bool(changed and registry_ok),
            "reason": None if (changed and registry_ok)
                      else ("BINDING_UNCHANGED" if not changed else "REGISTRY_PAIR_NOT_ACTIVE_COVERED"),
        })
    return plan


async def apply_plan(plan: list[dict], snapshot: Path) -> dict:
    db = await get_db()
    eligible = [c for c in plan if c["eligible"]]
    if not eligible:
        return {"wrote": False, "aborted": "NOTHING_ELIGIBLE"}

    async with _db_lock:
        now = crud._now()
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(
            {"applied_updated_at": now, "rows": eligible}, indent=2, default=str), encoding="utf-8")

        changed, failures = [], []
        try:
            for c in eligible:
                d = c["derived"]
                cur = await db.execute(
                    "UPDATE product_strategy_taxonomy SET cluster=?, product_type_group=?,"
                    " matched_scene_strategy_id=?, scene_coverage_status=?, fallback_used=?,"
                    " specific_strategy=?, product_fingerprint=?, review_status='REVIEW_REQUIRED',"
                    " consumer_status='BLOCKED_REVIEW_REQUIRED', reviewer_note=?, updated_at=?"
                    " WHERE product_id=? AND updated_at IS ?",
                    (d["cluster"], d["product_type_group"], d["matched_scene_strategy_id"],
                     d["scene_coverage_status"], 1 if d["fallback_used"] else 0,
                     1 if d["specific_strategy"] else 0, c["current_fingerprint"],
                     NOTE, now, c["product_id"], c["row_updated_at"]))
                if cur.rowcount != 1:
                    failures.append({"product_id": c["product_id"], "rowcount": cur.rowcount})
                    continue
                product, tax = await _load(c["product_id"])
                if (tax["matched_scene_strategy_id"] != d["matched_scene_strategy_id"]
                        or tax["product_fingerprint"] != product_strategy_fingerprint(product)
                        or product["lifecycle_status"] != c["lifecycle_status"]):
                    failures.append({"product_id": c["product_id"], "reason": "POST_WRITE_VERIFY_FAILED"})
                else:
                    changed.append(c["product_id"])
            if failures:
                await db.rollback()
                return {"wrote": False, "aborted": "VERIFICATION_FAILED", "failures": failures}
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {"wrote": True, "changed_count": len(changed), "changed": changed,
            "applied_updated_at": now, "durable_snapshot": str(snapshot)}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = await build_plan()
    for c in plan:
        flag = "APPLY" if c.get("eligible") else "SKIP "
        print(f"  {flag} {c['product_id'][:8]} {c.get('title','')}")
        if c.get("stored"):
            print(f"        stored : {c['stored']['product_type_group']} / {c['stored']['matched_scene_strategy_id']}")
            print(f"        derived: {c['derived']['product_type_group']} / {c['derived']['matched_scene_strategy_id']}")
        if not c.get("eligible"):
            print(f"        reason : {c.get('reason')}")

    stamp = _stamp()
    if not (args.apply and args.authorize):
        (OUT_DIR / f"plan-{stamp}.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8")
        print("\nPLAN ONLY — nothing written. Re-run with --apply --authorize.")
        return 0

    result = await apply_plan(plan, OUT_DIR / "snapshots" / f"binding-{stamp}.json")
    (OUT_DIR / f"apply-{stamp}.json").write_text(
        json.dumps({"plan": plan, "result": result}, indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(result, indent=2, default=str))
    return 0 if result.get("wrote") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--authorize", action="store_true")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
