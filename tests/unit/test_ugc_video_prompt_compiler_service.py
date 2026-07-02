import pytest

from agent.services.ugc_video_prompt_compiler_service import (
    _compact_overlay,
    _clean_name_for_dialog,
    compile_ugc_video_prompt,
)


def _product():
    return {
        "id": "4d491c01-2c5a-40c0-869e-54c50050d95d",
        "raw_product_title": "[NEW]Glad2Glow Day & Night Body Serum Set 24-HOUR Body",
        "product_display_name": "[NEW]Glad2Glow Day & Night Body Serum Set 24-HOUR Body",
    }


def _approved_package():
    return {
        "mode": "F2V",
        "claim_safe_rewrite": "Frame the serum as a body-care routine for smooth-feeling, fresh-smelling skin with no guaranteed outcomes.",
    }


def test_compiler_generates_single_block_final_prompt():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        camera_style="UGC_IPHONE_RAW",
        character_presence="VISIBLE_CREATOR",
        creator_persona="DEFAULT_CREATOR",
        target_language="BM_MS",
        safe_hook_angles=["Mulakan dengan creator tunjuk rutin body serum yang nampak natural dan claim-safe."],
        safe_cta_angles=["Akhiri dengan CTA lembut untuk cuba rutin body-care ini."],
    )

    assert result["generation_mode"] == "SINGLE"
    assert result["total_duration_seconds"] == 8
    assert result["camera_style"] == "UGC_IPHONE_RAW"
    assert result["character_presence"] == "VISIBLE_CREATOR"
    assert result["target_language"] == "BM_MS"
    assert len(result["prompt_blocks"]) == 1
    assert result["prompt_blocks"][0]["shot_count"] == 2
    # ADR-008 canonical: a CONCRETE presenter from the avatar registry, never
    # the generic "visible creator" placeholder.
    assert "The presenter is a Malaysian adult" in result["final_compiled_prompt_text"]
    assert "one visible creator" not in result["final_compiled_prompt_text"].lower()
    # Canonical 9-section structure with camera-style differentiation preserved
    assert result["final_compiled_prompt_text"].startswith("SECTION 1 - ROLE & OBJECTIVE")
    assert "SECTION 9 - NO_OVERLAY" in result["final_compiled_prompt_text"]
    assert "9:16 handheld" in result["final_compiled_prompt_text"]
    assert "Shot 1:" in result["final_compiled_prompt_text"]
    assert "Shot 2:" in result["final_compiled_prompt_text"]
    assert "Create a premium frames-to-video sequence" not in result["final_compiled_prompt_text"]
    # Internal directive keys must NOT leak into the engine-ready prompt
    assert "Claim-safe copy anchor" not in result["final_compiled_prompt_text"]
    assert "Block 1 (ANCHOR)" not in result["final_compiled_prompt_text"]
    assert result["prompt_blocks"][0]["dialogue_word_budget"] == 22


def test_workspace_entrypoint_uses_sweet_wps_by_default():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        target_language="BM_MS",
        safe_hook_angles=["Weh korang, ini memang ngam kalau nak bau rasa lagi kemas."],
        safe_cta_angles=["Kalau korang suka jenis yang senang masuk rutin harian, cuba yang ni dulu."],
    )
    block = result["prompt_blocks"][0]
    assert block["dialogue_word_budget"] == 22
    assert block["engine_prompt_text"].count("SECTION 6 - SPOKEN DIALOGUE") == 1


def test_compiler_generates_extend_continuation_lineage():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="EXTEND",
        duration_seconds=8,
        blocks=[
            {"block_index": 1, "duration_seconds": 10},
            {"block_index": 2, "duration_seconds": 6},
        ],
        camera_style="CINEMATIC_PRO",
        character_presence="VISIBLE_CREATOR",
        creator_persona="DEFAULT_CREATOR",
        target_language="EN_US",
        safe_hook_angles=["Open with a creator-led body serum moment that feels native and safe."],
        safe_cta_angles=["Close with a calm CTA to try the routine."],
    )

    assert result["generation_mode"] == "EXTEND"
    assert result["total_duration_seconds"] == 16
    assert len(result["prompt_blocks"]) == 2
    assert result["prompt_blocks"][0]["duration_seconds"] == 10
    assert result["prompt_blocks"][0]["shot_count"] == 3
    assert result["prompt_blocks"][1]["duration_seconds"] == 6
    assert result["prompt_blocks"][1]["shot_count"] == 1
    assert result["prompt_blocks"][1]["continuation_from_block_id"] == "block_1"
    assert result["continuation_lineage"][0]["continuation_from_block_id"] == "block_1"
    # ADR-008 canonical: continuation is naturalized prose inside SECTION 3/5,
    # never an internal "CONTINUATION:" label (scrub law).
    block2 = result["prompt_blocks"][1]["engine_prompt_text"]
    assert "continues the previous clip" in block2
    assert "exact final visible state" in block2
    # Cinematic camera style stays differentiated in SECTION 5
    assert "cinematic commercial look" in result["final_compiled_prompt_text"]


# ── Fix regression: internal process leakage ──────────────────────────────────

def test_engine_prompt_has_no_internal_process_leakage():
    """Internal generation rules must never appear in the engine prompt."""
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        safe_hook_angles=["Open naturally with the creator showing the serum."],
        safe_cta_angles=["Try this body serum for your daily skincare routine today."],
    )
    final = result["final_compiled_prompt_text"]
    assert "Total spoken budget" not in final
    assert "Deliver lines in natural colloquial Malay" not in final
    assert "Use everyday vocabulary" not in final
    assert "Sound like personal sharing" not in final
    assert "NOT a sales pitch" not in final
    assert "bahasa perbualan harian" not in final


# ── Fix regression: dialog duplication ────────────────────────────────────────

def test_engine_prompt_no_dialog_duplication():
    """Dialog lines must appear once only — in DIALOG SCRIPT, not also as | Audio:."""
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        safe_hook_angles=["Mulakan dengan creator tunjuk produk secara natural."],
        safe_cta_angles=["Cuba serum badan ni untuk rutin harian anda sekarang ya."],
    )
    final = result["final_compiled_prompt_text"]
    assert "| Audio:" not in final


# ── Fix regression: overlay verbatim copy ─────────────────────────────────────

def test_overlay_is_compact_not_verbatim_cta():
    """Overlay must not be the verbatim spoken CTA sentence."""
    long_cta = (
        "Kalau korang tengah cari serum badan yang boleh bagi kulit lembut dan wangi "
        "seharian, memang boleh cuba yang ni dulu sebab memang berbaloi."
    )
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        overlay_enabled=True,
        safe_cta_angles=[long_cta],
    )
    final = result["final_compiled_prompt_text"]
    # ADR-008 canonical: overlay lives inside SECTION 9 as permitted on-screen
    # text, still compact, never the verbatim CTA sentence.
    assert "On-screen text is permitted" in final, "Expected overlay permission for a long CTA"
    assert long_cta not in final.split("SECTION 9")[-1], "Overlay must not be verbatim CTA"
    import re as _re
    quoted = _re.search(r"permitted for this block only: '([^']+)'", final)
    assert quoted and len(quoted.group(1).split()) <= 6, "Overlay must be compact (≤6 words)"


def test_overlay_omitted_when_cta_too_short_to_truncate():
    """Overlay must be omitted when the CTA is already ≤5 words (fail-closed)."""
    short_cta = "Cuba ni sekarang."  # 3 words — fail-closed
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        overlay_enabled=True,
        safe_cta_angles=[short_cta],
    )
    assert "OVERLAY TEXT:" not in result["final_compiled_prompt_text"]


def test_overlay_omitted_when_overlay_disabled():
    """No overlay section must appear when overlay_enabled=False."""
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        overlay_enabled=False,
        safe_cta_angles=["Dapatkan kulit cerah dan lembut dengan serum badan terbaik ini."],
    )
    assert "OVERLAY TEXT:" not in result["final_compiled_prompt_text"]


# ── Fix regression: compact overlay anchor extraction ─────────────────────────

@pytest.mark.parametrize("cta,expected", [
    (
        "Kalau korang nak dapatkan sekarang, boleh terus order melalui link in bio.",
        "Link in bio",
    ),
    (
        "Jangan lupa beli sekarang sebelum stok habis ya.",
        "Beli sekarang",
    ),
    (
        "Kalau korang nak cuba sekarang, terus je order dari sini.",
        "Cuba sekarang",
    ),
])
def test_compact_overlay_extracts_anchor(cta: str, expected: str):
    assert _compact_overlay(cta) == expected


def test_compact_overlay_truncates_long_cta_without_anchor():
    cta = "Serum badan ni memang sesuai untuk rutin malam dan pagi anda setiap hari."
    result = _compact_overlay(cta)
    assert result is not None
    assert result != cta
    assert len(result.split()) <= 5


def test_compact_overlay_returns_none_for_short_cta():
    assert _compact_overlay("Cuba ni.") is None
    assert _compact_overlay("Try this.") is None
    assert _compact_overlay("") is None


# ── Fix regression: camera directives concrete ────────────────────────────────

def test_camera_directives_ugc_are_specific():
    """UGC camera setup must include concrete framing, movement, and lighting terms."""
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="T2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        camera_style="UGC_IPHONE_RAW",
    )
    final = result["final_compiled_prompt_text"]
    # ADR-008 canonical: UGC camera language stays concrete inside SECTION 5.
    assert "9:16 handheld" in final
    assert "micro-jitter" in final
    assert any(term in final for term in ("24mm", "26mm", "wide-equivalent"))
    assert any(term in final for term in ("natural indoor light", "natural light", "window light"))


def test_camera_directives_cinematic_are_specific():
    """Cinematic camera setup must include concrete stabilisation and lighting terms."""
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="T2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        camera_style="CINEMATIC_PRO",
    )
    final = result["final_compiled_prompt_text"]
    # ADR-008 canonical: cinematic style stays differentiated inside SECTION 5.
    assert "cinematic commercial look" in final
    assert any(term in final for term in ("stabilized", "controlled lighting", "premium"))
    assert "cinematic commercial look" not in compile_ugc_video_prompt(
        product=_product(), approved_package=_approved_package(), mode="T2V",
        generation_mode="SINGLE", duration_seconds=8, camera_style="UGC_IPHONE_RAW",
    )["final_compiled_prompt_text"], "UGC and cinematic must render differently"


# ── Fix regression: parenthesis variant tags stripped from product name ───────

@pytest.mark.parametrize("raw,expected", [
    (
        "LAVVA LA LUNA+ Campuran Beri (Mix Berry) - Kesan Cerah Kulit",
        "LAVVA LA LUNA+ Campuran Beri - Kesan Cerah Kulit",
    ),
    (
        "Product Name (Variant A) - Description",
        "Product Name - Description",
    ),
    (
        "Clean Name Without Parens",
        "Clean Name Without Parens",
    ),
    (
        "[NEW] Product (Scent) - Title",
        "Product - Title",
    ),
])
def test_clean_name_strips_parenthesis_variants(raw: str, expected: str):
    assert _clean_name_for_dialog(raw) == expected


def test_engine_prompt_no_parenthesis_in_product_name():
    """Parenthesis variant tags must not appear in the compiled engine prompt."""
    product = {
        "id": "test-id",
        "raw_product_title": "Test Serum (Mix Berry) - Glowing Skin",
        "product_display_name": "Test Serum (Mix Berry) - Glowing Skin",
    }
    result = compile_ugc_video_prompt(
        product=product,
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        safe_hook_angles=["Cuba serum ni untuk kulit cantik."],
        safe_cta_angles=["Dapatkan kulit cerah dengan serum ni sekarang."],
    )
    final = result["final_compiled_prompt_text"]
    assert "(Mix Berry)" not in final
