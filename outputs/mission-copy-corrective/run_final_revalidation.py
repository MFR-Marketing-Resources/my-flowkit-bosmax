"""COPY-CORRECTIVE — FINAL revalidation under the tightened authority (B1/B2).

NO provider calls. NO regeneration. For every ACTIVE eligible product's approved,
NON-quarantined Copy Set: re-stamp it via revalidate_copy_set (recompute real PI
grounding evidence + write a durable formula/sales verdict). If the copy genuinely
fails the tightened bar (ungrounded / generic) it is QUARANTINED, not repaired.
Already-quarantined sets stay contained. Products, PI and history are never deleted.
"""
import asyncio
import json
import os
import sys

REPO = r"C:\Users\USER\Desktop\_ref_flowkit"
sys.path.insert(0, REPO)
os.chdir(REPO)
OUT = os.path.join(REPO, "outputs", "mission-copy-corrective")
EXPECTED_DB = os.path.join(REPO, "flow_agent.db").lower()
REVIEWER = "corrective-final-revalidation"
RATIONALE = ("Final governance revalidation (B1/B2): real field-level PI grounding "
             "evidence + durable formula/sales verdict re-stamped. No provider, no "
             "regeneration.")


async def main() -> None:
    from agent.db import get_db
    from agent.models.copy_set import STATUS_COPY_APPROVED
    from agent.services.copy_eligibility_service import copy_eligibility
    from agent.services.copy_set_validity_service import (
        _clean, quarantine_copy_set, revalidate_copy_set,
    )

    db = await get_db()
    dblist = await (await db.execute("PRAGMA database_list")).fetchall()
    main_path = next((r[2] for r in dblist if r[1] == "main"), "")
    if os.path.abspath(main_path or "").lower() != EXPECTED_DB:
        raise SystemExit(f"ABORT: connected DB {main_path!r} != canonical")
    await db.execute("PRAGMA busy_timeout=60000")

    cur = await db.execute("SELECT id FROM product WHERE lifecycle_status='ACTIVE'")
    pids = [str(r["id"]) for r in await cur.fetchall()]
    await cur.close()

    restamped = quarantined = already_quar = ineligible = 0
    ledger = []
    for i, pid in enumerate(pids):
        elig = await copy_eligibility(pid)
        if not elig.get("eligible"):
            ineligible += 1
            continue
        cur = await db.execute(
            "SELECT copy_set_id, pi_eligibility_status FROM copy_set "
            "WHERE product_id=? AND status=? AND COALESCE(archived,0)=0",
            (pid, STATUS_COPY_APPROVED))
        sets = [(str(r["copy_set_id"]), _clean(r["pi_eligibility_status"])) for r in await cur.fetchall()]
        await cur.close()
        for cid, quar in sets:
            if quar:
                already_quar += 1
                continue
            try:
                await revalidate_copy_set(cid, reviewer=REVIEWER, rationale=RATIONALE)
                restamped += 1
                ledger.append({"product_id": pid, "copy_set_id": cid, "decision": "RESTAMPED"})
            except ValueError as e:
                msg = str(e)
                status = "BLOCKED" if "UNSAFE" in msg.upper() else "NEEDS_REVALIDATION"
                await quarantine_copy_set(cid, reason=f"COPY_CORRECTIVE_FINAL:{msg[:90]}", status=status)
                quarantined += 1
                ledger.append({"product_id": pid, "copy_set_id": cid, "decision": "QUARANTINED", "error": msg[:120]})
        if (i + 1) % 50 == 0:
            print(f"[FINAL] {i+1}/{len(pids)} | restamped={restamped} quar={quarantined} already_quar={already_quar}",
                  file=sys.stderr, flush=True)

    summary = {"cohort_active": len(pids), "ineligible": ineligible,
               "sets_restamped": restamped, "sets_quarantined_now": quarantined,
               "sets_already_quarantined": already_quar}
    with open(os.path.join(OUT, "final_revalidation_ledger.jsonl"), "w", encoding="utf-8") as f:
        for r in ledger:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "final_revalidation_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("FINAL_REVAL_DONE " + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
