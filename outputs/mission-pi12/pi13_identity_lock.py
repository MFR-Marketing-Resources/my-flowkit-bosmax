#!/usr/bin/env python
"""PI-13 Phase 1 identity lock (read-only, deterministic). Emits pi13_identity_lock.json.
Binds each of the 116 residual products to its DB identity, extracts variant/size/form, and
flags name-collision groups for INVESTIGATION (never assumes duplicate without evidence)."""
import sqlite3, json, re, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
R = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
ids = [x["product_id"] for x in R["incomplete"]] + [x["product_id"] for x in R["review"]]

SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(ml|l|g|gram|gm|kg|mg|oz|tablet|tablets|pcs|pieces|helai|keping|set|bottle|bottles|sachet|sachets|capsule|capsules|caps|pack|packs|pair|pairs)\b", re.I)
VARIANT = re.compile(r"(#\s?\d+|shade\s?\w+|combo\s?\d+|\bset\b|\bsingle\b|\bdouble\b|\btriple\b|\btripple\b|\bduo\b|\bkombo\b|\b\d+\s?in\s?1\b)", re.I)
PROMO = re.compile(r"^\s*(\[[^\]]*\]\s*)+")  # strip leading [..] promo tags for normalization


def norm(name):
    s = PROMO.sub("", name or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# collision groups across ALL real products (not just 116) to detect canonical/duplicate candidates
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
allrows = {r["id"]: dict(r) for r in con.execute("SELECT id,product_display_name,raw_product_title,brand,shop_name,source_url,tiktok_product_url FROM product WHERE id IN (%s)" % ",".join("?" * len(frozen["real_ids"])), frozen["real_ids"])}
bykey = collections.defaultdict(list)
for pid, r in allrows.items():
    key = norm(r["raw_product_title"] or r["product_display_name"])[:60]
    if key:
        bykey[key].append(pid)

lock = []
for pid in ids:
    p = dict(con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone())
    title = p["raw_product_title"] or p["product_display_name"] or ""
    sizes = ["".join(m) for m in SIZE.findall(title)]
    variants = [m if isinstance(m, str) else m[0] for m in VARIANT.findall(title)]
    key = norm(title)[:60]
    group = [x for x in bykey.get(key, []) if x != pid]
    dup_assessment = "UNIQUE_NAME"
    dup_detail = []
    if group:
        dup_assessment = "INVESTIGATE_NAME_COLLISION"
        for g in group[:5]:
            gr = allrows[g]
            same_url = bool(gr["source_url"]) and gr["source_url"] == p["source_url"]
            same_tt = bool(gr["tiktok_product_url"]) and gr["tiktok_product_url"] == p["tiktok_product_url"]
            dup_detail.append({"other_id": g, "other_title": (gr["raw_product_title"] or "")[:70],
                               "same_source_url": same_url, "same_tiktok_url": same_tt,
                               "verdict": "SAME_LISTING" if (same_url or same_tt) else "DISTINCT_LISTING_needs_variant/image/seller_check"})
    lock.append({
        "product_id": pid,
        "full_db_raw_title": title,
        "display_name": p["product_display_name"],
        "brand": p["brand"],
        "shop_name": p["shop_name"],
        "category": p["category"], "subcategory": p["subcategory"], "type": p["type"],
        "variant_size_form": {"sizes": sorted(set(sizes)), "variants": sorted(set(v.strip() for v in variants))},
        "stored_source_url": p["source_url"],
        "stored_tiktok_url": p["tiktok_product_url"],
        "image_identity": {"image_url": p["image_url"], "local_image_path": p["local_image_path"], "media_id": p["media_id"]},
        "identity_confidence_db": "LOCKED (canonical DB record)",
        "canonical_duplicate_assessment": dup_assessment,
        "collision_detail": dup_detail,
        # web-side fields — filled during Phase 2 recovery, must be proven before any write:
        "external_source_title": None, "identity_match_rationale": None, "identity_match_confidence": None,
    })

col = collections.Counter(x["canonical_duplicate_assessment"] for x in lock)
out = {"cohort": len(lock), "unique_ids": len(set(x["product_id"] for x in lock)),
       "assessment_distribution": dict(col),
       "collision_groups_to_investigate": [x["product_id"] for x in lock if x["canonical_duplicate_assessment"] != "UNIQUE_NAME"],
       "identity_lock": lock}
json.dump(out, open(REPO / "outputs/mission-pi12/pi13_identity_lock.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("cohort:", out["cohort"], "unique:", out["unique_ids"])
print("assessment:", dict(col))
print("collision groups to investigate:", len(out["collision_groups_to_investigate"]))
for x in lock:
    if x["canonical_duplicate_assessment"] != "UNIQUE_NAME":
        print("  ", x["product_id"][:8], "|", (x["display_name"] or "")[:40], "| collisions:", [d["verdict"] for d in x["collision_detail"]])
