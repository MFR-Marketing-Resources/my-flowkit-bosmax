"""Map the registration-queue drafts that are missing a cluster / product type by
running the DETERMINISTIC recompute (enable_text_assist=False) on each.

These are uncommitted FastMoss drafts whose strategy taxonomy was never derived
(blocked on evidence / duplicate-suspected). The cluster/product_type_group come
from the SAME deterministic keyword classifier the pipeline uses — no paid
provider call — so this is ZERO AI/credit cost. It derives the taxonomy at the
DRAFT level (authority) and syncs it to the queue row; it does NOT unblock the
draft for commit (evidence/duplicate resolution is separate registration work).

Drafts whose category/title genuinely match no rule stay generic_unclassified and
remain in the backlog (honest, not silently cleared).

Usage:
    python scripts/map_pending_draft_clusters.py            # dry-run (no writes)
    python scripts/map_pending_draft_clusters.py --apply    # persist + sync
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "flow_agent.db"
_GENERIC = {None, "", "generic_unclassified"}

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _reconfig_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _pending_rows() -> list[tuple[str, str, str]]:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    pred = (
        "(committed_product_id IS NULL OR TRIM(committed_product_id) = '') "
        "AND (cluster IS NULL OR TRIM(cluster) = '' OR cluster = 'generic_unclassified')"
    )
    rows = [
        (str(r["draft_id"] or ""), str(r["reference_id"] or ""), str(r["raw_product_title"] or ""))
        for r in con.execute(
            f"SELECT draft_id, reference_id, raw_product_title "
            f"FROM fastmoss_bulk_draft_status WHERE {pred}"
        )
    ]
    con.close()
    return [r for r in rows if r[0]]


def _recompute(draft_id: str):
    from agent.services.registration_draft_recompute_service import recompute_review_draft
    from agent.services.registration_draft_storage_service import (
        RegistrationDraftStorageService as Store,
    )

    draft = Store.get_draft(draft_id)
    if draft is None:
        return None
    return recompute_review_draft(draft, enable_text_assist=False)


def _cluster_of(refreshed) -> tuple[str | None, str | None]:
    tax = getattr(refreshed, "strategy_taxonomy", None)
    return (getattr(tax, "cluster", None), getattr(tax, "product_type_group", None))


def dry_run() -> None:
    rows = _pending_rows()
    print(f"pending drafts missing cluster/type: {len(rows)}")
    real = gen = noload = 0
    samples: list[str] = []
    for draft_id, _ref, title in rows:
        refreshed = _recompute(draft_id)
        if refreshed is None:
            noload += 1
            continue
        cluster, ptype = _cluster_of(refreshed)
        if cluster in _GENERIC:
            gen += 1
        else:
            real += 1
            if len(samples) < 12:
                samples.append(f"  {title[:36]:36s} -> {cluster} / {ptype}")
    print(f"\nWOULD MAP to a real cluster: {real}")
    print(f"stays generic_unclassified (needs better data / manual): {gen}")
    if noload:
        print(f"draft could not be loaded: {noload}")
    print("\nsamples:")
    print("\n".join(samples))
    print("\nDRY-RUN — no changes written. Re-run with --apply to persist + sync.")


async def apply() -> None:
    rows = _pending_rows()
    print(f"pending drafts to recompute: {len(rows)}")
    if not rows:
        print("nothing to do.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = DB_PATH.with_suffix(f".db.precluster-{stamp}")
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    from agent.services.fastmoss_bulk_promotion_service import sync_queue_row_from_draft
    from agent.services.registration_draft_storage_service import (
        RegistrationDraftStorageService as Store,
    )

    real = gen = failed = 0
    for draft_id, _ref, title in rows:
        try:
            refreshed = _recompute(draft_id)
            if refreshed is None:
                failed += 1
                continue
            Store.save_draft(refreshed)
            await sync_queue_row_from_draft(refreshed)
            cluster, _ptype = _cluster_of(refreshed)
            if cluster in _GENERIC:
                gen += 1
            else:
                real += 1
        except Exception as exc:  # never let one bad draft abort the batch
            failed += 1
            print(f"  FAILED {draft_id[:12]} ({title[:30]}): {exc}")
    print(f"\nAPPLIED: mapped {real} to a real cluster; {gen} stay generic; {failed} failed.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="persist + sync (default: dry-run)")
    args = ap.parse_args()
    _reconfig_stdout()
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 2
    if args.apply:
        asyncio.run(apply())
    else:
        dry_run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
