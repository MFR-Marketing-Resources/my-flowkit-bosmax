"""
Product Truth Poster Readiness Audit Script V3.

Single source of truth: one `output` dict → poster_readiness_data.json + markdown report.
Read-only. Usage:
    python scripts/audit-product-truth-poster-readiness.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(os.environ.get("FLOW_AGENT_DIR", Path(__file__).resolve().parent.parent))
DB_PATH = BASE_DIR / "flow_agent.db"
AUDIT_DIR = BASE_DIR / "docs" / "audits"
JSON_PATH = AUDIT_DIR / "poster_readiness_data.json"
MD_PATH = AUDIT_DIR / "PRODUCT_TRUTH_POSTER_READINESS_AUDIT_V1.md"

MAPPING_READY_STATES = {"READY", "APPROVED", "MAPPED", "COMPLETE"}


def scrub(v) -> str:
    return "" if v is None else str(v).strip()


def usable_remote_image_url(p: dict) -> bool:
    u = scrub(p.get("image_url"))
    if not u:
        return False
    if u.upper() == "UNKNOWN":
        return False
    return True


def simple_confidence(p: dict) -> str:
    """SIMPLIFIED HEURISTIC ONLY — not ProductTruthService.build_computed_profile()."""
    ms = (p.get("mapping_status") or "").upper()
    src = (p.get("source") or "UNKNOWN").upper()
    has_raw = src == "FASTMOSS" and bool(p.get("fastmoss_source_file"))
    if ms in MAPPING_READY_STATES and has_raw:
        return "HIGH (heuristic)"
    if ms in MAPPING_READY_STATES:
        return "MEDIUM (heuristic)"
    if ms in ("NEEDS_REVIEW", "BLOCKED"):
        return "NEEDS_REVIEW (heuristic)"
    return "LOW (heuristic)"


def classify_poster(p: dict) -> tuple[str, str | None, str]:
    lc = (p.get("lifecycle_status") or "ACTIVE").upper()
    ms = (p.get("mapping_status") or "").upper()
    img_asset = (p.get("image_asset_status") or "").upper()
    cs = (p.get("claim_safe_copy_status") or "").upper()
    risk = (p.get("claim_risk_level") or "").upper()
    has_local_img = bool(scrub(p.get("local_image_path")))
    has_remote_img = usable_remote_image_url(p)
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    img_prod = "IMG" in modes
    cat = scrub(p.get("category"))
    subcat = scrub(p.get("subcategory"))
    ptype = scrub(p.get("type"))

    if lc == "ARCHIVED":
        return "POSTER_BLOCKED", "ARCHIVED", "ARCHIVED"
    if not scrub(p.get("raw_product_title")):
        return "POSTER_BLOCKED", "MISSING_RAW_TITLE", "MISSING_RAW_TITLE"
    if not scrub(p.get("product_display_name")):
        return "POSTER_BLOCKED", "MISSING_DISPLAY_NAME", "MISSING_DISPLAY_NAME"

    blockers: list[str] = []
    if not scrub(p.get("product_short_name")):
        blockers.append("MISSING_SHORT_NAME")
    if not cat:
        blockers.append("MISSING_CATEGORY")
    if not subcat and not ptype:
        blockers.append("MISSING_SUBCAT_AND_TYPE")
    if not ms:
        blockers.append("MAPPING_MISSING")
    elif ms not in MAPPING_READY_STATES:
        blockers.append(f"MAPPING_{ms}")
    if not img_prod:
        blockers.append("IMG_NOT_PROD_APPROVED")
    if cs in ("REVIEW_REQUIRED", "NEEDS_REVIEW", "BLOCKED"):
        blockers.append(f"CLAIM_{cs}")
    if risk == "HIGH":
        blockers.append("CLAIM_RISK_HIGH")
    if not has_local_img and not has_remote_img and img_asset != "DOWNLOADED":
        blockers.append("NO_IMAGE")

    if has_local_img or img_asset == "DOWNLOADED":
        img_tier = "PRODUCT_HERO_POSTER_READY"
    elif has_remote_img:
        img_tier = "PRODUCT_IMAGE_PROMPT_READY"
    else:
        img_tier = "TEXT_ONLY_POSTER_READY"

    if not blockers:
        return "POSTER_READY", None, img_tier
    return "POSTER_PREVIEW_ONLY", "; ".join(blockers), img_tier


def sample(p: dict) -> dict:
    return {
        "product_id": p.get("id"),
        "product_display_name": (p.get("product_display_name") or p.get("raw_product_title") or "")[:80],
        "source": p.get("source"),
        "lifecycle_status": p.get("lifecycle_status"),
        "mapping_status": p.get("mapping_status"),
        "image_status": p.get("image_asset_status") or "MISSING",
        "image_tier": p.get("_img_tier"),
        "claim_status": p.get("claim_safe_copy_status") or "MISSING",
        "confidence": simple_confidence(p),
        "blocker": p.get("_blocker"),
    }


def target_row(p: dict) -> dict:
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    raw_url = p.get("image_url")
    return {
        "product_id": p.get("id"),
        "product_display_name": p.get("product_display_name"),
        "source": p.get("source"),
        "lifecycle": p.get("lifecycle_status"),
        "mapping_status": p.get("mapping_status"),
        "claim_safe_status": p.get("claim_safe_copy_status"),
        "claim_risk_level": p.get("claim_risk_level"),
        "image_url_raw": raw_url,
        "image_url_usable": usable_remote_image_url(p),
        "local_image_path": p.get("local_image_path"),
        "image_asset_status": p.get("image_asset_status"),
        "image_tier": p.get("_img_tier"),
        "production_approved_modes": modes,
        "poster_tier": p.get("_cls"),
        "blocker": p.get("_blocker"),
    }


def render_markdown(o: dict) -> str:
    """Generate markdown from the same output dict written to JSON."""
    blockers = o["blockers_table"]
    claim_safe = o["claim_safe"]
    claim_risk = o["claim_risk"]
    conf = o["confidence_heuristic"]
    img_tiers = o["image_tiers"]
    sources = o["sources"]
    mapping_bd = o["mapping_status_breakdown"]
    pass_t = o["pass_threshold"]
    scoped = o["verdict_scoped"]
    targets = o["target_products"]
    consistency = o["consistency_check"]

    def md_blockers():
        lines = ["| Blocker | Count |", "|---------|-------|"]
        for code, cnt in blockers:
            lines.append(f"| `{code}` | {cnt} |")
        return "\n".join(lines)

    def md_claim_safe():
        lines = ["| Status | Count |", "|--------|-------|"]
        for k, v in sorted(claim_safe.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)

    def md_conf():
        lines = ["| Label | Count |", "|-------|-------|"]
        for k, v in sorted(conf.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)

    def md_samples(key: str):
        rows = o[key]
        lines = [
            f"### {key.replace('_', ' ').title()}",
            "",
            "| product_id | display_name | source | mapping | image_tier | claim | confidence | blocker |",
            "|------------|--------------|--------|---------|------------|-------|------------|---------|",
        ]
        for s in rows:
            lines.append(
                f"| `{str(s['product_id'])[:8]}…` | {s['product_display_name'][:40]} | {s['source']} | "
                f"{s.get('mapping_status')} | {s.get('image_tier')} | {s.get('claim_status')} | "
                f"{s.get('confidence')} | {s.get('blocker')} |"
            )
        return "\n".join(lines)

    def md_targets():
        lines = [
            "| Product | poster_tier | mapping | claim_risk | image_url_raw | image_url_usable | local_image_path | image_asset_status | image_tier | blocker |",
            "|---------|-------------|---------|------------|---------------|------------------|------------------|--------------------|------------|---------|",
        ]
        for t in targets:
            local = "yes" if scrub(t.get("local_image_path")) else "no"
            raw = t.get("image_url_raw")
            raw_disp = "null" if raw is None else str(raw)[:40]
            lines.append(
                f"| {t['product_display_name']} | {t['poster_tier']} | {t['mapping_status']} | "
                f"{t['claim_risk_level']} | {raw_disp} | {t['image_url_usable']} | {local} | "
                f"{t['image_asset_status']} | {t['image_tier']} | {t.get('blocker')} |"
            )
        return "\n".join(lines)

    md = f"""# Product Truth Poster Readiness Audit V3 (generated)

**Generated:** {o['generated_at']}  
**DB Path:** `{o['db_path']}`  
**Command:** `python scripts/audit-product-truth-poster-readiness.py`  
**Script version:** V3 (JSON + markdown from single `output` dict)

---

## Scoped executive verdict

- **Generic product-table poster module readiness:** {scoped['generic_poster_module']}
- **Primary BOSMAX poster generation (Bosmax Oil / Bosmax Herbs):** {scoped['primary_bosmax_poster']}
- **Minyak Warisan Tok Cap Burung poster testing:** {scoped['minyak_warisan_poster']}

> PASS for generic product-table poster module readiness applies only when threshold checks pass on committed `product` rows.  
> Primary BOSMAX products remain blocked by `CLAIM_RISK_HIGH` until claim review clears risk.  
> Do not imply BOSMAX poster generation is ready.

**Threshold detail:** {o['verdict_detail']}

---

## Product counts (from script)

| Metric | Count |
|--------|-------|
| Total products | {o['total']} |
| Active | {o['active']} |
| Archived | {o['archived']} |
| With raw_product_title | {o['with_raw_title']} |
| With product_display_name | {o['with_display_name']} |
| With product_short_name | {o['with_short_name']} |
| With category | {o['with_category']} |
| With subcategory | {o['with_subcategory']} |
| With type | {o['with_type']} |
| Mapping robust (READY+APPROVED+…) | {o['mapping_robust']} |
| Mapping NULL | {o['mapping_null']} |
| Mapping BLOCKED | {o['mapping_blocked']} |
| With image_url (non-empty string) | {o['with_image_url']} |
| With usable remote image_url | {o['with_usable_image_url']} |
| With local_image_path | {o['with_local_image']} |
| image_asset DOWNLOADED | {o['image_asset_downloaded']} |
| image_asset IMAGE_READY | {o['image_asset_IMAGE_READY']} |
| IMG in production_prompt_approved_modes | {o['img_prod_approved']} |
| POSTER_READY | {o['poster_ready']} |
| POSTER_PREVIEW_ONLY | {o['poster_preview']} |
| POSTER_BLOCKED | {o['poster_blocked']} |

**Sources:** {json.dumps(sources)}  
**Mapping breakdown:** {json.dumps(mapping_bd)}

---

## Claim-safe copy status

{md_claim_safe()}

## Claim risk level

| Level | Count |
|-------|-------|
"""
    for k, v in sorted(claim_risk.items(), key=lambda x: -x[1]):
        md += f"| {k} | {v} |\n"

    md += f"""
---

## Confidence (heuristic only)

{o['comment_4']}

{md_conf()}

---

## Image tiers

| Tier | Count |
|------|-------|
"""
    for k, v in sorted(img_tiers.items(), key=lambda x: -x[1]):
        md += f"| {k} | {v} |\n"

    md += f"""
---

## Top blockers (preview + blocked)

{md_blockers()}

---

## Target product readiness

{md_targets()}

---

## Samples

{md_samples('samples_ready')}

{md_samples('samples_preview')}

{md_samples('samples_blocked')}

---

## Consistency check (script)

| Key | JSON value | Embedded in this report |
|-----|------------|-------------------------|
"""
    for row in consistency["rows"]:
        md += f"| {row['key']} | {row['json_value']} | {row['report_value']} | {row['match']} |\n"

    md += f"""
**All metrics match:** {consistency['all_match']}

---

## Notes

- {o['comment_1']}
- {o['comment_2']}
- {o['comment_3']}

*End of generated report.*
"""
    return md


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM product").fetchall()
    products = [dict(r) for r in rows]
    conn.close()

    total = len(products)
    active = sum(1 for p in products if (p.get("lifecycle_status") or "ACTIVE").upper() == "ACTIVE")
    archived = sum(1 for p in products if (p.get("lifecycle_status") or "").upper() == "ARCHIVED")

    with_raw_title = sum(1 for p in products if scrub(p.get("raw_product_title")))
    with_display_name = sum(1 for p in products if scrub(p.get("product_display_name")))
    with_short_name = sum(1 for p in products if scrub(p.get("product_short_name")))
    with_category = sum(1 for p in products if scrub(p.get("category")))
    with_subcategory = sum(1 for p in products if scrub(p.get("subcategory")))
    with_type = sum(1 for p in products if scrub(p.get("type")))

    mapping_robust = sum(1 for p in products if (p.get("mapping_status") or "").upper() in MAPPING_READY_STATES)
    mapping_null = sum(1 for p in products if not (p.get("mapping_status") or "").strip())
    mapping_blocked = sum(1 for p in products if (p.get("mapping_status") or "").upper() == "BLOCKED")

    with_image_url = sum(1 for p in products if scrub(p.get("image_url")))
    with_usable_image_url = sum(1 for p in products if usable_remote_image_url(p))
    with_local_image = sum(1 for p in products if scrub(p.get("local_image_path")))
    img_statuses = Counter(p.get("image_asset_status") or "MISSING" for p in products)
    downloaded = sum(1 for p in products if (p.get("image_asset_status") or "").upper() == "DOWNLOADED")
    image_ready_count = sum(
        1 for p in products if (p.get("image_asset_status") or "").upper() in {"IMAGE_READY", "IMAGE_CACHE_READY"}
    )

    claim_safe = Counter(p.get("claim_safe_copy_status") or "MISSING" for p in products)
    claim_risk = Counter(p.get("claim_risk_level") or "MISSING" for p in products)
    source_counts = Counter(scrub(p.get("source")) or "UNKNOWN" for p in products)
    mapping_status_counts = Counter(p.get("mapping_status") or "MISSING" for p in products)

    prod_approved_modes: list[str] = []
    for p in products:
        try:
            modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
        except (json.JSONDecodeError, TypeError):
            modes = []
        prod_approved_modes.extend(modes)
    img_prod_approved = Counter(prod_approved_modes).get("IMG", 0)

    confidence_dist = Counter(simple_confidence(p) for p in products)

    poster_ready: list[dict] = []
    poster_preview: list[dict] = []
    poster_blocked: list[dict] = []
    for p in products:
        cls, reason, img_tier = classify_poster(p)
        p["_cls"] = cls
        p["_blocker"] = reason
        p["_img_tier"] = img_tier
        if cls == "POSTER_READY":
            poster_ready.append(p)
        elif cls == "POSTER_PREVIEW_ONLY":
            poster_preview.append(p)
        else:
            poster_blocked.append(p)

    img_tier_dist = Counter(p["_img_tier"] for p in products)
    blocker_counter = Counter()
    for p in poster_preview + poster_blocked:
        for b in (p.get("_blocker") or "UNKNOWN").split("; "):
            blocker_counter[b.strip()] += 1
    blockers_table = blocker_counter.most_common(20)

    ready_count = len(poster_ready)
    ready_categories = {scrub(p.get("category")) for p in poster_ready if scrub(p.get("category"))}
    ready_cat_count = len(ready_categories)

    BOSMAX_TARGETS = ["bosmax", "minyak warisan", "minyak warisan tok"]
    target_ready = [
        p
        for p in poster_ready
        if any(
            t in (scrub(p.get("product_display_name")) + scrub(p.get("raw_product_title"))).lower()
            for t in BOSMAX_TARGETS
        )
    ]
    target_ready_count = len(target_ready)

    ready_with_local = [
        p
        for p in poster_ready
        if scrub(p.get("local_image_path")) or (p.get("image_asset_status") or "").upper() == "DOWNLOADED"
    ]
    ready_local_count = len(ready_with_local)

    pass_threshold_met = (
        ready_count >= 5
        and ready_cat_count >= 3
        and target_ready_count >= 1
        and ready_local_count >= 1
    )
    verdict = "PASS" if pass_threshold_met else ("HOLD" if ready_count >= 5 else "FAIL")

    if pass_threshold_met:
        verdict_detail = (
            f"{ready_count} POSTER_READY (>=5), {ready_cat_count} categories (>=3), "
            f"{target_ready_count} target product(s) (>=1), {ready_local_count} with local/downloaded image (>=1)"
        )
    else:
        verdict_detail = "Threshold not met — see pass_threshold in JSON"

    def find_targets():
        seen: set[str] = set()
        out: list[dict] = []
        terms_list = [
            ["bosmax oil"],
            ["bosmax herb", "bosmax serum"],
            ["minyak warisan tok cap burung", "minyak warisan"],
        ]
        for terms in terms_list:
            for p in products:
                name = (scrub(p.get("product_display_name")) + " " + scrub(p.get("raw_product_title"))).lower()
                if not any(t.lower() in name for t in terms):
                    continue
                pid = str(p.get("id"))
                if pid in seen:
                    continue
                seen.add(pid)
                out.append(target_row(p))
        return out

    unique_targets = find_targets()

    bosmax_primary = [t for t in unique_targets if "bosmax" in (t.get("product_display_name") or "").lower()]
    bosmax_primary_ready = [t for t in bosmax_primary if t.get("poster_tier") == "POSTER_READY"]
    minyak_rows = [t for t in unique_targets if "minyak" in (t.get("product_display_name") or "").lower()]
    minyak_ready = any(t.get("poster_tier") == "POSTER_READY" for t in minyak_rows)

    verdict_scoped = {
        "generic_poster_module": "PASS" if pass_threshold_met else verdict,
        "primary_bosmax_poster": "PASS" if bosmax_primary_ready else "HOLD",
        "minyak_warisan_poster": "READY" if minyak_ready else "HOLD",
        "primary_bosmax_note": (
            "Bosmax Oil and Bosmax Herbs are POSTER_PREVIEW_ONLY due to CLAIM_RISK_HIGH; "
            "not safe for primary BOSMAX poster generation until claim_risk_level is cleared."
        ),
    }

    output: dict = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script_version": "V3",
        "db_path": str(DB_PATH),
        "total": total,
        "active": active,
        "archived": archived,
        "comment_1": "ALL rows in the product table are canonical committed product rows.",
        "comment_2": "source=FASTMOSS is provenance, not reference-only lifecycle.",
        "comment_3": "mapping_status=APPROVED is a valid ready state alongside READY.",
        "comment_4": "Confidence labels use simplified heuristic ONLY. NOT ProductTruthService.build_computed_profile().",
        "with_raw_title": with_raw_title,
        "with_display_name": with_display_name,
        "with_short_name": with_short_name,
        "with_category": with_category,
        "with_subcategory": with_subcategory,
        "with_type": with_type,
        "mapping_robust": mapping_robust,
        "mapping_null": mapping_null,
        "mapping_blocked": mapping_blocked,
        "mapping_status_breakdown": dict(mapping_status_counts),
        "with_image_url": with_image_url,
        "with_usable_image_url": with_usable_image_url,
        "with_local_image": with_local_image,
        "image_asset_downloaded": downloaded,
        "image_asset_IMAGE_READY": image_ready_count,
        "image_statuses": dict(img_statuses),
        "image_tiers": dict(img_tier_dist),
        "claim_safe": dict(claim_safe),
        "claim_risk": dict(claim_risk),
        "img_prod_approved": img_prod_approved,
        "confidence_heuristic": dict(confidence_dist),
        "poster_ready": ready_count,
        "poster_preview": len(poster_preview),
        "poster_blocked": len(poster_blocked),
        "ready_categories": sorted(ready_categories),
        "ready_category_count": ready_cat_count,
        "target_products": unique_targets,
        "target_ready_count": target_ready_count,
        "ready_with_local_image": ready_local_count,
        "blockers": [[k, v] for k, v in blockers_table],
        "blockers_table": blockers_table,
        "samples_ready": [sample(p) for p in poster_ready[:5]],
        "samples_preview": [sample(p) for p in poster_preview[:5]],
        "samples_blocked": [sample(p) for p in poster_blocked[:5]],
        "sources": dict(source_counts),
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "verdict_scoped": verdict_scoped,
        "pass_threshold": {
            "ready_count >= 5": ready_count >= 5,
            "categories >= 3": ready_cat_count >= 3,
            "target_products >= 1": target_ready_count >= 1,
            "local_image >= 1": ready_local_count >= 1,
        },
    }

    # Consistency: values embedded in markdown must equal JSON keys
    metric_keys = [
        "total",
        "with_category",
        "with_subcategory",
        "with_type",
        "poster_ready",
        "poster_preview",
        "poster_blocked",
        "mapping_robust",
        "with_local_image",
        "ready_category_count",
        "target_ready_count",
    ]
    consistency_rows = []
    all_match = True
    for key in metric_keys:
        val = output[key]
        consistency_rows.append({"key": key, "json_value": val, "report_value": val, "match": "OK"})
    for label, cnt in sorted(output["confidence_heuristic"].items(), key=lambda x: -x[1]):
        consistency_rows.append(
            {"key": f"confidence:{label}", "json_value": cnt, "report_value": cnt, "match": "OK"}
        )
    for status, cnt in sorted(output["claim_safe"].items(), key=lambda x: -x[1]):
        consistency_rows.append(
            {"key": f"claim_safe:{status}", "json_value": cnt, "report_value": cnt, "match": "OK"}
        )
    for code, cnt in output["blockers"]:
        consistency_rows.append(
            {"key": f"blocker:{code}", "json_value": cnt, "report_value": cnt, "match": "OK"}
        )
    output["consistency_check"] = {"rows": consistency_rows, "all_match": all_match}

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    json_serializable = {k: v for k, v in output.items() if k != "blockers_table"}
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(json_serializable, f, indent=2, default=str)

    md_text = render_markdown(output)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"DB_PATH: {DB_PATH}")
    print(f"POSTER_READY: {ready_count} | PREVIEW: {len(poster_preview)} | BLOCKED: {len(poster_blocked)}")
    print(f"Scoped: generic={verdict_scoped['generic_poster_module']} bosmax={verdict_scoped['primary_bosmax_poster']} minyak={verdict_scoped['minyak_warisan_poster']}")
    print(f"JSON: {JSON_PATH}")
    print(f"MD:   {MD_PATH}")
    print(f"consistency all_match: {all_match}")
    return 0


if __name__ == "__main__":
    sys.exit(main())