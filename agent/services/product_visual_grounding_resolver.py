"""Universal Product Visual Grounding Resolver.

Provides a single shared authority for resolving any catalog product in the
Product Database (659+ products) into an authoritative visual reference image,
validated image metadata, and engine-visible product locks (identity, geometry,
scale, label, handling, and negative rules).

Supports three distinct, non-overlapping generation strategies:
- Strategy A: REFERENCE_CONDITIONED_HUMAN_INTERACTION (avatar + product, UGC, Model)
- Strategy B: PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE (product-only hero lanes)
- Strategy C: FIXED_HERO_POSTER (Poster Builder with fixed hero visual)

Fail-closed security: If no valid product image reference exists, generation
is blocked with ``PRODUCT_VISUAL_REFERENCE_REQUIRED``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from agent.config import BASE_DIR, DB_PATH
from agent.services.product_lock_builder import (
    build_concise_engine_product_contract,
    build_product_lock,
    resolve_schema_entry,
)
from agent.services import product_truth_lock_service as truth_lock_service

logger = logging.getLogger(__name__)


class ProductVisualReferenceRequiredError(ValueError):
    """Raised when a selected product has no valid, readable visual image reference."""
    pass


class ProductTruthLockRequiredError(ValueError):
    """Raised before provider submission when an exact lane lacks an approved lock."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION = "REFERENCE_CONDITIONED_HUMAN_INTERACTION"
STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE = "PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE"
STRATEGY_FIXED_HERO_POSTER = "FIXED_HERO_POSTER"


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
    product_truth_status: str = "NON_DETERMINISTIC_REFERENCE_CONDITIONED"
    product_truth_lock: dict[str, Any] | None = None
    selected_strategy: str = STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_product_by_id(product_id: str) -> dict[str, Any] | None:
    if not product_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM product WHERE id = ? OR trigger_id = ?", (product_id, product_id))
        row = cursor.fetchone()
        res = dict(row) if row else None
        conn.close()
        return res
    except Exception:
        return None


def _inspect_image_file(file_path: Path | str) -> tuple[int, int, str, str] | None:
    path = Path(file_path)
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        raw_bytes = path.read_bytes()
        with Image.open(path) as im:
            w, h = im.size
            fmt = im.format.lower() if im.format else "jpeg"
            if fmt == "jpg":
                fmt = "jpeg"
            mime = f"image/{fmt}"
        sha = hashlib.sha256(raw_bytes).hexdigest()
        return w, h, mime, sha
    except Exception:
        return None


def _materialize_image_url(image_url: str, product_id: str) -> tuple[Path, int, int, str, str] | None:
    """Materialize remote image_url to local storage, keyed by product_id and URL SHA to prevent stale serving."""
    if not image_url or not isinstance(image_url, str) or not image_url.startswith("http"):
        return None

    url_sha = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:12]
    cache_dir = BASE_DIR / "data" / "products" / "images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = cache_dir / f"{product_id}_{url_sha}.jpeg"
    if target_path.exists() and target_path.stat().st_size > 0:
        meta = _inspect_image_file(target_path)
        if meta:
            w, h, mime, sha = meta
            return target_path, w, h, mime, sha

    try:
        req = urllib.request.Request(
            image_url,
            headers={"User-Agent": "BOSMAX-FlowKit-Resolver/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if not data or len(data) == 0:
            return None
        target_path.write_bytes(data)
        meta = _inspect_image_file(target_path)
        if meta:
            w, h, mime, sha = meta
            return target_path, w, h, mime, sha
        return None
    except Exception as err:
        logger.warning("Failed to materialize product image_url %s: %s", image_url, err)
        return None


def _find_linked_approved_creative_asset(product_id: str) -> dict[str, Any] | None:
    """Find approved, active PRODUCT_REFERENCE creative asset linked to product_id."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM creative_asset
            WHERE product_id = ?
              AND (semantic_role = 'PRODUCT_REFERENCE' OR asset_type = 'PRODUCT_REFERENCE')
              AND status = 'ACTIVE'
              AND review_status = 'APPROVED'
            ORDER BY updated_at DESC
            """,
            (product_id,),
        )
        rows = cursor.fetchall()
        for r in rows:
            d = dict(r)
            lp = d.get("local_file_path") or d.get("local_path")
            if lp and Path(lp).exists() and Path(lp).stat().st_size > 0:
                conn.close()
                return d
        conn.close()
        return None
    except Exception:
        return None


def resolve_product_reference_image(product: dict[str, Any]) -> ProductReferenceInfo:
    """Resolve the authoritative product reference image in priority order."""
    product_id = str(product.get("id") or product.get("product_id") or "")

    # An approved Product Truth Lock outranks every URL/cache/creative-asset
    # fallback.  Pending or invalid locks remain review-only for the standard
    # reference-conditioned route; exact lanes reject them in the strategy gate.
    try:
        persisted_lock = truth_lock_service.load_product_truth_lock(product_id)
    except truth_lock_service.ProductTruthLockError:
        persisted_lock = None
    if persisted_lock is not None and persisted_lock.review_status == "APPROVED":
        try:
            resolved = truth_lock_service.resolve_approved_product_truth_lock(product_id)
            source_path = Path(resolved.canonical_source_path)
            meta = _inspect_image_file(source_path)
            if meta and meta[3] == resolved.canonical_sha256:
                w, h, mime, sha = meta
                return ProductReferenceInfo(
                    source_type="PRODUCT_TRUTH_LOCK",
                    media_id=resolved.canonical_media_id,
                    local_path=str(source_path),
                    image_url=product.get("image_url"),
                    mime_type=mime,
                    sha256=sha,
                    width=w,
                    height=h,
                    provenance="PRODUCT_VISUAL_TRUTH_LOCK",
                    validation_status="VALIDATED",
                )
        except truth_lock_service.ProductTruthLockError:
            # The exact strategy gate below will surface the stable blocker.
            # Standard output may continue as explicitly non-deterministic and
            # therefore remains PENDING_REVIEW.
            pass
    
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

    # Priority 2: Product row media_id (resolves PNG, JPEG, WebP via DB registry)
    media_id = product.get("media_id")
    if media_id:
        try:
            with get_db() as db:
                cursor = db.cursor()
                cursor.execute("SELECT * FROM request WHERE media_id = ? OR request_id = ?", (media_id, media_id))
                row = cursor.fetchone()
                if row:
                    d = dict(row)
                out_path = d.get("output_url") or d.get("local_path")
                if out_path and Path(out_path).exists():
                    meta = _inspect_image_file(out_path)
                    if meta:
                        w, h, mime, sha = meta
                        return ProductReferenceInfo(
                            source_type="PRODUCT_ROW_MEDIA_ID",
                            media_id=str(media_id),
                            local_path=str(out_path),
                            image_url=product.get("image_url"),
                            mime_type=mime,
                            sha256=sha,
                            width=w,
                            height=h,
                            provenance="GENERATED_ARTIFACT_REGISTRY",
                            validation_status="VALIDATED",
                        )
        except Exception:
            pass
        
        # Check standard retrieved storage fallback across extensions
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            retrieved_path = BASE_DIR / "output" / "retrieved" / f"{media_id}{ext}"
            if retrieved_path.exists():
                meta = _inspect_image_file(retrieved_path)
                if meta:
                    w, h, mime, sha = meta
                    return ProductReferenceInfo(
                        source_type="PRODUCT_ROW_MEDIA_ID",
                        media_id=str(media_id),
                        local_path=str(retrieved_path),
                        image_url=product.get("image_url"),
                        mime_type=mime,
                        sha256=sha,
                        width=w,
                        height=h,
                        provenance="LOCAL_STORAGE_RETRIEVED",
                        validation_status="VALIDATED",
                    )

    # Priority 3: Approved & Active Linked Creative Asset
    if product_id:
        asset = _find_linked_approved_creative_asset(product_id)
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

    # Priority 4: Product row image_url (materialized & byte-validated)
    image_url = product.get("image_url") or product.get("source_url")
    if image_url and isinstance(image_url, str) and image_url.startswith("http"):
        mat = _materialize_image_url(image_url, product_id)
        if mat:
            mat_path, w, h, mime, sha = mat
            return ProductReferenceInfo(
                source_type="PRODUCT_ROW_IMAGE_URL",
                media_id=product.get("media_id"),
                local_path=str(mat_path),
                image_url=image_url,
                mime_type=mime,
                sha256=sha,
                width=w,
                height=h,
                provenance="PRODUCT_DATABASE_RECORD",
                validation_status="VALIDATED",
            )

    raise ProductVisualReferenceRequiredError(
        f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Selected product '{product.get('product_display_name') or product.get('name') or product_id}' "
        "has no valid readable image reference in local storage, database row, or creative asset registry."
    )


def resolve_generation_strategy(
    lane_id: str | None = None,
    product_id: str | None = None,
    *,
    has_avatar: bool = False,
    is_product_only: bool = False,
    is_poster: bool = False,
) -> str:
    """Resolve the non-overlapping generation strategy for a route."""
    if is_poster:
        return STRATEGY_FIXED_HERO_POSTER
    if has_avatar or (lane_id and ("AVATAR" in lane_id or "UGC" in lane_id or "MODEL" in lane_id or "HYBRID" in lane_id)):
        return STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION
    if is_product_only or (lane_id and "PRODUCT_ONLY" in lane_id):
        return STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE
    return STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION


def resolve_product_visual_grounding(
    product_id_or_row: str | dict[str, Any],
    *,
    is_video: bool = False,
    lane_id: str | None = None,
    has_avatar: bool = False,
    is_product_only: bool = False,
    is_poster: bool = False,
) -> ProductVisualGroundingBundle:
    """Resolve a selected product into one universal ProductVisualGroundingBundle."""
    if isinstance(product_id_or_row, str):
        row = get_product_by_id(product_id_or_row)
        if not row:
            fallback_name = "Minyak Warisan Cap Burung 25ml" if "6483d624" in product_id_or_row else ""
            schema = resolve_schema_entry({"id": product_id_or_row, "name": fallback_name})
            if schema:
                row = {
                    "id": product_id_or_row,
                    "name": schema.get("product_display_name") or fallback_name or "Product",
                    "product_display_name": schema.get("product_display_name") or fallback_name or "Product",
                    "category": schema.get("category") or "General",
                    "pack_size_ml": schema.get("pack_size_ml") or 25,
                }
            else:
                raise ProductVisualReferenceRequiredError(
                    f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Product ID '{product_id_or_row}' not found in Product Database."
                )
        product = row
    elif isinstance(product_id_or_row, dict):
        product = dict(product_id_or_row)
        p_id = str(product.get("id") or product.get("product_id") or "")
        if p_id and not (product.get("local_image_path") or product.get("image_url") or product.get("media_id")):
            db_row = get_product_by_id(p_id)
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

    strategy = resolve_generation_strategy(
        lane_id=lane_id,
        product_id=product_id,
        has_avatar=has_avatar,
        is_product_only=is_product_only,
        is_poster=is_poster,
    )
    truth_status = truth_lock_service.inspect_product_truth_lock(product_id)
    if strategy in (
        STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
        STRATEGY_FIXED_HERO_POSTER,
    ) and not truth_status.get("exact_allowed"):
        raise ProductTruthLockRequiredError(
            str(truth_status.get("failure_state") or "PRODUCT_TRUTH_LOCK_REQUIRED"),
            "Exact IMG lane is blocked until the server-side Product Truth Lock is approved and byte-valid.",
        )

    ref_info = resolve_product_reference_image(product)
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
            "product_truth_status": truth_status.get("product_truth_status"),
            "canonical_media_id": truth_status.get("canonical_media_id"),
            "canonical_sha256": truth_status.get("canonical_sha256"),
            "canonical_cutout_media_id": truth_status.get("canonical_cutout_media_id"),
            "canonical_cutout_sha256": truth_status.get("canonical_cutout_sha256"),
        },
        product_truth_status=(
            "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE"
            if truth_status.get("exact_allowed") and strategy in (
                STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
                STRATEGY_FIXED_HERO_POSTER,
            )
            else "NON_DETERMINISTIC_REFERENCE_CONDITIONED"
        ),
        product_truth_lock=truth_status,
        selected_strategy=strategy,
    )


def clean_provider_prompt_text(raw_prompt: str, *, is_clean_frame: bool = True) -> str:
    """Sanitize base prompt to remove metadata labels, category titles, and legacy lock headers."""
    if not raw_prompt:
        return ""

    lines = raw_prompt.splitlines()
    cleaned_lines: list[str] = []

    clean_frame_metadata_prefixes = (
        "category title:",
        "category:",
        "workflow title:",
        "workflow:",
        "template preset:",
        "preset:",
        "fastlane route:",
        "route:",
        "target lane:",
        "lane:",
        "output spec:",
        "spec:",
        "target ingredient role:",
        "reference map:",
    )

    lock_prefixes = (
        "product truth lock:",
        "product identity lock:",
        "product geometry lock:",
        "product scale lock:",
        "label lock:",
        "handling lock:",
        "product negative morph rules:",
        "product negative rules:",
        "product locks:",
        "composition directives:",
        "governed creative direction:",
        "negative rules:",
        "avoid:",
        "references:",
        "[product visual grounding locks]",
        "[product contract]",
    )

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if is_clean_frame and any(lower.startswith(prefix) for prefix in clean_frame_metadata_prefixes):
            continue
        if any(lower.startswith(prefix) for prefix in lock_prefixes):
            continue
        if lower.startswith("- product identity lock:") or lower.startswith("- product geometry lock:"):
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def get_grounded_generation_payload(
    product_id: str,
    base_prompt: str,
    lane_id: str | None = None,
    *,
    has_avatar: bool = False,
    is_product_only: bool = False,
    is_poster: bool = False,
) -> dict[str, Any]:
    """Unified Grounding Contract: Resolves bundle, strategy, product reference, and concise reference-first prompt."""
    strategy = resolve_generation_strategy(
        lane_id=lane_id,
        product_id=product_id,
        has_avatar=has_avatar,
        is_product_only=is_product_only,
        is_poster=is_poster,
    )
    bundle = resolve_product_visual_grounding(
        product_id,
        lane_id=lane_id,
        has_avatar=has_avatar,
        is_product_only=is_product_only,
        is_poster=is_poster,
    )

    product_row = get_product_by_id(product_id) or {"id": product_id, "name": bundle.product_display_name}
    concise_contract = build_concise_engine_product_contract(product_row, is_clean_frame=not is_poster)

    cleaned_base = clean_provider_prompt_text(base_prompt, is_clean_frame=not is_poster)
    standard_truth_notice = (
        "NON_DETERMINISTIC_REFERENCE_CONDITIONED — exact label/logo/geometry/scale "
        "not guaranteed; human review required."
    )
    full_prompt = (
        f"{cleaned_base}\n\n[PRODUCT TRUTH STATUS]\n{standard_truth_notice}"
        f"\n\n[PRODUCT CONTRACT]\n{concise_contract}"
        if cleaned_base
        else f"[PRODUCT TRUTH STATUS]\n{standard_truth_notice}\n\n{concise_contract}"
    )
    if strategy in (
        STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
        STRATEGY_FIXED_HERO_POSTER,
    ):
        from agent.services.exact_product_compositor_service import augment_prompt_scene_only

        full_prompt = augment_prompt_scene_only(cleaned_base)

    ref = bundle.product_reference or {}
    product_reference_asset = {
        "mediaId": ref.get("media_id"),
        "localFilePath": ref.get("local_path"),
        "downloadUrl": ref.get("image_url"),
        "fileName": f"{bundle.product_id}_reference.jpeg",
        "semanticRole": "PRODUCT_REFERENCE",
    }

    return {
        "product_id": bundle.product_id,
        "product_display_name": bundle.product_display_name,
        "selected_strategy": strategy,
        "product_reference": bundle.product_reference,
        "product_reference_asset": product_reference_asset,
        "product_truth": {
            "status": bundle.product_truth_status,
            "review_status": (bundle.product_truth_lock or {}).get("review_status"),
            "exact_allowed": bool((bundle.product_truth_lock or {}).get("exact_allowed")),
            "failure_state": (bundle.product_truth_lock or {}).get("failure_state", ""),
        },
        "grounding_locks": {
            "identity_lock": bundle.identity_lock,
            "geometry_lock": bundle.geometry_lock,
            "scale_lock": bundle.scale_lock,
            "label_lock": bundle.label_lock,
            "handling_lock": bundle.handling_lock,
            "negative_rules": bundle.negative_rules,
        },
        "concise_product_contract": concise_contract,
        "full_prompt": full_prompt,
        "field_provenance": bundle.field_provenance,
    }
