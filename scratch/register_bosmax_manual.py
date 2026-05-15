import asyncio
import os
import sys
import aiosqlite

# Add project root to sys.path
sys.path.append(os.getcwd())

from agent.config import DB_PATH
from agent.db.schema import init_db

async def main():
    await init_db()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        pid = '5f648437-6307-48cd-a6b5-1250a0c3f9b6'
        now = '2026-05-13T03:21:00Z'
        print(f"Manually inserting product with ID: {pid}")
        await db.execute(
            "INSERT OR REPLACE INTO product (id, source, raw_product_title, product_display_name, product_short_name, local_image_path, asset_status, image_asset_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, 'MANUAL', 'Bosmax Proof', 'Bosmax Proof', 'Bosmax', 'C:\\Users\\USER\\Downloads\\Bosmax image.jpg', 'DOWNLOADED', 'READY', now, now)
        )
        await db.commit()
    print("Done.")

if __name__ == '__main__':
    asyncio.run(main())
