#!/usr/bin/env python
"""BOSMAX-MAPPING-TELEMETRY-CLOSURE-01 — read-only forensic audit + integrity baseline.

ZERO mutation: opens the canonical DB read-only (mode=ro) and only runs SELECTs.
Emits machine-readable evidence under docs/evidence/mapping-telemetry-closure-01/:
  - audit.json                  (every metric with its exact SQL + result)
  - db_integrity_baseline.json  (row counts + content sha256 of mutable tables)

Re-runnable: the audit is deterministic; db_integrity lets a later re-run prove the
canonical DB did not change (no-write proof). No credentials/tokens/personal paths.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "flow_agent.db"
OUT = REPO / "docs" / "evidence" / "mapping-telemetry-closure-01"

ACTIVE = "lifecycle_status='ACTIVE'"

# label -> SQL. Every number in the report traces to one of these.
QUERIES: dict[str, str] = {
    "active_total": f"SELECT COUNT(*) FROM product WHERE {ACTIVE}",
    "mapping_status_distribution_all": "SELECT COALESCE(mapping_status,'(null)') k, COUNT(*) n FROM product GROUP BY mapping_status ORDER BY n DESC",
    "mapping_status_distribution_active": f"SELECT COALESCE(mapping_status,'(null)') k, COUNT(*) n FROM product WHERE {ACTIVE} GROUP BY mapping_status ORDER BY n DESC",
    "active_mapping_null": f"SELECT COUNT(*) FROM product WHERE {ACTIVE} AND mapping_status IS NULL",
    "active_mapping_blocked": f"SELECT COUNT(*) FROM product WHERE {ACTIVE} AND mapping_status='BLOCKED'",
    "active_prompt_missing_fields": f"SELECT COUNT(*) FROM product WHERE {ACTIVE} AND prompt_readiness_status='MISSING_FIELDS'",
    "overlap_blocked_and_prompt_missing": f"SELECT COUNT(*) FROM product WHERE {ACTIVE} AND mapping_status='BLOCKED' AND prompt_readiness_status='MISSING_FIELDS'",
    "missing_copy_active": f"SELECT COUNT(*) FROM product p WHERE {ACTIVE} AND NOT EXISTS(SELECT 1 FROM copy_set c WHERE c.product_id=p.id AND COALESCE(c.archived,0)=0)",
    "missing_copy_by_mapping_status": f"SELECT COALESCE(mapping_status,'(null)') k, COUNT(*) n FROM product p WHERE {ACTIVE} AND NOT EXISTS(SELECT 1 FROM copy_set c WHERE c.product_id=p.id AND COALESCE(c.archived,0)=0) GROUP BY mapping_status ORDER BY n DESC",
    "missing_copy_with_intel_snapshot": f"SELECT COUNT(*) FROM product p WHERE {ACTIVE} AND NOT EXISTS(SELECT 1 FROM copy_set c WHERE c.product_id=p.id AND COALESCE(c.archived,0)=0) AND EXISTS(SELECT 1 FROM product_intelligence_snapshot s WHERE s.product_id=p.id)",
    "missing_intel_active": f"SELECT COUNT(*) FROM product p WHERE {ACTIVE} AND NOT EXISTS(SELECT 1 FROM product_intelligence_snapshot s WHERE s.product_id=p.id)",
    "active_by_source": f"SELECT COALESCE(source,'(null)') k, COUNT(*) n FROM product WHERE {ACTIVE} GROUP BY source ORDER BY n DESC",
}
# NOTE: failed-generation telemetry / dead-DOM classification is intentionally NOT in this
# mapping audit — it belongs to the failed-generation reporting PR (separate concern).

# Tables this workstream could theoretically mutate — content-hashed for a no-write proof.
INTEGRITY_TABLES = ["product", "product_strategy_taxonomy", "request_telemetry"]


def _fetch(cur, sql):
    rows = cur.execute(sql).fetchall()
    if len(rows) == 1 and len(rows[0]) == 1:
        return rows[0][0]
    if rows and len(rows[0]) == 2:
        return [{"key": r[0], "count": r[1]} for r in rows]
    return [list(r) for r in rows]


def _table_content_hash(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    h = hashlib.sha256()
    # order-stable: rowid ascending; hash the repr of every row
    for row in cur.execute(f"SELECT * FROM {table} ORDER BY rowid"):
        h.update(repr(tuple(row)).encode("utf-8", "replace"))
    return {"row_count": count, "sha256": h.hexdigest()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=10)
    cur = con.cursor()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    audit = {label: {"sql": sql, "result": _fetch(cur, sql)} for label, sql in QUERIES.items()}

    (OUT / "audit.json").write_text(
        json.dumps({"mission": "BOSMAX-MAPPING-TELEMETRY-CLOSURE-01",
                    "generated_at_utc": stamp, "db_file": DB.name, "audit": audit}, indent=2),
        encoding="utf-8",
    )

    integrity = {t: _table_content_hash(cur, t) for t in INTEGRITY_TABLES}
    (OUT / "db_integrity_baseline.json").write_text(
        json.dumps({"mission": "BOSMAX-MAPPING-TELEMETRY-CLOSURE-01",
                    "generated_at_utc": stamp, "db_file": DB.name,
                    "purpose": "no-write proof — re-run after any work; hashes must be identical",
                    "tables": integrity}, indent=2),
        encoding="utf-8",
    )
    con.close()

    print(f"WROTE {OUT / 'audit.json'}")
    print(f"WROTE {OUT / 'db_integrity_baseline.json'}")
    for t, v in integrity.items():
        print(f"  integrity {t}: rows={v['row_count']} sha256={v['sha256'][:16]}…")


if __name__ == "__main__":
    main()
