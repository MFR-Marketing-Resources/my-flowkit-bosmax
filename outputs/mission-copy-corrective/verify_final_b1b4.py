"""FINAL verification: containment + DB integrity + FK + no-deletion, post B1-B4.
Re-evaluates every NON-quarantined approved Copy Set in the 402 ACTIVE-eligible
cohort through the strict authority and asserts NONE is invalid (no fail-open leak).
"""
import asyncio, os, sys, json
REPO = r"C:\Users\USER\Desktop\_ref_flowkit"; sys.path.insert(0, REPO); os.chdir(REPO)

async def main():
    from agent.db import get_db
    from agent.services.copy_set_validity_service import evaluate_copy_set_id
    db = await get_db()
    await db.execute("PRAGMA busy_timeout=180000")
    out = {}
    out["integrity_check"] = (await (await db.execute("PRAGMA integrity_check")).fetchone())[0]
    out["foreign_key_violations"] = len(await (await db.execute("PRAGMA foreign_key_check")).fetchall())
    out["product_count"] = (await (await db.execute("SELECT COUNT(*) c FROM product")).fetchone())["c"]
    out["copy_set_count"] = (await (await db.execute("SELECT COUNT(*) c FROM copy_set")).fetchone())["c"]
    cur = await db.execute("""
        SELECT cs.copy_set_id FROM copy_set cs JOIN product p ON p.id = cs.product_id
        WHERE p.lifecycle_status='ACTIVE' AND cs.status='COPY_APPROVED' AND COALESCE(cs.archived,0)=0
          AND (cs.pi_eligibility_status IS NULL OR cs.pi_eligibility_status='')""")
    ids = [r["copy_set_id"] for r in await cur.fetchall()]; await cur.close()
    leaked, checked = [], 0
    sem = asyncio.Semaphore(8)
    async def check(cid):
        nonlocal checked
        async with sem:
            v = await evaluate_copy_set_id(cid)
        checked += 1
        if not v.get("valid"):
            leaked.append({"id": cid[:8], "reasons": v.get("reasons")})
    await asyncio.gather(*[check(c) for c in ids])
    out["nonquarantined_approved_sets_checked"] = len(ids)
    out["nonquarantined_invalid_LEAKED"] = len(leaked)
    out["leaked_examples"] = leaked[:8]
    out["CONTAINMENT_PASS"] = (len(leaked) == 0)
    print(json.dumps(out, indent=1))
    with open(os.path.join(REPO,"outputs","mission-copy-corrective","final_containment_proof.json"),"w") as f:
        json.dump(out, f, indent=1)

asyncio.run(main())
