import argparse
import asyncio
import json

from agent.db.schema import init_db
from agent.api.products import backfill_product_mapping, get_product_mapping_audit, repair_product_mapping


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--product-id")
    args = parser.parse_args()

    await init_db()
    if args.product_id:
        audit = await get_product_mapping_audit(args.product_id)
        repaired = await repair_product_mapping(args.product_id)
        print(json.dumps({"audit": audit, "repair": repaired}, indent=2))
        return

    result = await backfill_product_mapping()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())