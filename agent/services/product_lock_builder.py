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
        for k in ("name", "product_name", "product_display_name", "product_short_name", "raw_product_title", "type")
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
    """Explicit size evidence from the row (token or pack size). None = ambiguous."""
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
    """Resolve a product row to its authored UNIVERSAL_PRODUCT_SCHEMA entry.

    Match order: explicit ref/id keys → size-gated brand signature → exact
    product_name. Fail-closed against 5ml↔10ml contamination: a BOSMAX row is
    matched to a size variant ONLY with explicit size evidence; a bare, size-less
    "BOSMAX HERBS" row resolves to NOTHING (deterministic fallback) rather than
    guessing a size. Real runtime rows always carry the size (verified in
    flow_agent.db: "Bosmax Herbs 5 ML" / "Bosmax Oil 10 ML").
    """
    products = _schema().get("products") or {}
    if not products:
        return None

    # 1. Explicit operator intent — a ref/id key wins outright (never ambiguous).
    for key in ("product_truth_ref", "product_id", "schema_ref", "id"):
        candidate = _clean(product.get(key)).upper()
        if candidate and candidate in products:
            return products[candidate]

    name = _product_name_text(product)
    if not name:
        return None
    pack_ml = _parse_pack_ml(product)
    size_ml = _resolved_ml(name, pack_ml)

    # 2. BOSMAX family — size-gated, fail-closed on ambiguity.
    if "bosmax" in name:
        if size_ml == 5 and "BOSMAX_SERUM_5ML" in products:
            return products["BOSMAX_SERUM_5ML"]
        if size_ml == 10 and "BOSMAX_HERBS_10ML" in products:
            return products["BOSMAX_HERBS_10ML"]
        return None  # ambiguous bare BOSMAX → generic fallback, never a wrong size

    # 3. Minyak Warisan Cap Burung signature (single authored size).
    if ("minyak warisan" in name or "cap burung" in name) and "MWTCB_25ML_CAP_BURUNG" in products:
        return products["MWTCB_25ML_CAP_BURUNG"]

    # 4. Exact product_name substring for any other authored (non-BOSMAX) product.
    for entry in products.values():
        pn = _lower(entry.get("product_name"))
        if not pn or "bosmax" in pn:  # BOSMAX handled above (size-gated)
            continue
        if pn in name:
            return entry
        if name in pn and len(name) >= 8 and " " in name:
            return entry
    return None


# ── data-driven fallback (no schema entry) ─────────────────────────────────────

# Non-bottle / worn / large-format product families. For these the "palm-sized
# bottle, small relative to an adult hand" assumption is WRONG (a carpet, a jersey,
# or a mattress is not a handheld bottle), so they get a neutral real-world-scale
# lock instead. Tokens MUST be low-ambiguity substrings: e.g. "rug" is deliberately
# excluded because it matches "drugstore"/"drug"; carpets are covered by
# "karpet"/"carpet"/"permaidani" and furniture by "perabot"/"furniture"/"almari".
_NON_BOTTLE_TOKENS: tuple[str, ...] = (
    "karpet", "carpet", "permaidani",
    "jersi", "jersey", "seluar", "tudung", "hijab", "kasut", "selipar", "sandal",
    "cadar", "bedsheet", "tilam", "mattress", "langsir", "curtain",
    "perabot", "furniture", "almari",
)


def _fallback_scale_line(product: dict[str, Any]) -> str:
    """Deterministic scale lock for products with no authored schema entry.

    Two hard rules, both required for Google-Flow safety and portability:
      * NEVER print a numeric pack size (e.g. "300ml") into the scale sentence — the
        engine can render a literal measurement as a ruler/label/caption artifact.
        The pack size only *selects* a qualitative size class.
      * Do NOT force palm-sized-bottle / hand-relative framing onto products that are
        not handheld bottles (apparel, textiles, furniture, large-format).
    """
    pack_ml = _parse_pack_ml(product)
    haystack = " ".join(
        _lower(product.get(k))
        for k in (
            "type", "product_type", "product_scale", "physics_class", "category",
            "subcategory", "name", "product_name", "product_display_name", "raw_product_title",
        )
    )

    # Item 3 — non-bottle / large-format: neutral real-world scale, no hand/bottle framing.
    if any(tok in haystack for tok in _NON_BOTTLE_TOKENS):
        return (
            "Keep the product at its true real-world size and correct proportion relative to a person "
            "and the surrounding environment. Preserve its natural full-size scale; do not shrink it to "
            "a small palm object, do not enlarge the product for camera visibility, and do not distort it."
        )

    # Item 2 — qualitative size CLASS from pack size, never the numeric value.
    handheld: bool | None = None
    if pack_ml is not None:
        if pack_ml <= 6:
            size_phrase = "a tiny lip-balm / chapstick handheld size class"; handheld = True
        elif pack_ml <= 20:
            size_phrase = "a compact pocket roll-on handheld size class"; handheld = True
        elif pack_ml <= 60:
            size_phrase = "a small one-hand-grip bottle size class"; handheld = True
        elif pack_ml <= 150:
            size_phrase = "a medium one-hand bottle size class"; handheld = True
        elif pack_ml <= 500:
            size_phrase = "a large bottle or jar size class held with one or two hands"; handheld = False
        else:
            size_phrase = "a bulk container size class handled with two hands"; handheld = False
    elif any(tok in haystack for tok in ("roll on", "roll-on", "lip balm", "balm", "dropper", "serum")):
        size_phrase = "a compact roll-on / lip-balm handheld size class"; handheld = True
    elif any(tok in haystack for tok in ("bottle", "jar", "tube", "mist", "perfume", "supplement", "oil")):
        size_phrase = "a palm-sized bottle size class unless verified dimensions say otherwise"; handheld = True
    else:
        size_phrase = "its true-to-life real-world size, handled naturally without enlargement"; handheld = None

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
    """Strip bracket/parenthesis variant tags and SKU tails (mirrors the compiler's
    _product_name) so fallback identity locks never leak "(Mix Berry)"-style tags."""
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
            "The product's real size outranks label readability: never enlarge it so the label, "
            "text, or artwork reads more clearly, and if it is turned or rotated toward the "
            "camera its physical size stays exactly the same. Do not enlarge the product for "
            "camera visibility, and do not add any separate comparison object, second product, "
            "prop, ruler, or size marker to the scene."
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
            "product's real proportions, cap-to-body ratio, and label placement exactly, and match the "
            "same product-to-hand and product-to-finger relationship shown in the reference so the product "
            "reads at its true small real-world size in the hand. Do not enlarge the product for label "
            "readability, hero framing, or camera visibility, do not create forced-perspective overscale, "
            "and do not push the product much closer to the camera lens than the presenter's hand or face."
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
