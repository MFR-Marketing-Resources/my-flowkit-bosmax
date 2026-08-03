"""COPY-CORRECTIVE — containment + FREE strict revalidation (one combined pass).

For every ACTIVE canonical eligible product's non-archived APPROVED copy sets:
  strict deterministic review = eligible + non-generic + complete + safe + PI-grounded
  PASS  -> revalidate_copy_set  (write semantic receipt + lineage, clear quarantine)
  FAIL  -> quarantine_copy_set  (NEEDS_REVALIDATION + exact reason)  [containment]

NO provider calls. Backup-guarded (a fresh verified restore point exists). Idempotent
(re-running reproduces the same state). Writes ledgers + the truthful strict gap manifest.
"""
import asyncio
import json
import os
import sys

REPO = r"C:\Users\USER\Desktop\_ref_flowkit"
sys.path.insert(0, REPO)
os.chdir(REPO)

OUT = os.path.join(REPO, "outputs", "mission-copy-corrective")
REVIEWER = "corrective-revalidation-engine"
QUAR_PREFIX = "COPY_FINAL_CURSOR_PENDING_STRICT_REVIEW"
EXPECTED_DB = os.path.join(REPO, "flow_agent.db").lower()
DRY_RUN = bool(os.environ.get("DRY_RUN"))


async def main() -> None:
    from agent.db import get_db
    from agent.models.copy_set import STATUS_COPY_APPROVED, serialize_copy_set
    from agent.services.copy_eligibility_service import copy_eligibility
    from agent.services.copy_set_service import assess_copy_completeness, scan_copy_safety
    from agent.services.copy_set_validity_service import (
        _latest_approved_snapshot,
        _product_name,
        assess_semantic_grounding,
        detect_generic_copy,
        product_copy_classification,
        quarantine_copy_set,
        revalidate_copy_set,
    )

    db = await get_db()
    # HARD SAFETY GUARD: only ever mutate the canonical repo-root flow_agent.db.
    dblist = await (await db.execute("PRAGMA database_list")).fetchall()
    main_path = ""
    for r in dblist:
        if (r["name"] if hasattr(r, "keys") else r[1]) == "main":
            main_path = (r["file"] if hasattr(r, "keys") else r[2]) or ""
    if os.path.abspath(main_path).lower() != EXPECTED_DB:
        raise SystemExit(f"ABORT: connected DB {main_path!r} != canonical {EXPECTED_DB!r}")
    await db.execute("PRAGMA busy_timeout=30000")

    cur = await db.execute("SELECT id FROM product WHERE lifecycle_status='ACTIVE'")
    pids = [str(r["id"]) for r in await cur.fetchall()]
    await cur.close()

    ledger = []
    products = []
    tot_reval = tot_quar = 0
    mode = "DRY_RUN" if DRY_RUN else "LIVE"
    print(f"[{mode}] cohort={len(pids)} products — starting", file=sys.stderr, flush=True)
    for _i, pid in enumerate(pids):
        if _i and _i % 25 == 0:
            print(
                f"[{mode}] {_i}/{len(pids)} products | revalidated={tot_reval} quarantined={tot_quar}",
                file=sys.stderr,
                flush=True,
            )
        elig = await copy_eligibility(pid)
        snap = await _latest_approved_snapshot(pid)
        pname = await _product_name(pid)
        cur = await db.execute(
            "SELECT * FROM copy_set WHERE product_id=? AND status=? AND COALESCE(archived,0)=0",
            (pid, STATUS_COPY_APPROVED),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        await cur.close()

        reval = quar = 0
        for cs in rows:
            fields = serialize_copy_set(cs)
            usp = [u for u in (fields.get("usp_set") or []) if str(u).strip()]
            gen = detect_generic_copy(
                angle=str(fields.get("angle") or ""),
                hook=str(fields.get("hook") or ""),
                subhook=str(fields.get("subhook") or ""),
                usp_list=usp,
                cta=str(fields.get("cta") or ""),
                product_name=pname,
            )
            comp = assess_copy_completeness(fields)
            safe = scan_copy_safety(fields, product_id=pid)
            grounding = (
                assess_semantic_grounding(
                    hook=str(fields.get("hook") or ""),
                    subhook=str(fields.get("subhook") or ""),
                    usp_list=usp,
                    cta=str(fields.get("cta") or ""),
                    snapshot=snap,
                    product_title=pname,
                )
                if snap
                else {"grounded": False, "usp_grounding": [], "reasons": ["NO_SNAPSHOT"]}
            )
            fails = []
            if not elig.get("eligible"):
                fails.append("PRODUCT_INELIGIBLE")
            if gen["generic"]:
                fails.append("GENERIC")
            if not comp["complete"]:
                fails.append("INCOMPLETE")
            if not safe["safe"]:
                fails.append("UNSAFE")
            if not grounding["grounded"]:
                fails.append("UNGROUNDED")

            cid = str(cs["copy_set_id"])
            if not fails:
                if not DRY_RUN:
                    await revalidate_copy_set(
                        cid,
                        reviewer=REVIEWER,
                        rationale="Deterministic strict review PASS: non-generic, complete, safe, PI-grounded.",
                        usp_grounding=grounding.get("usp_grounding"),
                        genericness=gen,
                    )
                reval += 1
                decision = "REVALIDATED"
            else:
                if not DRY_RUN:
                    await quarantine_copy_set(cid, reason=f"{QUAR_PREFIX}:{','.join(fails)}")
                quar += 1
                decision = "QUARANTINED"
            ledger.append(
                {
                    "product_id": pid,
                    "copy_set_id": cid,
                    "decision": decision,
                    "fail_reasons": fails,
                    "generic": gen["generic"],
                    "grounded": grounding.get("grounded"),
                    "approved_by": str(cs.get("approved_by") or ""),
                }
            )
        tot_reval += reval
        tot_quar += quar
        # A product with >=1 revalidated (strict-passing) set now has a strict-valid
        # Copy Set -> closed for free. Verified independently after the real run.
        closed = reval > 0
        products.append(
            {
                "product_id": pid,
                "product_name": pname,
                "approved_sets": len(rows),
                "revalidated": reval,
                "quarantined": quar,
                "closed_free": closed,
                "residual_action": None if closed else "REPLACE_COPY_PAID",
            }
        )

    closed_free = sum(1 for p in products if p["closed_free"])
    residual = [p for p in products if not p["closed_free"]]
    summary = {
        "cohort_active": len(pids),
        "approved_sets_reviewed": tot_reval + tot_quar,
        "sets_revalidated_free": tot_reval,
        "sets_quarantined": tot_quar,
        "products_closed_free": closed_free,
        "products_residual_paid": len(residual),
        "residual_product_ids": [p["product_id"] for p in residual],
    }
    with open(os.path.join(OUT, "containment_revalidation_ledger.jsonl"), "w", encoding="utf-8") as f:
        for row in ledger:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "strict_gap_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "products": products}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "revalidation_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
