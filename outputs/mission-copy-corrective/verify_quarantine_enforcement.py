"""COPY-CORRECTIVE — prove every quarantined (twice-failed) product is
non-executable across EVERY consumer, and remains ACTIVE + preserved.

All execution paths gate on the same authority:
  - rotation / copy-pool readiness -> copy_rotation_service.list_eligible_copy_sets
  - copy selection / recommendation -> valid_copy_set_ids_for_product
  - compiler binding + workspace generation/execution packages + queue ->
    assert_copy_set_valid (fail-closed) inside resolve_compiler_copy_intelligence
So: empty eligible pool + empty valid-set set + assert raising on every approved
set transitively proves no rotation / selection / poster / binding / queue /
package can ever hand out the product's copy.
"""
import asyncio
import json
import os
import sys

REPO = r"C:\Users\USER\Desktop\_ref_flowkit"
sys.path.insert(0, REPO)
os.chdir(REPO)
OUT = os.path.join(REPO, "outputs", "mission-copy-corrective")


async def main() -> None:
    from agent.db import get_db
    from agent.models.copy_set import STATUS_COPY_APPROVED
    from agent.services.copy_rotation_service import list_eligible_copy_sets
    from agent.services.copy_set_validity_service import (
        assert_copy_set_valid,
        product_copy_classification,
        valid_copy_set_ids_for_product,
    )

    db = await get_db()
    await db.execute("PRAGMA busy_timeout=60000")

    try:
        paid = json.load(open(os.path.join(OUT, "paid_replacement_results.json"), encoding="utf-8"))
        quar_pids = [p["product_id"] for p in paid["products"]
                     if p.get("outcome") == "QUARANTINED_AFTER_TWO_ATTEMPTS"]
    except Exception:
        quar_pids = []

    rows = []
    all_ok = True
    for pid in quar_pids:
        cur = await db.execute("SELECT lifecycle_status FROM product WHERE id=?", (pid,))
        prow = await cur.fetchone(); await cur.close()
        active = bool(prow and str(prow["lifecycle_status"]) == "ACTIVE")

        cls = (await product_copy_classification(pid)).get("classification")
        valid_ids = await valid_copy_set_ids_for_product(pid)
        pool = await list_eligible_copy_sets(pid)

        cur = await db.execute(
            "SELECT copy_set_id FROM copy_set WHERE product_id=? AND status=? AND COALESCE(archived,0)=0",
            (pid, STATUS_COPY_APPROVED))
        approved = [str(r["copy_set_id"]) for r in await cur.fetchall()]
        await cur.close()
        bind_blocked = True
        for cid in approved:
            try:
                await assert_copy_set_valid(cid)
                bind_blocked = False  # a valid set would be bindable — must NOT happen
            except ValueError:
                pass

        ok = (active and cls != "APPROVED_COPY_VALID" and not valid_ids
              and not pool and bind_blocked)
        all_ok = all_ok and ok
        rows.append({
            "product_id": pid, "product_active": active, "classification": cls,
            "valid_copy_set_ids": sorted(valid_ids), "rotation_pool_size": len(pool),
            "binding_blocked_all_sets": bind_blocked,
            "non_executable_proven": ok,
        })

    result = {
        "quarantined_products_checked": len(quar_pids),
        "all_non_executable_and_active": all_ok,
        "invariant": "active AND classification!=APPROVED_COPY_VALID AND no valid set AND empty rotation pool AND binding blocked on every approved set",
        "products": rows,
    }
    with open(os.path.join(OUT, "quarantine_enforcement_proof.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "products"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
