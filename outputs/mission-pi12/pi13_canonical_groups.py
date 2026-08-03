#!/usr/bin/env python
"""PI-13 B-02: exact canonical connected-components (read-only).
Graph over ALL 651 real products; edge = shared non-empty source_url OR tiktok_product_url.
Union-find -> components. For each component containing >=1 residual-debt product, emit the full
group: members, PI class, title, variant/size, recommended canonical, FK/copy references, disposition.
This yields the EXACT canonical-group count and the true research burden (not row-counts)."""
import sqlite3, json, re, collections, difflib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
R = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
DEBT = set([x["product_id"] for x in R["incomplete"]] + [x["product_id"] for x in R["review"]])
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
REAL = frozen["real_ids"]
SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(ml|l|g|gram|gm|kg|mg|oz|tablet|tablets|pcs|helai|set|bottle|bottles|sachet|capsule|caps|pack|pair)\b", re.I)


def pi_class(pid):
    r = con.execute("SELECT readiness_status,completeness_score FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    if not r:
        return "MISSING"
    if r["readiness_status"] == "READY_WITH_GOVERNED_ABSENCE":
        return "GA"
    if r["completeness_score"] and r["completeness_score"] >= 1.0:
        return "FC"
    return "LEGACY"


rows = {r["id"]: dict(r) for r in con.execute("SELECT id,product_display_name,raw_product_title,brand,shop_name,source_url,tiktok_product_url FROM product WHERE id IN (%s)" % ",".join("?" * len(REAL)), REAL)}

# union-find
parent = {pid: pid for pid in rows}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x


def union(a, b):
    parent[find(a)] = find(b)


for url_field in ("source_url", "tiktok_product_url"):
    groups = collections.defaultdict(list)
    for pid, r in rows.items():
        if r[url_field]:
            groups[r[url_field]].append(pid)
    for _, members in groups.items():
        for m in members[1:]:
            union(members[0], m)

comp = collections.defaultdict(list)
for pid in rows:
    comp[find(pid)].append(pid)

# tables with a product_id FK (for reference counts)
fk_tables = []
for t in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
    if "product_id" in cols:
        fk_tables.append(t)


def fk_refs(pid):
    out = {}
    for t in fk_tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE product_id=?", (pid,)).fetchone()[0]
        if n:
            out[t] = n
    return out


def sizes(pid):
    return sorted(set("".join(m) for m in SIZE.findall(rows[pid]["raw_product_title"] or "")))


out_groups = []
multi = {k: v for k, v in comp.items() if len(v) > 1 and any(p in DEBT for p in v)}
for gid, members in multi.items():
    cls = {p: pi_class(p) for p in members}
    grounded = [p for p in members if cls[p] in ("GA", "FC")]
    canonical = grounded[0] if grounded else max(members, key=lambda p: len(rows[p]["raw_product_title"] or ""))
    titles = {p: (rows[p]["raw_product_title"] or "") for p in members}
    base = titles[canonical]
    out_groups.append({
        "duplicate_group_id": gid[:8],
        "size": len(members),
        "members": [{"product_id": p, "pi_class": cls[p], "in_debt": p in DEBT,
                     "title": titles[p][:60], "sizes": sizes(p),
                     "shared_source_url": rows[p]["source_url"], "shared_tiktok_url": rows[p]["tiktok_product_url"],
                     "title_sim_to_canonical": round(difflib.SequenceMatcher(None, base.lower(), titles[p].lower()).ratio(), 3),
                     "fk_refs": fk_refs(p)} for p in members],
        "recommended_canonical_id": canonical,
        "canonical_pi_class": cls[canonical],
        "debt_members": [p for p in members if p in DEBT],
        "disposition": ("COPY_FROM_CANONICAL" if grounded else "MERGE_BOTH_DEBT_then_research_canonical"),
    })

debt_in_groups = set(p for g in out_groups for p in g["debt_members"])
debt_unique = sorted(DEBT - debt_in_groups)
research_canonicals = [g["recommended_canonical_id"] for g in out_groups if not [m for m in g["members"] if m["pi_class"] in ("GA", "FC")]]
summary = {
    "total_components_with_debt": len(out_groups),
    "debt_products_in_groups": len(debt_in_groups),
    "debt_products_unique_no_group": len(debt_unique),
    "groups_with_grounded_canonical": sum(1 for g in out_groups if g["canonical_pi_class"] in ("GA", "FC")),
    "groups_all_debt_need_research": len(research_canonicals),
    "EXACT_web_research_burden": len(debt_unique) + len(research_canonicals),
    "unique_no_group_ids": debt_unique,
}
json.dump({"summary": summary, "groups": out_groups}, open(REPO / "outputs/mission-pi12/pi13_canonical_groups.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(summary, indent=1))
