"""SSOT Phase B backfill — populate cluster + product_type_group on existing
FastMoss queue rows from their linked registration draft's strategy_taxonomy.

The creative taxonomy (cluster / product_type_group) is already AUTO_DERIVED into
every registration draft; the queue table just never carried it. Going forward the
recompute + save-sync paths write it; this fills the rows that already exist by
reading each row's draft payload. Pure JSON/SQL — no provider, zero credit cost.

Usage:
    python -m scripts.backfill_phase_b_queue_taxonomy            # DRY-RUN
    python -m scripts.backfill_phase_b_queue_taxonomy --apply    # write (backs up first)

Idempotent: only fills rows whose cluster IS NULL / ''.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

from agent.config import BASE_DIR

DB_PATH = BASE_DIR / "flow_agent.db"


def _clean(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write changes (default is a dry-run report)")
    args = parser.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # draft_id -> (cluster, product_type_group) from each draft's strategy_taxonomy
    draft_tax: dict[str, tuple[str | None, str | None]] = {}
    for row in con.execute(
        "SELECT draft_id, payload_json FROM product_registration_review_draft"
    ):
        try:
            payload = json.loads(row["payload_json"])
        except (ValueError, TypeError):
            continue
        strategy = payload.get("strategy_taxonomy") or {}
        cluster = _clean(strategy.get("cluster"))
        ptg = _clean(strategy.get("product_type_group"))
        if cluster or ptg:
            draft_tax[row["draft_id"]] = (cluster, ptg)

    # committed rows: product_id -> taxonomy from product_strategy_taxonomy
    prod_tax: dict[str, tuple[str | None, str | None]] = {}
    for row in con.execute(
        "SELECT product_id, cluster, product_type_group FROM product_strategy_taxonomy"
    ):
        cluster = _clean(row["cluster"])
        ptg = _clean(row["product_type_group"])
        if cluster or ptg:
            prod_tax[row["product_id"]] = (cluster, ptg)

    has_column = "cluster" in {
        r[1] for r in con.execute("PRAGMA table_info(fastmoss_bulk_draft_status)")
    }
    select_cols = "reference_id, draft_id, committed_product_id" + (
        ", cluster" if has_column else "")
    rows = con.execute(
        f"SELECT {select_cols} FROM fastmoss_bulk_draft_status"
    ).fetchall()

    to_write: list[tuple[str | None, str | None, str]] = []
    distribution: Counter[str] = Counter()
    no_draft_taxonomy = 0
    for row in rows:
        if has_column and _clean(row["cluster"]):  # idempotent — already filled
            continue
        tax = draft_tax.get(row["draft_id"])
        if not tax:  # committed rows carry taxonomy on the product, not a draft
            tax = prod_tax.get(row["committed_product_id"])
        if not tax:
            no_draft_taxonomy += 1
            continue
        cluster, ptg = tax
        to_write.append((cluster, ptg, row["reference_id"]))
        distribution[cluster or "(none)"] += 1

    print(f"DB: {DB_PATH}")
    print(f"queue rows: {len(rows)} | drafts with taxonomy: {len(draft_tax)}")
    print(f"rows that would be filled: {len(to_write)} | "
          f"empty rows with no draft taxonomy (left as-is): {no_draft_taxonomy}")
    print("cluster distribution of filled rows:")
    for cluster, n in distribution.most_common():
        print(f"  {cluster:28s} {n}")

    if not args.apply:
        print("\nDRY-RUN — no changes written. Re-run with --apply to persist.")
        con.close()
        return 0

    if not has_column:
        print("\nERROR: column `cluster` is missing on fastmoss_bulk_draft_status. "
              "Deploy the schema migration (restart the runtime) before --apply.",
              file=sys.stderr)
        con.close()
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{DB_PATH}.prebackfill-b-{stamp}"
    shutil.copyfile(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    con.executemany(
        "UPDATE fastmoss_bulk_draft_status SET cluster=?, product_type_group=? "
        "WHERE reference_id=? AND (cluster IS NULL OR cluster='')",
        to_write,
    )
    con.commit()
    con.close()
    print(f"applied {len(to_write)} updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
