"""Canonical prompt compiler contract tests (ADR-008 mission proofs).

Locks: canonical 9-section structure · multi-block beyond 2 (workbook 1-7) ·
WPS budgeting from retained workbook (Safe default, Malay Sweet 2.7) ·
HYBRID / FRAMES / INGREDIENTS differentiation · NO_OVERLAY default ·
concrete avatar description rendering · no-leakage scrub · CTA final-block law.
"""
import re

import pytest

from agent.services import avatar_registry
from agent.services import canonical_prompt_compiler as cpc

PRODUCT = {"id": "prod-001", "name": "SKINTIFIC Matte Sunscreen", "category": "Beauty & Personal Care"}
COPY = {
    "angle": "routine_upgrade",
    "hook": "Weh korang, kulit muka aku tak berminyak dah sepanjang hari!",
    "subhook": "Dulu setiap tengah hari mesti muka macam kilang minyak.",
    "usp1": "Matte habis, tak melekit, terus jadi primer sebelum mekap.",
    "usp2": "SPF50+ PA+++ lindung sepanjang hari walaupun panas terik.",
    "cta": "Cepat grab sekarang, tekan beg kuning sebelum promo habis!",
    "formula_family": "HSO",
}


def _compile(mode="HYBRID", **kw):
    defaults = dict(
        source_mode=mode, engine="GOOGLE_FLOW", duration_seconds=8,
        product=PRODUCT, copy=COPY, target_language="BM_MS",
    )
    defaults.update(kw)
    return cpc.compile_prompt_set(**defaults)


def test_canonical_nine_sections_in_order_every_block():
    result = _compile(duration_seconds=16)
    assert result["total_blocks"] == 2
    for block in result["blocks"]:
        text = block["engine_prompt_text"]
        positions = [text.find(h) for h in cpc.CANONICAL_SECTIONS]
        assert all(p >= 0 for p in positions), f"missing section in block {block['block_index']}"
        assert positions == sorted(positions), "sections out of canonical order"


def test_multi_block_seven_blocks_google_flow_56s():
    # Workbook: Google Flow 56s = [8,8,8,8,8,8,8] — the 2-block cap is dead.
    result = _compile(duration_seconds=56)
    assert result["block_plan"] == [8, 8, 8, 8, 8, 8, 8]
    assert result["total_blocks"] == 7
    assert len(result["blocks"]) == 7


def test_flow_40s_requires_preferred_lane_then_resolves():
    with pytest.raises(ValueError, match="PREFERRED_LANE_REQUIRED"):
        _compile(duration_seconds=40)
    lane_a = _compile(duration_seconds=40, preferred_lane="10s")
    assert lane_a["block_plan"] == [10, 10, 10, 10]
    lane_b = _compile(duration_seconds=40, preferred_lane="8s")
    assert lane_b["block_plan"] == [8, 8, 8, 8, 8]


def test_wps_budget_from_workbook_safe_default_and_sweet_mode():
    # Malay 8s: Safe 2.4 → 19 words; Sweet 2.7 → 22 words (retained workbook).
    assert cpc.dialogue_word_budget(8, "BM_MS") == 19
    assert cpc.dialogue_word_budget(8, "BM_MS", wps_mode="SWEET") == 22
    assert cpc.dialogue_word_budget(10, "BM_MS", wps_mode="SWEET") == 27
    # English Safe 2.3 → 18
    assert cpc.dialogue_word_budget(8, "EN") == 18


def test_dialogue_richer_than_legacy_and_within_budget():
    result = _compile(duration_seconds=8, wps_mode="SWEET")
    block = result["blocks"][0]
    # Legacy budget was floor(8 * 1.7) = 13 words; Sweet authority = 22.
    assert block["dialogue_word_budget"] == 22
    assert block["dialogue_word_count"] > 13, "dialogue must beat the legacy skinny budget"
    assert block["dialogue_word_count"] <= 22


def test_dialogue_lands_on_complete_clause_not_mid_sentence():
    result = _compile(duration_seconds=8, wps_mode="SWEET")
    dialogue = result["blocks"][0]["dialogue"]
    assert dialogue.endswith((".", "!", "?"))
    assert not dialogue.endswith("cepat")


def test_section6_uses_trigger_angle_and_cta_type_clause_bank_for_thin_copy():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-frag-cta",
            "name": "SZINDORE PERFUME",
            "category": "Fragrance",
            "trigger_id": "CONFIDENCE_01",
            "copywriting_angle": "Confidence-led scent appeal and everyday freshness",
        },
        copy={
            "hook": "Weh, aku baru try ni.",
            "subhook": "Mula-mula nampak biasa je.",
            "cta": "Cuba tengok dulu.",
            "cta_type": "save_for_later",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    first, final = result["blocks"][0]["dialogue"], result["blocks"][-1]["dialogue"]
    assert "naik rasa yakin" in first.lower()
    assert "simpan dulu" in final.lower()


def test_cta_lands_only_in_final_block():
    result = _compile(duration_seconds=16)
    first, final = result["blocks"][0], result["blocks"][-1]
    assert "beg kuning" not in first["dialogue"]
    assert "beg kuning" in final["dialogue"]
    # hook opens block 1
    assert first["dialogue"].startswith("Weh korang")


def test_hybrid_embeds_concrete_presenter_never_generic():
    result = _compile(mode="HYBRID")
    text = result["blocks"][0]["engine_prompt_text"]
    assert "uploaded product image" in text
    assert "The presenter is a Malaysian adult" in text
    assert "one visible creator" not in text.lower()
    assert result["presenter"]["avatar_code"], "resolved presenter must be a real registry profile"


def test_hybrid_presenter_is_deterministic_per_product():
    a = _compile(mode="HYBRID")["presenter"]["avatar_code"]
    b = _compile(mode="HYBRID")["presenter"]["avatar_code"]
    assert a == b, "same product must keep the same presenter across regenerations"


def test_frames_is_motion_delta_only_no_rebuild():
    result = _compile(mode="FRAMES")
    text = result["blocks"][0]["engine_prompt_text"]
    assert "uploaded finished frame" in text
    assert "FRAME CONTINUITY SOURCE" in text
    assert "do not rebuild" in text.lower()
    # The ambiguous "single visual reference" wording contradicted the product
    # reference truth lock — both sources must now be explicitly scoped.
    assert "single visual reference" not in text
    # FRAMES must not inject a registry presenter description (frame is truth).
    assert "The presenter is a Malaysian adult" not in text


def test_frames_scopes_frame_continuity_vs_product_truth_sources():
    result = _compile(mode="FRAMES")
    text = result["blocks"][0]["engine_prompt_text"]
    # Frame = pose/scene/lighting/camera/motion continuity only.
    assert "FRAME CONTINUITY SOURCE" in text
    assert "presenter pose, scene continuity, lighting, camera distance" in text
    # Product reference = identity/scale/geometry/label only; never a scene reset.
    assert "PRODUCT TRUTH SOURCE" in text
    assert "must not reset the scene" in text
    assert "override the uploaded frame composition" in text


def test_hybrid_mode_polish_keeps_creator_as_persuasion_engine():
    result = _compile(mode="HYBRID", duration_seconds=16)
    text = result["blocks"][-1]["engine_prompt_text"].lower()
    assert "persuasion engine" in text
    assert "face, hand, and product" in text
    assert "detached product-only montage" in text


def test_frames_mode_polish_preserves_continuation_tension():
    result = _compile(mode="FRAMES", duration_seconds=16)
    text = result["blocks"][-1]["engine_prompt_text"].lower()
    assert "mid-thought continuation point" in text
    assert "existing tension" in text
    assert "newly performed cta tableau" in text or "fresh hero re-block" in text


def test_mode_specific_visual_story_differs_between_hybrid_frames_and_ingredients():
    hybrid = _compile(mode="HYBRID")["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"]
    frames = _compile(mode="FRAMES")["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"]
    ingredients = _compile(
        mode="INGREDIENTS",
        asset_role_map={"PRODUCT_REFERENCE": "img1", "AVATAR_REFERENCE": "img2"},
    )["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"]
    assert "uploaded finished frame" not in hybrid.lower()
    assert "new reveal" in frames.lower()
    assert "reference-led opening beat" in ingredients.lower()
    assert "creator-led opening beat" in hybrid.lower()


def test_fragrance_family_injects_scent_specific_visual_focus():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=8,
        product={"id": "prod-frag", "name": "SZINDORE PERFUME", "category": "Fragrance"},
        copy=COPY,
        target_language="BM_MS",
    )
    text = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"]
    assert "scent-led confidence" in text.lower() or "scent-confidence" in text.lower()


def test_section4_and_section8_follow_cta_payoff_logic():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-frag-cta-visual",
            "name": "SZINDORE PERFUME",
            "category": "Fragrance",
            "trigger_id": "CONFIDENCE_01",
            "copywriting_angle": "Confidence-led scent appeal and everyday freshness",
        },
        copy={
            "hook": "Weh, bau dia terus sedap.",
            "subhook": "Sekali pandang dah nampak premium.",
            "cta": "Save dulu kalau belum grab.",
            "cta_type": "save_for_later",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "bookmark-worthy end hold" in s4
    assert "bookmark-worthy end hold" in s8


def test_laundry_family_clause_bank_injects_refill_and_repeat_buy_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-laundry",
            "name": "SUMIKKO DETERGENT REFILL",
            "category": "Laundry",
        },
        copy={
            "hook": "Weh, besar juga refill ni.",
            "subhook": "Sekali tengok terus nampak guna lama.",
            "cta": "Grab dulu kalau sesuai.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    assert "stok rumah" in final_dialogue or "ulang beli" in final_dialogue


def test_household_family_does_not_drift_into_food_taste_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-household",
            "name": "LANTAIKILAT FLOOR SPRAY",
            "category": "Household Care",
        },
        copy={
            "hook": "Sekali tengok terus nampak practical.",
            "subhook": "Jenis botol yang memang senang capai bila nak guna cepat.",
            "usp1": "Grip dia sedap pegang dan nozzle nampak terus fungsinya.",
            "cta": "Check dulu kalau tengah cari barang rumah yang mudah pakai.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "appetite" not in s4
    assert "temptation" not in s4
    assert "guna dia hari-hari" in final_dialogue


def test_food_family_keeps_taste_language_when_copy_is_actually_edible():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-food",
            "name": "KOPI PAK NGAH",
            "category": "Food & Beverage",
        },
        copy={
            "hook": "Packaging dia terus buat aku teringin nak cuba.",
            "subhook": "Sekali tengok terus boleh bayang minum panas-panas.",
            "usp1": "Pack dia nampak kemas, senang simpan, senang bancuh.",
            "cta": "Grab dulu kalau jenis suka stok benda sedap kat rumah.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "appetite or temptation" in s4


def test_baby_care_final_dialogue_prefers_parent_native_closing_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-baby", "name": "COMFY BABY LOTION", "category": "Baby Care"},
        copy={
            "hook": "Weh, sekali sapu terus nampak tenang.",
            "subhook": "Jenis routine yang buat parent rasa kurang serabut.",
            "usp1": "Botol senang pegang, pump dia tak serabut, dan packaging nampak lembut.",
            "cta": "Simpan dulu kalau tengah cari standby untuk rumah.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "parent memang suka simpan benda ni dekat-dekat" in final_dialogue
    assert "parent kongsi" in s7


def test_wellness_final_dialogue_prefers_grounded_routine_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-wellness", "name": "HERBA TOK AYAH", "category": "Wellness"},
        copy={
            "hook": "Packaging dia nampak kemas, tak over sangat.",
            "subhook": "Terus rasa macam senang masuk routine harian.",
            "usp1": "Botol dia jelas, senang simpan, dan tak nampak hype.",
            "cta": "Save dulu kalau tengah survey routine support yang sesuai.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "senang kekal dalam routine" in final_dialogue
    assert "grounded dan tak hype" in s7


def test_beauty_voice_and_dialogue_push_getting_ready_native_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-beauty", "name": "SKINTIFIC Matte Sunscreen", "category": "Beauty & Personal Care"},
        copy={
            "hook": "Weh korang, kulit muka aku tak berminyak dah sepanjang hari!",
            "subhook": "Dulu setiap tengah hari mesti muka macam kilang minyak.",
            "usp1": "Matte habis, tak melekit, terus jadi primer sebelum mekap.",
            "usp2": "SPF50+ PA+++ lindung sepanjang hari walaupun panas terik.",
            "cta": "Cepat grab sekarang, tekan beg kuning sebelum promo habis!",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "siap-siap betul sebelum keluar" in s7


def test_fragrance_voice_and_dialogue_push_real_social_notice_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-fragrance", "name": "SZINDORE PERFUME", "category": "Fragrance"},
        copy={
            "hook": "Weh, bau dia terus sedap.",
            "subhook": "Sekali pandang dah nampak premium.",
            "usp1": "Botol dia kemas, spray dia halus, terus rasa mahal.",
            "usp2": "Jenis bau yang buat orang pusing kepala tanya pakai apa.",
            "cta": "Save dulu kalau belum grab.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "orang perasan bila lalu" in final_dialogue
    assert "orang memang akan perasan dekat dunia sebenar" in s7


def test_electronics_voice_clause_avoids_spec_sheet_demo_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-electronics", "name": "AEROFIT SMART WATCH", "category": "Electronics"},
        copy={
            "hook": "Sekali tengok terus nampak moden.",
            "subhook": "Screen dia terus nampak jelas.",
            "usp1": "Notifikasi senang nampak, strap nampak kemas, dan menu dia tak serabut.",
            "usp2": "Jenis gadget yang terus nampak guna hari-hari, bukan syok sendiri.",
            "cta": "Check dulu spec dia.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "bukan macam baca spec sheet depan kamera" in s7


def test_household_voice_clause_avoids_staged_product_showcase_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-household", "name": "LANTAIKILAT FLOOR SPRAY", "category": "Household Care"},
        copy={
            "hook": "Sekali tengok terus nampak practical untuk rumah.",
            "subhook": "Jenis botol yang memang senang capai bila nak guna cepat.",
            "usp1": "Grip sedap pegang, nozzle jelas, dan terus nampak cara guna dia.",
            "usp2": "Memang jenis barang yang terus masuk rutin kemas rumah.",
            "cta": "Check dulu kalau tengah cari barang rumah yang mudah pakai.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "bukan macam product showcase yang dibuat-buat" in s7


def test_laundry_voice_clause_avoids_staged_refill_demo_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-laundry", "name": "SUMIKKO DETERGENT REFILL", "category": "Laundry"},
        copy={
            "hook": "Weh, besar juga refill ni.",
            "subhook": "Sekali tengok terus nampak guna lama.",
            "usp1": "Saiz refill nampak berbaloi, senang tuang, dan tak serabut simpan.",
            "usp2": "Memang jenis stok rumah yang terus masuk rutin basuh baju.",
            "cta": "Grab dulu kalau sesuai.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "bukan macam demo refill yang terlalu tersusun" in s7


def test_fashion_voice_clause_avoids_camera_aware_fashion_shoot_language():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-fashion", "name": "KURUNG AIRA", "category": "Fashion"},
        copy={
            "hook": "Sekali pakai terus nampak kemas.",
            "subhook": "Jatuh kain dia memang nampak jadi bila bergerak.",
            "usp1": "Potongan dia buat badan nampak tersusun tanpa usaha lebih.",
            "usp2": "Memang jenis pakai terus rasa lengkap bila keluar rumah.",
            "cta": "Grab dulu kalau nak pakai terus rasa lengkap.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s7 = result["blocks"][-1]["sections"]["SECTION 7 - VOICE & DELIVERY"].lower()
    assert "bukan macam fashion shoot yang terlalu sedar kamera" in s7


def test_electronics_family_clause_bank_strengthens_visual_proof_and_end_payoff():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=8,
        product={
            "id": "prod-watch",
            "name": "AEROFIT SMART WATCH",
            "category": "Electronics",
        },
        copy={
            "hook": "Sekali tengok terus nampak moden.",
            "subhook": "Screen dia terus nampak jelas.",
            "cta": "Check dulu spec dia.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][0]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "feature-proof read" in s4
    assert "close-up detail of the device screen" in s8


def test_visual_story_and_end_frame_use_compressed_alias_for_long_product_names():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-electronics-alias",
            "name": "(W)UGREEN PD20W Fast Charger Pengecas Pantas, Palam UK, dengan Set Kabel, Serasi dengan iPhone 8-16 Pro Max Samsung S25 Ultra Android Cellphone Mobile Phone Siri, SKU: 70297",
            "category": "Phones & Electronics",
            "bosmax_product_family": "electronics_wearable",
        },
        copy={
            "hook": "Sekali tengok terus nampak function dia.",
            "cta": "Check dulu spec dia.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"]
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"]
    assert "UGREEN PD20W Fast Charger Pengecas Pantas" in s4
    assert "Samsung S25 Ultra Android Cellphone Mobile Phone Siri" not in s4
    assert "SKU: 70297" not in s4
    assert "UGREEN PD20W Fast Charger Pengecas Pantas" in s8
    assert "Samsung S25 Ultra Android Cellphone Mobile Phone Siri" not in s8


def test_strong_family_hook_skips_generic_strategic_opener():
    laundry = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-laundry-hook",
            "name": "SUMIKKO DETERGENT REFILL BESAR",
            "category": "Laundry",
            "bosmax_product_family": "laundry_care",
        },
        copy={
            "hook": "Weh, refill dia nampak besar terus.",
            "cta": "Kalau sesuai, terus stok rumah.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    food = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-food-hook",
            "name": "SAMBAL IKAN BILIS PEDAS",
            "category": "Food & Beverage",
            "bosmax_product_family": "food_beverage",
        },
        copy={
            "hook": "Packaging dia terus buat rasa lapar.",
            "cta": "Kalau jenis suka pedas, simpan dulu.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    assert "aku memang cepat percaya" not in laundry["blocks"][0]["dialogue"].lower()
    assert "paling penting, rasa selesa" not in food["blocks"][0]["dialogue"].lower()
    assert food["blocks"][0]["dialogue"].lower().count("packaging dia terus buat") == 1


def test_section8_end_frame_pose_varies_by_family():
    electronics = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-end-electronics",
            "name": "UGREEN FAST CHARGER",
            "category": "Electronics",
            "bosmax_product_family": "electronics_wearable",
        },
        copy={"hook": "Sekali tengok terus nampak function dia.", "cta": "Check dulu spec dia.", "formula_family": "HSO"},
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    baby = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-end-baby",
            "name": "Baby Wipes Newborn",
            "category": "Baby Care",
            "bosmax_product_family": "BABY_WIPES",
        },
        copy={"hook": "Sekali tengok terus rasa tenang nak guna.", "cta": "Simpan dulu untuk standby rumah.", "formula_family": "HSO"},
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    assert "proof-to-camera hold" in electronics["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "calm standby hold" in baby["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()


def test_soft_try_cta_does_not_get_harder_bridge_prepended():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-beauty-soft-cta",
            "name": "Minyak Habbatus Sauda Al Khair 30ml",
            "category": "Beauty & Personal Care",
            "bosmax_product_family": "BEAUTY_PERSONAL_CARE",
        },
        copy={
            "hook": "Terus rasa pagi tu lebih tersusun.",
            "cta": "Try dulu kalau ngam.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    assert "kalau dah suka, terus grab" not in final_dialogue
    assert "try dulu kalau ngam" in final_dialogue


def test_explicit_female_health_sensitive_fashion_item_stays_fashion_family():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-fashion-sensitive",
            "name": "OFVOGUE Seluar Panjang Wanita Bootcut",
            "category": "Fashion",
            "type": "Pants",
            "bosmax_product_family": "FEMALE_HEALTH_SENSITIVE",
        },
        copy={"hook": "Jatuh dia terus nampak kemas.", "cta": "Grab kalau suka.", "formula_family": "HSO"},
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "fit, drape, texture" in s4
    assert "careful routine support" not in s4


def test_explicit_household_storage_hijab_item_routes_to_fashion_family():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-hijab-drift",
            "name": "PANDA QUEENIE TUDUNG BAWAL PRINTED HIJAB",
            "category": "Muslim Fashion",
            "type": "Square Hijabs",
            "bosmax_product_family": "HOUSEHOLD_STORAGE_ORGANIZER",
        },
        copy={"hook": "Sekali bentang terus nampak jatuh dia.", "cta": "Save dulu kalau suka style ni.", "formula_family": "HSO"},
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "fit, drape, texture" in s4
    assert "practical home utility" not in s4


def test_accessory_small_item_phone_holder_routes_to_electronics_family():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-phone-holder",
            "name": "HOTOP 360 Rotatable Car Phone Holder",
            "category": "Automotive & Motorcycle",
            "type": "Mounts & Holders",
            "bosmax_product_family": "ACCESSORY_SMALL_ITEM",
        },
        copy={"hook": "Sekali tengok terus nampak function dia.", "cta": "Check dulu spec dia.", "formula_family": "HSO"},
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "feature clarity and daily-use usefulness" in s4
    assert "practical home utility" not in s4


def test_explicit_baby_family_beats_fragrance_free_keyword_drift():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-baby-wipes",
            "name": "Baby Wipes Newborn Fragrance-free",
            "category": "Baby Care",
            "bosmax_product_family": "BABY_WIPES",
        },
        copy={
            "hook": "Baby Wipes Newborn Fragrance-free menonjolkan rutin penjagaan diri yang lebih kemas dan premium.",
            "cta": "Lihat bagaimana Baby Wipes Newborn Fragrance-free menyokong rutin harian.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
        scene_context="a calm Malaysian nursery corner",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    assert "parent-trust" in s4 or "routine bayi" in s4
    assert "scent-led confidence" not in s4
    assert "parent memang suka simpan benda ni dekat-dekat" in final_dialogue


def test_legacy_generic_hook_is_discarded_so_family_dialogue_can_lead():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-electronics-long",
            "name": "(W)UGREEN PD20W Fast Charger Pengecas Pantas, Palam UK, dengan Set Kabel, Serasi dengan iPhone 8-16 Pro Max Samsung S25 Ultra Android Cellphone Mobile Phone Siri, SKU: 70297",
            "category": "Phones & Electronics",
            "bosmax_product_family": "electronics_wearable",
        },
        copy={
            "hook": "(W)UGREEN PD20W Fast Charger Pengecas Pantas, Palam UK, dengan Set Kabel, Serasi dengan iPhone 8-16 Pro Max Samsung S25 Ultra Android Cellphone Mobile Phone Siri, SKU: 70297 menonjolkan rutin penjagaan diri yang lebih kemas dan premium dengan presentation yang jelas dan meyakinkan.",
            "cta": "Lihat bagaimana (W)UGREEN PD20W Fast Charger Pengecas Pantas, Palam UK, dengan Set Kabel, Serasi dengan iPhone 8-16 Pro Max Samsung S25 Ultra Android Cellphone Mobile Phone Siri, SKU: 70297 menyokong rutin harian yang lebih teratur dan mudah difahami.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    opening = result["blocks"][0]["dialogue"].lower()
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    assert "rutin penjagaan diri yang lebih kemas" not in opening
    assert "sekali tengok terus nampak function dia" in opening
    assert "kenapa benda ni berguna" in final_dialogue


def test_health_supplement_explicit_family_routes_to_wellness_not_beauty():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={
            "id": "prod-wellness",
            "name": "Pentavite Multivitamin Lelaki",
            "category": "Health",
            "bosmax_product_family": "HEALTH_SUPPLEMENT",
        },
        copy={
            "hook": "Pentavite Multivitamin Lelaki diposisikan sebagai rutin self-care luaran yang premium, discreet, dan kemas.",
            "cta": "Semak bagaimana Pentavite Multivitamin Lelaki dibingkaikan sebagai self-care luaran tanpa tuntutan perubatan atau prestasi.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s4 = result["blocks"][0]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    opening = result["blocks"][0]["dialogue"].lower()
    assert "careful routine support" in s4
    assert "non-claim routine context" in s4
    assert "percaya" in opening
    assert "aura dia terus naik" not in opening


def test_ingredients_requires_role_map_and_normalizes_missing_style():
    with pytest.raises(ValueError, match="INGREDIENTS_ASSET_ROLE_MAP_INCOMPLETE"):
        _compile(mode="INGREDIENTS")
    result = _compile(
        mode="INGREDIENTS",
        asset_role_map={"PRODUCT_REFERENCE": "img1", "AVATAR_REFERENCE": "img2"},
        scene_context="a bright modern bathroom counter",
    )
    text = result["blocks"][0]["engine_prompt_text"]
    assert "product reference controls the product" in text
    assert "person reference controls the presenter" in text
    assert "environment comes from this description only" in text.lower()
    assert "bright modern bathroom counter" in text


def test_ingredients_style_reference_controls_environment_only():
    result = _compile(
        mode="INGREDIENTS",
        asset_role_map={"PRODUCT_REFERENCE": "img1", "AVATAR_REFERENCE": "img2",
                        "STYLE_SCENE_REFERENCE": "img3"},
    )
    text = result["blocks"][0]["engine_prompt_text"]
    assert "style reference controls the environment and mood only" in text


def test_ingredients_mode_polish_enforces_reference_hierarchy():
    result = _compile(
        mode="INGREDIENTS",
        duration_seconds=16,
        asset_role_map={"PRODUCT_REFERENCE": "img1", "AVATAR_REFERENCE": "img2",
                        "STYLE_SCENE_REFERENCE": "img3"},
    )
    text = result["blocks"][-1]["engine_prompt_text"].lower()
    assert "authority hierarchy is strict" in text
    assert "style or scene guidance may decorate the world only after product and avatar truth are already satisfied" in text
    assert "reference-faithful and balanced" in text


def test_no_overlay_default_and_explicit_allowance():
    result = _compile()
    s9 = result["blocks"][0]["sections"]["SECTION 9 - NO_OVERLAY"]
    assert "No on-screen text of any kind" in s9
    allowed = _compile(overlay_allowed=True, overlay_text="Cuba ni")
    s9b = allowed["blocks"][0]["sections"]["SECTION 9 - NO_OVERLAY"]
    assert "Cuba ni" in s9b


def test_engine_text_has_no_internal_leakage():
    result = _compile(duration_seconds=24)  # 3 blocks
    for block in result["blocks"]:
        text = block["engine_prompt_text"]
        assert not re.search(r"\bHYBRID\b", text)
        assert not re.search(r"\bWPS\b", text, re.IGNORECASE)
        assert "block_plan" not in text
        assert "BOS_" not in text
        assert block["scrub_violations"] == []


def test_language_lock_section6_malay_others_english():
    result = _compile(duration_seconds=8)
    sections = result["blocks"][0]["sections"]
    assert "Weh korang" in sections["SECTION 6 - SPOKEN DIALOGUE"]
    for header in ("SECTION 1 - ROLE & OBJECTIVE", "SECTION 7 - VOICE & DELIVERY"):
        assert "Weh korang" not in sections[header]
    assert "Malay only" in sections["SECTION 7 - VOICE & DELIVERY"]
    assert "No voice-over" in sections["SECTION 7 - VOICE & DELIVERY"]
    assert "No off-camera speech" in sections["SECTION 7 - VOICE & DELIVERY"]


def test_section7_is_shorter_but_keeps_behavior_lock():
    result = _compile(duration_seconds=8)
    s7 = result["blocks"][0]["sections"]["SECTION 7 - VOICE & DELIVERY"]
    assert "present in the moment" in s7
    assert "No voice-over" in s7
    assert "No audio-only dialogue" in s7
    assert "not a narrator" not in s7.lower()


def test_t2v_section8_has_no_lowercase_sentence_stitching():
    result = _compile(mode="T2V", duration_seconds=16, scene_context="a bright lived-in bathroom counter at home")
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"]
    assert ". The close" in s8
    assert "The close must resolve as a believable social moment with the product centered and the label readable" in s8


def test_images_mode_single_still_under_same_authority():
    result = _compile(mode="IMAGES")
    assert result["total_blocks"] == 1
    block = result["blocks"][0]
    assert "single still image" in block["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower() \
        or "single commercial product image" in block["sections"]["SECTION 1 - ROLE & OBJECTIVE"].lower()
    assert block["dialogue"] == ""
    assert "static 9:16" in block["sections"]["SECTION 5 - SHOT & CAMERA RULES"].lower()
    assert "micro-jitter" not in block["sections"]["SECTION 5 - SHOT & CAMERA RULES"].lower()


def test_images_mode_polish_enforces_static_sellability_only():
    result = _compile(mode="IMAGES")
    text = result["blocks"][0]["engine_prompt_text"].lower()
    assert "still-image persuasion only" in text
    assert "static sellability" in text
    assert "composition alone" in text


def test_t2v_mode_polish_enforces_scene_first_native_persuasion():
    result = _compile(mode="T2V", duration_seconds=16, scene_context="a bright lived-in bathroom counter at home")
    text = result["blocks"][-1]["engine_prompt_text"].lower()
    assert "scene-first persuasion only" in text
    assert "real moment already happening" in text
    assert "discovered inside the scene" in text
    assert "believable social moment with the product centered and the label readable" in text


def test_sunscreen_does_not_false_positive_into_authority_trigger():
    norm = cpc.normalize_copy_intelligence(COPY, product=PRODUCT)
    assert norm["trigger_id"] != "AUTHORITY_01"


def test_t2v_continuation_keeps_scene_native_not_generic_reset():
    result = _compile(mode="T2V", duration_seconds=16, scene_context="a bright lived-in bathroom counter at home")
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    assert "lived-in, scene-native, and socially believable" in s4


def test_t2v_baby_scene_injects_parent_routine_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-baby", "name": "COMFY BABY LOTION", "category": "Baby Care"},
        copy={
            "hook": "Weh, sekali sapu terus nampak tenang.",
            "subhook": "Jenis routine yang buat parent rasa kurang serabut.",
            "usp1": "Botol senang pegang, pump dia tak serabut, dan packaging nampak lembut.",
            "cta": "Simpan dulu kalau tengah cari standby untuk rumah.",
            "formula_family": "HSO",
        },
        scene_context="a bright lived-in nursery corner after bath time",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "after-bath lotion prep" in s3
    assert "stays within easy reach for the next routine" in s4
    assert "stays within easy reach for the next routine" in s8


def test_t2v_wellness_scene_injects_measured_routine_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-wellness", "name": "HERBA TOK AYAH", "category": "Wellness"},
        copy={
            "hook": "Packaging dia nampak kemas, tak over sangat.",
            "subhook": "Terus rasa macam senang masuk routine harian.",
            "usp1": "Botol dia jelas, senang simpan, dan tak nampak hype.",
            "cta": "Save dulu kalau tengah survey routine support yang sesuai.",
            "formula_family": "HSO",
        },
        scene_context="a quiet home kitchen counter during a real morning routine",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "morning water prep" in s3
    assert "quietly deciding this stays in the routine" in s4
    assert "quietly deciding this stays in the routine" in s8


def test_t2v_beauty_scene_injects_getting_ready_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-beauty", "name": "SKINTIFIC Matte Sunscreen", "category": "Beauty & Personal Care"},
        copy={
            "hook": "Weh korang, kulit muka aku tak berminyak dah sepanjang hari!",
            "subhook": "Dulu setiap tengah hari mesti muka macam kilang minyak.",
            "usp1": "Matte habis, tak melekit, terus jadi primer sebelum mekap.",
            "usp2": "SPF50+ PA+++ lindung sepanjang hari walaupun panas terik.",
            "cta": "Cepat grab sekarang, tekan beg kuning sebelum promo habis!",
            "formula_family": "HSO",
        },
        scene_context="a bright lived-in bathroom counter during a rushed weekday morning",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "rushed sink-side prep" in s3
    assert "stays within reach for the next rushed morning or touch-up" in s4
    assert "stays within reach for the next rushed morning or touch-up" in s8


def test_t2v_fragrance_scene_injects_social_ready_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-fragrance", "name": "SZINDORE PERFUME", "category": "Fragrance"},
        copy={
            "hook": "Weh, bau dia terus sedap.",
            "subhook": "Sekali pandang dah nampak premium.",
            "usp1": "Botol dia kemas, spray dia halus, terus rasa mahal.",
            "usp2": "Jenis bau yang buat orang pusing kepala tanya pakai apa.",
            "cta": "Save dulu kalau belum grab.",
            "formula_family": "HSO",
        },
        scene_context="a bright apartment doorway moment just before heading out",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "grabbing keys" in s3 or "grabbing keys" in s3.replace("grabing", "grabbing")
    assert "would be noticed by people nearby" in s4
    assert "would be noticed by people nearby" in s8


def test_t2v_electronics_scene_injects_everyday_use_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-electronics", "name": "AEROFIT SMART WATCH", "category": "Electronics"},
        copy={
            "hook": "Sekali tengok terus nampak moden.",
            "subhook": "Screen dia terus nampak jelas.",
            "usp1": "Notifikasi senang nampak, strap nampak kemas, dan menu dia tak serabut.",
            "usp2": "Jenis gadget yang terus nampak guna hari-hari, bukan syok sendiri.",
            "cta": "Check dulu spec dia.",
            "formula_family": "HSO",
        },
        scene_context="a real morning rush near the front door while checking time and notifications",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "checking time at the door" in s3
    assert "stays on the body for the next task" in s4
    assert "stays on the body for the next task" in s8


def test_t2v_household_scene_injects_cleanup_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-household", "name": "LANTAIKILAT FLOOR SPRAY", "category": "Household Care"},
        copy={
            "hook": "Sekali tengok terus nampak practical untuk rumah.",
            "subhook": "Jenis botol yang memang senang capai bila nak guna cepat.",
            "usp1": "Grip sedap pegang, nozzle jelas, dan terus nampak cara guna dia.",
            "usp2": "Memang jenis barang yang terus masuk rutin kemas rumah.",
            "cta": "Check dulu kalau tengah cari barang rumah yang mudah pakai.",
            "formula_family": "HSO",
        },
        scene_context="a lived-in kitchen corner during a quick cleanup before guests arrive",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "wiping a spill" in s3
    assert "goes back within easy reach for the next cleanup" in s4
    assert "goes back within easy reach for the next cleanup" in s8


def test_t2v_laundry_scene_injects_wash_cycle_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-laundry", "name": "SUMIKKO DETERGENT REFILL", "category": "Laundry"},
        copy={
            "hook": "Weh, besar juga refill ni.",
            "subhook": "Sekali tengok terus nampak guna lama.",
            "usp1": "Saiz refill nampak berbaloi, senang tuang, dan tak serabut simpan.",
            "usp2": "Memang jenis stok rumah yang terus masuk rutin basuh baju.",
            "cta": "Grab dulu kalau sesuai.",
            "formula_family": "HSO",
        },
        scene_context="a real laundry corner while sorting clothes before a wash cycle",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "sorting clothes" in s3
    assert "ready for the next cycle" in s4
    assert "ready for the next cycle" in s8


def test_t2v_fashion_scene_injects_getting_dressed_native_cues():
    result = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-fashion", "name": "KURUNG AIRA", "category": "Fashion"},
        copy={
            "hook": "Sekali pakai terus nampak kemas.",
            "subhook": "Jatuh kain dia memang nampak jadi bila bergerak.",
            "usp1": "Potongan dia buat badan nampak tersusun tanpa usaha lebih.",
            "usp2": "Memang jenis pakai terus rasa lengkap bila keluar rumah.",
            "cta": "Grab dulu kalau nak pakai terus rasa lengkap.",
            "formula_family": "HSO",
        },
        scene_context="a real doorway mirror moment while adjusting outfit before heading out",
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    s3 = result["blocks"][-1]["sections"]["SECTION 3 - CONTINUITY & STATE LOCK"].lower()
    s4 = result["blocks"][-1]["sections"]["SECTION 4 - VISUAL STORY"].lower()
    s8 = result["blocks"][-1]["sections"]["SECTION 8 - CTA & END FRAME"].lower()
    assert "adjusting sleeves" in s3
    assert "about to walk out feeling put together" in s4
    assert "about to walk out feeling put together" in s8


def test_fashion_family_cta_lands_cleanly_without_awkward_fragment():
    result = cpc.compile_prompt_set(
        source_mode="HYBRID",
        engine="GOOGLE_FLOW",
        duration_seconds=16,
        product={"id": "prod-fashion", "name": "KURUNG AIRA", "category": "Fashion"},
        copy={
            "hook": "Sekali pakai terus nampak kemas.",
            "subhook": "Jatuh kain dia memang nampak jadi bila bergerak.",
            "usp1": "Potongan dia buat badan nampak tersusun tanpa usaha lebih.",
            "cta": "Grab dulu kalau nak pakai terus rasa lengkap.",
            "formula_family": "HSO",
        },
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    final_dialogue = result["blocks"][-1]["dialogue"].lower()
    assert "pakai sekali terus nampak jadi" in final_dialogue
    assert "jadi orang" not in final_dialogue


def test_avatar_registry_explicit_id_and_prose():
    profile = avatar_registry.resolve_presenter("BOS_F_ALYA_01")
    assert profile["character_name"] == "Alya"
    prose = avatar_registry.presenter_prose(profile)
    assert "Malaysian adult woman" in prose
    assert "office" in prose.lower()
    assert "BOS_F_ALYA_01" not in prose, "registry codes must never leak into prose"


def test_legacy_entrypoint_delegates_and_uncaps_blocks():
    # The workspace package callers keep their contract, but final output is canonical.
    from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
    result = compile_ugc_video_prompt(
        product=PRODUCT,
        approved_package={"scene_context": "a bright vanity table"},
        mode="F2V",
        target_language="BM_MS",
        generation_mode="SINGLE",
        duration_seconds=8,
        copy_intelligence=COPY,
    )
    assert result["final_compiled_prompt_text"].count("SECTION 6 - SPOKEN DIALOGUE") == 1
    block = result["prompt_blocks"][0]
    assert block["engine_prompt_text"].startswith("SECTION 1 - ROLE & OBJECTIVE")
    assert block["dialogue_word_budget"] == 22  # Workspace entrypoint defaults to SweetWPS 2.7 × 8s
    assert "one visible creator" not in block["engine_prompt_text"].lower()
    # multi-block beyond 2 via explicit blocks
    multi = compile_ugc_video_prompt(
        product=PRODUCT, approved_package={}, mode="F2V", target_language="BM_MS",
        generation_mode="EXTEND", duration_seconds=8, copy_intelligence=COPY,
        blocks=[{"duration_seconds": 8}] * 4,
    )
    assert len(multi["prompt_blocks"]) == 4, "the 2-block cap must be gone"


def test_prompt_intel_audit_minyak_warisan_maps_to_wellness_not_beauty():
    product = {
        "id": "prod-minyak",
        "name": "Minyak Warisan Tok Cap Burung",
        "category": "Health & Personal Care",
        "subcategory": "Traditional Herbal Oil",
        "type": "Minyak Angin",
        "bosmax_product_family": "BEAUTY_PERSONAL_CARE"
    }
    family = cpc._infer_product_family(product)
    assert family == "wellness"


def test_prompt_intel_audit_baby_milk_powder_maps_to_food_beverage_not_baby_care():
    product = {
        "id": "prod-milk",
        "name": "Organic Baby Milk Powder Step 1 900g",
        "category": "Baby Care",
        "subcategory": "Diaper",
        "type": "Pants",
        "bosmax_product_family": "BABY_CARE"
    }
    family = cpc._infer_product_family(product)
    assert family == "food_beverage"


def test_prompt_intel_audit_strong_hook_omits_generic_filler():
    product = {
        "id": "prod-minyak",
        "name": "Minyak Warisan Tok Cap Burung",
        "category": "Health & Personal Care"
    }
    copy = {
        "hook": "Anak melalak pukul 2 pagi baru kau kalut nak cari minyak?",
        "subhook": "Minyak hijau cap merah ni simpan siap-siap dalam laci bilik tidur.",
        "cta": "Tap beg kuning sekarang untuk standby.",
        "formula_family": "HSO",
    }
    # Compile prompt set for a single block
    res = cpc.compile_prompt_set(
        source_mode="T2V",
        engine="GOOGLE_FLOW",
        duration_seconds=8,
        product=product,
        copy=copy,
        target_language="BM_MS"
    )
    dialogue = res["blocks"][0]["dialogue"]
    # Verify it does not contain generic filler like "Terus naik rasa yakin" or "Terus rasa routine tu lebih kemas"
    assert "Terus naik rasa yakin" not in dialogue
    assert "Terus rasa routine tu lebih kemas" not in dialogue
    assert "Anak melalak" in dialogue


def test_prompt_intel_audit_section8_payoff_contains_no_meta_wording():
    # Test all family visual end payoffs do not contain abstract meta phrasings
    families = ["fragrance", "beauty_personal_care", "laundry_care", "household_care", "baby_care", "food_beverage", "fashion_apparel", "electronics", "wellness", "general"]
    for fam in families:
        bank = cpc._family_clause_bank(fam)
        payoff = bank["end_payoff"]
        assert "payoff" not in payoff
        assert "rather than a generic" not in payoff
        assert "instead of a generic" not in payoff
        assert "rather than a vague" not in payoff
        assert "ending" not in payoff


# ── Visual-truth incident (oversize / flash / overlay-metadata leakage) ─────────
# Control case: the operator's successful FRAMES prompt ("Sample prompt yang
# sukses.txt") anchored the composed frame as the single visual truth, enumerated
# NO_OVERLAY fully, and never cut away to a product-only flash shot. These tests
# pin those semantics into the shared compiler for every mode.

_ING_KW = dict(asset_role_map={"PRODUCT_REFERENCE": True, "AVATAR_REFERENCE": True})
_VIDEO_MODES_KW = [("T2V", {}), ("HYBRID", {}), ("FRAMES", {}), ("INGREDIENTS", _ING_KW)]


def _s(mode, section, **kw):
    return _compile(mode, **kw)["blocks"][0]["sections"][section].lower()


def test_frames_composed_frame_is_scoped_continuity_truth():
    # The frame is the CONTINUITY authority; the product reference is the
    # GEOMETRY/SCALE authority. Both scoped, no contradictory single-source claim.
    s3 = _s("FRAMES", "SECTION 3 - CONTINUITY & STATE LOCK")
    assert "frame continuity source" in s3
    assert "single visual reference" not in s3
    assert "continue only" in s3 and "visible frame state" in s3
    assert "motion only" in s3
    assert "do not rebuild" in s3
    assert "product truth source" in s3
    assert "must not reset the scene" in s3


@pytest.mark.parametrize("mode,kw", _VIDEO_MODES_KW)
def test_video_modes_block_product_flash_and_cutaway_packshot(mode, kw):
    s5 = _s(mode, "SECTION 5 - SHOT & CAMERA RULES", **kw)
    # The unrequested-flash / cutaway / insert-montage / spotlight bans must be present…
    assert "isolated product-only flash shot" in s5
    assert "cutaway" in s5 and "packshot" in s5
    assert "product-only insert montage" in s5
    assert "sudden hero product spotlight" in s5
    assert "true small scale" in s5


@pytest.mark.parametrize("mode,kw", _VIDEO_MODES_KW)
def test_anti_flash_guard_is_scene_neutral_not_presenter_hardcoded(mode, kw):
    # …but the guard must NOT force presenter/hands globally — it must stay valid for
    # legitimate product-only scenes (bedside/drawer/shelf standby). Audit blocker #1.
    s5 = _s(mode, "SECTION 5 - SHOT & CAMERA RULES", **kw)
    # the old hardcode must be gone
    assert "the product stays in the presenter's hands" not in s5
    # both branches must be expressed conditionally
    assert "if the presenter is holding the product" in s5
    assert "resting in its own scene" in s5          # product-only scene preserved
    assert "unrequested" in s5                        # only *unrequested* flashes are blocked


def test_images_mode_has_no_video_anti_flash_rule():
    # A single still may legitimately be product-led; the flash rule is video-only.
    s5 = _s("IMAGES", "SECTION 5 - SHOT & CAMERA RULES")
    assert "cutaway" not in s5 and "packshot" not in s5


@pytest.mark.parametrize("mode,kw", _VIDEO_MODES_KW + [("IMAGES", {})])
def test_no_overlay_blocks_metadata_style_text_everywhere(mode, kw):
    s9 = _s(mode, "SECTION 9 - NO_OVERLAY", **kw)
    for phrase in [
        "no captions", "no subtitles", "no lower-thirds", "no sticker text",
        "no floating text", "no price text", "no label callouts", "no watermarks",
        "metadata-style text", "pack size", "founding",
    ]:
        assert phrase in s9, f"[{mode}] SECTION 9 missing overlay guard: {phrase}"
    # only the real printed label may be readable — never a drawn graphic
    assert "printed on the real product label" in s9


def test_overlay_allowed_branch_still_scoped_and_blocks_metadata():
    # Audit blocker #3: even when an overlay is approved, metadata-style drawn text
    # (product name / pack size / founding year / tagline as a graphic) stays banned.
    s9 = _compile(overlay_allowed=True, overlay_text="Cuba ni")["blocks"][0][
        "sections"]["SECTION 9 - NO_OVERLAY"].lower()
    assert "cuba ni" in s9                            # the approved overlay survives
    for phrase in ["no other captions", "label callouts", "metadata-style text",
                   "pack size", "founding", "printed on the real product label"]:
        assert phrase in s9, f"overlay_allowed branch missing metadata guard: {phrase}"



def test_bound_approved_copy_excludes_family_bank_filler():
    # Regression: a BOUND approved Copy Set (copy_source=selected_copy_set) was
    # padded with generic family-bank filler ("Botol dia tersusun, memang tak
    # rasa hype") that displaced the set's own USP/CTA inside the word budget
    # (observed in the real F2V run wep_8fde2467254bfc90, 2026-07-08).
    approved = dict(COPY, copy_source="selected_copy_set")
    result = _compile(mode="FRAMES", copy=approved)
    dialogue = " ".join(
        block["sections"]["SECTION 6 - SPOKEN DIALOGUE"] for block in result["blocks"]
    )
    # Approved copy present.
    assert "tak berminyak" in dialogue
    # Generic bank filler must not appear alongside a bound approved set.
    assert "tersusun" not in dialogue
    assert "tak rasa hype" not in dialogue


def test_fallback_copy_still_gets_bank_support():
    # Without a bound approved set the banks keep dialogue from going mute.
    result = _compile(mode="FRAMES", copy={})
    dialogue = " ".join(
        block["sections"]["SECTION 6 - SPOKEN DIALOGUE"] for block in result["blocks"]
    )
    assert dialogue.strip(), "fallback dialogue must not be empty"
