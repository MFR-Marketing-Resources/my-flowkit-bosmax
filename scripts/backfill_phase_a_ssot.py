"""SSOT Phase A backfill — set `product.bosmax_product_family` for existing products.

The family had no DB column and was re-derived by every consumer, so it drifted
(root of the sensitive-mislabel bug class). Phase A gives it a column; this script
backfills the existing catalogue by deriving the family from each product's stored
title + taxonomy — a PURE, DETERMINISTIC computation (no provider, zero credit cost).

hook_angles / cta_angles / pain_points are deliberately NOT backfilled: they were
dropped at commit historically with no recoverable source. New commits carry them
forward from the operator's registration draft.

Usage:
    python -m scripts.backfill_phase_a_ssot            # DRY-RUN: report only
    python -m scripts.backfill_phase_a_ssot --apply    # write (after a DB backup)

Idempotent: only fills rows where bosmax_product_family IS NULL / ''.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

from agent.config import BASE_DIR
from agent.services.product_intelligence_service import (
    resolve_product_intelligence_profile,
)

DB_PATH = BASE_DIR / "flow_agent.db"


def _derive_family(row: sqlite3.Row) -> str:
    profile = resolve_product_intelligence_profile(
        {
            "id": row["id"],
            "raw_product_title": row["raw_product_title"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "type": row["type"],
        }
    )
    return str(profile.get("bosmax_product_family") or "UNKNOWN_REVIEW_REQUIRED")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write changes (default is a dry-run report)")
    args = parser.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    columns = {r[1] for r in con.execute("PRAGMA table_info(product)")}
    has_column = "bosmax_product_family" in columns

    select_cols = "id, raw_product_title, category, subcategory, type"
    if has_column:
        select_cols += ", bosmax_product_family"
    rows = con.execute(f"SELECT {select_cols} FROM product").fetchall()

    distribution: Counter[str] = Counter()
    to_write: list[tuple[str, str]] = []
    for row in rows:
        family = _derive_family(row)
        distribution[family] += 1
        current = row["bosmax_product_family"] if has_column else None
        if not (current or "").strip():
            to_write.append((family, row["id"]))

    print(f"DB: {DB_PATH}")
    print(f"products scanned: {len(rows)} | bosmax_product_family column exists: {has_column}")
    print("derived family distribution:")
    for fam, n in distribution.most_common():
        print(f"  {fam:28s} {n}")
    print(f"rows that would be filled (currently empty): {len(to_write)}")

    if not args.apply:
        print("\nDRY-RUN — no changes written. Re-run with --apply to persist.")
        con.close()
        return 0

    if not has_column:
        print("\nERROR: column `bosmax_product_family` is missing. Deploy the schema "
              "migration (restart the runtime) before --apply.", file=sys.stderr)
        con.close()
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{DB_PATH}.prebackfill-{stamp}"
    shutil.copyfile(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    con.executemany(
        "UPDATE product SET bosmax_product_family=? "
        "WHERE id=? AND (bosmax_product_family IS NULL OR bosmax_product_family='')",
        to_write,
    )
    con.commit()
    con.close()
    print(f"applied {len(to_write)} updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
