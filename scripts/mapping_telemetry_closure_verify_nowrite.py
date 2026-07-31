#!/usr/bin/env python
"""BOSMAX-MAPPING-TELEMETRY-CLOSURE-01 — canonical DB no-write proof.

Recomputes the content sha256 of the mutable tables and compares to
db_integrity_baseline.json. Exit 0 + PASS only if every hash is identical — i.e. this
mission's read-only audit + dry-run mutated nothing in the canonical database.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "flow_agent.db"
BASELINE = REPO / "docs" / "evidence" / "mapping-telemetry-closure-01" / "db_integrity_baseline.json"


def _hash(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    h = hashlib.sha256()
    for row in cur.execute(f"SELECT * FROM {table} ORDER BY rowid"):
        h.update(repr(tuple(row)).encode("utf-8", "replace"))
    return count, h.hexdigest()


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["tables"]
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=10)
    cur = con.cursor()
    ok = True
    for table, base in baseline.items():
        count, digest = _hash(cur, table)
        match = (count == base["row_count"] and digest == base["sha256"])
        ok = ok and match
        print(f"  {table:32} rows {count} {'==' if count==base['row_count'] else '!='} {base['row_count']} "
              f"| sha256 {'MATCH' if digest==base['sha256'] else 'MISMATCH'}")
    con.close()
    print("NO-WRITE PROOF:", "PASS — canonical DB unchanged" if ok else "FAIL — canonical DB CHANGED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
