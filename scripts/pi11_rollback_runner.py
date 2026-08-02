#!/usr/bin/env python
"""PI-11 targeted PRE_PI11 ROLLBACK (owner decision after both corrective projections were rejected).

The 530 PI-11 approvals were produced by the rejected runner and must not remain authoritative. This
runner RETRACTS each bad PI-11 approval and restores the genuine pre-PI-11 authoritative snapshot
(from the verified PRE_PI11 backup) where one existed, else returns the product truthfully to
MISSING_APPROVED_INTELLIGENCE. Bad snapshots are RETAINED as immutable audit history (status
SUPERSEDED); nothing is deleted; `product`/taxonomy/lifecycle/fixtures/copy tables are never touched.

Per product, classify against the PRE_PI11 backup:
  RESTORE_PRE_PI11               a genuine pre-PI-11 APPROVED snapshot existed -> restore it, retract PI-11
  RETURN_TO_MISSING             none existed -> retract PI-11, product returns to MISSING
  SKIP_POST_PI11_LEGITIMATE_CHANGE  a legitimate non-PI-11 snapshot became authoritative AFTER the bad run -> preserve
  CONFLICT                       CAS mismatch (fail closed, ledgered)

CAS guards (verified again at apply time): exact snapshot id, current status, reviewer prefix,
version, and content-hash. Any mismatch fails closed for that product.

Modes:
  --dry-run (DEFAULT): classify the whole cohort vs the backup. WRITES NOTHING.
  --apply            : perform the status-only rollback transactionally with CAS. HARD-GATED behind
                       PI11_ROLLBACK_APPLY_APPROVED=1. NOT run in this phase.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_DB = str(REPO / "flow_agent.db")
PRE_PI11_BACKUP = str(REPO / ".ai" / "backups" / "flow_agent_PRE_PI11_20260802T092351Z.db")
PI11_PREFIX = "claude-owner-delegated-pi11"
APPLY_ENV = "PI11_ROLLBACK_APPLY_APPROVED"

FIXTURE_SQL = (
    "(LOWER(TRIM(COALESCE(raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(id,'')) LIKE 'fixture|_%' ESCAPE '|')"
)

# immutable CONTENT columns hashed for CAS (excludes volatile status/updated_at metadata)
CONTENT_COLS = ("snapshot_id", "product_id", "version", "approved_by", "product_description",
                "benefits_json", "usp_json", "usage_text", "ingredients_text", "warnings_text",
                "target_customer_text", "allowed_claims_json", "blocked_claims_json",
                "buyer_persona_snapshot_json", "copy_strategy_summary_json", "source_urls_json",
                "image_evidence_json", "claim_gate", "claim_risk_level", "readiness_status",
                "completeness_score")


def is_pi11(snap):
    return str((snap or {}).get("approved_by") or "").startswith(PI11_PREFIX)


def content_hash(snap):
    return hashlib.sha256(json.dumps({k: snap.get(k) for k in CONTENT_COLS}, sort_keys=True,
                                     default=str).encode("utf-8", "replace")).hexdigest()


def classify_rollback(live_snaps, backup_snaps):
    """PURE. Given a product's live and backup snapshots (lists of dicts), return the rollback plan."""
    live_by_id = {s["snapshot_id"]: s for s in live_snaps}
    live_approved = [s for s in live_snaps if s.get("status") == "APPROVED"]
    cur_auth = max(live_approved, key=lambda s: s.get("version") or 0) if live_approved else None
    backup_approved = [s for s in backup_snaps if s.get("status") == "APPROVED"]
    pre = max(backup_approved, key=lambda s: s.get("version") or 0) if backup_approved else None

    if cur_auth is None:
        return {"decision": "CONFLICT", "reason": "NO_LIVE_APPROVED_SNAPSHOT",
                "before_authoritative": None, "after_authoritative": None}

    if not is_pi11(cur_auth):
        # a legitimate non-PI-11 snapshot is authoritative (created after the bad run) -> preserve
        return {"decision": "SKIP_POST_PI11_LEGITIMATE_CHANGE",
                "reason": "AUTHORITATIVE_IS_NON_PI11",
                "before_authoritative": cur_auth["snapshot_id"],
                "after_authoritative": cur_auth["snapshot_id"]}

    # current authoritative IS a PI-11 snapshot -> rollback required
    retract = [s for s in live_approved if is_pi11(s)]
    retract_cas = [{"snapshot_id": s["snapshot_id"], "status": "APPROVED", "version": s.get("version"),
                    "reviewer_prefix": PI11_PREFIX, "content_hash": content_hash(s)} for s in retract]

    if pre is not None:
        live_pre = live_by_id.get(pre["snapshot_id"])
        if live_pre is None:
            return {"decision": "CONFLICT", "reason": "PRE_PI11_SNAPSHOT_ABSENT_IN_LIVE",
                    "before_authoritative": cur_auth["snapshot_id"], "after_authoritative": None}
        if content_hash(live_pre) != content_hash(pre):
            return {"decision": "CONFLICT", "reason": "PRE_PI11_CONTENT_DRIFT",
                    "before_authoritative": cur_auth["snapshot_id"], "after_authoritative": None}
        return {"decision": "RESTORE_PRE_PI11", "reason": "PRE_PI11_APPROVED_SNAPSHOT_EXISTS",
                "before_authoritative": cur_auth["snapshot_id"],
                "after_authoritative": pre["snapshot_id"],
                "retract_cas": retract_cas,
                "restore_cas": {"snapshot_id": live_pre["snapshot_id"], "status": live_pre.get("status"),
                                "version": live_pre.get("version"), "content_hash": content_hash(live_pre)}}
    return {"decision": "RETURN_TO_MISSING", "reason": "NO_PRE_PI11_APPROVED_SNAPSHOT",
            "before_authoritative": cur_auth["snapshot_id"], "after_authoritative": None,
            "retract_cas": retract_cas, "restore_cas": None}


# ── I/O ──────────────────────────────────────────────────────────────────────────────────────
def snapshots(con, pid):
    return [dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE product_id=? ORDER BY version", (pid,))]


def cohort(live):
    rows = live.execute(
        "SELECT DISTINCT s.product_id FROM product_intelligence_snapshot s JOIN product p ON p.id=s.product_id "
        f"WHERE s.approved_by LIKE '{PI11_PREFIX}%' AND s.approved_by NOT LIKE '{PI11_PREFIX}-corrective%' "
        f"AND NOT {FIXTURE_SQL}").fetchall()
    return [r[0] for r in rows]


def plan_all(live, backup, ids):
    out = []
    for pid in ids:
        plan = classify_rollback(snapshots(live, pid), snapshots(backup, pid))
        plan["product_id"] = pid
        out.append(plan)
    return out


def apply_one_rollback(live, backup, pid, plan=None):
    """Status-only, transactional, CAS-guarded rollback for ONE product on the given connections.
    If `plan` is provided (a dry-run plan) it is VERIFIED against live now (CAS catches any drift
    since the plan was computed); otherwise it is classified fresh. Fail-closed: any CAS drift rolls
    back the product's transaction, leaving no partial state."""
    if plan is None:
        plan = classify_rollback(snapshots(live, pid), snapshots(backup, pid))
    if plan["decision"] in ("SKIP_POST_PI11_LEGITIMATE_CHANGE", "CONFLICT"):
        return {"product_id": pid, "result": plan["decision"], "reason": plan.get("reason")}
    try:
        live.execute("BEGIN")
        # re-verify CAS against the live rows NOW (fail closed on any drift)
        for cas in plan["retract_cas"]:
            row = live.execute("SELECT * FROM product_intelligence_snapshot WHERE snapshot_id=?",
                               (cas["snapshot_id"],)).fetchone()
            if row is None or row["status"] != "APPROVED" or content_hash(dict(row)) != cas["content_hash"] \
                    or not str(row["approved_by"] or "").startswith(PI11_PREFIX):
                raise RuntimeError(f"CAS_MISMATCH_RETRACT {cas['snapshot_id']}")
        if plan["decision"] == "RESTORE_PRE_PI11":
            rc = plan["restore_cas"]
            row = live.execute("SELECT * FROM product_intelligence_snapshot WHERE snapshot_id=?",
                               (rc["snapshot_id"],)).fetchone()
            if row is None or content_hash(dict(row)) != rc["content_hash"]:
                raise RuntimeError(f"CAS_MISMATCH_RESTORE {rc['snapshot_id']}")
        # status-only transitions: retract bad PI-11 -> SUPERSEDED; restore pre-PI-11 -> APPROVED
        for cas in plan["retract_cas"]:
            live.execute("UPDATE product_intelligence_snapshot SET status='SUPERSEDED' "
                         "WHERE snapshot_id=? AND status='APPROVED'", (cas["snapshot_id"],))
        if plan["decision"] == "RESTORE_PRE_PI11":
            live.execute("UPDATE product_intelligence_snapshot SET status='APPROVED' WHERE snapshot_id=?",
                         (plan["restore_cas"]["snapshot_id"],))
        live.execute("COMMIT")
        return {"product_id": pid, "result": plan["decision"], "after_authoritative": plan["after_authoritative"]}
    except Exception as exc:
        live.execute("ROLLBACK")
        return {"product_id": pid, "result": "CONFLICT", "reason": str(exc)}


def apply_rollback(ids):
    """Status-only, transactional, CAS-guarded rollback. HARD-GATED. NOT run in the dry-run phase."""
    backup = sqlite3.connect(f"file:{Path(PRE_PI11_BACKUP).as_posix()}?mode=ro", uri=True)
    backup.row_factory = sqlite3.Row
    live = sqlite3.connect(LIVE_DB)
    live.row_factory = sqlite3.Row
    live.execute("PRAGMA foreign_keys=ON")
    results = [apply_one_rollback(live, backup, pid) for pid in ids]
    live.close()
    backup.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="rollback_plan.json")
    a = ap.parse_args()
    if a.apply:
        if os.environ.get(APPLY_ENV) != "1":
            print(f"REFUSED: --apply is hard-gated. Set {APPLY_ENV}=1 only under explicit owner authorization.")
            sys.exit(2)
        live = sqlite3.connect(f"file:{Path(LIVE_DB).as_posix()}?mode=ro", uri=True)
        live.row_factory = sqlite3.Row
        ids = cohort(live)
        live.close()
        from collections import Counter
        res = apply_rollback(ids)
        print("APPLY results:", dict(Counter(r["result"] for r in res)))
        return

    live = sqlite3.connect(f"file:{Path(LIVE_DB).as_posix()}?mode=ro", uri=True)
    live.row_factory = sqlite3.Row
    backup = sqlite3.connect(f"file:{Path(PRE_PI11_BACKUP).as_posix()}?mode=ro", uri=True)
    backup.row_factory = sqlite3.Row
    ids = cohort(live)
    res = plan_all(live, backup, ids)
    live.close()
    backup.close()
    out = REPO / "outputs" / "mission-pi11" / "audit" / a.out
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, default=str)
    from collections import Counter
    dec = Counter(r["decision"] for r in res)
    print("ROLLBACK DRY-RUN (no writes). decisions:", dict(dec), "| total", len(res))
    print("reconciliation sum:", sum(dec.values()), "== cohort", len(ids))
    print("report ->", out)


if __name__ == "__main__":
    main()
