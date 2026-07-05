"""Shared engine-visible PRODUCT LOCK builder (product-truth scale/geometry hardener).

Root problem this module fixes: the authored product-truth lock authority
(``agent/authority/UNIVERSAL_PRODUCT_SCHEMA.json`` — ``product_truth_ref`` /
``scale_lock`` / ``label_lock`` / ``pack_size_ml``) was ORPHANED — no runtime code
loaded it — and the canonical prompt compiler emitted only a single generic
"preserve appearance" sentence for SECTION 2. The generation engine therefore never
received a hard identity + geometry + physical-scale + negative-morph + frame
persistence lock, letting bottles enlarge, round out, and drift 5ml↔10ml.

This builder is the single source that turns product truth into engine-visible lock
prose. Priority order for truth:

1. UNIVERSAL_PRODUCT_SCHEMA.json entry resolved from the product row (authored
   literal truth — used verbatim). This is where palm-scale/silhouette evidence is
   represented as first-class ``scale_lock`` semantics.
2. A deterministic data-driven fallback derived from the product row (pack size,
   family/packaging descriptors) so the lock is NEVER silently dropped for products
   that are not (yet) in the schema.

The emitted lock text is deterministic and scrub-safe: it contains no source-mode
taxonomy tokens (see canonical_prompt_compiler._LEAK_PATTERNS), so it can be
inserted directly into the final compiled prompt.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"


@lru_cache(maxsize=1)
def _schema() -> dict:
    try:
        with open(_AUTHORITY_DIR / "UNIVERSAL_PRODUCT_SCHEMA.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"products": {}}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _parse_pack_ml(product: dict[str, Any]) -> int | None:
    for key in ("pack_size_ml", "volume_ml", "net_volume_ml", "size_ml"):
        raw = product.get(key)
        if raw not in (None, ""):
            try:
                return int(round(float(raw)))
            except (TypeError, ValueError):
                pass
    haystack = " ".join(
        _lower(product.get(k))
        for k in ("name", "product_name", "product_short_name", "raw_product_title", "type")
    )
    match = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", haystack)
    if match:
        try:
            return int(round(float(match.group(1))))
        except (TypeError, ValueError):
            return None
    return None


def resolve_schema_entry(product: dict[str, Any]) -> dict | None:
    """Resolve a product row to its authored UNIVERSAL_PRODUCT_SCHEMA entry.

    Match order: explicit ref/id keys → exact product_name → brand+size signature.
    The BOSMAX signature path fails closed against 5ml↔10ml contamination: a row
    that reads as 10ml is never matched to the 5ml entry.
    """
    products = _schema().get("products") or {}
    if not products:
        return None

    for key in ("product_truth_ref", "product_id", "schema_ref", "id"):
        candidate = _clean(product.get(key)).upper()
        if candidate and candidate in products:
            return products[candidate]

    name = _lower(
        product.get("name")
        or product.get("product_name")
        or product.get("product_short_name")
        or product.get("raw_product_title")
    )
    if not name:
        return None

    for entry in products.values():
        pn = _lower(entry.get("product_name"))
        if not pn:
            continue
        # Forward: authored name fully contained in the row name (strong).
        # Reverse: row name inside authored name only when it is specific enough
        # (multi-word, >=8 chars) so short generic words like "oil" never match.
        if pn in name:
            return entry
        if name in pn and len(name) >= 8 and " " in name:
            return entry

    pack_ml = _parse_pack_ml(product)
    is_ten_ml = "10ml" in name or "10 ml" in name or pack_ml == 10
    if ("minyak warisan" in name or "cap burung" in name) and "MWTCB_25ML_CAP_BURUNG" in products:
        return products["MWTCB_25ML_CAP_BURUNG"]
    if "bosmax" in name and not is_ten_ml and "BOSMAX_SERUM_5ML" in products:
        if any(tok in name for tok in ("5ml", "5 ml", "roll on", "roll-on", "serum", "herbal oil")) or pack_ml == 5:
            return products["BOSMAX_SERUM_5ML"]
    return None


# ── data-driven fallback (no schema entry) ─────────────────────────────────────

def _fallback_scale_line(product: dict[str, Any]) -> str:
    pack_ml = _parse_pack_ml(product)
    haystack = " ".join(
        _lower(product.get(k))
        for k in ("type", "product_type", "product_scale", "physics_class", "category", "name", "product_name")
    )
    if pack_ml is not None:
        size_phrase = f"exact {pack_ml}ml container scale"
        if pack_ml <= 6:
            size_phrase += " (lip-balm / chapstick size class)"
        elif pack_ml <= 30:
            size_phrase += " (compact pocket / palm size class)"
    elif any(tok in haystack for tok in ("roll on", "roll-on", "lip balm", "balm", "dropper", "serum")):
        size_phrase = "exact compact roll-on / lip-balm size class"
    elif any(tok in haystack for tok in ("bottle", "jar", "tube", "mist", "perfume", "supplement", "oil")):
        size_phrase = "exact palm-sized bottle scale unless verified dimensions say otherwise"
    else:
        size_phrase = "exact true-to-life product scale, handled naturally in hand without enlargement"
    return (
        f"Keep the product at {size_phrase}, small relative to an adult hand, fingers, and face. "
        "Do not enlarge the product for camera visibility, and do not push it into a larger bottle category."
    )


def _fallback_identity_line(product: dict[str, Any]) -> str:
    name = _clean(
        product.get("name")
        or product.get("product_name")
        or product.get("product_short_name")
        or "the product"
    )
    return (
        f"Preserve the exact identity of {name}: its real label, wordmark, colour, material, "
        "cap, and readable text. Do not relabel, redesign, recolour, replace, or simplify it."
    )


# ── public lock builder ────────────────────────────────────────────────────────

def build_product_lock(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> dict[str, Any]:
    """Return engine-visible product lock components.

    Keys: identity_lock, geometry_lock, scale_lock, reference_lock,
    negative_morph, frame_persistence (empty strings where not applicable),
    plus matched_product_id (schema id or None) for telemetry/tests.
    """
    entry = resolve_schema_entry(product or {})

    if entry:
        truth_ref = _clean(entry.get("product_truth_ref"))
        label_lock = _clean(entry.get("label_lock"))
        identity_lock = (
            f"PRODUCT IDENTITY LOCK: Preserve the exact product identity — {truth_ref} "
            f"{label_lock} Do not relabel, redesign, recolour, replace, or simplify the product."
        )
        authored_scale = _clean(entry.get("scale_lock"))
        scale_lock = (
            f"PRODUCT SCALE LOCK: {authored_scale} "
            "Keep it at true palm scale — small relative to an adult hand, fingers, and face. "
            "Do not enlarge the product for camera visibility."
        )
        matched_id = entry.get("product_id")
    else:
        identity_lock = f"PRODUCT IDENTITY LOCK: {_fallback_identity_line(product or {})}"
        scale_lock = f"PRODUCT SCALE LOCK: {_fallback_scale_line(product or {})}"
        matched_id = None

    geometry_lock = (
        "PRODUCT GEOMETRY LOCK: Preserve the exact silhouette, body shape, cap-to-body ratio, "
        "neck and shoulder proportion, and front/back flatness of the real product. Never let it "
        "become rounder, bulkier, taller, swollen, bulbous, or a generic container, and never turn "
        "it into a perfume, syrup, skincare, supplement, spray, pump, or cosmetic bottle."
    )
    negative_morph = (
        "PRODUCT NEGATIVE MORPH RULES: Forbidden — enlarging the product, rounding or bulking its "
        "silhouette, swapping it for a bigger or generic bottle, changing the cap, body, or label "
        "proportion, drifting the label, or resizing it for the camera. The product's real size and "
        "shape outrank hero framing and any instruction to show the product clearly."
    )
    reference_lock = (
        (
            "PRODUCT REFERENCE LOCK: Treat the attached product reference image as the hard visual, "
            "geometry, and physical-scale truth source, not mood or style inspiration. Reproduce the "
            "product's real proportions and small real-world size exactly, and do not upscale it for visibility."
        )
        if has_product_reference
        else ""
    )
    frame_persistence = (
        (
            "FRAME PERSISTENCE LOCK: Across every frame keep the identical product identity, silhouette, "
            "cap-to-body ratio, label placement, and small real-world scale — no growth, no rounding, no "
            "morphing, no cap, body, or label mutation, and no progressive enlargement as the camera moves."
        )
        if is_video
        else ""
    )

    return {
        "identity_lock": identity_lock,
        "geometry_lock": geometry_lock,
        "scale_lock": scale_lock,
        "reference_lock": reference_lock,
        "negative_morph": negative_morph,
        "frame_persistence": frame_persistence,
        "matched_product_id": matched_id,
    }


def section_2_lock_lines(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> list[str]:
    """Identity + geometry + scale + negative-morph lines for SECTION 2 (all modes)."""
    lock = build_product_lock(
        product, is_video=is_video, has_product_reference=has_product_reference,
    )
    return [
        lock["identity_lock"],
        lock["geometry_lock"],
        lock["scale_lock"],
        lock["negative_morph"],
    ]


def section_3_lock_lines(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> list[str]:
    """Reference lock (when a product reference exists) + frame persistence (video)."""
    lock = build_product_lock(
        product, is_video=is_video, has_product_reference=has_product_reference,
    )
    return [line for line in (lock["reference_lock"], lock["frame_persistence"]) if line]
