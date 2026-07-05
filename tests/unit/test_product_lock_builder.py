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
    for token in [
        "25ml", "green", "glass", "red ribbed", "flat-front", "compact",
        "palm", "small relative to an adult hand",
    ]:
        assert token in blob, f"missing product truth token: {token}"
    # anti-drift semantics
    for forbidden_drift in ["round", "bulbous", "generic", "perfume", "syrup", "skincare", "cosmetic"]:
        assert forbidden_drift in blob, f"missing negative-morph guard: {forbidden_drift}"
    assert "do not enlarge the product for camera visibility" in blob


# ── 2. BOSMAX 5ml lock ─────────────────────────────────────────────────────────

def test_bosmax_5ml_lock_tiny_and_no_10ml():
    lock = plb.build_product_lock(BOS5, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "BOSMAX_SERUM_5ML"
    blob = " ".join(lock.values()).lower()
    for token in ["5ml", "lip balm", "roll-on", "black", "palm", "bosmax herbs"]:
        assert token in blob, f"missing product truth token: {token}"
    for forbidden in ["perfume", "spray", "supplement", "skincare", "pump"]:
        assert forbidden in blob, f"missing forbidden-container guard: {forbidden}"
    assert "10ml" not in blob and "10 ml" not in blob, "5ml lock leaked 10ml scale"


# ── 3. BOSMAX 5ml vs 10ml separation (both authored, size-gated) ────────────────

def test_bosmax_10ml_has_its_own_authored_lock():
    entry = plb.resolve_schema_entry(BOS10)
    assert entry is not None and entry["product_id"] == "BOSMAX_HERBS_10ML"
    lock = plb.build_product_lock(BOS10, is_video=True, has_product_reference=True)
    assert lock["matched_product_id"] == "BOSMAX_HERBS_10ML"
    blob = " ".join(lock.values()).lower()
    assert "10ml" in blob and "5ml" not in blob
    assert "never shrink to the smaller-variant scale" in blob


def test_bosmax_5ml_and_10ml_never_inherit_each_other():
    s2_5 = _s2(BOS5, "IMAGES")
    s2_10 = _s2(BOS10, "IMAGES")
    assert "5ml" in s2_5 and "10ml" not in s2_5
    assert "10ml" in s2_10 and "5ml" not in s2_10
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


# ── 5. Regression: fallback + graceful degrade ─────────────────────────────────

def test_unlisted_product_still_gets_strong_lock_via_fallback():
    unlisted = {"id": "x1", "name": "Some New 30ml Herbal Oil Bottle", "category": "Wellness"}
    assert plb.resolve_schema_entry(unlisted) is None
    lock = plb.build_product_lock(unlisted, is_video=True, has_product_reference=False)
    blob = " ".join(v for v in lock.values() if isinstance(v, str)).lower()
    assert "product identity lock" in blob
    assert "product geometry lock" in blob
    assert "product scale lock" in blob
    assert "30ml" in blob  # pack size derived from name
    assert "do not enlarge the product for camera visibility" in blob


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
