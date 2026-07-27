"""Shared engine-visible PRODUCT LOCK builder.

The authored product authority in ``UNIVERSAL_PRODUCT_SCHEMA.json`` is the
primary product-truth source. A product reference image is supporting visual
evidence only where it agrees with that structured authority. This distinction
matters for catalog/display names that differ from the text physically printed
on a package and for stale generated references with incorrect geometry.
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
        for k in (
            "name",
            "product_name",
            "product_display_name",
            "product_short_name",
            "raw_product_title",
            "type",
        )
    )
    match = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", haystack)
    if match:
        try:
            return int(round(float(match.group(1))))
        except (TypeError, ValueError):
            return None
    return None


def _product_name_text(product: dict[str, Any]) -> str:
    return _lower(
        product.get("name")
        or product.get("product_name")
        or product.get("product_display_name")
        or product.get("product_short_name")
        or product.get("raw_product_title")
    )


def _resolved_ml(name: str, pack_ml: int | None) -> int | None:
    if pack_ml in (5, 10, 25):
        return pack_ml
    if "10ml" in name or "10 ml" in name:
        return 10
    if "5ml" in name or "5 ml" in name:
        return 5
    if "25ml" in name or "25 ml" in name:
        return 25
    return None


def resolve_schema_entry(product: dict[str, Any]) -> dict | None:
    """Resolve a runtime product row to one authored schema entry.

    Explicit identifiers win. BOSMAX variants are size-gated so a size-less
    family row cannot inherit the wrong 5ml/10ml lock.
    """
    products = _schema().get("products") or {}
    if not products:
        return None

    for key in ("product_truth_ref", "product_id", "schema_ref", "id"):
        candidate = _clean(product.get(key)).upper()
        if candidate and candidate in products:
            return products[candidate]
        for entry in products.values():
            if candidate and candidate in {_clean(alias).upper() for alias in entry.get("legacy_aliases") or []}:
                return entry

    name = _product_name_text(product)
    if not name:
        return None
    size_ml = _resolved_ml(name, _parse_pack_ml(product))

    if "bosmax" in name:
        if size_ml == 5 and "BOSMAX_SERUM_5ML" in products:
            return products["BOSMAX_SERUM_5ML"]
        if size_ml == 10 and "BOSMAX_HERBS_10ML" in products:
            return products["BOSMAX_HERBS_10ML"]
        return None

    if ("minyak warisan" in name or "cap burung" in name) and "MWCB_25ML_CAP_BURUNG" in products:
        return products["MWCB_25ML_CAP_BURUNG"]

    for entry in products.values():
        product_name = _lower(entry.get("product_name"))
        if not product_name or "bosmax" in product_name:
            continue
        if product_name in name:
            return entry
        if name in product_name and len(name) >= 8 and " " in name:
            return entry
    return None


_NON_BOTTLE_TOKENS: tuple[str, ...] = (
    "karpet",
    "carpet",
    "permaidani",
    "jersi",
    "jersey",
    "seluar",
    "tudung",
    "hijab",
    "kasut",
    "selipar",
    "sandal",
    "cadar",
    "bedsheet",
    "tilam",
    "mattress",
    "langsir",
    "curtain",
    "perabot",
    "furniture",
    "almari",
)


def _fallback_scale_line(product: dict[str, Any]) -> str:
    pack_ml = _parse_pack_ml(product)
    haystack = " ".join(
        _lower(product.get(k))
        for k in (
            "type",
            "product_type",
            "product_scale",
            "physics_class",
            "category",
            "subcategory",
            "name",
            "product_name",
            "product_display_name",
            "raw_product_title",
        )
    )

    if any(token in haystack for token in _NON_BOTTLE_TOKENS):
        return (
            "Keep the product at its true real-world size and correct proportion relative to a person "
            "and the surrounding environment. Preserve its natural full-size scale; do not shrink it to "
            "a small palm object, do not enlarge the product for camera visibility, and do not distort it."
        )

    handheld: bool | None = None
    if pack_ml is not None:
        if pack_ml <= 6:
            size_phrase = "a tiny lip-balm / chapstick handheld size class"
            handheld = True
        elif pack_ml <= 20:
            size_phrase = "a compact pocket roll-on handheld size class"
            handheld = True
        elif pack_ml <= 60:
            size_phrase = "a small one-hand-grip bottle size class"
            handheld = True
        elif pack_ml <= 150:
            size_phrase = "a medium one-hand bottle size class"
            handheld = True
        elif pack_ml <= 500:
            size_phrase = "a large bottle or jar size class held with one or two hands"
            handheld = False
        else:
            size_phrase = "a bulk container size class handled with two hands"
            handheld = False
    elif any(token in haystack for token in ("roll on", "roll-on", "lip balm", "balm", "dropper", "serum")):
        size_phrase = "a compact roll-on / lip-balm handheld size class"
        handheld = True
    elif any(token in haystack for token in ("bottle", "jar", "tube", "mist", "perfume", "supplement", "oil")):
        size_phrase = "a palm-sized bottle size class unless verified dimensions say otherwise"
        handheld = True
    else:
        size_phrase = "its true-to-life real-world size, handled naturally without enlargement"

    if handheld is True:
        tail = " It stays small relative to an adult hand, fingers, and face."
    elif handheld is False:
        tail = " It stays correct in proportion to an adult hand and body, not shrunk to a palm-sized object."
    else:
        tail = " Keep it at its correct real-world proportion, neither shrunk nor enlarged for the camera."
    return (
        f"Keep the product at {size_phrase}.{tail} "
        "Do not enlarge the product for camera visibility, and do not push it into a different size category."
    )


def _clean_display_name(raw: str) -> str:
    cleaned = re.sub(r"\s*\[[^\]]*\]\s*", " ", raw)
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"\bsku\s*:\s*.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+-\s+", " - ", cleaned).strip(" -")
    return cleaned or _clean(raw)


def _fallback_identity_line(product: dict[str, Any]) -> str:
    raw = _clean(
        product.get("name")
        or product.get("product_name")
        or product.get("product_display_name")
        or product.get("product_short_name")
        or product.get("raw_product_title")
        or "the product"
    )
    name = _clean_display_name(raw)
    return (
        f"Preserve the exact identity of {name}: its real label, wordmark, colour, material, "
        "cap, and readable text. Do not relabel, redesign, recolour, replace, or simplify it."
    )


def _structured_label_authority(entry: dict[str, Any]) -> str:
    lines = [_clean(value) for value in (entry.get("printed_label_lines") or []) if _clean(value)]
    layout = _clean(entry.get("label_layout_lock"))
    forbidden = [_clean(value) for value in (entry.get("forbidden_printed_label_tokens") or []) if _clean(value)]
    conflict = _clean(entry.get("reference_conflict_policy"))
    parts: list[str] = []
    if lines:
        parts.append(
            "PHYSICAL PRINTED LABEL AUTHORITY: The only visible printed label lines, in reading order, are: "
            + " | ".join(lines)
            + "."
        )
    if layout:
        parts.append(f"LABEL LAYOUT AUTHORITY: {layout}")
    if forbidden:
        parts.append(
            "FORBIDDEN PRINTED LABEL TOKENS: Never print, infer, insert, regroup, or copy these tokens onto the package: "
            + " | ".join(forbidden)
            + "."
        )
    if conflict:
        parts.append(f"REFERENCE CONFLICT POLICY: {conflict}")
    return " ".join(parts)


def build_product_lock(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> dict[str, Any]:
    """Return engine-visible identity, geometry, scale and reference locks."""
    entry = resolve_schema_entry(product or {})
    structured_authority = ""

    if entry:
        truth_ref = _clean(entry.get("product_truth_ref"))
        label_lock = _clean(entry.get("label_lock"))
        structured_authority = _structured_label_authority(entry)
        identity_lock = (
            f"PRODUCT IDENTITY LOCK: Preserve the exact product identity — {truth_ref} "
            f"{label_lock} {structured_authority} "
            "Do not relabel, redesign, recolour, replace, or simplify the product."
        )
        authored_scale = _clean(entry.get("scale_lock"))
        scale_lock = (
            f"PRODUCT SCALE LOCK: {authored_scale} "
            "Keep it at true palm scale — small relative to an adult hand, fingers, and face. "
            "The product's real size outranks label readability: never enlarge it so the label, "
            "text, or artwork reads more clearly, and if it is turned or rotated toward the "
            "camera its physical size stays exactly the same. Do not enlarge the product for "
            "camera visibility, and do not add any separate comparison object, second product, "
            "prop, ruler, or size marker to the scene."
        )
        matched_id = entry.get("product_id")
    else:
        truth_ref = ""
        identity_lock = f"PRODUCT IDENTITY LOCK: {_fallback_identity_line(product or {})}"
        scale_lock = f"PRODUCT SCALE LOCK: {_fallback_scale_line(product or {})}"
        matched_id = None

    if structured_authority:
        label_truth_source = "the structured physical-package and printed-label authority in this lock"
    elif has_product_reference:
        label_truth_source = "the attached reference image"
    else:
        label_truth_source = "the real printed product label described in this product truth lock"
    identity_lock += (
        f" LABEL TEXT LOCK: The printed label text, typography, and layout must match {label_truth_source} exactly — "
        "never re-typeset, shorten, translate, or restyle the printed product name, and never add dosage, usage, "
        "or instruction text that is not physically printed on the real label."
    )

    geometry_detail = f" Structured geometry authority: {truth_ref}" if entry and truth_ref else ""
    geometry_lock = (
        "PRODUCT GEOMETRY LOCK: Preserve the exact silhouette, body shape, cap-to-body ratio, neck and shoulder "
        "proportion, and front/back flatness of the real product. Never let it become rounder, bulkier, taller, "
        "swollen, bulbous, or a generic container, and never turn it into a perfume, syrup, skincare, supplement, "
        f"spray, pump, or cosmetic bottle.{geometry_detail}"
    )
    negative_morph = (
        "PRODUCT NEGATIVE MORPH RULES: Forbidden — enlarging the product, rounding or bulking its silhouette, "
        "swapping it for a bigger or generic bottle, changing the cap, body, or label proportion, drifting the "
        "label, or resizing it for the camera. The product's real size and shape outrank hero framing and any "
        "instruction to show the product clearly."
    )

    if has_product_reference and structured_authority:
        reference_lock = (
            "PRODUCT REFERENCE LOCK: Treat the attached product reference image as supporting evidence and as hard "
            "visual and physical-scale truth only for details that agree with the structured product truth in this "
            "lock, not mood or style inspiration. Reproduce the real proportions, cap-to-body ratio, and label placement "
            "exactly where they agree, and match the same product-to-hand and product-to-finger relationship shown in "
            "the reference so the product reads at its true small real-world size in the hand. Do not enlarge the product "
            "for label readability, hero framing, or camera visibility, do not create forced-perspective overscale, and "
            "do not push the product much closer to the camera lens than the presenter's hand or face. The structured "
            "bottle geometry, physical printed label lines, label layout, forbidden printed tokens, and reference-conflict "
            "policy are the final authority. If the attached image conflicts by showing different text, a stale label, a "
            "tall or narrow body, a longer neck, different shoulders, different teal coverage, or any other rejected trait, "
            "ignore that conflicting feature and follow the structured authority."
        )
    elif has_product_reference:
        reference_lock = (
            "PRODUCT REFERENCE LOCK: Treat the attached product reference image as the hard visual, geometry, and "
            "physical-scale truth source, not mood or style inspiration. Reproduce the product's real proportions, "
            "cap-to-body ratio, and label placement exactly, and match the same product-to-hand and product-to-finger "
            "relationship shown in the reference so the product reads at its true small real-world size in the hand. "
            "Do not enlarge the product for label readability, hero framing, or camera visibility, do not create "
            "forced-perspective overscale, and do not push the product much closer to the camera lens than the "
            "presenter's hand or face."
        )
    else:
        reference_lock = ""

    frame_persistence = (
        "FRAME PERSISTENCE LOCK: Across every frame keep the identical product identity, silhouette, cap-to-body "
        "ratio, label placement, and small real-world scale — no growth, no rounding, no morphing, no cap, body, or "
        "label mutation, and no progressive enlargement as the camera moves."
        if is_video
        else ""
    )

    if structured_authority and has_product_reference:
        no_modification_lock = (
            "PRODUCT NO-MODIFICATION LOCK: Do NOT modify, change, restyle, redesign, or reinterpret the product in ANY "
            "way. The product must retain ALL original details, design, colors, label text, typography, materials, finish, "
            "and packaging EXACTLY as shown in the product reference image only where it agrees with the structured "
            "product truth in this lock; conflicting reference details must be ignored and the structured product truth "
            "is final."
        )
    elif structured_authority:
        no_modification_lock = (
            "PRODUCT NO-MODIFICATION LOCK: Do NOT modify, change, restyle, redesign, or reinterpret the product in ANY "
            "way. The product must retain ALL original details, design, colors, label text, typography, materials, finish, "
            "and packaging EXACTLY as defined by the structured product truth in this lock."
        )
    elif has_product_reference:
        no_modification_lock = (
            "PRODUCT NO-MODIFICATION LOCK: Do NOT modify, change, restyle, redesign, or reinterpret the product in ANY "
            "way. The product must retain ALL of its original details, design, colors, label text, typography, materials, "
            "finish, and packaging EXACTLY as shown in the product reference image."
        )
    else:
        no_modification_lock = (
            "PRODUCT NO-MODIFICATION LOCK: Do NOT modify, change, restyle, redesign, or reinterpret the product in ANY "
            "way. The product must retain ALL original details, design, colors, label text, typography, materials, finish, "
            "and packaging EXACTLY as described in this product truth lock."
        )

    scale_anchor_lock = (
        "PRODUCT SCALE ANCHOR: When a presenter holds the product, keep it in a natural grip at chest level or lower, "
        "at its true real-world size relative to the hand, fingers, and face. The product must never drift toward the "
        "camera, float, or fill the frame. Keep it clearly legible by FACING it to the camera with sharp focus and good "
        "lighting — NEVER by enlarging it."
    )
    hand_anatomy_lock = (
        "HAND ANATOMY LOCK: Any hand that holds or touches the product must be anatomically correct — exactly five "
        "fingers per hand with natural length, joints, and spacing. Forbidden — extra fingers, duplicated, fused, or "
        "missing fingers, double thumbs, warped knuckles, elongated or distorted hands, especially around the product grip."
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
        "hand_anatomy_lock": hand_anatomy_lock,
        "no_modification_lock": no_modification_lock,
        "scale_anchor_lock": scale_anchor_lock,
        "matched_product_id": matched_id,
    }


def section_2_lock_lines(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> list[str]:
    lock = build_product_lock(
        product,
        is_video=is_video,
        has_product_reference=has_product_reference,
    )
    lines = [
        lock["identity_lock"],
        lock["geometry_lock"],
        lock["scale_lock"],
        lock["negative_morph"],
        lock["no_modification_lock"],
        lock["scale_anchor_lock"],
    ]
    if lock["hand_anatomy_lock"]:
        lines.append(lock["hand_anatomy_lock"])
    return lines


def section_3_lock_lines(
    product: dict[str, Any],
    *,
    is_video: bool,
    has_product_reference: bool,
) -> list[str]:
    lock = build_product_lock(
        product,
        is_video=is_video,
        has_product_reference=has_product_reference,
    )
    return [line for line in (lock["reference_lock"], lock["frame_persistence"]) if line]


def build_concise_engine_product_contract(
    product: dict[str, Any],
    *,
    is_clean_frame: bool = True,
) -> str:
    """Compile ONE concise model-facing product contract paragraph (60-110 words).

    Communicates minimum required truths without schema audit prose or stale narratives:
    1. Use attached image as sole product reference for identity.
    2. Short packaging identity sentence.
    3. Short scale anchor sentence.
    4. Short no-redesign / no-duplicate sentence.
    5. Short clean-frame sentence.
    """
    entry = resolve_schema_entry(product or {})
    raw_name = (
        (entry.get("product_display_name") if entry else None)
        or product.get("name")
        or product.get("product_name")
        or product.get("product_display_name")
        or product.get("raw_product_title")
        or "the product"
    )
    name_clean = _clean_display_name(_clean(raw_name))

    matched_id = entry.get("product_id") if entry else None
    if matched_id == "MWCB_25ML_CAP_BURUNG":
        contract = (
            f"Use the attached image as the sole product reference for {name_clean}. "
            "Preserve the exact compact 25ml green-glass bottle, red ribbed cap, and physical printed label. "
            "Keep it naturally small in an adult hand at palm scale. "
            "Do not enlarge, redesign, duplicate, or relabel it."
        )
    elif entry:
        contract = (
            f"Use the attached image as the sole product reference for {name_clean}. "
            "Preserve the exact packaging family, silhouette, cap style, colors, and physical printed label. "
            "Keep it naturally proportioned at true real-world scale relative to hands and surroundings. "
            "Do not enlarge, redesign, duplicate, or relabel it."
        )
    else:
        contract = (
            f"Use the attached image as the sole product reference for {name_clean}. "
            "Preserve its exact packaging identity, shape, cap, color, and physical printed label. "
            "Keep it naturally proportioned at true real-world scale without enlargement. "
            "Do not enlarge, redesign, duplicate, or relabel it."
        )

    if is_clean_frame:
        contract += " Do not render added captions, headlines, CTAs, buttons, or UI overlay; only text physically printed on the product may appear."

    return contract
