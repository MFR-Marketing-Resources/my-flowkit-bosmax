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
from agent.services.product_catalog_audit import build_mapping_summary
from agent.services.product_intelligence import enrich_product


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-limit", type=int, default=30)
    args = parser.parse_args()

    await init_db()
    raw_products = await crud.list_products(limit=10000)
    enriched_products = [await enrich_product(product, persist=False) for product in raw_products]
    summary = build_mapping_summary(raw_products, enriched_products, sample_limit=args.sample_limit)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())