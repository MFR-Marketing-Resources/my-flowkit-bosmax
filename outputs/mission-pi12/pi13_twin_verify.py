#!/usr/bin/env python
"""PI-13 twin verification (read-only). For each COPY_FROM_GROUNDED_TWIN candidate, confirm the
shared URL is PRODUCT-SPECIFIC and the debt row's title matches the grounded twin's title, so we
never copy intelligence across a coincidental shop-level URL match (Blocker-1 safety)."""
import sqlite3, json, re, difflib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
DA = json.load(open(REPO / "outputs/mission-pi12/pi13_duplicate_analysis.json", encoding="utf-8"))
PROMO = re.compile(r"(\[[^\]]*\]|【[^】]*】|\([^)]*\))")
PRODUCT_URL = re.compile(r"/product/\d+|/products/|-i\d{6,}|/item/|itemid=|product_id=", re.I)


def norm(s):
    s = PROMO.sub(" ", s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title(pid):
    r = con.execute("SELECT raw_product_title,product_display_name FROM product WHERE id=?", (pid,)).fetchone()
    return r["raw_product_title"] or r["product_display_name"] or ""


verified, rejected = [], []
for d in DA["collision_detail"]:
    pid = d["product_id"]
    tw = next((p for p in d["partners"] if p["class"] in ("GA", "FC")), None)
    if not tw:
        continue
    url = d["shared_url"] or ""
    url_specific = bool(PRODUCT_URL.search(url))
    t1, t2 = norm(title(pid)), norm(title(tw["id"]))
    sim = difflib.SequenceMatcher(None, t1, t2).ratio()
    # verified if titles are near-identical (same listing import) OR product-specific URL + good title match
    ok = (sim >= 0.95) or (url_specific and sim >= 0.60)
    rec = {"product_id": pid, "twin_id": tw["id"], "twin_class": tw["class"], "shared_url": url,
           "url_product_specific": url_specific, "title_similarity": round(sim, 3),
           "basis": ("near_identical_title" if sim >= 0.95 else ("product_url+title" if ok else "insufficient")),
           "debt_title": title(pid)[:70], "twin_title": title(tw["id"])[:70]}
    (verified if ok else rejected).append(rec)

print("COPY_FROM_GROUNDED_TWIN verification:")
print("  VERIFIED (product-specific URL + title sim>=0.60):", len(verified))
print("  REJECTED (needs manual/other path):", len(rejected))
from collections import Counter
print("  verified basis:", dict(Counter(r["basis"] for r in verified)))
print("\n-- REJECTED (will NOT auto-copy; route to research/manual) --")
for r in rejected:
    print("  %s sim=%.2f url=%s" % (r["product_id"][:8], r["title_similarity"], (r["shared_url"] or "")[:60]))
json.dump({"verified": verified, "rejected": rejected}, open(REPO / "outputs/mission-pi12/pi13_twin_verify.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote pi13_twin_verify.json  (verified twins:", len(verified), ")")
