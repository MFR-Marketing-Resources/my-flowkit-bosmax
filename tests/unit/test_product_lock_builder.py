"""Product-truth scale/geometry lock proofs (P1 incident regression).

Guards the fix for the orphaned UNIVERSAL_PRODUCT_SCHEMA lock authority: every
final compiled prompt for every mode must carry engine-visible identity, geometry,
palm-scale, and negative-morph locks (plus reference + frame-persistence where
applicable), and BOSMAX 5ml must never inherit 10ml scale.
"""
import pytest

from agent.services import canonical_prompt_compiler as cpc
from agent.services import product_lock_builder as plb

MW25 = {
    "id": "MWTCB_25ML_CAP_BURUNG",
    "name": "Minyak Warisan Tok Cap Burung 25ml",
    "category": "Wellness",
    "product_truth_ref": "MWTCB_25ML_CAP_BURUNG",
}
BOS5 = {
    "id": "BOSMAX_SERUM_5ML",
    "name": "BOSMAX Serum 5ML / BOSMAX HERBS Herbal Oil Roll On",
    "category": "Wellness",
    "product_truth_ref": "BOSMAX_SERUM_5ML",
}
BOS10 = {
    "id": "BOSMAX_HERBS_10ML",
    "name": "BOSMAX HERBS 10ml Herbal Oil Roll On",
    "category": "Wellness",
}
# Real runtime rows (flow_agent.db shape: name lives in product_display_name;
# there is NO product_truth_ref / pack_size_ml column).
REAL_BOS5 = {"id": "90349f8c", "product_display_name": "Bosmax Herbs 5 ML", "product_short_name": "Bosmax Herbs 5 ML", "type": "Male Health", "category": "Health"}
REAL_BOS10 = {"id": "b460ffbd", "product_display_name": "Bosmax Oil 10 ML", "product_short_name": "Bosmax Oil 10 ML", "type": "Male Health", "category": "Health"}
REAL_MW = {"id": "6483d624", "product_display_name": "Minyak Warisan Tok Cap Burung 25ml", "product_short_name": "Minyak Cap Burung", "brand": "Cap Burung", "type": "Minyak Angin", "category": "Health & Personal Care"}
COPY = {"angle": "routine", "hook": "Cuba tengok ni", "cta": "Tap beg kuning", "formula_family": "HSO"}

ALL_MODES = ["T2V", "HYBRID", "FRAMES", "INGREDIENTS", "IMAGES"]
VIDEO_MODES = ["T2V", "HYBRID", "FRAMES", "INGREDIENTS"]
REFERENCE_MODES = ["HYBRID", "FRAMES", "INGREDIENTS"]


def _compile(product, mode):
    kw = dict(source_mode=mode, engine="GOOGLE_FLOW", duration_seconds=8, product=product, copy=COPY)
    if mode == "INGREDIENTS":
        kw["asset_role_map"] = {"PRODUCT_REFERENCE": True, "AVATAR_REFERENCE": True}
    return cpc.compile_prompt_set(**kw)


def _s2(product, mode):
    return _compile(product, mode)["blocks"][0]["sections"]["SECTION 2 - PRODUCT TRUTH LOCK"].lower()


def _s3(product, mode):
    return _compile(product, mode)["blocks"][0]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()


# ── 1. Minyak Warisan lock ─────────────────────────────────────────────────────

def test_minyak_warisan_lock_geometry_and_scale():
    lock = plb.build_product_lock(MW25, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "MWTCB_25ML_CAP_BURUNG"
    blob = " ".join(lock.values()).lower()
    # Identity tokens come from product_truth_ref; scale/palm tokens from scale_lock.
    # NOTE: the pack-size token ("25ml") is deliberately NOT required here — it must
    # not appear in the engine-facing scale lock (see the Flow-safe test below).
    for token in [
        "green", "glass", "red ribbed", "flat-front", "compact",
        "palm", "small relative to an adult hand",
    ]:
        assert token in blob, f"missing product truth token: {token}"
    # anti-drift semantics
    for forbidden_drift in ["round", "bulbous", "generic", "perfume", "syrup", "skincare", "cosmetic"]:
        assert forbidden_drift in blob, f"missing negative-morph guard: {forbidden_drift}"
    assert "do not enlarge the product for camera visibility" in blob


def test_minyak_warisan_scale_lock_is_flow_safe_qualitative():
    """Google-Flow-safe scale: qualitative hand-fit + size-class + depth language,
    with NO numeric physical dimension (cm/mm/inch) and NO pack-size token inside
    the engine-facing scale sentence. Flow can render literal measurements as
    ruler/diagram/caption artifacts, so the scale lock must stay measurement-free.
    """
    lock = plb.build_product_lock(MW25, is_video=True, has_product_reference=True)
    scale = lock["scale_lock"].lower()
    # required qualitative size-class + hand-fit + perspective/depth anchors
    for phrase in [
        "compact palm-size",
        "fits naturally in one hand",
        "fingers wrapping comfortably",
        "small handheld household herbal-oil bottle",
        "slightly larger than a chapstick-size roll-on",
        "compact handheld size family",
        "natural handheld depth plane",
        "closer to the camera lens",
    ]:
        assert phrase in scale, f"missing Flow-safe scale anchor: {phrase}"
    # anti-drift + anti-upscale guards
    for forbidden in [
        "perfume", "supplement", "syrup", "spray", "cosmetic",
        "oversized medicine bottle", "dominate the hand", "dominate", "frame",
    ]:
        assert forbidden in scale, f"missing anti-drift/anti-upscale guard: {forbidden}"
    # measurement / pack-size tokens must NOT leak into the engine-facing scale lock
    for numeric in ["cm", "mm", "inch", "25ml", "25 ml"]:
        assert numeric not in scale, f"numeric token leaked into Flow scale lock: {numeric}"


@pytest.mark.parametrize("mode", ALL_MODES)
def test_minyak_warisan_flow_safe_scale_reaches_section2(mode):
    """Proof: the qualitative Flow-safe scale wording propagates into the compiled
    engine-facing SECTION 2 for every mode (T2V, HYBRID, FRAMES/F2V,
    INGREDIENTS/I2V, IMAGES/IMG)."""
    s2 = _s2(MW25, mode)
    for phrase in [
        "compact palm-size",
        "slightly larger than a chapstick-size roll-on",
        "natural handheld depth plane",
        "closer to the camera lens",
    ]:
        assert phrase in s2, f"[{mode}] Flow-safe scale anchor missing from SECTION 2: {phrase}"
    # The pack-size token must not leak into the engine-facing SCALE LOCK line.
    # (It legitimately appears in the product-identity header, which we do NOT touch.)
    scale_line = next((ln for ln in s2.splitlines() if "product scale lock" in ln), "")
    assert scale_line, f"[{mode}] SECTION 2 is missing the PRODUCT SCALE LOCK line"
    assert "25ml" not in scale_line and "25 ml" not in scale_line, (
        f"[{mode}] pack-size token leaked into the SECTION 2 SCALE LOCK line"
    )


# ── 2. BOSMAX 5ml lock ─────────────────────────────────────────────────────────

def test_bosmax_5ml_lock_lipbalm_size_no_chapstick_no_numbers():
    lock = plb.build_product_lock(BOS5, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "BOSMAX_SERUM_5ML"
    blob = " ".join(lock.values()).lower()
    # 5ml now uses the qualitative "lip balm" anchor + finger-fit (no numeric scale).
    for token in ["lip balm", "fingers", "roll-on", "black", "palm", "bosmax herbs"]:
        assert token in blob, f"missing product truth token: {token}"
    for forbidden in ["perfume", "spray", "supplement", "skincare", "pump"]:
        assert forbidden in blob, f"missing forbidden-container guard: {forbidden}"
    # the engine-facing SCALE LOCK must be number-free and must NOT carry the 10ml
    # variant's "chapstick" anchor (the numeric survives only in the internal id / real name).
    scale = lock["scale_lock"].lower()
    assert "5ml" not in scale and "10ml" not in scale and "10 ml" not in scale, "numeric scale leaked"
    assert "chapstick" not in scale, "5ml scale lock leaked the 10ml chapstick anchor"


# ── 3. BOSMAX 5ml vs 10ml separation (both authored, size-gated) ────────────────

def test_bosmax_10ml_has_its_own_authored_lock():
    entry = plb.resolve_schema_entry(BOS10)
    assert entry is not None and entry["product_id"] == "BOSMAX_HERBS_10ML"
    lock = plb.build_product_lock(BOS10, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "BOSMAX_HERBS_10ML"
    blob = " ".join(lock.values()).lower()
    # 10ml uses the qualitative "chapstick" anchor; no "lip balm" bleed.
    assert "chapstick" in blob and "lip balm" not in blob
    # numeric pack size must not leak into the engine-facing scale (only the internal id / real name carry it).
    scale = lock["scale_lock"].lower()
    assert "10ml" not in scale and "5ml" not in scale
    assert "never shrink to the smaller-variant scale" in blob


def test_bosmax_5ml_and_10ml_never_inherit_each_other():
    s2_5 = _s2(BOS5, "IMAGES")
    s2_10 = _s2(BOS10, "IMAGES")
    # qualitative anchors, mutually exclusive
    assert "lip balm" in s2_5 and "chapstick" not in s2_5
    assert "chapstick" in s2_10 and "lip balm" not in s2_10
    # the numeric pack size must not leak into the engine-facing SCALE LOCK line
    # (it legitimately appears in the product-identity header / real name).
    scale_line_5 = next((ln for ln in s2_5.splitlines() if "product scale lock" in ln), "")
    scale_line_10 = next((ln for ln in s2_10.splitlines() if "product scale lock" in ln), "")
    assert scale_line_5 and scale_line_10
    assert "5ml" not in scale_line_5 and "10ml" not in scale_line_10
    assert plb.resolve_schema_entry(BOS5)["product_id"] == "BOSMAX_SERUM_5ML"
    assert plb.resolve_schema_entry(BOS10)["product_id"] == "BOSMAX_HERBS_10ML"


def test_ambiguous_bare_bosmax_fails_closed_to_fallback():
    # No size evidence → must NOT guess a size; falls back to a generic (still
    # strong) lock rather than mislabelling as 5ml or 10ml.
    bare = {"id": "x", "product_display_name": "BOSMAX HERBS", "category": "Wellness"}
    assert plb.resolve_schema_entry(bare) is None
    lock = plb.build_product_lock(bare, is_video=True, has_product_reference=False)
    assert lock["matched_product_id"] is None
    blob = " ".join(v for v in lock.values() if isinstance(v, str)).lower()
    assert "5ml" not in blob and "10ml" not in blob


# ── 3b. Real runtime row shapes (flow_agent.db) ─────────────────────────────────

def test_real_runtime_rows_resolve_correctly():
    assert plb.resolve_schema_entry(REAL_BOS5)["product_id"] == "BOSMAX_SERUM_5ML"
    assert plb.resolve_schema_entry(REAL_BOS10)["product_id"] == "BOSMAX_HERBS_10ML"
    assert plb.resolve_schema_entry(REAL_MW)["product_id"] == "MWTCB_25ML_CAP_BURUNG"


def test_real_10ml_row_never_maps_to_5ml():
    # "Bosmax Oil 10 ML" (real active product) must never carry 5ml truth.
    lock = plb.build_product_lock(REAL_BOS10, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "BOSMAX_HERBS_10ML"
    assert "5ml" not in " ".join(lock.values()).lower()


# ── 4. Mode propagation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("product", [MW25, BOS5, BOS10])
@pytest.mark.parametrize("mode", ALL_MODES)
def test_every_mode_carries_identity_geometry_scale_negmorph(product, mode):
    s2 = _s2(product, mode)
    assert "product identity lock" in s2
    assert "product geometry lock" in s2
    assert "product scale lock" in s2
    assert "negative morph" in s2


@pytest.mark.parametrize("product", [MW25, BOS5])
@pytest.mark.parametrize("mode", VIDEO_MODES)
def test_video_modes_carry_frame_persistence(product, mode):
    assert "frame persistence lock" in _s3(product, mode)


def test_image_mode_has_no_frame_persistence():
    assert "frame persistence lock" not in _s3(MW25, "IMAGES")


@pytest.mark.parametrize("product", [MW25, BOS5])
@pytest.mark.parametrize("mode", REFERENCE_MODES)
def test_reference_modes_carry_reference_lock(product, mode):
    assert "product reference lock" in _s3(product, mode)


def test_t2v_has_no_reference_lock_but_strong_text_scale_lock():
    # T2V has no product image → no reference lock, but S2 text lock compensates.
    assert "product reference lock" not in _s3(MW25, "T2V")
    assert "product scale lock" in _s2(MW25, "T2V")


# ── 4b. Product-reference SCALE authority (global reference-scale incident) ─────
# Root incident: live Flow still rendered MWTCB oversized after text scale_lock.
# The shared reference lock must bind the uploaded reference as hard SCALE truth
# (product-to-hand relationship, cap/body ratio, label placement, anti-upscale,
# anti-forced-perspective), globally for every product — not just identity.

_REF_SCALE_PHRASES = [
    "hard visual",
    "physical-scale truth",
    "not mood or style inspiration",
    "cap-to-body ratio",
    "label placement",
    "product-to-hand",
    "product-to-finger",
    "true small real-world size",
    "do not enlarge the product for label readability",
    "hero framing",
    "forced-perspective overscale",
    "closer to the camera lens",
]


@pytest.mark.parametrize("product", [MW25, BOS5, BOS10])
def test_product_reference_lock_binds_scale_hand_fit_and_anti_forced_perspective(product):
    ref = plb.build_product_lock(
        product, is_video=True, has_product_reference=True,
    )["reference_lock"].lower()
    for phrase in _REF_SCALE_PHRASES:
        assert phrase in ref, f"[{product['id']}] reference lock missing scale-authority phrase: {phrase}"
    # never a numeric physical dimension
    for numeric in ["cm", "mm", "inch"]:
        assert numeric not in ref, f"numeric dimension leaked into reference lock: {numeric}"


def test_no_reference_lock_when_no_product_image():
    # No image → no reference lock at all (must not claim an uploaded reference exists).
    assert plb.build_product_lock(MW25, is_video=True, has_product_reference=False)["reference_lock"] == ""


@pytest.mark.parametrize("product", [MW25, BOS5, BOS10])
@pytest.mark.parametrize("mode", REFERENCE_MODES)
def test_image_modes_carry_reference_scale_authority_in_section3(product, mode):
    """HYBRID / FRAMES / INGREDIENTS compiled SECTION 3 carries reference-scale
    authority (hand-fit + anti-forced-perspective), globally for every product."""
    s3 = _s3(product, mode)
    assert "product reference lock" in s3
    assert "product-to-hand" in s3
    assert "forced-perspective overscale" in s3
    assert "closer to the camera lens" in s3


def test_img_with_product_reference_carries_scale_authority():
    s3 = cpc.compile_prompt_set(
        source_mode="IMAGES", product=MW25, copy=COPY,
        asset_role_map={"PRODUCT_REFERENCE": True},
    )["blocks"][0]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    assert "product reference lock" in s3
    assert "product-to-hand" in s3 and "forced-perspective overscale" in s3


def test_img_without_product_image_has_no_reference_scale_claim():
    # IMG with no product image → falls back to schema scale lock, no reference claim.
    s3 = _s3(MW25, "IMAGES")
    s2 = _s2(MW25, "IMAGES")
    assert "product reference lock" not in s3
    assert "product scale lock" in s2  # schema fallback still present


def test_mwtcb_reference_scale_regression_across_image_modes():
    """MWTCB regression: with a product reference, every image-assisted mode binds
    bottle-to-hand scale + cap/body ratio + anti-forced-perspective; no numeric dim."""
    for mode in ["HYBRID", "FRAMES", "INGREDIENTS"]:
        s3 = _s3(MW25, mode)
        for phrase in ["product-to-hand", "cap-to-body ratio", "label placement",
                       "forced-perspective overscale", "closer to the camera lens"]:
            assert phrase in s3, f"[{mode}] MWTCB reference-scale missing: {phrase}"


# ── 5. Regression: fallback + graceful degrade ─────────────────────────────────

def test_unlisted_product_still_gets_strong_lock_via_fallback():
    unlisted = {"id": "x1", "name": "Some New 30ml Herbal Oil Bottle", "category": "Wellness"}
    assert plb.resolve_schema_entry(unlisted) is None
    lock = plb.build_product_lock(unlisted, is_video=True, has_product_reference=False)
    blob = " ".join(v for v in lock.values() if isinstance(v, str)).lower()
    assert "product identity lock" in blob
    assert "product geometry lock" in blob
    assert "product scale lock" in blob
    # pack size drives a qualitative size CLASS, but the numeric value must NOT be
    # printed into the engine-facing scale lock (Flow can draw it as a ruler).
    scale = lock["scale_lock"].lower()
    assert "one-hand-grip bottle size class" in scale  # 30ml -> small handheld bottle class
    assert "30ml" not in scale and "30 ml" not in scale
    assert "do not enlarge the product for camera visibility" in blob


def test_fallback_scale_never_prints_numeric_pack_size():
    # Item 2: a sized non-authored product derives a qualitative size CLASS, but the
    # numeric pack size must never be printed into the engine-facing scale lock — Flow
    # can render a literal measurement as a ruler/label/caption artifact.
    for name, size_class in [
        ("New Serum 100ml Bottle", "medium one-hand bottle size class"),
        ("Kombo Kokojar Balang Saiz 300ml", "large bottle or jar size class"),
        ("Bulk Refill 1000ml Drum", "bulk container size class"),
    ]:
        scale = plb.build_product_lock(
            {"id": "z", "name": name, "category": "Wellness"},
            is_video=False, has_product_reference=False,
        )["scale_lock"].lower()
        assert size_class in scale, f"expected {size_class!r} for {name!r}"
        for num in ["100ml", "300ml", "1000ml", "100 ml", "300 ml", "1000 ml"]:
            assert num not in scale, f"numeric pack size leaked into scale lock: {num} ({name})"


def test_fallback_non_bottle_product_gets_no_palm_bottle_framing():
    # Item 3: carpets, apparel, bedding, furniture are not handheld bottles — they must
    # NOT inherit the palm-sized / small-relative-to-hand bottle assumption.
    for name in [
        "Classy 6XXXL Karpet Velvet Paling Besar",
        "Qayraa Jersi Muslimah Labuh",
        "Premium Cadar Bedsheet Set",
        "Almari Perabot Kayu",
    ]:
        scale = plb.build_product_lock(
            {"id": "n", "name": name, "category": "Home"},
            is_video=False, has_product_reference=False,
        )["scale_lock"].lower()
        assert "true real-world size" in scale, f"non-bottle {name!r} missing real-world scale"
        assert "palm-sized" not in scale, f"non-bottle {name!r} kept palm-sized bottle framing"
        assert "small relative to an adult hand" not in scale, f"non-bottle {name!r} kept hand framing"


def test_fallback_bottle_product_still_gets_handheld_scale():
    # Guard: a genuine bottle (spray/mist) must still get palm/handheld framing so the
    # non-bottle guard does not over-reach.
    scale = plb.build_product_lock(
        {"id": "b", "name": "Elianto Body Spray Fragrance Mist", "category": "Beauty"},
        is_video=False, has_product_reference=False,
    )["scale_lock"].lower()
    assert "palm-sized bottle" in scale
    assert "small relative to an adult hand" in scale


def test_non_bottle_guard_ignores_ambiguous_substrings_like_drug():
    # Regression: the non-bottle guard must use low-ambiguity tokens. A "drugstore"
    # roll-on must NOT be misclassified as a carpet/non-bottle ("rug" substring),
    # which would strip its handheld palm-scale framing.
    for name in ["Drugstore Beauty Roll On", "Herbal Drug Serum Dropper"]:
        scale = plb.build_product_lock(
            {"id": "d", "name": name, "category": "Beauty"},
            is_video=False, has_product_reference=False,
        )["scale_lock"].lower()
        assert "true real-world size" not in scale, f"{name!r} wrongly classified non-bottle"
        assert "small relative to an adult hand" in scale, f"{name!r} lost handheld framing"


def test_thin_name_with_size_resolves_and_without_size_fails_closed():
    # Thin name WITH size evidence resolves; a size-less BOSMAX name does not.
    assert (plb.resolve_schema_entry({"id": "p1", "name": "Bosmax Herbs 5 ML"}) or {}).get("product_id") == "BOSMAX_SERUM_5ML"
    assert plb.resolve_schema_entry({"id": "p1b", "name": "BOSMAX HERBS"}) is None
    # Minyak has a single authored size → its brand signature is unambiguous.
    thin_mw = {"id": "p2", "name": "Minyak Warisan Tok Cap Burung", "category": "Wellness"}
    assert (plb.resolve_schema_entry(thin_mw) or {}).get("product_id") == "MWTCB_25ML_CAP_BURUNG"


def test_explicit_ref_key_overrides_ambiguity():
    # Operator explicitly setting product_truth_ref is unambiguous intent.
    assert plb.resolve_schema_entry({"product_truth_ref": "BOSMAX_SERUM_5ML", "name": "whatever"})["product_id"] == "BOSMAX_SERUM_5ML"


def test_generic_word_does_not_false_match_authored_entry():
    # A single generic word that happens to be a substring of an authored name
    # (e.g. "oil" inside "...Herbal Oil Roll On") must NOT resolve to that product.
    assert plb.resolve_schema_entry({"id": "g", "name": "Oil"}) is None
    assert plb.resolve_schema_entry({"id": "g2", "name": "Serum"}) is None


def test_empty_product_does_not_crash_and_still_locks():
    lock = plb.build_product_lock({}, is_video=False, has_product_reference=False)
    assert lock["identity_lock"] and lock["geometry_lock"] and lock["scale_lock"]
    assert lock["frame_persistence"] == "" and lock["reference_lock"] == ""


# ── 5b. IMG reference-lock propagation ─────────────────────────────────────────

def test_img_with_product_reference_gets_reference_lock():
    result = cpc.compile_prompt_set(
        source_mode="IMAGES", product=MW25, copy=COPY,
        asset_role_map={"PRODUCT_REFERENCE": True},
    )
    s3 = result["blocks"][0]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    assert "product reference lock" in s3


def test_img_without_reference_still_has_full_section2_lock():
    s2 = _s2(MW25, "IMAGES")
    s3 = _s3(MW25, "IMAGES")
    assert "product reference lock" not in s3  # no image attached
    for token in ["product identity lock", "product geometry lock", "product scale lock", "negative morph"]:
        assert token in s2


def test_ugc_img_path_propagates_product_reference_when_image_attached():
    from agent.services import ugc_video_prompt_compiler_service as ugc
    base = dict(
        approved_package={"scene_context": "clean desk"}, mode="IMG",
        target_language="BM_MS", generation_mode="SINGLE", duration_seconds=8,
    )
    with_img = ugc.compile_ugc_video_prompt(product={**MW25, "media_id": "abc-123"}, **base)
    without_img = ugc.compile_ugc_video_prompt(product=dict(MW25), **base)
    joined_with = with_img["final_compiled_prompt_text"].lower()
    joined_without = without_img["final_compiled_prompt_text"].lower()
    assert "product reference lock" in joined_with
    assert "product reference lock" not in joined_without
    # Both must still carry the full SECTION 2 text lock.
    for joined in (joined_with, joined_without):
        assert "product scale lock" in joined and "product geometry lock" in joined


# ── 6. Guardrail: scrub-safety ─────────────────────────────────────────────────

@pytest.mark.parametrize("product", [MW25, BOS5, BOS10])
@pytest.mark.parametrize("mode", ALL_MODES)
def test_locks_never_trip_engine_scrub(product, mode):
    result = _compile(product, mode)
    for block in result["blocks"]:
        assert block["scrub_violations"] == [], block["scrub_violations"]


# ── 7. MWTCB object-class + relative-scale (post-#214/#215/#217 overscale) ──────
# Remaining gap: the engine had the SHAPE description but no named OBJECT CLASS,
# and the non-reference scale path (T2V + schema scale) never said physical scale
# outranks label readability. Both added globally/per-product without numerics.

def test_mwtcb_object_class_named_flat_traditional_medicated_oil():
    lock = plb.build_product_lock(MW25, is_video=True, has_product_reference=True)
    ident = lock["identity_lock"].lower()
    for phrase in ["flat traditional medicated-oil", "flat-front glass herbal-oil",
                   "minyak-angin", "pocket-size"]:
        assert phrase in ident, f"object-class grounding missing: {phrase}"
    # explicit anti-round / anti-tall / anti-wrong-container class
    for forbidden in ["cylindrical", "round-bodied", "tall", "perfume", "syrup",
                      "supplement", "cosmetic"]:
        assert forbidden in ident, f"object-class negative missing: {forbidden}"


def test_scale_outranks_label_readability_and_no_comparison_object():
    scale = plb.build_product_lock(MW25, is_video=True, has_product_reference=False)["scale_lock"].lower()
    assert "real size outranks label readability" in scale
    assert "turned or rotated toward the" in scale and "physical size stays exactly the same" in scale
    assert "do not add any separate comparison object" in scale
    assert "ruler" in scale and "size marker" in scale        # anti-measurement-prop
    for numeric in ["cm", "mm", "inch"]:
        assert numeric not in scale


@pytest.mark.parametrize("mode", ALL_MODES)
def test_object_class_and_scale_precedence_reach_section2_every_mode(mode):
    # Including T2V (no reference image) — the mode most prone to overscale.
    s2 = _s2(MW25, mode)
    assert "flat traditional medicated-oil" in s2       # object class
    assert "real size outranks label readability" in s2  # readability precedence
    assert "comparison object" in s2                     # anti-prop / anti-vape-insertion


def test_no_vape_or_pod_object_named_in_mwtcb_locks():
    # The real bottle is near small-pod height, but naming vape/pod risks the engine
    # DRAWING one. Assert no such distractor object leaks into any MWTCB lock.
    blob = " ".join(v for v in plb.build_product_lock(
        MW25, is_video=True, has_product_reference=True).values() if isinstance(v, str)).lower()
    for distractor in ["vape", "pod-device", "pod device", "e-cigarette", "soda can"]:
        assert distractor not in blob, f"distractor object leaked into MWTCB lock: {distractor}"


def test_bosmax_inherits_readability_precedence_without_mwtcb_contamination():
    for prod, own_class in ((BOS5, "lip balm"), (BOS10, "chapstick")):
        scale = plb.build_product_lock(prod, is_video=True, has_product_reference=False)["scale_lock"].lower()
        assert "real size outranks label readability" in scale   # global improvement reaches BOSMAX
        assert own_class in scale                                # BOSMAX keeps its own qualitative scale class
        ident = plb.build_product_lock(prod, is_video=True, has_product_reference=False)["identity_lock"].lower()
        # MWTCB object-class must NOT bleed into BOSMAX identity
        assert "medicated-oil" not in ident and "minyak-angin" not in ident
    # 5ml<->10ml separation intact (qualitative anchors, no numeric leak)
    bos5_scale = plb.build_product_lock(BOS5, is_video=True, has_product_reference=False)["scale_lock"].lower()
    assert "chapstick" not in bos5_scale and "10ml" not in bos5_scale
