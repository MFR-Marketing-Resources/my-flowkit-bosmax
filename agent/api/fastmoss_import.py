from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from agent.services.fastmoss_import_service import (
    get_fastmoss_import_batch,
    get_latest_fastmoss_import_batch,
    import_fastmoss_batch,
)


router = APIRouter(prefix="/fastmoss", tags=["fastmoss"])


@router.post("/import-batch")
async def upload_fastmoss_import_batch(
    creator_search: UploadFile | None = File(default=None),
    export_ad_list: UploadFile | None = File(default=None),
    export_advertiser_list: UploadFile | None = File(default=None),
    shop_list: UploadFile | None = File(default=None),
    sales_rank: UploadFile | None = File(default=None),
    new_products_ranking: UploadFile | None = File(default=None),
    product_search_data: UploadFile | None = File(default=None),
    product_search_sales_rank: UploadFile | None = File(default=None),
    most_promoted_products_rank: UploadFile | None = File(default=None),
    video_product_list: UploadFile | None = File(default=None),
) -> dict:
    return await import_fastmoss_batch(
        {
            "creator_search": creator_search,
            "export_ad_list": export_ad_list,
            "export_advertiser_list": export_advertiser_list,
            "shop_list": shop_list,
            "sales_rank": sales_rank,
            "new_products_ranking": new_products_ranking,
            "product_search_data": product_search_data,
            "product_search_sales_rank": product_search_sales_rank,
            "most_promoted_products_rank": most_promoted_products_rank,
            "video_product_list": video_product_list,
        }
    )


@router.get("/import-batch/latest")
async def latest_fastmoss_import_batch() -> dict:
    return get_latest_fastmoss_import_batch()


@router.get("/import-batch/{batch_id}")
async def fastmoss_import_batch(batch_id: str) -> dict:
    return get_fastmoss_import_batch(batch_id)
