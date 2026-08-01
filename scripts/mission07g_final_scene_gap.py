#!/usr/bin/env python
"""BOSMAX-07G-FINAL-SCENE-GAP-04 — bounded closure of the last real-product scene gap.

TARGET (mission scope, exactly one product)
    5d298e84  "Limited Edition Petite Sample Joielle Baby 15g"
        beauty_personal_care/beauty_personal_care_other/BEAUTY_PERSONAL_CARE  PARTIAL
    ->  baby_care/baby_skincare/BABY_SKINCARE                                 COVERED

    Its title names a sample SIZE, not a substance, and both truth fields are empty, so
    it auto-derived to the beauty generic fallback. The packaging is decisive: a JOIELLE
    BABY petite-sample box printing natural rub 15gm, baby lotion 15gm, baby cream 15gm,
    baby bath 15ml, baby oil 15ml, baby shampoo 15ml, top to toe cleanser 15ml, wonder
    cream 5g and a VCO set. BABY_SKINCARE is a pack / label / age-guidance / texture
    CHECK grammar that already forbids infant application and efficacy claims, so it fits
    a multi-item infant trial box without asserting any single substance's function.

REPAIR (disclosed defect, NOT mission scope)
    8e75f1a8  stored cluster 'beauty_personal_care' for product_type_group
    'traditional_herbal_preparation'. That pair exists in NO registry row - an orphaned
    binding introduced by PR #583, where the backfill was applied before the cluster was
    corrected to 'sensitive_wellness' and never re-applied afterwards. The scene id was
    right so the KPI looked clean, which is exactly why it needs an explicit repair.

Both rows are re-derived from the authority module - nothing is hand-written - and both
stay REVIEW_REQUIRED. Neither product has an approved Product Truth, so neither is
released into P4/P6 by this script.

SAFETY
  * `--apply` + `--authorize` required; default prints the plan and writes nothing.
  * refuses any id not listed here;
  * refuses unless the target (cluster, product_type_group) is ACTIVE + COVERED in the
    registry AND carries a 1:1 P4 entry;
  * refuses to write a GENERIC_FALLBACK or non-COVERED binding;
  * one transaction, CAS on `updated_at`, `rowcount == 1` per row;
  * protected tables (product, registry, copy_set) hashed before AND after - any drift
    rolls the whole cohort back;
  * durable before/after snapshot + plan digest written before mutating;
  * post-write re-read proves binding, coverage, fallback, fingerprint and lifecycle.
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

from agent.authority.product_type_copy_strategy_registry import (  # noqa: E402
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY,
)
from agent.db import crud  # noqa: E402
from agent.db.schema import _db_lock, get_db  # noqa: E402
from agent.services.product_strategy_taxonomy_service import (  # noqa: E402
    build_product_strategy_taxonomy_candidate,
    product_strategy_fingerprint,
)
from agent.services.scene_contract_service import (  # noqa: E402
    GENERIC_FALLBACK_ID,
    evaluate_scene_contract,
)

OUT_DIR = REPO / "outputs" / "mission-07g-final-scene-gap"

TARGET_ID = "5d298e84-2dc2-4747-9a0b-77499f5c8569"
REPAIR_ID = "8e75f1a8-ba43-444e-8b40-c71d140c76c5"
COHORT: tuple[str, ...] = (TARGET_ID, REPAIR_ID)
ROLE = {TARGET_ID: "MISSION_TARGET", REPAIR_ID: "DISCLOSED_PR583_ORPHAN_REPAIR"}

NOTE = (
    "Mission-07G-FINAL-SCENE-GAP-04: binding re-derived from catalog product-type "
    "authority; held for human review because no approved Product Truth exists"
)

# Hashed before and after the write. Nothing in this mission may touch them.
PROTECTED_TABLES = ("product", "product_strategy_type_registry", "copy_set")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def _load(pid: str):
    db = await get_db()
    cur = await db.execute("SELECT * FROM product WHERE id=?", (pid,))
    prow = await cur.fetchone()
    await cur.close()
    cur = await db.execute(
        "SELECT * FROM product_strategy_taxonomy WHERE product_id=?", (pid,))
    trow = await cur.fetchone()
    await cur.close()
    return (dict(prow) if prow else None), (dict(trow) if trow else None)


async def _protected_hashes() -> dict[str, str]:
    """Stable content hash per protected table, order-independent."""
    db = await get_db()
    out: dict[str, str] = {}
    for table in PROTECTED_TABLES:
        cur = await db.execute(f"SELECT * FROM {table}")
        rows = [dict(r) for r in await cur.fetchall()]
        await cur.close()
        payload = json.dumps(
            sorted(json.dumps(r, sort_keys=True, default=str) for r in rows))
        out[table] = hashlib.sha256(payload.encode()).hexdigest()
    return out


async def _registry_and_p4_ok(cluster: str, group: str, scene_id: str) -> tuple[bool, str]:
    db = await get_db()
    cur = await db.execute(
        "SELECT registry_status, scene_coverage_status, matched_scene_strategy_id"
        " FROM product_strategy_type_registry WHERE cluster=? AND product_type_group=?",
        (cluster, group))
    row = await cur.fetchone()
    await cur.close()
    if row is None:
        return False, "REGISTRY_PAIR_ABSENT"
    if row[0] != "ACTIVE" or row[1] != "COVERED":
        return False, f"REGISTRY_PAIR_NOT_ACTIVE_COVERED({row[0]}/{row[1]})"
    if str(row[2]) != scene_id:
        return False, f"REGISTRY_SCENE_MISMATCH(registry={row[2]} derived={scene_id})"
    if (cluster, group, scene_id) not in PRODUCT_TYPE_COPY_STRATEGY_REGISTRY:
        return False, "P4_ENTRY_MISSING"
    return True, "OK"


def _plan_digest(plan: list[dict]) -> str:
    material = [
        [c["product_id"], c["derived"]["cluster"], c["derived"]["product_type_group"],
         c["derived"]["matched_scene_strategy_id"], c["target_fingerprint"]]
        for c in sorted(plan, key=lambda c: c["product_id"]) if c["eligible"]
    ]
    return hashlib.sha256(
        json.dumps(material, separators=(",", ":")).encode()).hexdigest()


async def build_plan() -> list[dict]:
    plan: list[dict] = []
    for pid in COHORT:
        product, tax = await _load(pid)
        if not product or not tax:
            plan.append({"product_id": pid, "role": ROLE[pid], "eligible": False,
                         "reason": "ROW_MISSING"})
            continue
        candidate = build_product_strategy_taxonomy_candidate(
            product, materialization_status="MATERIALIZED")
        derived = {
            "cluster": candidate.cluster,
            "product_type_group": candidate.product_type_group,
            "matched_scene_strategy_id": candidate.matched_scene_strategy_id,
            "scene_coverage_status": candidate.scene_coverage_status,
            "fallback_used": bool(candidate.fallback_used),
            "specific_strategy": bool(candidate.specific_strategy),
            "review_status": candidate.review_status,
            "consumer_status": candidate.consumer_status,
        }
        stored = {k: tax.get(k) for k in
                  ("cluster", "product_type_group", "matched_scene_strategy_id",
                   "scene_coverage_status")}
        changed = any(str(derived[k]) != str(stored[k]) for k in stored)
        ok, why = await _registry_and_p4_ok(
            derived["cluster"], derived["product_type_group"],
            derived["matched_scene_strategy_id"])
        contract = evaluate_scene_contract(derived)
        refusals = []
        if not changed:
            refusals.append("BINDING_UNCHANGED")
        if not ok:
            refusals.append(why)
        if derived["matched_scene_strategy_id"] == GENERIC_FALLBACK_ID:
            refusals.append("REFUSE_GENERIC_FALLBACK")
        if derived["scene_coverage_status"] != "COVERED" or derived["fallback_used"]:
            refusals.append("REFUSE_NOT_COVERED")
        if contract["scene_contract_status"] != "COMPLETE":
            refusals.append(f"CONTRACT_NOT_COMPLETE{contract['scene_gap_reasons']}")
        plan.append({
            "product_id": pid, "role": ROLE[pid],
            "title": "".join(c for c in str(product.get("raw_product_title") or "")
                             if ord(c) < 128)[:64],
            "lifecycle_status": product.get("lifecycle_status"),
            "stored": stored, "derived": derived,
            "target_contract": contract,
            "stored_fingerprint": tax.get("product_fingerprint"),
            "target_fingerprint": product_strategy_fingerprint(product),
            "row_updated_at": tax.get("updated_at"),
            "eligible": not refusals, "reason": refusals or None,
        })
    return plan


async def apply_plan(plan: list[dict], snapshot: Path, expected_digest: str) -> dict:
    db = await get_db()
    eligible = [c for c in plan if c["eligible"]]
    if not eligible:
        return {"wrote": False, "aborted": "NOTHING_ELIGIBLE"}
    if _plan_digest(plan) != expected_digest:
        return {"wrote": False, "aborted": "PLAN_DIGEST_MISMATCH"}

    async with _db_lock:
        before_hashes = await _protected_hashes()
        now = crud._now()
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps({
            "applied_updated_at": now, "plan_digest": expected_digest,
            "protected_before": before_hashes, "rows": eligible,
        }, indent=2, default=str), encoding="utf-8")

        changed, failures = [], []
        try:
            for c in eligible:
                d = c["derived"]
                cur = await db.execute(
                    "UPDATE product_strategy_taxonomy SET cluster=?, product_type_group=?,"
                    " matched_scene_strategy_id=?, scene_coverage_status=?, fallback_used=?,"
                    " specific_strategy=?, product_fingerprint=?, review_status=?,"
                    " consumer_status=?, reviewer_note=?, updated_at=?"
                    " WHERE product_id=? AND updated_at IS ?",
                    (d["cluster"], d["product_type_group"], d["matched_scene_strategy_id"],
                     d["scene_coverage_status"], 1 if d["fallback_used"] else 0,
                     1 if d["specific_strategy"] else 0, c["target_fingerprint"],
                     d["review_status"], d["consumer_status"], NOTE, now,
                     c["product_id"], c["row_updated_at"]))
                if cur.rowcount != 1:
                    failures.append({"product_id": c["product_id"],
                                     "reason": f"ROWCOUNT_{cur.rowcount}"})
                    continue
                product, tax = await _load(c["product_id"])
                post = evaluate_scene_contract(tax)
                if (tax["matched_scene_strategy_id"] != d["matched_scene_strategy_id"]
                        or tax["scene_coverage_status"] != "COVERED"
                        or bool(tax["fallback_used"])
                        or tax["product_fingerprint"] != product_strategy_fingerprint(product)
                        or product["lifecycle_status"] != c["lifecycle_status"]
                        or post["scene_contract_status"] != "COMPLETE"):
                    failures.append({"product_id": c["product_id"],
                                     "reason": "POST_WRITE_VERIFY_FAILED", "post": post})
                else:
                    changed.append(c["product_id"])

            after_hashes = await _protected_hashes()
            drifted = {t: [before_hashes[t], after_hashes[t]] for t in PROTECTED_TABLES
                       if before_hashes[t] != after_hashes[t]}
            if drifted:
                failures.append({"reason": "PROTECTED_TABLE_DRIFT", "tables": drifted})

            if failures:
                await db.rollback()
                post_rollback = await _protected_hashes()
                return {"wrote": False, "aborted": "VERIFICATION_FAILED",
                        "failures": failures,
                        "rollback_restored_protected": post_rollback == before_hashes}
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return {"wrote": True, "changed_count": len(changed), "changed": changed,
            "applied_updated_at": now, "plan_digest": expected_digest,
            "protected_tables_unchanged": True,
            "durable_snapshot": str(snapshot)}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = await build_plan()
    digest = _plan_digest(plan)
    for c in plan:
        print(f"  {'APPLY' if c.get('eligible') else 'SKIP '} {c['product_id']}  [{c['role']}]")
        print(f"        {c.get('title','')}")
        if c.get("stored"):
            print(f"        stored : {c['stored']['cluster']}/{c['stored']['product_type_group']}"
                  f"/{c['stored']['matched_scene_strategy_id']} ({c['stored']['scene_coverage_status']})")
            print(f"        derived: {c['derived']['cluster']}/{c['derived']['product_type_group']}"
                  f"/{c['derived']['matched_scene_strategy_id']} ({c['derived']['scene_coverage_status']})"
                  f"  contract={c['target_contract']['scene_contract_status']}"
                  f" variants={c['target_contract']['scene_variants_count']}")
        if not c.get("eligible"):
            print(f"        reason : {c.get('reason')}")
    print(f"\n  PLAN_DIGEST = {digest}")

    stamp = _stamp()
    if not (args.apply and args.authorize):
        (OUT_DIR / f"plan-{stamp}.json").write_text(
            json.dumps({"plan": plan, "plan_digest": digest}, indent=2, default=str),
            encoding="utf-8")
        print("\nPLAN ONLY — nothing written. Re-run with --apply --authorize.")
        return 0

    result = await apply_plan(plan, OUT_DIR / "snapshots" / f"final-gap-{stamp}.json", digest)
    (OUT_DIR / f"apply-{stamp}.json").write_text(
        json.dumps({"plan": plan, "plan_digest": digest, "result": result},
                   indent=2, default=str), encoding="utf-8")
    print("\n" + json.dumps(result, indent=2, default=str))
    return 0 if result.get("wrote") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--authorize", action="store_true")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
