#!/usr/bin/env python
"""PI-11 targeted PRE_PI11 ROLLBACK — hardened (owner defects 1-8).

Retract the 530 rejected PI-11 approvals (status APPROVED->SUPERSEDED, retained as immutable audit
history), restore the genuine pre-PI-11 authoritative snapshot from the VERIFIED PRE_PI11 backup, or
return the product truthfully to MISSING. Status-only; never deletes history; never writes
product/taxonomy/lifecycle/fixtures/copy. Whole-cohort atomic, CAS-exact, fail-closed.

Modes:
  --dry-run (DEFAULT): verify backups, classify the whole cohort, write the ledger. NO canonical writes.
  --apply            : one BEGIN IMMEDIATE over all 530; verify backups + cohort digest + 318/212/0/0;
                       CAS-exact conditional updates (rowcount==1); COMMIT only if every product
                       passes, else ROLLBACK all. HARD-GATED behind PI11_ROLLBACK_APPLY_APPROVED=1.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, sys, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_DB = (REPO / "flow_agent.db").resolve()
PRE_PI11_BACKUP = (REPO / ".ai" / "backups" / "flow_agent_PRE_PI11_20260802T092351Z.db").resolve()
BACKUP_DIR = REPO / ".ai" / "backups"
AUDIT = REPO / "outputs" / "mission-pi11" / "audit"
PI11_PREFIX = "claude-owner-delegated-pi11"
APPLY_ENV = "PI11_ROLLBACK_APPLY_APPROVED"

# defect 1: the previously-verified PRE_PI11 backup fingerprint (from the containment manifest).
VERIFIED_BACKUP_SHA256 = "2a61093bda0b700e22a37963c59066061dc903438de7cc72937f4571d82bc178"
VERIFIED_BACKUP_SIZE = 275308544

# defect 4: the frozen, authorized plan shape (dry-run of head bee4027).
EXPECTED_COUNTS = {"RESTORE_PRE_PI11": 318, "RETURN_TO_MISSING": 212,
                   "SKIP_POST_PI11_LEGITIMATE_CHANGE": 0, "CONFLICT": 0}
EXPECTED_COHORT_DIGEST = "4ecc22cdac78ebace299063ddc75bd4c6f03a143bf1836a2ee33c63271bfb07f"

# Fix 2: the authorized write-free plan is frozen cryptographically (deterministic JSON of head
# ed903c0+). Apply refuses unless the on-disk plan matches this exact fingerprint AND structure.
AUTHORIZED_PLAN_PATH = REPO / "outputs" / "mission-pi11" / "audit" / "rollback_plan.json"
AUTHORIZED_PLAN_SHA256 = "1492b8ab565c57d918d2f9cda928a3db1aff4ad2ac51e376b312c2e0d4644f56"
AUTHORIZED_PLAN_SIZE = 425129
EXPECTED_COHORT_SIZE = 530

# defect 2: EVERY snapshot column, explicitly classified. STATUS_METADATA is the audited set that
# legitimately changes on a status transition (empirically: exactly status + updated_at across all
# 318 pre-PI-11 snapshots). All other columns are SEMANTIC and part of the content hash. If the live
# schema deviates from KNOWN_SNAPSHOT_COLS the run FAILS CLOSED (a new column must be re-audited).
STATUS_METADATA_COLS = frozenset({"status", "updated_at"})
KNOWN_SNAPSHOT_COLS = frozenset({
    "snapshot_id", "product_id", "version", "status", "product_description", "benefits_json",
    "usp_json", "usage_text", "ingredients_text", "warnings_text", "target_customer_text",
    "paste_anything_summary", "source_urls_json", "image_evidence_json", "package_notes",
    "size_or_volume", "product_form_factor", "packaging_description", "product_truth_lock",
    "claim_gate", "claim_risk_level", "claim_tokens_json", "allowed_claims_json",
    "blocked_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json",
    "confidence_score", "completeness_score", "readiness_status", "created_from_review_draft_id",
    "created_by", "approved_by", "approved_at", "supersedes_snapshot_id", "created_at", "updated_at",
})

FIXTURE_SQL = (
    "(LOWER(TRIM(COALESCE(raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(id,'')) LIKE 'fixture|_%' ESCAPE '|')"
)


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def semantic_cols(con):
    """defect 2: derive the semantic-hash columns from the ACTUAL schema; fail closed on any
    unknown/missing column so a schema change cannot silently weaken the hash."""
    actual = frozenset(r[1] for r in con.execute("PRAGMA table_info(product_intelligence_snapshot)"))
    if actual != KNOWN_SNAPSHOT_COLS:
        raise RuntimeError(f"SCHEMA_FAIL_CLOSED unclassified/missing columns: "
                           f"{sorted(actual ^ KNOWN_SNAPSHOT_COLS)}")
    return sorted(actual - STATUS_METADATA_COLS)


def content_hash(snap, cols):
    return hashlib.sha256(json.dumps({c: snap.get(c) for c in cols}, sort_keys=True,
                                     default=str).encode("utf-8", "replace")).hexdigest()


# Fix 3: the rejected runner ONLY. A corrective snapshot (…-pi11-corrective) is a DIFFERENT,
# legitimate reviewer and must never be treated as a bad snapshot anywhere.
CORRECTIVE_PREFIX = PI11_PREFIX + "-corrective"


def is_bad_pi11(snap):
    by = str((snap or {}).get("approved_by") or "")
    return by.startswith(PI11_PREFIX) and not by.startswith(CORRECTIVE_PREFIX)


# backwards-compatible alias (same exact-bad-reviewer semantics everywhere)
is_pi11 = is_bad_pi11


# ── DB verification (defect 1) ────────────────────────────────────────────────────────────────
def verify_db(path, expect_sha=None, expect_size=None):
    p = Path(path).resolve()
    if not p.exists():
        raise RuntimeError(f"DB_MISSING {p}")
    sha, size = sha256_file(p), p.stat().st_size
    if expect_sha is not None and sha != expect_sha:
        raise RuntimeError(f"DB_SHA_MISMATCH {p}: {sha} != {expect_sha}")
    if expect_size is not None and size != expect_size:
        raise RuntimeError(f"DB_SIZE_MISMATCH {p}: {size} != {expect_size}")
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        con.close()
    if integrity != "ok" or fk:
        raise RuntimeError(f"DB_INTEGRITY_FAIL {p}: integrity={integrity} fk_violations={len(fk)}")
    return {"path": str(p), "sha256": sha, "size_bytes": size, "integrity": integrity, "fk_violations": len(fk)}


def validate_plan_ids(plans_raw):
    """Fix 2: structural validation independent of the file fingerprint — exactly 530 UNIQUE product
    ids and the authorized cohort digest; reject duplicates / unexpected count."""
    ids = [x["product_id"] for x in plans_raw]
    if len(ids) != EXPECTED_COHORT_SIZE:
        raise RuntimeError(f"PLAN_ID_COUNT {len(ids)} != {EXPECTED_COHORT_SIZE}")
    if len(set(ids)) != EXPECTED_COHORT_SIZE:
        dupes = [i for i in set(ids) if ids.count(i) > 1]
        raise RuntimeError(f"PLAN_DUPLICATE_IDS {dupes[:5]}")
    plans = {x["product_id"]: x for x in plans_raw}
    if cohort_digest(plans) != EXPECTED_COHORT_DIGEST:
        raise RuntimeError("PLAN_COHORT_DIGEST_MISMATCH")
    return plans


def verify_plan_file(path=None):
    """Fix 2: refuse to apply unless the on-disk authorized plan matches the exact SHA-256 + byte
    size AND passes structural validation. A mutable local plan is never trusted on digest alone."""
    p = Path(path or AUTHORIZED_PLAN_PATH).resolve()
    if not p.exists():
        raise RuntimeError(f"PLAN_MISSING {p}")
    sha, size = sha256_file(p), p.stat().st_size
    if sha != AUTHORIZED_PLAN_SHA256:
        raise RuntimeError(f"PLAN_SHA_MISMATCH {sha} != {AUTHORIZED_PLAN_SHA256}")
    if size != AUTHORIZED_PLAN_SIZE:
        raise RuntimeError(f"PLAN_SIZE_MISMATCH {size} != {AUTHORIZED_PLAN_SIZE}")
    plans = validate_plan_ids(json.load(open(p, encoding="utf-8")))
    return plans, {"sha256": sha, "size_bytes": size}


def snapshot_live_backup():
    """Fresh consistent online backup of the CURRENT live DB before any mutation (defect 1)."""
    dst = BACKUP_DIR / f"flow_agent_PRE_ROLLBACK_{_utcnow()}.db"
    src = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
    out = sqlite3.connect(str(dst))
    with out:
        src.backup(out)
    out.close(); src.close()
    return verify_db(dst)


# ── classification (defects 3,5) ──────────────────────────────────────────────────────────────
def _cas(snap):
    return {"snapshot_id": snap["snapshot_id"], "product_id": snap["product_id"],
            "version": snap.get("version"), "status": snap.get("status"),
            "approved_by": snap.get("approved_by")}


def classify_rollback(live_snaps, backup_snaps, cols):
    """PURE. Returns the rollback plan for one product, including idempotence states (defect 5)."""
    live_by_id = {s["snapshot_id"]: s for s in live_snaps}
    live_approved = [s for s in live_snaps if s.get("status") == "APPROVED"]
    cur_auth = max(live_approved, key=lambda s: s.get("version") or 0) if live_approved else None
    backup_approved = [s for s in backup_snaps if s.get("status") == "APPROVED"]
    backup_approved_ids = {s["snapshot_id"] for s in backup_approved}
    pre = max(backup_approved, key=lambda s: s.get("version") or 0) if backup_approved else None
    pi11_snaps = [s for s in live_snaps if is_pi11(s)]
    pi11_approved = [s for s in live_approved if is_pi11(s)]

    def base(dec, reason, before=None, after=None, **extra):
        d = {"decision": dec, "reason": reason, "before_authoritative": before, "after_authoritative": after}
        d.update(extra)
        return d

    # no live APPROVED snapshot
    if cur_auth is None:
        if pi11_snaps and all(s.get("status") == "SUPERSEDED" for s in pi11_snaps) and not backup_approved:
            return base("SKIPPED_ALREADY_ROLLED_BACK", "RETURN_TO_MISSING_ALREADY_APPLIED")
        return base("CONFLICT", "NO_LIVE_APPROVED_AND_NOT_A_CLEAN_ROLLBACK")

    # authoritative is a non-PI-11 snapshot
    if not is_pi11(cur_auth):
        pi11_clean = all(s.get("status") == "SUPERSEDED" for s in pi11_snaps) if pi11_snaps else True
        if cur_auth["snapshot_id"] in backup_approved_ids and pi11_clean:
            return base("SKIPPED_ALREADY_ROLLED_BACK", "RESTORE_ALREADY_APPLIED",
                        cur_auth["snapshot_id"], cur_auth["snapshot_id"])
        if cur_auth["snapshot_id"] not in backup_approved_ids:
            if not pi11_clean:
                return base("CONFLICT", "LEGIT_CHANGE_BUT_PI11_STILL_APPROVED",
                            cur_auth["snapshot_id"], cur_auth["snapshot_id"])
            return base("SKIP_POST_PI11_LEGITIMATE_CHANGE", "AUTHORITATIVE_IS_NON_PI11",
                        cur_auth["snapshot_id"], cur_auth["snapshot_id"])
        return base("CONFLICT", "NON_PI11_AUTHORITATIVE_UNEXPECTED_STATE",
                    cur_auth["snapshot_id"], cur_auth["snapshot_id"])

    # authoritative IS a PI-11 snapshot -> rollback required
    retract_cas = [{**_cas(s), "content_hash": content_hash(s, cols)} for s in pi11_approved]
    if pre is not None:
        live_pre = live_by_id.get(pre["snapshot_id"])
        if live_pre is None:
            return base("CONFLICT", "PRE_PI11_SNAPSHOT_ABSENT_IN_LIVE", cur_auth["snapshot_id"])
        if content_hash(live_pre, cols) != content_hash(pre, cols):
            return base("CONFLICT", "PRE_PI11_CONTENT_DRIFT", cur_auth["snapshot_id"])
        if live_pre.get("status") != "SUPERSEDED":
            return base("CONFLICT", f"PRE_PI11_UNEXPECTED_STATUS:{live_pre.get('status')}", cur_auth["snapshot_id"])
        return base("RESTORE_PRE_PI11", "PRE_PI11_APPROVED_SNAPSHOT_EXISTS",
                    cur_auth["snapshot_id"], pre["snapshot_id"], retract_cas=retract_cas,
                    restore_cas={**_cas(live_pre), "content_hash": content_hash(live_pre, cols)})
    return base("RETURN_TO_MISSING", "NO_PRE_PI11_APPROVED_SNAPSHOT",
                cur_auth["snapshot_id"], None, retract_cas=retract_cas, restore_cas=None)


# ── I/O ──────────────────────────────────────────────────────────────────────────────────────
def snapshots(con, pid):
    return [dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE product_id=? ORDER BY version", (pid,))]


def cohort(live):
    rows = live.execute(
        "SELECT DISTINCT s.product_id FROM product_intelligence_snapshot s JOIN product p ON p.id=s.product_id "
        f"WHERE s.approved_by LIKE '{PI11_PREFIX}%' AND s.approved_by NOT LIKE '{PI11_PREFIX}-corrective%' "
        f"AND NOT {FIXTURE_SQL}").fetchall()
    return sorted(r[0] for r in rows)


def cohort_digest(plans):
    h = hashlib.sha256()
    for pid in sorted(plans):
        p = plans[pid]
        h.update((pid + ":" + p["decision"] + ":" + str(p.get("after_authoritative")) + "\n").encode())
    return h.hexdigest()


def _ledger_row(pid, plan, cas_result, txid, committed):
    def snap_state(con, sid):
        if not sid:
            return None
        r = con.execute("SELECT version,status FROM product_intelligence_snapshot WHERE snapshot_id=?", (sid,)).fetchone()
        return {"version": r["version"], "status": r["status"]} if r else None
    return {"product_id": pid, "decision": plan["decision"], "reason": plan.get("reason"),
            "bad_snapshot_id": plan.get("before_authoritative"),
            "restored_snapshot_id": plan.get("after_authoritative"),
            "retract_cas": plan.get("retract_cas"), "restore_cas": plan.get("restore_cas"),
            "cas_result": cas_result, "transaction_id": txid, "committed": committed}


def plan_all(live, backup, ids, cols):
    return {pid: {**classify_rollback(snapshots(live, pid), snapshots(backup, pid), cols),
                  "product_id": pid} for pid in ids}


def write_ledger(name, rows):
    AUDIT.mkdir(parents=True, exist_ok=True)
    with open(AUDIT / name, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return str(AUDIT / name)


# ── apply (defects 3,4,6) — HARD-GATED, atomic, CAS-exact ─────────────────────────────────────
def normalize_counts(counts, expected):
    """Fix 1: normalize every expected decision key (incl. zero-value SKIP/CONFLICT) before compare.
    A raw Counter omits zero keys, so `dict(Counter({RESTORE:318,RETURN:212})) != {…,SKIP:0,CONFLICT:0}`
    would make the production counts check ALWAYS fail. Also guards against leaked extra decisions."""
    normalized = {k: counts.get(k, 0) for k in expected}
    return normalized, (normalized == expected and sum(counts.values()) == sum(expected.values()))


def plan_fingerprint(plan):
    """Content-sensitive fingerprint: decision + authoritative ids + every CAS semantic content hash.
    Any semantic-field drift since the authorized dry-run changes this and aborts the rollback."""
    rc = tuple(sorted((c["snapshot_id"], c["content_hash"]) for c in (plan.get("retract_cas") or [])))
    restore = plan.get("restore_cas")
    return (plan["decision"], plan.get("before_authoritative"), plan.get("after_authoritative"),
            rc, (restore["snapshot_id"], restore["content_hash"]) if restore else None)


def _product_fingerprint(live):
    rows = live.execute("SELECT * FROM product ORDER BY id").fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8", "replace"))
    return h.hexdigest()


def _in(ids):
    ids = list(ids)
    return "(" + ",".join("?" * len(ids)) + ")", ids


def verify_postconditions(live, plans, ids, product_fp_before, total_updates):
    """Fix 4: hard postconditions asserted AFTER all updates, BEFORE COMMIT. Any mismatch raises so
    the whole transaction rolls back. Expected magnitudes are DERIVED from the plans (so this is
    correct for the 530 cohort and for tests)."""
    restore = [p for p in plans.values() if p["decision"] == "RESTORE_PRE_PI11"]
    ret = [p for p in plans.values() if p["decision"] == "RETURN_TO_MISSING"]
    n_restore, n_return = len(restore), len(ret)
    bad_ids = [p["before_authoritative"] for p in (restore + ret)]
    restored_ids = [p["after_authoritative"] for p in restore]
    return_pids = [pid for pid, p in plans.items() if p["decision"] == "RETURN_TO_MISSING"]

    def cnt(sql, params=()):
        return live.execute(sql, params).fetchone()[0]

    # 1. no bad PI-11 snapshot remains APPROVED
    if bad_ids:
        ph, pv = _in(bad_ids)
        if cnt(f"SELECT COUNT(*) FROM product_intelligence_snapshot WHERE status='APPROVED' AND snapshot_id IN {ph}", pv):
            raise RuntimeError("POSTCOND_BAD_STILL_APPROVED")
    # 2. every restored pre-PI-11 snapshot is APPROVED
    if restored_ids:
        ph, pv = _in(restored_ids)
        if cnt(f"SELECT COUNT(*) FROM product_intelligence_snapshot WHERE status='APPROVED' AND snapshot_id IN {ph}", pv) != n_restore:
            raise RuntimeError("POSTCOND_RESTORED_NOT_APPROVED")
    # 3. every returned product has zero APPROVED snapshot
    if return_pids:
        ph, pv = _in(return_pids)
        if cnt(f"SELECT COUNT(DISTINCT product_id) FROM product_intelligence_snapshot WHERE status='APPROVED' AND product_id IN {ph}", pv):
            raise RuntimeError("POSTCOND_RETURN_STILL_APPROVED")
    # 4. affected reconciled + 5. exact status-transition count
    if n_restore + n_return != len(bad_ids):
        raise RuntimeError("POSTCOND_RECONCILE")
    if total_updates != 2 * n_restore + n_return:
        raise RuntimeError(f"POSTCOND_TRANSITIONS {total_updates} != {2 * n_restore + n_return}")
    # 6. no duplicate APPROVED within the affected cohort
    if ids:
        ph, pv = _in(ids)
        dup = live.execute(f"SELECT product_id FROM product_intelligence_snapshot WHERE status='APPROVED' "
                           f"AND product_id IN {ph} GROUP BY product_id HAVING COUNT(*)>1", pv).fetchall()
        if dup:
            raise RuntimeError(f"POSTCOND_DUP_APPROVED {len(dup)}")
        # 7. no fixture id in the affected cohort
        if cnt(f"SELECT COUNT(*) FROM product p WHERE p.id IN {ph} AND {FIXTURE_SQL}", pv):
            raise RuntimeError("POSTCOND_FIXTURE_INCLUDED")
    # 8. product/lifecycle rows unchanged
    if _product_fingerprint(live) != product_fp_before:
        raise RuntimeError("POSTCOND_PRODUCT_TABLE_CHANGED")
    # 9. referential integrity
    if live.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("POSTCOND_FK_VIOLATION")


def execute_cohort(live, backup, cols, ids, frozen_plans, expected_counts, expected_digest, txid):
    """One BEGIN IMMEDIATE over the WHOLE cohort. Re-reads/reclassifies all, verifies counts + cohort
    digest + that each product's live fingerprint still matches the AUTHORIZED frozen plan (catches
    semantic drift), then CAS-exact conditional updates (rowcount==1). COMMIT only if every product
    passes; one failure ROLLs BACK ALL. Returns (committed, ledger)."""
    ledger, committed, total_updates = [], False, 0
    try:
        live.execute("BEGIN IMMEDIATE")
        product_fp_before = _product_fingerprint(live)
        plans = plan_all(live, backup, ids, cols)
        counts = Counter(p["decision"] for p in plans.values())
        normalized, ok = normalize_counts(counts, expected_counts)
        if not ok:
            raise RuntimeError(f"COUNTS_MISMATCH {normalized} != {expected_counts} (raw {dict(counts)})")
        if cohort_digest(plans) != expected_digest:
            raise RuntimeError("COHORT_DIGEST_MISMATCH")
        for pid in ids:
            plan = plans[pid]
            frozen = frozen_plans.get(pid)
            if frozen is None or plan_fingerprint(plan) != plan_fingerprint(frozen):
                raise RuntimeError(f"DRIFT_SINCE_AUTHORIZED_PLAN {pid}")
            if plan["decision"] in ("SKIP_POST_PI11_LEGITIMATE_CHANGE", "SKIPPED_ALREADY_ROLLED_BACK"):
                ledger.append(_ledger_row(pid, plan, "SKIP", txid, None)); continue
            if plan["decision"] == "CONFLICT":
                raise RuntimeError(f"CONFLICT_IN_COHORT {pid}:{plan['reason']}")
            for cas in plan["retract_cas"]:
                row = live.execute("SELECT * FROM product_intelligence_snapshot WHERE snapshot_id=?",
                                   (cas["snapshot_id"],)).fetchone()
                if row is None or content_hash(dict(row), cols) != cas["content_hash"]:
                    raise RuntimeError(f"CAS_HASH_MISMATCH_RETRACT {cas['snapshot_id']}")
                n = live.execute(
                    "UPDATE product_intelligence_snapshot SET status='SUPERSEDED' WHERE snapshot_id=? "
                    "AND product_id=? AND version=? AND status='APPROVED' AND approved_by LIKE ? "
                    "AND approved_by NOT LIKE ?",
                    (cas["snapshot_id"], cas["product_id"], cas["version"],
                     PI11_PREFIX + "%", CORRECTIVE_PREFIX + "%")).rowcount
                if n != 1:
                    raise RuntimeError(f"CAS_ROWCOUNT_RETRACT {cas['snapshot_id']} n={n}")
                total_updates += n
            if plan["decision"] == "RESTORE_PRE_PI11":
                rc = plan["restore_cas"]
                row = live.execute("SELECT * FROM product_intelligence_snapshot WHERE snapshot_id=?",
                                   (rc["snapshot_id"],)).fetchone()
                if row is None or content_hash(dict(row), cols) != rc["content_hash"]:
                    raise RuntimeError(f"CAS_HASH_MISMATCH_RESTORE {rc['snapshot_id']}")
                n = live.execute(
                    "UPDATE product_intelligence_snapshot SET status='APPROVED' WHERE snapshot_id=? "
                    "AND product_id=? AND version=? AND status='SUPERSEDED'",
                    (rc["snapshot_id"], rc["product_id"], rc["version"])).rowcount
                if n != 1:
                    raise RuntimeError(f"CAS_ROWCOUNT_RESTORE {rc['snapshot_id']} n={n}")
                total_updates += n
            ledger.append(_ledger_row(pid, plan, "APPLIED", txid, None))
        verify_postconditions(live, plans, ids, product_fp_before, total_updates)
        live.execute("COMMIT")
        committed = True
    except Exception as exc:
        live.execute("ROLLBACK")
        ledger.append({"transaction_id": txid, "committed": False, "aborted": str(exc)})
    for r in ledger:
        r["committed"] = committed
    return committed, ledger


def apply_rollback():
    backup_meta = verify_db(PRE_PI11_BACKUP, VERIFIED_BACKUP_SHA256, VERIFIED_BACKUP_SIZE)  # Fix 1
    frozen_plans, plan_meta = verify_plan_file()  # Fix 2: cryptographically frozen authorized plan
    live_backup_meta = snapshot_live_backup()  # Fix 1: fresh online backup BEFORE mutation
    txid = "rb-" + uuid.uuid4().hex[:16]
    live = sqlite3.connect(str(LIVE_DB)); live.row_factory = sqlite3.Row
    live.execute("PRAGMA foreign_keys=ON")
    backup = sqlite3.connect(f"file:{PRE_PI11_BACKUP.as_posix()}?mode=ro", uri=True); backup.row_factory = sqlite3.Row
    cols = semantic_cols(live)
    if semantic_cols(backup) != cols:
        raise RuntimeError("SCHEMA_FAIL_CLOSED live/backup snapshot schema differ")
    ids = cohort(live)
    committed, ledger = execute_cohort(live, backup, cols, ids, frozen_plans,
                                       EXPECTED_COUNTS, EXPECTED_COHORT_DIGEST, txid)
    result = {"transaction_id": txid, "committed": committed, "backup": backup_meta,
              "authorized_plan": plan_meta, "live_backup": live_backup_meta,
              "counts": dict(Counter(r.get("decision") for r in ledger))}
    if committed:
        result["post_integrity"] = live.execute("PRAGMA integrity_check").fetchone()[0]  # Fix 4 post-commit
        result["post_fk_violations"] = len(live.execute("PRAGMA foreign_key_check").fetchall())
    else:  # Fix 5: surface the abort reason
        result["abort_reason"] = next((r.get("aborted") for r in ledger if r.get("aborted")), "UNKNOWN")
    write_ledger("rollback_ledger_apply.jsonl", ledger)
    live.close(); backup.close()
    return result


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
        res = apply_rollback()
        print("APPLY:", json.dumps(res, default=str))
        if not res.get("committed"):  # Fix 5: a rolled-back transaction must exit non-zero
            print("ABORTED_ROLLED_BACK:", res.get("abort_reason"))
            sys.exit(1)
        return

    # write-free: verify backup, classify, ledger
    backup_meta = verify_db(PRE_PI11_BACKUP, VERIFIED_BACKUP_SHA256, VERIFIED_BACKUP_SIZE)
    live = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True); live.row_factory = sqlite3.Row
    backup = sqlite3.connect(f"file:{PRE_PI11_BACKUP.as_posix()}?mode=ro", uri=True); backup.row_factory = sqlite3.Row
    cols = semantic_cols(live)
    ids = cohort(live)
    plans = plan_all(live, backup, ids, cols)
    txid = "dry-" + uuid.uuid4().hex[:16]
    ledger = [_ledger_row(pid, plans[pid], "PLANNED", txid, "DRY_RUN") for pid in ids]
    write_ledger("rollback_ledger_dryrun.jsonl", ledger)
    with open(AUDIT / a.out, "w", encoding="utf-8") as fh:
        json.dump([plans[pid] for pid in ids], fh, indent=1, ensure_ascii=False, default=str)
    live.close(); backup.close()
    counts = Counter(p["decision"] for p in plans.values())
    print("ROLLBACK DRY-RUN (no writes). counts:", dict(counts))
    print("reconciliation sum:", sum(counts.values()), "== cohort", len(ids))
    print("cohort_digest:", cohort_digest(plans))
    print("backup verified:", backup_meta["sha256"][:16], "integrity", backup_meta["integrity"])
    print("semantic hash columns:", len(cols), "of", len(KNOWN_SNAPSHOT_COLS), "(excl status,updated_at)")


if __name__ == "__main__":
    main()
