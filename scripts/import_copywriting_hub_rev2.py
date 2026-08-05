"""Import 'Copywriting Hub-Rev2.xlsx' into the live catalog (operator-approved).

Decisions locked with the owner:
  * Match key   = TikTok product-id from /view/product/<id> OR /pdp/<id>.
                  ('Product ID' column is float-corrupt -> IGNORED.)
  * Policy      = FILE WINS (overwrite) on everything EXCEPT 3 killer products
                  (Minyak Warisan Cap Burung, Bosmax Herbs, Bosmax Oil) which are
                  never touched.
  * Replace old = active products NOT in the file (and not killer) are ARCHIVED.
  * No overlap  = match-by-id + skip killer; file rows whose name collides an
                  existing product (different listing) are HELD for manual review.
  * Copy        = approve ALL (incl HIGH-risk / medical) per owner.

Staged & idempotent-friendly (each phase re-derives buckets from the CURRENT db):
  phase1   identity(new only)/commerce  -> product           (crud.create/update)
  phase2   cluster + product_type_group -> product_strategy_taxonomy
  phase3   copy + product knowledge     -> PI draft -> approved snapshot
  archive  active, not-in-file, not-killer -> lifecycle ARCHIVED

Existing product NAMES are kept stable (only NEW products take names from file) to
avoid identity churn / fingerprint invalidation. Commerce/taxonomy/copy are refreshed.

Zero network, zero credit. Dry-run by default; --apply writes. Back up first.

Usage:
    python scripts/import_copywriting_hub_rev2.py --phase 1
    python scripts/import_copywriting_hub_rev2.py --phase 1 --apply [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "flow_agent.db"
XLSX = Path(r"C:\Users\USER\Downloads\Copywriting Hub-Rev2.xlsx")
SRC_TAG = "Copywriting Hub-Rev2.xlsx"
REVIEWER_ID = "copywriting_hub_rev2_import"
NOTE = "Copywriting Hub-Rev2 file-authoritative import"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

KILLER_PREFIX = {"6483d624", "90349f8c", "b460ffbd"}  # Minyak Warisan Cap Burung, Bosmax Herbs, Bosmax Oil
CLUSTER_XW = {
    "electronics_accessories": "electronics_accessory",
    "fashion_accessories": "fashion_accessory",
    "health_devices": "health_device",
    "kitchen_tools": "kitchen_tool",
    "ready_to_eat_food": "food_ready_to_eat",
}
RID = re.compile(r"/(?:pdp|product)/(\d{6,})")


def _reconf():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def s(v):
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def norm(v):
    return re.sub(r"\s+", " ", str(v or "").strip()).lower()


def cluster_xw(c):
    n = re.sub(r"[^a-z0-9]+", "_", str(c or "").strip().lower()).strip("_")
    return CLUSTER_XW.get(n, n)


def nums(v):
    if v is None:
        return (None, None)
    if isinstance(v, (int, float)):
        f = round(float(v), 2)
        return (f, f)
    found = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v).replace(",", ""))]
    if not found:
        return (None, None)
    return (round(min(found), 2), round(max(found), 2))


def parse_file():
    import openpyxl
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["COPYWRITING HUB"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    H = {n: i for i, n in enumerate(header) if n is not None}

    def col(r, n):
        i = H.get(n)
        return r[i] if (i is not None and i < len(r)) else None

    recs = []
    for r in rows[1:]:
        if not any(c is not None and str(c).strip() for c in r):
            continue
        url = s(col(r, "TikTok URL"))
        m = RID.search(url or "")
        pmin, pmax = nums(col(r, "Price (RM)"))
        camt, _ = nums(col(r, "Commission Amount"))
        recs.append({
            "tiktok_id": m.group(1) if m else None,
            "name": s(col(r, "Product Name")),
            "cluster": cluster_xw(col(r, "Cluster Name")),
            "type": s(col(r, "Product Type Code")),
            "image_url": s(col(r, "Image URL")),
            "tiktok_url": url,
            "price_min": pmin, "price_max": pmax,
            "commission_rate": s(col(r, "Commission Rate")),
            "commission_amount": camt,
            "risk_tier": s(col(r, "risk_tier")),
            "medical_flag": s(col(r, "medical_flag")),
            # copy + knowledge (phase 3)
            "product_knowledge_text": s(col(r, "Product Knowledge Text")),
            "benefits": s(col(r, "Benefits Text")),
            "usage": s(col(r, "Usage Text")),
            "target_customer": s(col(r, "Target Customer Text")),
            "ingredients": s(col(r, "Ingredients Text")),
            "warnings": s(col(r, "Warnings Text")),
            "paste": s(col(r, "Paste Anything About Product")),
            "pain": s(col(r, "Pain Points")),
            "hook": s(col(r, "Hook Angles")),
            "subhook": s(col(r, "Subhook")),
            "usp": s(col(r, "USP Product")),
            "cta": s(col(r, "CTA Angles")),
            "size_or_volume": s(col(r, "Size/Volume")),
            "package_notes": s(col(r, "Package Notes")),
        })
    return recs


def _to_list(text, cap=20):
    """Split a free-text cell into list[str] on line breaks only (preserve copy
    verbatim; do not fragment sentences on punctuation)."""
    if not text:
        return []
    parts = [p.strip(" \t-•*").strip() for p in re.split(r"[\r\n]+", str(text)) if p.strip()]
    return parts[:cap]


def build_draft_payload(rec):
    """Map one file row -> ProductIntelligenceReviewDraft mutation fields.
    claim_gate / claim_risk_level are derived by the service, not set here."""
    benefits = _to_list(rec["benefits"])
    usp = _to_list(rec["usp"])
    hooks = _to_list(rec["hook"])
    ctas = _to_list(rec["cta"])
    pains = _to_list(rec["pain"])
    subhooks = _to_list(rec["subhook"])
    # allowed_claims: benefits + usp (the marketable, file-authored claims), deduped
    allowed, seen = [], set()
    for c in benefits + usp:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            allowed.append(c)
    persona = {k: v for k, v in {
        "audience": rec["target_customer"],
        "pain_points": pains,
        "desires": benefits,
    }.items() if v}
    strategy = {k: v for k, v in {
        "hook_angles": hooks,
        "cta_angles": ctas,
        "subhook": subhooks,
        "usp": usp,
        "pain_points": pains,
    }.items() if v}
    payload = {
        "product_description": rec["product_knowledge_text"],
        "benefits_json": benefits or None,
        "usp_json": usp or None,
        "hook_angles_json": hooks or None,
        "cta_angles_json": ctas or None,
        "pain_points_json": pains or None,
        "subhook_json": subhooks or None,
        "usage_text": rec["usage"],
        "ingredients_text": rec["ingredients"],
        "warnings_text": rec["warnings"],
        "target_customer_text": rec["target_customer"],
        "paste_anything_summary": rec["paste"],
        "size_or_volume": rec["size_or_volume"],
        "package_notes": rec["package_notes"],
        "allowed_claims_json": allowed or None,
        "buyer_persona_snapshot_json": persona or None,
        "copy_strategy_summary_json": strategy or None,
        "reviewer_note": NOTE,
        "created_by": REVIEWER_ID,
    }
    return {k: v for k, v in payload.items() if v is not None}


def _is_killer(pid):
    return (pid or "")[:8] in KILLER_PREFIX


def classify(recs):
    """Match file rows to CURRENT db state (read-only)."""
    import sqlite3
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sysById, allnames = {}, {}
    prod_rows = con.execute(
        "SELECT id,source,lifecycle_status,product_display_name,raw_product_title,"
        "product_short_name,price,price_min,price_max,commission_amount,commission_rate,"
        "image_url,tiktok_product_url FROM product"
    ).fetchall()
    for r in prod_rows:
        m = RID.search(r["tiktok_product_url"] or "")
        if m:
            sysById[m.group(1)] = r
        for nm in (r["product_display_name"], r["raw_product_title"], r["product_short_name"]):
            if nm:
                allnames.setdefault(norm(nm), []).append(r["id"])
    con.close()

    update, create, hold, noid = [], [], [], []
    for rec in recs:
        if not rec["tiktok_id"]:
            noid.append(rec)
        elif rec["tiktok_id"] in sysById:
            row = sysById[rec["tiktok_id"]]
            if _is_killer(row["id"]):
                continue  # protected: never touch
            update.append((rec, row))
        elif norm(rec["name"]) in allnames:
            hold.append(rec)  # name collides existing listing -> manual, avoid dup
        else:
            create.append(rec)
    matched_uuids = {row["id"] for _, row in update}
    return {
        "update": update, "create": create, "hold": hold, "noid": noid,
        "sysById": sysById, "matched_uuids": matched_uuids, "prod_rows": prod_rows,
    }


# --------------------------------------------------------------------------- #
# PHASE 1 — identity (new only) + commerce
# --------------------------------------------------------------------------- #
async def phase1(b, apply, limit):
    from agent.db import crud
    created = updated = failed = 0
    # CREATE new
    todo = b["create"][:limit] if limit else b["create"]
    for rec in todo:
        try:
            if apply:
                await crud.create_product(
                    raw_product_title=rec["name"] or "(unnamed)",
                    source="MANUAL",
                    product_display_name=rec["name"],
                    price=rec["price_min"],
                    price_min=rec["price_min"],
                    price_max=rec["price_max"],
                    commission_amount=rec["commission_amount"],
                    commission_rate=rec["commission_rate"],
                    currency="MYR",
                    image_url=rec["image_url"],
                    tiktok_product_url=rec["tiktok_url"],
                    source_url=rec["tiktok_url"],
                    fastmoss_source_file=SRC_TAG,
                )
            created += 1
        except Exception as exc:
            failed += 1
            print(f"  CREATE FAIL {(rec['name'] or '')[:34]}: {exc}")
    # UPDATE commerce on existing (names kept stable)
    todo = b["update"][:limit] if limit else b["update"]
    for rec, row in todo:
        try:
            payload = {
                "price": rec["price_min"],
                "price_min": rec["price_min"],
                "price_max": rec["price_max"],
                "commission_amount": rec["commission_amount"],
                "commission_rate": rec["commission_rate"],
            }
            if rec["image_url"]:
                payload["image_url"] = rec["image_url"]
            payload = {k: v for k, v in payload.items() if v is not None}
            if apply:
                await crud.update_product(row["id"], **payload)
            updated += 1
        except Exception as exc:
            failed += 1
            print(f"  UPDATE FAIL {row['id'][:10]}: {exc}")
    verb = "CREATED/UPDATED" if apply else "would create/update"
    print(f"PHASE 1 {verb}: create={created} update={updated} failed={failed}")


# --------------------------------------------------------------------------- #
# PHASE 2 — cluster + product_type_group (file-authoritative)
# --------------------------------------------------------------------------- #
async def phase2(b, apply, limit):
    import sqlite3
    from agent.services.product_strategy_taxonomy_service import (
        product_strategy_fingerprint,
        lookup_product_strategy_type_registry_entry,
        review_product_strategy_taxonomy,
    )
    from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomyReviewRequest

    # after phase1, re-classify so newly-created products are matched too
    recs = parse_file()
    b = classify(recs)

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    targets = [(rec, row["id"]) for rec, row in b["update"]]
    if limit:
        targets = targets[:limit]
    verified = review_req = skipped = failed = 0
    for rec, pid in targets:
        try:
            entry = lookup_product_strategy_type_registry_entry(rec["cluster"], rec["type"])
            if not entry:
                skipped += 1
                print(f"  SKIP no-registry-pair {rec['cluster']}/{rec['type']} ({(rec['name'] or '')[:26]})")
                continue
            prod = dict(con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone())
            fp = product_strategy_fingerprint(prod)
            rstatus = "VERIFIED" if entry.get("registry_status") == "ACTIVE" else "REVIEW_REQUIRED"
            req = ProductStrategyTaxonomyReviewRequest(
                expected_product_fingerprint=fp,
                cluster=rec["cluster"],
                product_type_group=rec["type"],
                matched_scene_strategy_id=str(entry.get("matched_scene_strategy_id")),
                scene_coverage_status=entry.get("scene_coverage_status"),
                review_status=rstatus,
                reviewer_id=REVIEWER_ID,
                reviewer_note=NOTE,
            )
            if apply:
                await review_product_strategy_taxonomy(pid, req)
            if rstatus == "VERIFIED":
                verified += 1
            else:
                review_req += 1
        except Exception as exc:
            failed += 1
            print(f"  PHASE2 FAIL {pid[:10]} {rec['cluster']}/{rec['type']}: {exc}")
    con.close()
    verb = "BOUND" if apply else "would bind"
    print(f"PHASE 2 {verb}: verified={verified} review_required={review_req} skipped={skipped} failed={failed}")


# --------------------------------------------------------------------------- #
# PHASE 3 — copy + product knowledge -> PI draft -> approved snapshot
# --------------------------------------------------------------------------- #
_TERMINAL_DRAFT = ("APPROVED", "REJECTED", "SUPERSEDED")


async def phase3(b, apply, limit):
    import sqlite3
    from agent.services.product_intelligence_review_draft_service import (
        create_review_draft, create_revision_draft, update_review_draft, approve_review_draft,
    )
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftCreateRequest as CreateReq,
        ProductIntelligenceReviewDraftUpdateRequest as UpdateReq,
        ProductIntelligenceReviewDraftApproveRequest as ApproveReq,
    )

    recs = parse_file()
    b = classify(recs)
    targets = [(rec, row["id"]) for rec, row in b["update"]]
    if limit:
        targets = targets[:limit]

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    approved_pids = {r[0] for r in con.execute(
        "SELECT DISTINCT product_id FROM product_intelligence_snapshot WHERE status='APPROVED'")}
    open_draft = {}
    for r in con.execute(
        "SELECT product_id, draft_id FROM product_intelligence_review_draft "
        "WHERE review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')"):
        open_draft.setdefault(r["product_id"], r["draft_id"])
    con.close()

    # ---- dry-run: PREDICT claim-blocked via the offline scanner (no writes) ----
    if not apply:
        try:
            from agent.services.product_intelligence_claim_safety_service import evaluate_claim_safety
        except Exception:
            evaluate_claim_safety = None
        blocked = review = safe = incomplete = 0
        for rec, pid in targets:
            f = build_draft_payload(rec)
            need = ("product_description", "benefits_json", "usp_json", "target_customer_text",
                    "allowed_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json")
            if any(not f.get(k) for k in need):
                incomplete += 1
                continue
            if evaluate_claim_safety is None:
                continue
            gate = (evaluate_claim_safety(f, product=None) or {}).get("claim_gate")
            if gate == "CLAIM_BLOCKED":
                blocked += 1
            elif gate == "CLAIM_REVIEW_REQUIRED":
                review += 1
            else:
                safe += 1
        print(f"PHASE 3 would process {len(targets)}: predict approve~={safe+review} "
              f"claim_blocked~={blocked} missing_copy_critical={incomplete} "
              f"(revision-path={sum(1 for _,p in targets if p in approved_pids)})")
        return

    # ---- apply ----
    APPROVE = ApproveReq(
        approved_by="owner",
        approval_note="Phase 3 bulk approve (owner directive: approve all incl HIGH/medical)",
        allow_incomplete_product_knowledge=True,
        claim_review_acknowledged=True,
    )
    approved = blocked = failed = 0
    blocked_list = []
    for rec, pid in targets:
        fields = build_draft_payload(rec)
        try:
            if pid in approved_pids:
                draft = await create_revision_draft(
                    pid, created_by=REVIEWER_ID, revision_reason="PHASE3_FILE_WINS_COPY_IMPORT")
                await update_review_draft(draft.draft_id, UpdateReq(**fields))
                did = draft.draft_id
            elif pid in open_draft:
                did = open_draft[pid]
                await update_review_draft(did, UpdateReq(**fields))
            else:
                draft = await create_review_draft(pid, CreateReq(**fields))
                did = draft.draft_id
            try:
                await approve_review_draft(did, APPROVE)
                approved += 1
            except Exception as aexc:
                if "CLAIM_BLOCKED" in str(aexc):
                    blocked += 1
                    blocked_list.append({"product_id": pid, "name": rec["name"]})
                else:
                    raise
        except Exception as exc:
            failed += 1
            print(f"  PHASE3 FAIL {pid[:10]} ({(rec['name'] or '')[:24]}): {str(exc)[:110]}")
    print(f"PHASE 3 APPROVED: approved={approved} claim_blocked={blocked} failed={failed}")
    if blocked_list:
        outp = REPO / "outputs" / "copywriting-hub-rev2-import"
        outp.mkdir(parents=True, exist_ok=True)
        (outp / "claim_blocked.json").write_text(
            json.dumps(blocked_list, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {len(blocked_list)} CLAIM_BLOCKED drafts imported (not live); "
              f"list: outputs/copywriting-hub-rev2-import/claim_blocked.json")


# --------------------------------------------------------------------------- #
# ARCHIVE — active, not-in-file, not-killer
# --------------------------------------------------------------------------- #
async def archive(b, apply, limit):
    from agent.db import crud
    recs = parse_file()
    b = classify(recs)
    to_arch = [
        r for r in b["prod_rows"]
        if r["lifecycle_status"] == "ACTIVE"
        and r["id"] not in b["matched_uuids"]
        and not _is_killer(r["id"])
    ]
    if limit:
        to_arch = to_arch[:limit]
    done = failed = 0
    for r in to_arch:
        try:
            if apply:
                await crud.update_product(
                    r["id"],
                    lifecycle_status="ARCHIVED",
                    archived_at=_now(),
                    archived_reason="Replaced by Copywriting Hub-Rev2 import",
                    archived_by=REVIEWER_ID,
                )
            done += 1
        except Exception as exc:
            failed += 1
            print(f"  ARCHIVE FAIL {r['id'][:10]}: {exc}")
    verb = "ARCHIVED" if apply else "would archive"
    print(f"ARCHIVE {verb}: {done} (failed={failed})")


# --------------------------------------------------------------------------- #
# UNARCHIVE — file-matched products that were archived BEFORE this import
# (owner: make them active as part of the current catalog; keep dup-merges archived)
# --------------------------------------------------------------------------- #
async def unarchive(b, apply, limit):
    import sqlite3
    from agent.db import crud
    recs = parse_file()
    b = classify(recs)
    file_pids = {row["id"] for _, row in b["update"]}
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, archived_reason FROM product WHERE lifecycle_status='ARCHIVED'").fetchall()
    con.close()
    targets = [
        r["id"] for r in rows
        if r["id"] in file_pids
        and not str(r["archived_reason"] or "").startswith("DUPLICATE_MERGED_TO_CANONICAL")
    ]
    kept_dup = sum(
        1 for r in rows if r["id"] in file_pids
        and str(r["archived_reason"] or "").startswith("DUPLICATE_MERGED_TO_CANONICAL"))
    if limit:
        targets = targets[:limit]
    done = failed = 0
    for pid in targets:
        try:
            if apply:
                await crud.update_product(
                    pid,
                    lifecycle_status="ACTIVE",
                    unarchived_at=_now(),
                    unarchived_reason="Present in Copywriting Hub-Rev2 current catalog",
                )
            done += 1
        except Exception as exc:
            failed += 1
            print(f"  UNARCHIVE FAIL {pid[:10]}: {exc}")
    verb = "UNARCHIVED" if apply else "would un-archive"
    print(f"UNARCHIVE {verb}: {done} | kept DUPLICATE_MERGED archived: {kept_dup} | failed={failed}")


# --------------------------------------------------------------------------- #
# RECLASSIFY — owner-approved: re-home the 25 file-generic / home_appliance-catchall
# products to their correct ACTIVE registry pair (by product name keywords)
# --------------------------------------------------------------------------- #
_RECLASS_RULES = [
    (r"bedak|compact powder", "beauty_makeup", "face_powder"),
    (r"tonic rambut|rambut uban|rambut gugur|minoxidil|foligrowth|hair.?growth|greyvive",
     "beauty_personal_care", "hair_treatment"),
    (r"hair remov|remover|pencukur|shaver|trimmer|removal device",
     "beauty_personal_care", "personal_care_device"),
    (r"toner", "beauty_skincare", "facial_cleanser"),
    (r"ubat acne|acne treatment|song ren", "sensitive_wellness", "traditional_herbal_preparation"),
    (r"bekas|food container|food saver|penutup makanan|microwave.?safe|food.*bowl|multipurpose",
     "kitchen_storage", "food_cover"),
    (r"aircon cleaner|penghilang noda|stain remover|sunlight|dishwash|pencuci|cleaner",
     "household_cleaning", "household_cleaner"),
    (r"\bmop\b|penyapu|sawang|broom|spin mop", "household_cleaning", "cleaning_tool"),
    (r"tisu|tissue|kitchen paper|kertas dapur", "household_cleaning", "cleaning_cloth"),
    (r"wallsticker|wall sticker|marble sticker|floor.*30|self adhesive.*marble|lantai",
     "home_improvement", "wall_covering"),
    (r"usb port|extension|extended sleeve", "electronics_accessory", "electronics_accessory"),
]


async def reclassify(b, apply, limit):
    import re as _re
    import sqlite3
    from agent.services.product_strategy_taxonomy_service import (
        product_strategy_fingerprint,
        lookup_product_strategy_type_registry_entry,
        review_product_strategy_taxonomy,
    )
    from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomyReviewRequest

    cur = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    cur.row_factory = sqlite3.Row
    prods = cur.execute(
        "SELECT p.id, p.product_display_name nm FROM product p "
        "JOIN product_strategy_taxonomy t ON t.product_id=p.id "
        "WHERE p.lifecycle_status='ACTIVE' AND (t.cluster='generic_unclassified' "
        "OR (t.cluster='home_equipment' AND t.product_type_group='home_appliance'))").fetchall()
    targets = []
    for r in prods:
        low = (r["nm"] or "").lower()
        for pat, cl, ty in _RECLASS_RULES:
            if _re.search(pat, low):
                targets.append((r["id"], cl, ty))
                break
    if limit:
        targets = targets[:limit]
    done = skip = failed = 0
    for pid, cl, ty in targets:
        try:
            entry = lookup_product_strategy_type_registry_entry(cl, ty)
            if not entry or entry.get("registry_status") != "ACTIVE":
                skip += 1
                print(f"  SKIP no-active-pair {cl}/{ty}")
                continue
            prod = dict(cur.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone())
            fp = product_strategy_fingerprint(prod)
            req = ProductStrategyTaxonomyReviewRequest(
                expected_product_fingerprint=fp, cluster=cl, product_type_group=ty,
                matched_scene_strategy_id=str(entry.get("matched_scene_strategy_id")),
                scene_coverage_status=entry.get("scene_coverage_status"),
                review_status="VERIFIED", reviewer_id=REVIEWER_ID,
                reviewer_note="Reclassify file-generic / home_appliance catch-all by name (owner-approved)")
            if apply:
                await review_product_strategy_taxonomy(pid, req)
            done += 1
        except Exception as exc:
            failed += 1
            print(f"  RECLASS FAIL {pid[:10]}: {str(exc)[:90]}")
    cur.close()
    verb = "RECLASSIFIED" if apply else "would reclassify"
    print(f"RECLASSIFY {verb}: {done} skip={skip} failed={failed}")


# --------------------------------------------------------------------------- #
# REGISTER-PAIRS — owner-approved: create taxonomy pairs for 9 file-uncovered
# products (fallback scene coverage), then bind them. Cluster/type become correct;
# scene coverage stays pending (FALLBACK) until a scene strategy is built.
# --------------------------------------------------------------------------- #
_NEW_PAIRS = [
    ("fashion_accessory", "bag", "Bag & Wallet"),
    ("beauty_skincare", "medicated_patch", "Medicated Patch"),
    ("home_decor", "artificial_plant", "Artificial Plant"),
    ("home_improvement", "bathroom_fixture", "Bathroom Fixture"),
    ("stationery", "sticker", "Sticker"),
]
_NEWPAIR_RULES = [
    (r"\bbeg\b|dompet|silang badan|beg pinggang|mini bag|\bbag\b|wallet", "fashion_accessory", "bag"),
    (r"plaster|ketuat|hydrocolloid|jagung kaki|corn", "beauty_skincare", "medicated_patch"),
    (r"artificial flower|fake flower|poppies", "home_decor", "artificial_plant"),
    (r"bidet", "home_improvement", "bathroom_fixture"),
    (r"pelekat 3d|buku pelekat|sticker book", "stationery", "sticker"),
]


async def register_pairs(b, apply, limit):
    import re as _re
    import sqlite3
    from agent.services.product_strategy_taxonomy_service import (
        register_product_strategy_type,
        product_strategy_fingerprint,
        lookup_product_strategy_type_registry_entry,
        review_product_strategy_taxonomy,
    )
    from agent.models.product_strategy_taxonomy import (
        ProductStrategyTypeRegistrationRequest,
        ProductStrategyTaxonomyReviewRequest,
    )
    reg_done = reg_exist = reg_fail = 0
    for cl, ty, dn in _NEW_PAIRS:
        try:
            if apply:
                await register_product_strategy_type(ProductStrategyTypeRegistrationRequest(
                    cluster=cl, product_type_group=ty, display_name=dn,
                    matched_scene_strategy_id="GENERIC_FALLBACK",
                    scene_coverage_status="FALLBACK_ONLY", registry_status="REVIEW_REQUIRED",
                    auto_classification_enabled=False, reviewer_id=REVIEWER_ID,
                    reviewer_note="New taxonomy pair for file-uncovered category (owner-approved)"))
            reg_done += 1
        except Exception as exc:
            if "ALREADY_REGISTERED" in str(exc):
                reg_exist += 1
            else:
                reg_fail += 1
                print(f"  REGISTER FAIL {cl}/{ty}: {str(exc)[:90]}")
    cur = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    cur.row_factory = sqlite3.Row
    prods = cur.execute(
        "SELECT p.id, p.product_display_name nm FROM product p "
        "JOIN product_strategy_taxonomy t ON t.product_id=p.id "
        "WHERE p.lifecycle_status='ACTIVE' AND (t.cluster='generic_unclassified' "
        "OR (t.cluster='home_equipment' AND t.product_type_group='home_appliance'))").fetchall()
    bound = failed = 0
    for r in prods:
        low = (r["nm"] or "").lower()
        pair = next(((c, t) for pat, c, t in _NEWPAIR_RULES if _re.search(pat, low)), None)
        if not pair:
            continue
        try:
            entry = lookup_product_strategy_type_registry_entry(*pair)
            if not entry:
                if apply:
                    print(f"  no registry entry for {pair} (register first)")
                continue
            prod = dict(cur.execute("SELECT * FROM product WHERE id=?", (r["id"],)).fetchone())
            fp = product_strategy_fingerprint(prod)
            req = ProductStrategyTaxonomyReviewRequest(
                expected_product_fingerprint=fp, cluster=pair[0], product_type_group=pair[1],
                matched_scene_strategy_id=str(entry.get("matched_scene_strategy_id")),
                scene_coverage_status=entry.get("scene_coverage_status"),
                review_status="REVIEW_REQUIRED", reviewer_id=REVIEWER_ID,
                reviewer_note="Bind to new taxonomy pair (owner-approved; scene coverage pending)")
            if apply:
                await review_product_strategy_taxonomy(r["id"], req)
            bound += 1
        except Exception as exc:
            failed += 1
            print(f"  BIND FAIL {r['id'][:10]}: {str(exc)[:90]}")
    cur.close()
    verb = "DONE" if apply else "dry-run"
    print(f"REGISTER-PAIRS {verb}: pairs_registered={reg_done} already={reg_exist} "
          f"reg_failed={reg_fail} products_bound={bound} bind_failed={failed}")


# --------------------------------------------------------------------------- #
# IMAGES — materialize (download) image_url for products with asset_status=UNRESOLVED
# --------------------------------------------------------------------------- #
async def images(b, apply, limit):
    import sqlite3
    from agent.api.products import cache_product_image
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id FROM product WHERE lifecycle_status='ACTIVE' AND asset_status='UNRESOLVED' "
        "AND image_url IS NOT NULL AND image_url<>''").fetchall()
    con.close()
    targets = [r["id"] for r in rows]
    if limit:
        targets = targets[:limit]
    ok = fail = 0
    for pid in targets:
        try:
            if apply:
                res = await cache_product_image(pid)
                if (res or {}).get("status") == "success":
                    ok += 1
                else:
                    fail += 1
            else:
                ok += 1
        except Exception as exc:
            fail += 1
            print(f"  IMG FAIL {pid[:10]}: {str(exc)[:90]}")
    verb = "CACHED" if apply else "would cache"
    print(f"IMAGES {verb}: ok={ok} fail={fail} (of {len(targets)})")


# --------------------------------------------------------------------------- #
# RESTORE-CLUSTER — undo file-wins downgrades: products the file marked
# "Generic / Unclassified" that had a REAL cluster pre-import -> restore from backup
# --------------------------------------------------------------------------- #
BACKUP_DB = REPO / "flow_agent.db.precopyhub-20260805T090450Z"


async def restore_cluster(b, apply, limit):
    import sqlite3
    from agent.services.product_strategy_taxonomy_service import (
        product_strategy_fingerprint,
        lookup_product_strategy_type_registry_entry,
        review_product_strategy_taxonomy,
    )
    from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomyReviewRequest

    cur = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    cur.row_factory = sqlite3.Row
    bak = sqlite3.connect(f"file:{BACKUP_DB.as_posix()}?mode=ro", uri=True)
    bak.row_factory = sqlite3.Row
    bakclu = {r["product_id"]: (r["cluster"], r["product_type_group"])
              for r in bak.execute("SELECT product_id,cluster,product_type_group FROM product_strategy_taxonomy")}
    gen = cur.execute(
        "SELECT p.id FROM product p JOIN product_strategy_taxonomy t ON t.product_id=p.id "
        "WHERE p.lifecycle_status='ACTIVE' AND (t.cluster IS NULL OR t.cluster='generic_unclassified')").fetchall()
    targets = []
    for r in gen:
        bc = bakclu.get(r["id"])
        if bc and bc[0] and bc[0] != "generic_unclassified":
            targets.append((r["id"], bc[0], bc[1]))
    if limit:
        targets = targets[:limit]
    done = skip = failed = 0
    for pid, cl, ty in targets:
        try:
            entry = lookup_product_strategy_type_registry_entry(cl, ty)
            if not entry:
                skip += 1
                continue
            prod = dict(cur.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone())
            fp = product_strategy_fingerprint(prod)
            rstatus = "VERIFIED" if entry.get("registry_status") == "ACTIVE" else "REVIEW_REQUIRED"
            req = ProductStrategyTaxonomyReviewRequest(
                expected_product_fingerprint=fp, cluster=cl, product_type_group=ty,
                matched_scene_strategy_id=str(entry.get("matched_scene_strategy_id")),
                scene_coverage_status=entry.get("scene_coverage_status"),
                review_status=rstatus, reviewer_id=REVIEWER_ID,
                reviewer_note="Restore cluster downgraded by file-wins generic (pre-import backup)")
            if apply:
                await review_product_strategy_taxonomy(pid, req)
            done += 1
        except Exception as exc:
            failed += 1
            print(f"  RESTORE FAIL {pid[:10]}: {str(exc)[:90]}")
    cur.close()
    bak.close()
    verb = "RESTORED" if apply else "would restore"
    print(f"RESTORE-CLUSTER {verb}: {done} skip={skip} failed={failed}")


def _print_buckets(b):
    print(f"file rows: update={len(b['update'])} create={len(b['create'])} "
          f"hold={len(b['hold'])} no-id={len(b['noid'])}")


async def _close_db():
    """Close the shared aiosqlite connection so the process exits (its bg thread
    otherwise keeps the interpreter alive)."""
    try:
        from agent.db import schema
        conn = getattr(schema, "_db_connection", None)
        if conn is not None:
            await conn.close()
            schema._db_connection = None
    except Exception:
        pass


async def run(phase, apply, limit):
    recs = parse_file()
    b = classify(recs)
    _print_buckets(b)
    sys.stdout.flush()
    try:
        if phase == "1":
            await phase1(b, apply, limit)
        elif phase == "2":
            await phase2(b, apply, limit)
        elif phase == "3":
            await phase3(b, apply, limit)
        elif phase == "archive":
            await archive(b, apply, limit)
        elif phase == "unarchive":
            await unarchive(b, apply, limit)
        elif phase == "images":
            await images(b, apply, limit)
        elif phase == "restore-cluster":
            await restore_cluster(b, apply, limit)
        elif phase == "reclassify":
            await reclassify(b, apply, limit)
        elif phase == "register-pairs":
            await register_pairs(b, apply, limit)
        else:
            print(f"phase {phase} not implemented in this file yet")
    finally:
        await _close_db()
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    choices=["1", "2", "3", "archive", "unarchive", "images",
                             "restore-cluster", "reclassify", "register-pairs"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    _reconf()
    if not DB.exists():
        print(f"DB not found: {DB}")
        return 2
    if not XLSX.exists():
        print(f"XLSX not found: {XLSX}")
        return 2
    asyncio.run(run(args.phase, args.apply, args.limit or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
