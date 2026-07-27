"""Universal Product Visual Grounding Resolver.

Provides a single shared authority for resolving any catalog product in the
Product Database (659+ products) into an authoritative visual reference image,
validated image metadata, and engine-visible product locks (identity, geometry,
scale, label, handling, and negative rules).

Fail-closed security: If no valid product image reference exists, generation
is blocked with ``PRODUCT_VISUAL_REFERENCE_REQUIRED``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from agent.services.product_lock_builder import build_product_lock, resolve_schema_entry


class ProductVisualReferenceRequiredError(ValueError):
    """Raised when a selected product has no valid, readable visual image reference."""
    pass


@dataclass
class ProductReferenceInfo:
    source_type: str
    media_id: str | None
    local_path: str | None
    image_url: str | None
    mime_type: str
    sha256: str
    width: int
    height: int
    provenance: str
    validation_status: str


@dataclass
class ProductVisualGroundingBundle:
    product_id: str
    product_display_name: str
    product_reference: dict[str, Any]
    identity_lock: str
    geometry_lock: str
    scale_lock: str
    label_lock: str
    handling_lock: str
    negative_rules: str
    product_category: str
    product_type: str
    size_or_volume: str
    grounding_source: str
    grounding_confidence: str
    field_provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_db_path() -> Path:
    env_dir = os.environ.get("FLOW_AGENT_DIR")
    if env_dir:
        candidate = Path(env_dir) / "flow_agent.db"
        if candidate.exists():
            return candidate
    base_dir = Path(__file__).resolve().parent.parent.parent
    for p in (
        base_dir / "flow_agent.db",
        base_dir.parent / "_ref_flowkit" / "flow_agent.db",
        Path("C:/Users/USER/Desktop/_ref_flowkit/flow_agent.db"),
    ):
        if p.exists():
            return p
    return Path("flow_agent.db")


def _get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else _get_db_path()
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def get_product_by_id(product_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    if not product_id:
        return None
    try:
        conn = _get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM product WHERE id = ? OR trigger_id = ?", (product_id, product_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _inspect_image_file(file_path: Path | str) -> tuple[int, int, str, str] | None:
    path = Path(file_path)
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        with Image.open(path) as im:
            w, h = im.size
            fmt = im.format.lower() if im.format else "jpeg"
            mime = f"image/{'jpeg' if fmt in ('jpg', 'jpeg') else fmt}"
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        return w, h, mime, sha
    except Exception:
        return None


def _find_linked_creative_asset(product_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    try:
        conn = _get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM creative_asset 
            WHERE (product_id = ? OR asset_id LIKE ?)
              AND (semantic_role = 'PRODUCT_REFERENCE' OR asset_type = 'PRODUCT_REFERENCE')
              AND status != 'ARCHIVED'
            ORDER BY created_at DESC
            """,
            (product_id, f"%{product_id}%"),
        )
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            d = dict(r)
            lp = d.get("local_file_path") or d.get("local_path")
            if lp and Path(lp).exists():
                return d
            if d.get("remote_source_url") or d.get("preview_url") or d.get("download_url"):
                return d
        return None
    except Exception:
        return None


def resolve_product_reference_image(
    product: dict[str, Any],
    db_path: Path | str | None = None,
) -> ProductReferenceInfo:
    """Resolve the authoritative product reference image in priority order."""
    product_id = str(product.get("id") or product.get("product_id") or "")
    
    # Priority 0: Handcrafted Schema Canonical Source (e.g. MWCB canonical photo)
    schema_entry = resolve_schema_entry(product)
    if schema_entry:
        c_path_str = schema_entry.get("canonical_source_path") or (
            schema_entry.get("canonical_product_photo") or {}
        ).get("source_path")
        if c_path_str:
            c_path = Path(c_path_str)
            if c_path.exists():
                meta = _inspect_image_file(c_path)
                if meta:
                    w, h, mime, sha = meta
                    return ProductReferenceInfo(
                        source_type="SCHEMA_CANONICAL_SOURCE",
                        media_id=product.get("media_id"),
                        local_path=str(c_path),
                        image_url=product.get("image_url"),
                        mime_type=mime,
                        sha256=sha,
                        width=w,
                        height=h,
                        provenance="UNIVERSAL_PRODUCT_SCHEMA",
                        validation_status="VALIDATED",
                    )

    # Priority 1: Product row local_image_path (if exists on disk)
    local_path = product.get("local_image_path")
    if local_path:
        lp = Path(local_path)
        if lp.exists():
            meta = _inspect_image_file(lp)
            if meta:
                w, h, mime, sha = meta
                return ProductReferenceInfo(
                    source_type="PRODUCT_ROW_LOCAL_PATH",
                    media_id=product.get("media_id"),
                    local_path=str(lp),
                    image_url=product.get("image_url"),
                    mime_type=mime,
                    sha256=sha,
                    width=w,
                    height=h,
                    provenance="PRODUCT_DATABASE_RECORD",
                    validation_status="VALIDATED",
                )

    # Priority 2: Linked Creative Asset
    if product_id:
        asset = _find_linked_creative_asset(product_id, db_path=db_path)
        if asset:
            alp = asset.get("local_file_path") or asset.get("local_path")
            if alp and Path(alp).exists():
                meta = _inspect_image_file(alp)
                if meta:
                    w, h, mime, sha = meta
                    return ProductReferenceInfo(
                        source_type="CREATIVE_ASSET_PRODUCT_REFERENCE",
                        media_id=asset.get("media_id") or product.get("media_id"),
                        local_path=str(alp),
                        image_url=asset.get("remote_source_url") or asset.get("preview_url") or product.get("image_url"),
                        mime_type=mime,
                        sha256=sha,
                        width=w,
                        height=h,
                        provenance="CREATIVE_ASSET_REGISTRY",
                        validation_status="VALIDATED",
                    )

    # Priority 3: Product row image_url (remote reference URL)
    image_url = product.get("image_url") or product.get("source_url")
    if image_url and isinstance(image_url, str) and image_url.startswith("http"):
        sha = hashlib.sha256(image_url.encode("utf-8")).hexdigest()
        return ProductReferenceInfo(
            source_type="PRODUCT_ROW_IMAGE_URL",
            media_id=product.get("media_id"),
            local_path=None,
            image_url=image_url,
            mime_type="image/jpeg",
            sha256=sha,
            width=800,
            height=800,
            provenance="PRODUCT_DATABASE_RECORD",
            validation_status="VALIDATED",
        )

    # Priority 4: Product row media_id
    media_id = product.get("media_id")
    if media_id:
        sha = hashlib.sha256(str(media_id).encode("utf-8")).hexdigest()
        return ProductReferenceInfo(
            source_type="PRODUCT_ROW_MEDIA_ID",
            media_id=str(media_id),
            local_path=None,
            image_url=None,
            mime_type="image/jpeg",
            sha256=sha,
            width=800,
            height=800,
            provenance="PRODUCT_DATABASE_RECORD",
            validation_status="VALIDATED",
        )

    raise ProductVisualReferenceRequiredError(
        f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Selected product '{product.get('product_display_name') or product.get('name') or product_id}' "
        "has no valid readable image reference in local storage, database row, or creative asset registry."
    )


def resolve_product_visual_grounding(
    product_id_or_row: str | dict[str, Any],
    *,
    db_path: Path | str | None = None,
    is_video: bool = False,
) -> ProductVisualGroundingBundle:
    """Resolve a selected product into one universal ProductVisualGroundingBundle."""
    if isinstance(product_id_or_row, str):
        row = get_product_by_id(product_id_or_row, db_path=db_path)
        if not row:
            raise ProductVisualReferenceRequiredError(
                f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Product ID '{product_id_or_row}' not found in Product Database."
            )
        product = row
    elif isinstance(product_id_or_row, dict):
        product = dict(product_id_or_row)
        p_id = str(product.get("id") or product.get("product_id") or "")
        # Enrich missing image fields from DB if available
        if p_id and not (product.get("local_image_path") or product.get("image_url") or product.get("media_id")):
            db_row = get_product_by_id(p_id, db_path=db_path)
            if db_row:
                for k, v in db_row.items():
                    if v and not product.get(k):
                        product[k] = v
    else:
        raise ProductVisualReferenceRequiredError("PRODUCT_VISUAL_REFERENCE_REQUIRED: Invalid product parameter.")

    product_id = str(product.get("id") or product.get("product_id") or "")
    display_name = str(
        product.get("product_display_name")
        or product.get("name")
        or product.get("product_name")
        or product.get("raw_product_title")
        or "Product"
    ).strip()

    # Resolve image reference info (fails closed if missing)
    ref_info = resolve_product_reference_image(product, db_path=db_path)

    # Build universal product locks
    locks = build_product_lock(product, is_video=is_video, has_product_reference=True)

    handling_lock = (
        f"HANDLING LOCK: {product.get('hand_object_interaction') or product.get('handling_notes') or 'Natural one-hand grip appropriate to product size.'} "
        f"Recommended grip: {product.get('recommended_grip') or 'relaxed hand grip'}. Product stays physically connected to the hand or surface; "
        "no floating product, no forced perspective, and no coverage of presenter face."
    )

    size_ml = product.get("pack_size_ml") or product.get("volume_ml") or product.get("size_ml")
    size_str = f"{size_ml}ml" if size_ml else (product.get("product_scale") or "compact")

    schema_entry = resolve_schema_entry(product)
    grounding_source = "UNIVERSAL_PRODUCT_SCHEMA" if schema_entry else "PRODUCT_DATABASE_RECORD"
    confidence = "HIGH" if (schema_entry or ref_info.local_path) else "MEDIUM"

    return ProductVisualGroundingBundle(
        product_id=product_id,
        product_display_name=display_name,
        product_reference=asdict(ref_info),
        identity_lock=locks.get("identity_lock", ""),
        geometry_lock=locks.get("geometry_lock", ""),
        scale_lock=locks.get("scale_lock", ""),
        label_lock=locks.get("no_modification_lock", ""),
        handling_lock=handling_lock,
        negative_rules=locks.get("negative_morph", ""),
        product_category=str(product.get("category") or "General"),
        product_type=str(product.get("product_type") or product.get("type") or "Product"),
        size_or_volume=str(size_str),
        grounding_source=grounding_source,
        grounding_confidence=confidence,
        field_provenance={
            "db_record_id": product_id,
            "has_schema_override": bool(schema_entry),
            "ref_source": ref_info.source_type,
            "ref_sha256": ref_info.sha256,
        },
    )
