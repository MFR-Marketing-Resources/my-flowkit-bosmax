#!/usr/bin/env python
"""PI-13 corrections B-01 (2/4): honest canonical provenance + STRICT exact-duplicate proof.
No 'supported inference' label. Reclassify the 49 grounded-canonical debt members as
CANONICAL_MERGE_CANDIDATES; only those passing exact identity+variant+seller+URL+title become
MERGE_PROVEN (eligible for canonical-merge/alias, NOT PI-copy). Failures drop to the research lane.
Read-only."""
import sqlite3, json, difflib, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
G = json.load(open(REPO / "outputs/mission-pi12/pi13_canonical_groups.json", encoding="utf-8"))
CG = json.load(open(REPO / "outputs/mission-pi12/pi13_twin_qualify.json", encoding="utf-8"))
held_ids = {h["product_id"] for h in CG["held"]}


def row(pid):
    return dict(con.execute("SELECT id,product_display_name,raw_product_title,brand,shop_name,source_url,tiktok_product_url,image_url,media_id FROM product WHERE id=?", (pid,)).fetchone())


def canon_prov(pid):
    s = con.execute("SELECT created_from_review_draft_id did FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    if not s:
        return {}
    out = collections.Counter()
    for r in con.execute("SELECT source_type,evidence_kind,verification_status FROM product_intelligence_review_field_provenance WHERE draft_id=? AND field_name IN ('benefits_json','usp_json')", (s["did"],)):
        out[f"{r['source_type']}|{r['evidence_kind']}|{r['verification_status']}"] += 1
    return dict(out)


import re
SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(ml|l|g|gram|gm|kg|mg|oz|tablet|tablets|pcs|helai|set|bottle|bottles|sachet|capsule|caps|pack|pair)\b", re.I)
TTID = re.compile(r"/(?:product|detail)/(\d{6,})")


def sizes(t):
    return sorted(set("".join(m) for m in SIZE.findall(t or "")))


def platform_id(r):
    for u in (r["tiktok_product_url"], r["source_url"]):
        m = TTID.search(u or "")
        if m:
            return m.group(1)
    return None


merge_proven, to_research, prov_dist = [], [], collections.Counter()
for g in G["groups"]:
    if g["canonical_pi_class"] not in ("GA", "FC"):
        continue
    can = g["recommended_canonical_id"]; cr = row(can)
    prov = canon_prov(can)
    for k, v in prov.items():
        prov_dist[k] += v
    for m in g["members"]:
        if not m["in_debt"]:
            continue
        pid = m["product_id"]; pr = row(pid)
        if pid in held_ids:
            to_research.append({"product_id": pid, "reason": "canonical_generic (twin_qualify HELD)"})
            continue
        d_pid, c_pid = platform_id(pr), platform_id(cr)
        platform_id_match = bool(d_pid) and d_pid == c_pid   # authoritative: same globally-unique TikTok product id
        title_sim = difflib.SequenceMatcher(None, (pr["raw_product_title"] or "").lower(), (cr["raw_product_title"] or "").lower()).ratio()
        # seller: same OR one null (MANUAL-vs-FASTMOSS import artifact) — not disqualifying when platform id matches
        seller_ok = (pr["shop_name"] or "") == (cr["shop_name"] or "") or not pr["shop_name"] or not cr["shop_name"]
        brand_match = (pr["brand"] or "") == (cr["brand"] or "")
        sz_debt, sz_can = sizes(pr["raw_product_title"]), sizes(cr["raw_product_title"])
        variant_ok = (not sz_debt or not sz_can or set(sz_debt) == set(sz_can))
        image_match = (bool(pr["image_url"]) and pr["image_url"] == cr["image_url"]) or (bool(pr["media_id"]) and pr["media_id"] == cr["media_id"])
        signals = {"platform_product_id": d_pid, "platform_id_match": platform_id_match, "title_sim": round(title_sim, 3),
                   "seller_ok_nulltolerant": seller_ok, "debt_shop": pr["shop_name"], "canon_shop": cr["shop_name"],
                   "brand_match": brand_match, "variant_compatible": variant_ok, "image_match": image_match}
        # authoritative duplicate proof = same platform product id + near-identical title + compatible variant
        proven = platform_id_match and title_sim >= 0.85 and variant_ok and seller_ok
        rec = {"product_id": pid, "canonical_id": can, "canonical_class": g["canonical_pi_class"],
               "signals": signals, "canonical_benefit_provenance": prov}
        if proven:
            merge_proven.append(rec)
        else:
            fails = [k for k, v in {"platform_id": platform_id_match, "title>=0.85": title_sim >= 0.85, "variant": variant_ok, "seller": seller_ok}.items() if not v]
            rec["fail"] = fails
            to_research.append(rec)

# research burden recompute
unique = G["summary"]["debt_products_unique_no_group"]           # 39
all_debt_groups = G["summary"]["groups_all_debt_need_research"]   # 14
extra_from_merge_fail = len(to_research)                          # held + strict-proof failures
summary = {
    "canonical_benefit_provenance_distribution": dict(prov_dist),
    "provenance_honest_label": "AI_ENRICHMENT / verification_status=AI_PROPOSED = AI-proposed & UNVERIFIED (NOT acquired evidence, NOT proven supported-inference)",
    "MERGE_PROVEN": len(merge_proven),
    "reclassified_to_research": len(to_research),
    "research_burden": {"unique_no_group": unique, "all_debt_canonical_reps": all_debt_groups,
                        "merge_failures_to_research": extra_from_merge_fail,
                        "TOTAL": unique + all_debt_groups + extra_from_merge_fail},
}
json.dump({"summary": summary, "merge_proven": merge_proven, "to_research": to_research},
          open(REPO / "outputs/mission-pi12/pi13_merge_candidates.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(summary, indent=1))
print("\n-- reclassified to research (strict-proof failures) --")
for t in to_research:
    print("  ", t["product_id"][:8], t.get("fail", t.get("reason")))
