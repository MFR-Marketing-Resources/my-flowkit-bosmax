"""Mission-08B D3: govern the provenance residue of the failed first live pilot.

WHAT HAPPENED
The 2026-08-01 pilot round acquired real evidence through the authenticated TikTok relay,
but two extraction defects (B-08B-D1 marketplace boilerplate, B-08B-D2 review-stream
leakage) put four bad values into three drafts. The draft FIELDS were restored the same
day; the four provenance rows recording those values were not, so the evidence table still
claimed a rejected value was pending review — provenance asserting Product Truth that the
draft no longer holds.

WHAT THIS SCRIPT DOES
Marks exactly those four rows `verification_status=REJECTED / reviewer_decision=REJECTED`
with an explanatory note. It deletes nothing: a rejected row is the audit trail of the
defect, and deleting it would erase the only durable record that the bad value ever
existed. The ten legitimate rows from the same pilot (real image URLs, the proven `30ml`
measurement, AI_PROPOSED fills of empty fields, a clean labelled-section materials read)
are asserted untouched.

SAFETY MODEL — the same one mission08a_canonical_duplicate_repair.py used:
  * plan first (default): print what WOULD change, write the plan JSON, touch nothing;
  * --apply: online-backup the DB, then one transaction of CAS updates — every UPDATE's
    WHERE clause re-checks the row's current declared_value prefix and its unreviewed
    status, so a row that changed since the audit is refused, not clobbered;
  * proof JSON records before/after for every targeted row plus whole-table counts.

Run from the repo root:
    python scripts/mission08b_provenance_cleanup.py           # plan only
    python scripts/mission08b_provenance_cleanup.py --apply
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "flow_agent.db"
EVIDENCE_DIR = REPO / "docs" / "evidence" / "mission08b_provenance_cleanup"

PILOT_PRODUCT_IDS = (
    "60c65d01-5d27-465b-8b9b-20d3a8cd8b99",  # Teachers Day Gift Bag
    "1063eec6-976c-415f-95dd-be5c7b53608b",  # Nakamichi Windshield 30ml
    "aae1b6f9-6d8f-43e3-9723-0d517ae8daec",  # Diamond Coating Spray
)

# The four rows, identified three ways at once (id + field + current-value prefix) so a
# drifted table makes the CAS refuse rather than guess. Prefixes are from the live audit.
REJECT_ROWS = (
    {
        "review_provenance_id": "cb075f4d-7f45-40cc-8242-fe0aeccf6508",
        "product_id": PILOT_PRODUCT_IDS[0],
        "field_name": "product_description",
        "declared_value_prefix": "Buy Teachers Day Gift Bag",
        "defect": "B-08B-D1",
        "why": "TikTok og:description SEO template stored as a product description; "
               "the draft value was restored to the curated description the same day.",
    },
    {
        "review_provenance_id": "3dfe7408-f31b-4b40-8078-a2ca418b8de5",
        "product_id": PILOT_PRODUCT_IDS[1],
        "field_name": "product_description",
        "declared_value_prefix": "Buy Nakamichi Rapid Windshield",
        "defect": "B-08B-D1",
        "why": "TikTok og:description SEO template stored as a product description; "
               "the draft value was restored to the curated description the same day.",
    },
    {
        "review_provenance_id": "d307f1e3-019b-4e95-b1b4-1ee2626f0810",
        "product_id": PILOT_PRODUCT_IDS[1],
        "field_name": "ingredients_text",
        "declared_value_prefix": "LiquidItem:3 Bottle",
        "defect": "B-08B-D2",
        "why": "Customer-review stream (masked usernames, 'Verified purchase') captured "
               "by the labelled-section parser and stored as ingredients; the draft "
               "field was cleared the same day.",
    },
    {
        "review_provenance_id": "930c3fd7-ec80-463e-ab90-463846404e1d",
        "product_id": PILOT_PRODUCT_IDS[2],
        "field_name": "product_description",
        "declared_value_prefix": "Buy Diamond Coating",
        "defect": "B-08B-D1",
        "why": "TikTok og:description SEO template stored as a product description; "
               "the draft value was restored to the curated description the same day.",
    },
)

# The ten legitimate pilot rows. Asserted UNTOUCHED at the end — a cleanup that quietly
# widened its own scope would be the same class of defect it is cleaning up.
KEEP_ROW_IDS = (
    "2c0e9f48-01cc-48f1-ae55-6f584a276a3d",  # P1 ingredients_text (clean labelled read)
    "9338852e-ebd7-46ad-988c-3fdda977b90c",  # P1 image_evidence_json
    "a4b73865-73cf-4845-adb6-6ccb824ea3a9",  # P1 product_form_factor (AI_PROPOSED)
    "1e06f7bf-d6b3-4127-8bc7-1a377e38b3a6",  # P2 image_evidence_json
    "3970ec37-12a9-4c89-b8b1-7e8d09a5aa83",  # P2 usage_text (AI_PROPOSED)
    "5480cd0c-3649-43f6-ab68-18702b34b846",  # P2 size_or_volume = 30ml (proven)
    "6260187b-bd44-40c8-a1f9-e67677ee066a",  # P2 product_form_factor (AI_PROPOSED)
    "0344c00d-b0bb-4023-a123-87e1427efe4e",  # P3 product_form_factor (AI_PROPOSED)
    "7cc0d9f7-2781-4f96-a16c-1ca8836193da",  # P3 image_evidence_json
    "8ee16288-d4b6-4c68-a5d0-fe0cab79ca42",  # P3 package_notes (AI_PROPOSED)
)

REVIEWER_NOTE = ("mission-08B D3 cleanup | first-live-pilot extraction defect {defect}: "
                 "{why} This value never became Product Truth and must not be re-promoted.")


def _row(cur: sqlite3.Cursor, rid: str) -> dict | None:
    cur.execute("SELECT * FROM product_intelligence_review_field_provenance "
                "WHERE review_provenance_id=?", (rid,))
    row = cur.fetchone()
    return dict(row) if row else None


def _table_counts(cur: sqlite3.Cursor) -> dict:
    counts = {}
    for table in ("product", "product_intelligence_review_draft",
                  "product_intelligence_review_field_provenance",
                  "product_intelligence_snapshot"):
        cur.execute(f"SELECT COUNT(*) c FROM {table}")
        counts[table] = cur.fetchone()["c"]
    return counts


def main() -> int:
    apply = "--apply" in sys.argv
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB), timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    counts_before = _table_counts(cur)
    plan = {"stamp": stamp, "mode": "APPLY" if apply else "PLAN",
            "counts_before": counts_before, "targets": [], "keep_asserted": []}

    ok = True
    for target in REJECT_ROWS:
        row = _row(cur, target["review_provenance_id"])
        entry = {**target, "found": bool(row)}
        if not row:
            entry["verdict"] = "MISSING — refuse"
            ok = False
        elif not str(row["declared_value"] or "").startswith(
                target["declared_value_prefix"]):
            entry["verdict"] = "VALUE_DRIFTED — refuse"
            entry["current_value"] = str(row["declared_value"])[:120]
            ok = False
        elif row["reviewer_decision"] == "REJECTED":
            entry["verdict"] = "ALREADY_REJECTED — idempotent no-op"
        else:
            entry["verdict"] = "WILL_REJECT"
            entry["before"] = {k: row[k] for k in
                              ("verification_status", "reviewer_decision",
                               "reviewer_note")}
        plan["targets"].append(entry)

    for rid in KEEP_ROW_IDS:
        row = _row(cur, rid)
        if row is None:
            plan["keep_asserted"].append({"id": rid, "state": "MISSING"})
            ok = False
        else:
            plan["keep_asserted"].append({
                "id": rid, "state": "PRESENT",
                "hash": hashlib.sha256(json.dumps(
                    {k: row[k] for k in row.keys()}, sort_keys=True,
                    default=str).encode()).hexdigest()[:16]})

    plan_path = EVIDENCE_DIR / f"cleanup_plan.{stamp}.json"
    plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False, default=str),
                         encoding="utf-8")
    for entry in plan["targets"]:
        print(f"  {entry['verdict']:34} {entry['field_name']:20} "
              f"#{entry['review_provenance_id'][:8]}")
    print(f"plan -> {plan_path}")

    if not ok:
        print("REFUSED: at least one target is missing or drifted. Nothing was changed.")
        conn.close()
        return 2
    if not apply:
        print("PLAN ONLY. Re-run with --apply to execute.")
        conn.close()
        return 0

    # consistent online backup BEFORE any write
    backup_path = EVIDENCE_DIR / f"flow_agent.pre-cleanup.{stamp}.db"
    dst = sqlite3.connect(str(backup_path))
    with dst:
        conn.backup(dst)
    dst.close()
    print(f"backup -> {backup_path} ({backup_path.stat().st_size} bytes)")

    now = datetime.now(timezone.utc).isoformat()
    changed = []
    with conn:
        for target in REJECT_ROWS:
            note = REVIEWER_NOTE.format(defect=target["defect"], why=target["why"])
            # CAS: id AND current value prefix AND still-unreviewed. 0 rows on any
            # mismatch — refuse, never clobber.
            cur.execute(
                "UPDATE product_intelligence_review_field_provenance "
                "SET verification_status='REJECTED', reviewer_decision='REJECTED', "
                "    reviewer_note=?, updated_at=? "
                "WHERE review_provenance_id=? AND product_id=? AND field_name=? "
                "  AND declared_value LIKE ? "
                "  AND (reviewer_decision IS NULL OR reviewer_decision='') ",
                (note, now, target["review_provenance_id"], target["product_id"],
                 target["field_name"], target["declared_value_prefix"] + "%"))
            changed.append({"id": target["review_provenance_id"],
                            "rows_updated": cur.rowcount})
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"CAS refused {target['review_provenance_id']} "
                    f"(rowcount={cur.rowcount}) — transaction rolls back")

    proof = {"stamp": stamp, "changed": changed, "after": [], "keep_after": [],
             "counts_after": _table_counts(cur)}
    for target in REJECT_ROWS:
        row = _row(cur, target["review_provenance_id"])
        proof["after"].append({
            "id": target["review_provenance_id"],
            "verification_status": row["verification_status"],
            "reviewer_decision": row["reviewer_decision"],
            "declared_value_prefix_still": str(row["declared_value"])[:40],
        })
    for keep, rid in zip(plan["keep_asserted"], KEEP_ROW_IDS):
        row = _row(cur, rid)
        now_hash = hashlib.sha256(json.dumps(
            {k: row[k] for k in row.keys()}, sort_keys=True,
            default=str).encode()).hexdigest()[:16]
        proof["keep_after"].append({"id": rid, "unchanged": now_hash == keep["hash"]})
        if now_hash != keep["hash"]:
            raise RuntimeError(f"KEEP row {rid} changed — scope violation")
    # rejection changes row CONTENT, never row COUNT
    if proof["counts_after"] != counts_before:
        raise RuntimeError("table counts changed — a rejection must not add/remove rows")

    proof_path = EVIDENCE_DIR / f"cleanup_proof.{stamp}.json"
    proof_path.write_text(json.dumps(proof, indent=1, ensure_ascii=False, default=str),
                          encoding="utf-8")
    print(f"proof -> {proof_path}")
    print("APPLIED: 4 rows rejected, 10 pilot rows asserted untouched, counts unchanged.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
