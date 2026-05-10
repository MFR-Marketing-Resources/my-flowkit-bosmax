from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.db import crud
from agent.db.schema import init_db
from agent.services.product_catalog_audit import build_cleanup_plan


def _compact_plan(plan: dict) -> dict:
    return {
        "null_mapping_status_before": plan["null_mapping_status_before"],
        "test_fixture_rows_found": plan["test_fixture_rows_found"],
        "stale_duplicate_rows_found": plan["stale_duplicate_rows_found"],
        "valid_product_needs_backfill_rows": plan["valid_product_needs_backfill_rows"],
        "unknown_requires_review_rows": plan["unknown_requires_review_rows"],
        "null_mapping_rows": plan["null_mapping_rows"],
        "rows_to_delete": plan["rows_to_delete"],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply

    await init_db()
    products = await crud.list_products(limit=10000)
    plan = build_cleanup_plan(products)

    if not dry_run:
        deleted_ids: list[str] = []
        for row in plan["rows_to_delete"]:
            product_id = row["id"]
            await crud.delete_product(product_id)
            deleted_ids.append(product_id)

        remaining = await crud.list_products(limit=10000)
        post_plan = build_cleanup_plan(remaining)
        print(
            json.dumps(
                {
                    "mode": "apply",
                    "deleted_count": len(deleted_ids),
                    "deleted_ids": deleted_ids,
                    "before": _compact_plan(plan),
                    "after": {
                        "null_mapping_status_after": post_plan["null_mapping_status_before"],
                        "remaining_test_fixture_rows": post_plan["test_fixture_rows_found"],
                        "remaining_stale_duplicate_rows": post_plan["stale_duplicate_rows_found"],
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print(json.dumps({"mode": "dry-run", **_compact_plan(plan)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())