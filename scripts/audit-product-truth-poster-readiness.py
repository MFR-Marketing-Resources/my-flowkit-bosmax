"""
Product Truth Poster Readiness Audit Script.
Read-only. Connects to the real runtime DB and produces a comprehensive
readiness report for the poster/image prompt generation module.

Usage:
    python scripts/audit-product-truth-poster-readiness.py
"""
import sqlite3
import json
import sys
import os
from pathlib import Path
from collections import Counter

# ── Resolve the actual DB path ──────────────────────────────
BASE_DIR = Path(os.environ.get("FLOW_AGENT_DIR", Path(__file__).resolve().parent.parent))
DB_PATH = BASE_DIR / "flow_agent.db"

if not DB_PATH.exists():
    print(f"ERROR: DB not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

def scrub(v):
    return "" if v is None else str(v).strip()

rows = conn.execute("SELECT * FROM product").fetchall()
products = [dict(r) for r in rows]
total = len(products)

active = sum(1 for p in products if (p.get("lifecycle_status") or "ACTIVE").upper() == "ACTIVE")
archived = sum(1 for p in products if (p.get("lifecycle_status") or "").upper() == "ARCHIVED")
ref_only = sum(1 for p in products if str(p.get("source") or "").upper() in ("FASTMOSS",))
canonical = [p for p in products if str(p.get("source") or "").upper() not in ("FASTMOSS",)]
with_raw_title = sum(1 for p in products if scrub(p.get("raw_product_title")))
with_display_name = sum(1 for p in products if scrub(p.get("product_display_name")))
with_short_name = sum(1 for p in products if scrub(p.get("product_short_name")))
with_category = sum(1 for p in products if scrub(p.get("category")))
with_subcategory = sum(1 for p in products if scrub(p.get("subcategory")))
with_type = sum(1 for p in products if scrub(p.get("type")))
mapping_ready = sum(1 for p in products if (p.get("mapping_status") or "").upper() in ("READY", "MAPPED", "COMPLETE"))
mapping_not_ready = total - mapping_ready
with_image_url = sum(1 for p in products if scrub(p.get("image_url")))
with_local_image = sum(1 for p in products if scrub(p.get("local_image_path")))
img_statuses = Counter(p.get("image_asset_status") or "MISSING" for p in products)
claim_safe = Counter(p.get("claim_safe_copy_status") or "MISSING" for p in products)
claim_risk = Counter(p.get("claim_risk_level") or "MISSING" for p in products)
source_counts = Counter(scrub(p.get("source")) or "UNKNOWN" for p in products)
mapping_status_counts = Counter(p.get("mapping_status") or "MISSING" for p in products)
image_ready_states = {"IMAGE_READY", "IMAGE_CACHE_READY"}
image_ready_count = sum(1 for p in products if (p.get("image_asset_status") or "").upper() in image_ready_states)

# IMG production approval count
prod_approved_modes = []
for p in products:
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    prod_approved_modes.extend(modes)
img_prod_approved = Counter(prod_approved_modes).get("IMG", 0)

# Product Truth confidence (simplified local compute)
def simple_confidence(p):
    ms = (p.get("mapping_status") or "").upper()
    src = (p.get("source") or "UNKNOWN").upper()
    has_raw = src == "FASTMOSS" and bool(p.get("fastmoss_source_file"))
    if ms == "READY" and src == "FASTMOSS" and has_raw:
        return "HIGH"
    elif ms == "READY":
        return "MEDIUM"
    elif ms in ("NEEDS_REVIEW", "BLOCKED"):
        return "NEEDS_REVIEW"
    return "LOW"

confidence_labels = [simple_confidence(p) for p in products]
confidence_dist = Counter(confidence_labels)

# Poster readiness gate
def classify(p):
    lc = (p.get("lifecycle_status") or "ACTIVE").upper()
    src = scrub(p.get("source") or "").upper()
    if lc == "ARCHIVED":
        return "POSTER_BLOCKED", "ARCHIVED"
    if not scrub(p.get("raw_product_title")):
        return "POSTER_BLOCKED", "MISSING_RAW_TITLE"
    if not scrub(p.get("product_display_name")):
        return "POSTER_BLOCKED", "MISSING_DISPLAY_NAME"
    if src == "FASTMOSS":
        if scrub(p.get("category")) and scrub(p.get("product_short_name")):
            return "POSTER_PREVIEW_ONLY", "REFERENCE_ONLY"
        return "POSTER_BLOCKED", "REFERENCE_ONLY_INCOMPLETE"
    blockers = []
    if not scrub(p.get("product_short_name")):
        blockers.append("MISSING_SHORT_NAME")
    if not scrub(p.get("category")):
        blockers.append("MISSING_CATEGORY")
    if not scrub(p.get("subcategory")) and not scrub(p.get("type")):
        blockers.append("MISSING_SUBCAT_AND_TYPE")
    ms = (p.get("mapping_status") or "").upper()
    if ms and ms not in ("READY", "MAPPED", "COMPLETE"):
        blockers.append(f"MAPPING_{ms}")
    has_img = bool(scrub(p.get("local_image_path"))) or bool(scrub(p.get("image_url")))
    if not has_img:
        blockers.append("NO_IMAGE")
    cs = (p.get("claim_safe_copy_status") or "").upper()
    if cs in ("REVIEW_REQUIRED", "NEEDS_REVIEW", "BLOCKED"):
        blockers.append(f"CLAIM_{cs}")
    if (p.get("claim_risk_level") or "").upper() == "HIGH":
        blockers.append("CLAIM_RISK_HIGH")
    try:
        modes = json.loads(p.get("production_prompt_approved_modes") or "[]")
    except (json.JSONDecodeError, TypeError):
        modes = []
    if "IMG" not in modes:
        blockers.append("IMG_NOT_PROD_APPROVED")
    if not blockers:
        return "POSTER_READY", None
    return "POSTER_PREVIEW_ONLY", "; ".join(blockers)

poster_ready, poster_preview, poster_blocked = [], [], []
for p in products:
    cls, reason = classify(p)
    p["_cls"] = cls
    p["_blocker"] = reason
    (poster_ready if cls == "POSTER_READY" else poster_preview if cls == "POSTER_PREVIEW_ONLY" else poster_blocked).append(p)

blocker_counter = Counter()
for p in poster_preview + poster_blocked:
    for b in (p.get("_blocker") or "UNKNOWN").split("; "):
        blocker_counter[b.strip()] += 1

def sample(p):
    return {
        "product_id": p.get("id"),
        "product_display_name": p.get("product_display_name") or p.get("raw_product_title"),
        "source": p.get("source"),
        "lifecycle_status": p.get("lifecycle_status"),
        "mapping_status": p.get("mapping_status"),
        "image_status": p.get("image_asset_status") or "MISSING",
        "claim_status": p.get("claim_safe_copy_status") or "MISSING",
        "confidence": simple_confidence(p),
        "blocker": p.get("_blocker"),
    }

# Print and collect
print(f"DB_PATH: {DB_PATH}")
print(f"Total: {total} | Active: {active} | Archived: {archived} | Ref-Only: {ref_only} | Canonical: {len(canonical)}")
print(f"Ready: {len(poster_ready)} | Preview: {len(poster_preview)} | Blocked: {len(poster_blocked)}")
print(f"Confidence: {dict(confidence_dist)}")
print(f"Top blockers: {blocker_counter.most_common(10)}")

output = {
    "db_path": str(DB_PATH),
    "total": total, "active": active, "archived": archived, "ref_only": ref_only, "canonical": len(canonical),
    "with_raw_title": with_raw_title, "with_display_name": with_display_name, "with_short_name": with_short_name,
    "with_category": with_category, "with_subcategory": with_subcategory, "with_type": with_type,
    "mapping_ready": mapping_ready, "mapping_not_ready": mapping_not_ready,
    "with_image_url": with_image_url, "with_local_image": with_local_image,
    "image_statuses": dict(img_statuses), "image_ready": image_ready_count,
    "claim_safe": dict(claim_safe), "claim_risk": dict(claim_risk),
    "img_prod_approved": img_prod_approved,
    "confidence": dict(confidence_dist),
    "poster_ready": len(poster_ready), "poster_preview": len(poster_preview), "poster_blocked": len(poster_blocked),
    "blockers": blocker_counter.most_common(20),
    "samples_ready": [sample(p) for p in poster_ready[:5]],
    "samples_preview": [sample(p) for p in poster_preview[:5]],
    "samples_blocked": [sample(p) for p in poster_blocked[:5]],
    "sources": dict(source_counts),
    "mapping_statuses": dict(mapping_status_counts),
    "verdict": "PASS" if len(poster_ready) > 0 else ("HOLD" if len(poster_preview) > 0 else "FAIL"),
}
output["detail"] = (
    f"{len(poster_ready)} POSTER_READY" if len(poster_ready) > 0
    else f"{len(poster_preview)} PREVIEW_ONLY, 0 ready" if len(poster_preview) > 0
    else "No products meet any readiness tier"
)

audit_dir = Path(__file__).resolve().parent.parent / "docs" / "audits"
audit_dir.mkdir(parents=True, exist_ok=True)
json_path = audit_dir / "poster_readiness_data.json"
with open(json_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"Data written to: {json_path}")
conn.close()
