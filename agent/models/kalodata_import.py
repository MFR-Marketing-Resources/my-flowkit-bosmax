"""Kalodata/External catalog staged import — data contracts.

Additive feature (2026-07-13): parses the Owner's Kalodata/Fastmoss merged
workbook into a STAGED reference catalog (JSON files in OPERATOR_PACK_DIR)
that is unioned into the existing FastMoss reference layer. Zero AI calls,
zero direct `product` table writes — promotion stays behind the existing
reviewed /fastmoss-bulk gates.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class KalodataMergedRow(BaseModel):
    row_no: int
    sumber: str = "KALODATA"  # KALODATA | FASTMOSS | MANUAL
    product_name: str
    image_url: str | None = None
    category_path: str | None = None
    price: float | None = None  # midpoint when the cell held a range
    price_min: float | None = None
    price_max: float | None = None
    price_raw: str | None = None
    launch_date: str | None = None  # ISO yyyy-mm-dd
    rating: float | None = None
    sold_count: int | None = None
    avg_unit_price: float | None = None
    commission_rate: str | None = None
    creator_number: int | None = None
    conversion: str | None = None
    tiktok_product_url: str | None = None
    tiktok_product_id: str | None = None
    # URL = recovered losslessly from the TikTok URL · CELL = integral cell
    # value below float53 precision · LOW = cell beyond float precision
    # (unrecoverable) · NONE = nothing available
    tiktok_product_id_confidence: str = "NONE"
    source_url: str | None = None


class KalodataHubRow(BaseModel):
    row_no: int
    product_id: str | None = None
    product_name: str = ""
    product_type: str | None = None
    category: str | None = None
    target_avatar: str | None = None
    pain_point: str | None = None
    emotion_trigger: str | None = None
    dream_outcome: str | None = None
    key_ingredient_feature: str | None = None
    main_benefit: str | None = None
    secondary_benefit: str | None = None
    usp: str | None = None
    hook_type: str | None = None

    def has_any_enrichment(self) -> bool:
        return any(
            (v or "").strip()
            for v in (
                self.target_avatar, self.pain_point, self.emotion_trigger,
                self.dream_outcome, self.key_ingredient_feature,
                self.main_benefit, self.secondary_benefit, self.usp,
                self.hook_type,
            )
        )


class KalodataImportReport(BaseModel):
    source_path: str
    parsed_merged: int = 0
    parsed_hub: int = 0
    staged: int = 0
    skipped_duplicate_in_file: int = 0
    skipped_invalid: int = 0
    product_id_from_url: int = 0
    product_id_low_confidence: int = 0
    price_ranges_parsed: int = 0
    hub_matched: int = 0
    hub_unmatched_rows: list[int] = Field(default_factory=list)
    staged_catalog_path: str = ""
    staged_hub_path: str = ""


class KalodataImportRequest(BaseModel):
    source_path: str | None = None


class KalodataApplyHubRequest(BaseModel):
    reference_ids: list[str] | None = None


class KalodataCacheImagesRequest(BaseModel):
    product_ids: list[str]
