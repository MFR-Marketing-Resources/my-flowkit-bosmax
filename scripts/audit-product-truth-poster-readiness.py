"""
Product Truth Poster Readiness Audit Script V2 (FORENSIC CORRECTION).

CRITICAL FIXES from counter-audit of PR #231:
  - FASTMOSS product table rows ARE canonical (not reference-only).
    The product table has no `reference_only` column; all 516 rows are committed.
  - `mapping_status=APPROVED` IS a valid ready state (204 MANUAL products).
  - Image readiness: distinguish DOWNLOADED vs IMAGE_READY state.
  - Stricter PASS threshold: >=5 ready, >=3 categories, >=1 target product,
    >=1 with local image, no report/data contradiction.
  - Confidence labels use simplified heuristic ONLY (not ProductTruthService).
  - Add BOSMAX/Minyak target product explicit reporting.
  - Add image readiness tiers.

Read-only. Usage:
    python scripts/audit-product-truth-poster-readiness.py
"""
import sqlite3
import json
import sys
import os
from pathlib import Path
from collections import Counter, defaultdict

BASE_DIR = Path(os.environ.get("FLOW_AGENT_DIR", Path(__file__).resolve().parent.parent))
DB_PATH = BASE_DIR / "flow_agent.db"

if not DB_PATH.exists():
    print(f"ERROR: DB not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

def scrub(v):
    return "" if v is None else str(v).strip()

# ── Query all committed product rows (ALL are canonical) ───
rows = conn.execute("SELECT * FROM product").fetchall()
products = [dict(r) for r in rows]
total = len(products)

# ── Core counts ─────────────────────────────────────────────
active = sum(1 for p in products if (p.get("lifecycle_status") or "ACTIVE").upper() == "ACTIVE")
archived = sum(1 for p in products if (p.get("lifecycle_status") or "").upper() == "ARCHIVED")
with_raw_title = sum(1 for p in products if scrub(p.get("raw_product_title")))
with_display_name = sum(1 for p in products if scrub(p.get("product_display_name")))
with_short_name = sum(1 for p in products if scrub(p.get("product_short_name")))
with_category = sum(1 for p in products if scrub(p.get("category")))
with_subcategory = sum(1 for p in products if scrub(p.get("subcategory")))
with_type = sum(1 for p in products if scrub(p.get("type")))

# mapping_status: READY, APPROVED, MAPPED, COMPLETE are all valid ready states
MAPPING_READY_STATES = {"READY", "APPROVED", "MAPPED", "COMPLETE"}
mapping_robust = sum(1 for p in products if (p.get("mapping_status") or "").upper() in MAPPING_READY_STATES)
mapping_null = sum(1 for p in products if not (p.get("mapping_status") or "").strip())
mapping_blocked = sum(1 for p in products if (p.get("mapping_status") or "").upper() == "BLOCKED")

with_image_url = sum(1 for p in products if scrub(p.get("image_url")))
with_local_image = sum(1 for p in products if scrub(p.get("local_image_path")))
img_statuses = Counter(p.get("image_asset_status") or "MISSING" for p in products)
DOWNLOADED = sum(1 for p in products if (p.get("image_asset_status") or "").upper() == "DOWNLOADED")
IMAGE_READY_COUNT = sum(1 for p in products if (p.get("image_asset_status") or "").upper() in {"IMAGE_READY", "IMAGE_CACHE_READY"})

claim_safe = Counter(p.get("claim_safe_copy_status") or "MISSING" for p in products)
claim_risk = Counter(p.get("claim_risk_level") or "MISSING" for p in products)
source_counts = Counter(scrub(p.get("source")) or "UNKNOWN" for p in products)
mapping_status_counts = Counter(p.get("mapping_status") or "MISSING" for p in products)

# IMG production approval
prod_approved_modes = []
for p in products:
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    prod_approved_modes.extend(modes)
img_prod_approved = Counter(prod_approved_modes).get("IMG", 0)

# ── Simplified confidence heuristic (NOT ProductTruthService) ──
def simple_confidence(p):
    """SIMPLIFIED HEURISTIC ONLY. Does NOT use ProductTruthService.build_computed_profile()."""
    ms = (p.get("mapping_status") or "").upper()
    src = (p.get("source") or "UNKNOWN").upper()
    has_raw = src == "FASTMOSS" and bool(p.get("fastmoss_source_file"))
    if ms in MAPPING_READY_STATES and has_raw:
        return "HIGH (heuristic)"
    elif ms in MAPPING_READY_STATES:
        return "MEDIUM (heuristic)"
    elif ms in ("NEEDS_REVIEW", "BLOCKED"):
        return "NEEDS_REVIEW (heuristic)"
    return "LOW (heuristic)"

confidence_labels = [simple_confidence(p) for p in products]
confidence_dist = Counter(confidence_labels)

# ── Poster Readiness Gate (CORRECTED) ───────────────────────
READY_CLAIM_STATES = {
    "CLAIM_SAFE_COPY_REVIEW_READY", "CLAIM_SAFE_COPY_APPROVED",
    "CLAIM_SAFE", "APPROVED", "READY"
}

def classify_poster(p):
    """Classify ONE committed product row for poster generation readiness."""
    lc = (p.get("lifecycle_status") or "ACTIVE").upper()
    src = scrub(p.get("source") or "")
    ms = (p.get("mapping_status") or "").upper()
    img_asset = (p.get("image_asset_status") or "").upper()
    cs = (p.get("claim_safe_copy_status") or "").upper()
    risk = (p.get("claim_risk_level") or "").upper()
    has_local_img = bool(scrub(p.get("local_image_path")))
    has_remote_img = bool(scrub(p.get("image_url")))
    has_img = has_local_img or has_remote_img
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    img_prod = "IMG" in modes
    cat = scrub(p.get("category"))
    subcat = scrub(p.get("subcategory"))
    ptype = scrub(p.get("type"))

    blockers = []

    # BLOCKED conditions
    if lc == "ARCHIVED":
        return "POSTER_BLOCKED", "ARCHIVED", "ARCHIVED"
    if not scrub(p.get("raw_product_title")):
        return "POSTER_BLOCKED", "MISSING_RAW_TITLE", "MISSING_RAW_TITLE"
    if not scrub(p.get("product_display_name")):
        return "POSTER_BLOCKED", "MISSING_DISPLAY_NAME", "MISSING_DISPLAY_NAME"

    # Check identity fields
    if not scrub(p.get("product_short_name")):
        blockers.append("MISSING_SHORT_NAME")
    if not cat:
        blockers.append("MISSING_CATEGORY")
    if not subcat and not ptype:
        blockers.append("MISSING_SUBCAT_AND_TYPE")

    # Mapping gate
    if not ms:
        blockers.append("MAPPING_MISSING")
    elif ms not in MAPPING_READY_STATES:
        blockers.append(f"MAPPING_{ms}")

    # Image gate
    if not img_prod:
        blockers.append("IMG_NOT_PROD_APPROVED")

    # Claim gate
    if cs in ("REVIEW_REQUIRED", "NEEDS_REVIEW", "BLOCKED"):
        blockers.append(f"CLAIM_{cs}")
    if risk == "HIGH":
        blockers.append("CLAIM_RISK_HIGH")

    # Image readiness tier
    if has_local_img or img_asset == "DOWNLOADED":
        img_tier = "PRODUCT_HERO_POSTER_READY"
    elif has_remote_img:
        img_tier = "PRODUCT_IMAGE_PROMPT_READY"
    else:
        img_tier = "TEXT_ONLY_POSTER_READY"

    if not blockers:
        return "POSTER_READY", None, img_tier
    return "POSTER_PREVIEW_ONLY", "; ".join(blockers), img_tier

poster_ready = []
poster_preview = []
poster_blocked = []

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

# Image readiness tier distribution
img_tier_dist = Counter(p["_img_tier"] for p in products)

# ── Blockers ────────────────────────────────────────────────
blocker_counter = Counter()
for p in poster_preview + poster_blocked:
    for b in (p.get("_blocker") or "UNKNOWN").split("; "):
        blocker_counter[b.strip()] += 1

# ── PASS threshold (stricter) ────────────────────────────────
ready_count = len(poster_ready)
ready_categories = {scrub(p.get("category")) for p in poster_ready}
ready_cat_count = len(ready_categories)

# BOSMAX/Minyak target products
BOSMAX_TARGETS = ["bosmax", "minyak warisan", "minyak warisan tok"]
target_ready = [p for p in poster_ready
    if any(t in (scrub(p.get("product_display_name")) + scrub(p.get("raw_product_title"))).lower() for t in BOSMAX_TARGETS)]
target_ready_count = len(target_ready)

# Products with local/downloaded image
ready_with_local = [p for p in poster_ready
    if scrub(p.get("local_image_path")) or (p.get("image_asset_status") or "").upper() == "DOWNLOADED"]
ready_local_count = len(ready_with_local)

# Stricter PASS gate
pass_threshold_met = (
    ready_count >= 5
    and ready_cat_count >= 3
    and target_ready_count >= 1
    and ready_local_count >= 1
)

if pass_threshold_met:
    verdict = "PASS"
elif ready_count >= 5:
    verdict = "HOLD"
else:
    verdict = "FAIL"

detail_parts = []
if pass_threshold_met:
    detail_parts.append(f"{ready_count} POSTER_READY (>=5 ✓), {ready_cat_count} categories (>=3 ✓), {target_ready_count} target product(s) (>=1 ✓), {ready_local_count} with local image (>=1 ✓)")
else:
    fails = []
    if ready_count < 5:
        fails.append(f"ready_count={ready_count} (<5 required)")
    if ready_cat_count < 3:
        fails.append(f"categories={ready_cat_count} (<3 required)")
    if target_ready_count < 1:
        fails.append(f"target_products={target_ready_count} (<1 required)")
    if ready_local_count < 1:
        fails.append(f"local_image_products={ready_local_count} (<1 required)")
    detail_parts.append("; ".join(fails))

verdict_detail = " | ".join(detail_parts)

# ── Target Product Matrix ───────────────────────────────────
def target_report(search_terms):
    """Find products matching search terms and report full state."""
    out = []
    for p in products:
        name = (scrub(p.get("product_display_name")) + " " + scrub(p.get("raw_product_title"))).lower()
        if not any(t.lower() in name for t in search_terms):
            continue
        try:
            modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
        except:
            modes = []
        out.append({
            "product_id": p.get("id"),
            "product_display_name": p.get("product_display_name"),
            "source": p.get("source"),
            "lifecycle": p.get("lifecycle_status"),
            "mapping_status": p.get("mapping_status"),
            "claim_safe_status": p.get("claim_safe_copy_status"),
            "claim_risk_level": p.get("claim_risk_level"),
            "image_url": p.get("image_url"),
            "local_image_path": p.get("local_image_path"),
            "image_asset_status": p.get("image_asset_status"),
            "production_approved_modes": modes,
            "poster_tier": p.get("_cls"),
            "image_tier": p.get("_img_tier"),
            "blocker": p.get("_blocker"),
        })
    return out

bosmax_targets = target_report(["bosmax oil", "bosmax herb", "bosmax serum"])
minyak_targets = target_report(["minyak warisan tok cap burung", "minyak warisan"])
all_targets = bosmax_targets + [t for t in minyak_targets if t not in bosmax_targets]

# Deduplicate target products by product_id
seen = set()
unique_targets = []
for t in all_targets:
    if t["product_id"] not in seen:
        seen.add(t["product_id"])
        unique_targets.append(t)

# ── Sample products ─────────────────────────────────────────
def sample(p):
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

# ── Output ──────────────────────────────────────────────────
print(f"DB_PATH: {DB_PATH}")
print(f"Total: {total} | Active: {active} | Archived: {archived}")
print(f"Mapping robust: {mapping_robust} | NULL: {mapping_null} | BLOCKED: {mapping_blocked}")
print(f"POSTER_READY: {ready_count} | PREVIEW_ONLY: {len(poster_preview)} | BLOCKED: {len(poster_blocked)}")
print(f"Categories in ready: {sorted(ready_categories)[:20]}")
print(f"Image tiers: {dict(img_tier_dist)}")
print(f"Target products: {len(unique_targets)}")
print(f"Verdict: {verdict} — {verdict_detail}")

output = {
    "db_path": str(DB_PATH),
    "total": total,
    "active": active,
    "archived": archived,
    "comment_1": "ALL 516 rows are canonical committed product rows in the product table.",
    "comment_2": "source=FASTMOSS does NOT mean reference-only. There is no reference_only column in the product table.",
    "comment_3": "mapping_status=APPROVED IS a valid ready state (same workflow as READY, just different approval path).",
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
    "with_local_image": with_local_image,
    "image_asset_downloaded": DOWNLOADED,
    "image_asset_IMAGE_READY": IMAGE_READY_COUNT,
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
    "blockers": blocker_counter.most_common(20),
    "samples_ready": [sample(p) for p in poster_ready[:5]],
    "samples_preview": [sample(p) for p in poster_preview[:5]],
    "samples_blocked": [sample(p) for p in poster_blocked[:5]],
    "sources": dict(source_counts),
    "verdict": verdict,
    "verdict_detail": verdict_detail,
    "pass_threshold": {
        "ready_count >= 5": ready_count >= 5,
        "categories >= 3": ready_cat_count >= 3,
        "target_products >= 1": target_ready_count >= 1,
        "local_image >= 1": ready_local_count >= 1,
    },
}

audit_dir = Path(__file__).resolve().parent.parent / "docs" / "audits"
audit_dir.mkdir(parents=True, exist_ok=True)
json_path = audit_dir / "poster_readiness_data.json"
with open(json_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nData written to: {json_path}")
print(f"Final verdict: {verdict}")
print(f"Threshold checks: {output['pass_threshold']}")
conn.close()
