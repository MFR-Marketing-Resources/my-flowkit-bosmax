import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from agent.db import crud
from agent.db.schema import init_db

async def main():
    await init_db()
    # Check if exists
    existing = await crud.get_product('5f648437-6307-48cd-a6b5-1250a0c3f9b6')
    if existing:
        print("Product already exists, updating...")
        await crud.update_product(
            '5f648437-6307-48cd-a6b5-1250a0c3f9b6',
            local_image_path='C:\\Users\\USER\\Downloads\\Bosmax image.jpg',
            asset_status='DOWNLOADED',
            image_asset_status='READY'
        )
    else:
        print("Creating product...")
        await crud.create_product(
            id='5f648437-6307-48cd-a6b5-1250a0c3f9b6',
            raw_product_title='Bosmax Proof',
            local_image_path='C:\\Users\\USER\\Downloads\\Bosmax image.jpg',
            asset_status='DOWNLOADED',
            image_asset_status='READY'
        )
    print("Done.")

if __name__ == '__main__':
    asyncio.run(main())
