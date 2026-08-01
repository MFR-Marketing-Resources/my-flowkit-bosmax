"""Mission-08A canonical repair: converge the duplicate-open-draft product groups.

AUTHORITY
Owner-approved for EXACTLY the product groups that already hold more than one OPEN
Product Intelligence review draft, plus the B-586-04 uniqueness migration. Nothing else in
the catalogue may be touched, and this script proves that afterwards rather than asserting
it.

WHAT IT DOES NOT DO
  * never deletes a draft or a provenance row — the losing rows are RETAINED and marked
    SUPERSEDED, which is the only terminal state that does not fabricate a review;
  * never writes approved_by / approved_at / rejected_by / rejected_at / reviewed_by;
  * never auto-selects between two CONFLICTING values. Non-conflicting evidence (the
    winner is silent, the loser has a value) is merged; a real disagreement is reported and
    left readable on the superseded row for a human.

The convergence rule is not invented here. It is the SAME recency authority every reader
already uses (`COALESCE(updated_at, created_at) DESC, draft_id DESC`), imported from
`product_intelligence_draft_lifecycle`, so the draft that survives is the draft the
application would have served. The previous in-code rule used `draft_id ASC` and would have
kept the OPPOSITE row in both live groups.

USAGE
    python scripts/mission08a_canonical_duplicate_repair.py --plan     # read-only
    python scripts/mission08a_canonical_duplicate_repair.py --apply    # mutates
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.services.product_intelligence_draft_lifecycle import (  # noqa: E402
    SQL_CANONICAL_ORDER,
    SQL_OPEN_PREDICATE,
    SUPERSEDED,
)

DB = REPO / "flow_agent.db"
EVIDENCE_DIR = REPO / "docs" / "evidence" / "mission08a_canonical_repair"

# Every column that carries evidence a human could want to read back.
EVIDENCE_COLUMNS = (
    "product_description", "benefits_json", "usp_json", "usage_text", "ingredients_text",
    "warnings_text", "target_customer_text", "paste_anything_summary", "package_notes",
    "size_or_volume", "product_form_factor", "packaging_description",
    "source_urls_json", "image_evidence_json", "allowed_claims_json",
    "blocked_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json",
)
# Reviewer identity. Convergence must never write any of these.
REVIEW_IDENTITY_COLUMNS = ("approved_by", "approved_at", "rejected_by", "rejected_at",
                           "reviewed_by")

INTELLIGENCE_TABLES = ("product_intelligence_review_draft",
                       "product_intelligence_review_field_provenance",
                       "product_intelligence_snapshot",
                       "product")


def _sha(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _is_empty(value) -> bool:
    text = str(value or "").strip()
    return text in ("", "[]", "{}", "null", "None")


def connect(readonly: bool = True) -> sqlite3.Connection:
    uri = f"file:{DB.as_posix()}?mode=ro" if readonly else DB.as_posix()
    con = sqlite3.connect(uri, uri=readonly, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def duplicate_groups(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT product_id FROM product_intelligence_review_draft "
        f"WHERE {SQL_OPEN_PREDICATE} GROUP BY product_id HAVING COUNT(*) > 1"
        " ORDER BY product_id")]


def group_rows(con: sqlite3.Connection, product_id: str) -> dict:
    drafts = [dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        "ORDER BY draft_id", (product_id,))]
    prov = [dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_review_field_provenance WHERE product_id=? "
        "ORDER BY review_provenance_id", (product_id,))]
    return {"product_id": product_id, "drafts": drafts, "provenance": prov}


def plan_for(con: sqlite3.Connection, product_id: str) -> dict:
    """Decide the survivor and classify every field of every loser. No mutation."""
    open_rows = [dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        f"AND {SQL_OPEN_PREDICATE} ORDER BY {SQL_CANONICAL_ORDER}", (product_id,))]
    if len(open_rows) < 2:
        return {"product_id": product_id, "action": "NO_ACTION_REQUIRED",
                "open_draft_count": len(open_rows)}
    winner, losers = open_rows[0], open_rows[1:]
    merges: dict[str, dict] = {}
    conflicts: list[dict] = []
    for loser in losers:
        for column in EVIDENCE_COLUMNS:
            loser_value, winner_value = loser.get(column), winner.get(column)
            if _is_empty(loser_value):
                continue
            if _is_empty(winner_value):
                # winner is silent -> adopting loses nothing
                merges.setdefault(column, {"from_draft_id": loser["draft_id"],
                                           "value": loser_value})
            elif str(winner_value).strip() != str(loser_value).strip():
                # a real disagreement: NEITHER is auto-selected
                conflicts.append({"field": column, "winner_draft_id": winner["draft_id"],
                                  "loser_draft_id": loser["draft_id"]})
    return {
        "product_id": product_id,
        "action": "CONVERGE",
        "canonical_draft_id": winner["draft_id"],
        "canonical_selected_by": "COALESCE(updated_at, created_at) DESC, draft_id DESC",
        "superseded_draft_ids": [row["draft_id"] for row in losers],
        "merge_fields": {k: v["from_draft_id"] for k, v in merges.items()},
        "_merge_values": {k: v["value"] for k, v in merges.items()},
        "conflicting_fields_preserved_unresolved": conflicts,
    }


def table_fingerprint(con: sqlite3.Connection) -> dict:
    """Content hash for the intelligence tables, row counts for everything else."""
    out: dict = {}
    for table in INTELLIGENCE_TABLES:
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
        rows.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
        out[table] = {"rows": len(rows), "content_sha256": _sha(rows)}
    for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if name in INTELLIGENCE_TABLES:
            continue
        out[name] = {"rows": con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]}
    return out


def take_backup(stamp: str) -> dict:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = EVIDENCE_DIR / f"flow_agent.pre_repair.{stamp}.db"
    source = sqlite3.connect(DB.as_posix(), timeout=60)
    target = sqlite3.connect(backup_path.as_posix())
    with target:
        source.backup(target)
    integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
    fk = target.execute("PRAGMA foreign_key_check").fetchall()
    target.close()
    source.close()
    digest = hashlib.sha256()
    with backup_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {"path": str(backup_path), "bytes": backup_path.stat().st_size,
            "integrity_check": integrity, "foreign_key_violations": len(fk),
            "sha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="mutate the canonical DB (default is a read-only plan)")
    parser.add_argument("--plan", action="store_true", help="read-only (default)")
    args = parser.parse_args()
    apply_changes = bool(args.apply)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    con = connect(readonly=True)
    targets = duplicate_groups(con)
    print(f"DUPLICATE_OPEN_GROUPS={len(targets)}")
    for product_id in targets:
        title = con.execute("SELECT raw_product_title FROM product WHERE id=?",
                            (product_id,)).fetchone()
        print(f"  target product_id={product_id} title={title[0] if title else None!r}")
    plans = [plan_for(con, product_id) for product_id in targets]
    before_state = {product_id: group_rows(con, product_id) for product_id in targets}
    before_fingerprint = table_fingerprint(con)
    con.close()

    public_plan = [{k: v for k, v in plan.items() if not k.startswith("_")}
                   for plan in plans]
    plan_digest = _sha(public_plan)
    print(f"REPAIR_PLAN_DIGEST={plan_digest}")
    print(json.dumps(public_plan, indent=2)[:4000])

    if not targets:
        print("NOTHING_TO_REPAIR")
        return 0
    if not apply_changes:
        print("\nPLAN ONLY — nothing was written. Re-run with --apply to execute.")
        return 0

    backup = take_backup(stamp)
    print(f"BACKUP={backup['path']}")
    print(f"BACKUP_SHA256={backup['sha256']}")
    print(f"BACKUP_INTEGRITY_CHECK={backup['integrity_check']}")
    if backup["integrity_check"] != "ok" or backup["foreign_key_violations"]:
        print("ABORT: backup failed its own integrity check")
        return 2

    snapshot = {"stamp": stamp, "plan_digest": plan_digest, "plan": public_plan,
                "before": before_state, "backup": backup}
    snapshot_path = EVIDENCE_DIR / f"canonical_repair_snapshot.{stamp}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str),
                             encoding="utf-8")
    snapshot_sha = _sha(snapshot)
    print(f"SNAPSHOT={snapshot_path}")
    print(f"SNAPSHOT_SHA256={snapshot_sha}")

    # STEP 1 — schema. `SUPERSEDED` is not yet permitted by the live CHECK constraint, so
    # the structural convergence cannot run until the B-586-04 migration has been applied.
    # `init_db` owns that migration (CHECK rebuild -> converge -> UNIQUE index) and is
    # idempotent, so this is the same code path a normal runtime start takes — the repair
    # does not carry a second, divergent copy of the migration.
    import asyncio

    from agent.db import schema as schema_module

    asyncio.run(schema_module.init_db())
    asyncio.run(schema_module.close_db())
    print("MIGRATION_APPLIED (CHECK + convergence + unique index)")

    # STEP 2 — evidence merges. The migration converges STRUCTURALLY (it decides which
    # draft stays open) but deliberately never moves a value between rows. Adopting the
    # fields the winner is silent about is a judgement about evidence, so it happens here,
    # under the recorded plan digest, and only for the two authorized groups.
    write = sqlite3.connect(DB.as_posix(), timeout=60)
    write.row_factory = sqlite3.Row
    write.execute("PRAGMA foreign_keys=ON")
    try:
        with write:
            for plan in plans:
                if plan["action"] != "CONVERGE":
                    continue
                merge_values = plan["_merge_values"]
                if merge_values:
                    sets = ", ".join(f"{column}=?" for column in merge_values)
                    # updated_at is deliberately preserved: convergence is not an edit by
                    # a reviewer and must not look like recent human activity.
                    cursor = write.execute(
                        f"UPDATE product_intelligence_review_draft SET {sets}, "
                        "updated_at=updated_at WHERE draft_id=?",
                        [*merge_values.values(), plan["canonical_draft_id"]])
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            f"merge touched {cursor.rowcount} rows, expected 1")
                for loser_id in plan["superseded_draft_ids"]:
                    # The migration should already have done this. Assert it rather than
                    # assume it: a loser still open here means the two convergence rules
                    # disagreed, which is exactly the class of bug B-586-04 is about.
                    status = write.execute(
                        "SELECT review_status FROM product_intelligence_review_draft "
                        "WHERE draft_id=?", (loser_id,)).fetchone()
                    if status is None or status[0] != SUPERSEDED:
                        raise RuntimeError(
                            f"{loser_id}: expected {SUPERSEDED} after migration, "
                            f"found {status[0] if status else 'MISSING'}")
    finally:
        write.close()
    print("APPLIED")

    # ── proof ────────────────────────────────────────────────────────────────
    con = connect(readonly=True)
    failures: list[str] = []
    remaining = duplicate_groups(con)
    print(f"PROOF duplicate_open_groups_remaining={len(remaining)}")
    if remaining:
        failures.append(f"duplicates remain: {remaining}")

    for plan in plans:
        product_id = plan["product_id"]
        open_now = [dict(r) for r in con.execute(
            "SELECT draft_id FROM product_intelligence_review_draft WHERE product_id=? "
            f"AND {SQL_OPEN_PREDICATE}", (product_id,))]
        print(f"PROOF {product_id} open_drafts={len(open_now)} "
              f"canonical={plan.get('canonical_draft_id')}")
        if len(open_now) != 1 or open_now[0]["draft_id"] != plan["canonical_draft_id"]:
            failures.append(f"{product_id}: wrong survivor {open_now}")
        before_drafts = {d["draft_id"] for d in before_state[product_id]["drafts"]}
        after_drafts = {r[0] for r in con.execute(
            "SELECT draft_id FROM product_intelligence_review_draft WHERE product_id=?",
            (product_id,))}
        if before_drafts != after_drafts:
            failures.append(f"{product_id}: draft rows added/removed")
        before_prov = {p["review_provenance_id"]
                       for p in before_state[product_id]["provenance"]}
        after_prov = {r[0] for r in con.execute(
            "SELECT review_provenance_id FROM "
            "product_intelligence_review_field_provenance WHERE product_id=?",
            (product_id,))}
        if before_prov != after_prov:
            failures.append(f"{product_id}: provenance rows added/removed")
        print(f"PROOF {product_id} drafts_retained={len(after_drafts)} "
              f"provenance_retained={len(after_prov)}")
        for row in con.execute(
                "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
                "AND review_status=?", (product_id, SUPERSEDED)):
            for column in REVIEW_IDENTITY_COLUMNS:
                if row[column] is not None:
                    failures.append(
                        f"{row['draft_id']}: fabricated {column}={row[column]!r}")

    after_fingerprint = table_fingerprint(con)
    touched = [name for name in before_fingerprint
               if before_fingerprint[name] != after_fingerprint.get(name)]
    print(f"PROOF tables_changed={touched}")
    if touched != ["product_intelligence_review_draft"]:
        failures.append(f"non-target tables changed: {touched}")
    con.close()

    proof_path = EVIDENCE_DIR / f"canonical_repair_proof.{stamp}.json"
    proof_path.write_text(json.dumps(
        {"stamp": stamp, "plan_digest": plan_digest, "snapshot_sha256": snapshot_sha,
         "backup": backup, "before_fingerprint": before_fingerprint,
         "after_fingerprint": after_fingerprint, "tables_changed": touched,
         "failures": failures}, indent=2, default=str), encoding="utf-8")
    print(f"PROOF_FILE={proof_path}")

    if failures:
        print("REPAIR_VERDICT=FAILED")
        for failure in failures:
            print(f"  FAIL {failure}")
        return 1
    print("REPAIR_VERDICT=GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
