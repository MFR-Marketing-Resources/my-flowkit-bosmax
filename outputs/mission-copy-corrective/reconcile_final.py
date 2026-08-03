"""COPY-CORRECTIVE — authoritative FINAL reconciliation (read-only).

Recomputes, via the shared strict validity authority itself (not run counters),
the true strict-valid closure over the ACTIVE canonical eligible cohort, plus the
zero-tolerance PASS invariants. Run AFTER the paid replacement completes.
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
    from agent.models.copy_set import STATUS_COPY_APPROVED, serialize_copy_set
    from agent.services.copy_eligibility_service import copy_eligibility
    from agent.services.copy_set_validity_service import (
        detect_generic_copy,
        product_copy_classification,
    )

    db = await get_db()
    await db.execute("PRAGMA busy_timeout=60000")
    cur = await db.execute("SELECT id FROM product WHERE lifecycle_status='ACTIVE'")
    pids = [str(r["id"]) for r in await cur.fetchall()]
    await cur.close()

    buckets: dict = {}
    eligible = 0
    valid_products = []
    gap_products = []
    # zero-tolerance invariants over the sets that back a VALID product
    valid_with_generic = 0
    valid_missing_receipt = 0
    for pid in pids:
        elig = await copy_eligibility(pid)
        if not elig.get("eligible"):
            buckets["INELIGIBLE"] = buckets.get("INELIGIBLE", 0) + 1
            continue
        eligible += 1
        c = await product_copy_classification(pid)
        cls = c.get("classification")
        buckets[cls] = buckets.get(cls, 0) + 1
        if cls == "APPROVED_COPY_VALID":
            valid_products.append(pid)
            vid = c.get("valid_copy_set_id")
            cur = await db.execute("SELECT * FROM copy_set WHERE copy_set_id=?", (vid,))
            row = await cur.fetchone()
            await cur.close()
            if row:
                f = serialize_copy_set(dict(row))
                usp = [u for u in (f.get("usp_set") or []) if str(u).strip()]
                if detect_generic_copy(
                    hook=str(f.get("hook") or ""), subhook=str(f.get("subhook") or ""),
                    usp_list=usp, cta=str(f.get("cta") or ""),
                    product_name=c.get("product_name") or "",
                )["generic"]:
                    valid_with_generic += 1
                claim = json.loads(dict(row).get("claim_review_json") or "{}")
                if not (isinstance(claim.get("semantic_review"), dict) and claim["semantic_review"]):
                    valid_missing_receipt += 1
        else:
            gap_products.append({"product_id": pid, "classification": cls,
                                 "recommended_next_action": c.get("recommended_next_action")})

    strict_valid = buckets.get("APPROVED_COPY_VALID", 0)
    result = {
        "cohort_active_eligible": eligible,
        "products_strict_valid": strict_valid,
        "products_without_strict_valid": eligible - strict_valid,
        "classification_counts": buckets,
        "PASS_invariants": {
            "strict_valid_with_generic_filler": valid_with_generic,
            "strict_valid_missing_semantic_receipt": valid_missing_receipt,
        },
        "gap_products": gap_products,
    }
    with open(os.path.join(OUT, "final_reconciliation.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    # print headline only (gap list may be long)
    print(json.dumps({k: v for k, v in result.items() if k != "gap_products"}, ensure_ascii=False, indent=2))
    print(f"gap_products: {len(gap_products)}")


if __name__ == "__main__":
    asyncio.run(main())
