from agent.services.registration_hook_cta_generation_service import (
    generate_registration_hook_cta,
)


def test_sensitive_health_hook_cta_stays_claim_safe():
    result = generate_registration_hook_cta(
        {
            "product_name": "Bosmax Herbs 5 ML",
            "benefits_text": "Membantu keyakinan kelelakian dan ketegangan.",
            "target_customer_text": "Lelaki dewasa",
            "usage_text": "Sapuan luaran setiap hari.",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["ketegangan", "bahagian intim"],
            "copy_route": "STEALTH",
            "silo": "health_supp_stealth_01",
        }
    )

    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "luaran" in combined
    assert "prestasi fizikal lelaki" not in combined
    assert "ketegangan" not in combined
    assert "ubat kuat" not in combined
    assert "cure" not in combined


def test_general_product_hook_cta_is_non_empty():
    result = generate_registration_hook_cta(
        {
            "product_name": "Atlas Laundry Liquid",
            "benefits_text": "Membantu cucian harian kelihatan lebih bersih dan wangi.",
            "target_customer_text": "Isi rumah moden",
            "usage_text": "Tuang ke dalam mesin basuh.",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "laundry_01",
        }
    )

    assert len(result["hook_angles"]) == 3
    assert len(result["cta_angles"]) == 3


# ---------------------------------------------------------------------------
# Gender mapping: fashion, baby & sensitive product address-style tests
# ---------------------------------------------------------------------------


def test_kurung_fashion_product_maps_to_saya_akak():
    """Women's traditional fashion (baju kurung) must use SAYA_AKAK persona."""
    result = generate_registration_hook_cta(
        {
            "product_name": "Bidasari Kurung Cotton Embroidery Cutwork",
            "benefits_text": "Kain cotton selesa untuk dipakai seharian.",
            "target_customer_text": "Wanita moden",
            "usage_text": "",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "fashion_01",
        }
    )
    combined_output = " ".join(result.get("hook_angles", []) + result.get("cta_angles", []))
    assert "akak" in combined_output.lower(), (
        "Expected SAYA_AKAK persona (akak) for kurung fashion product, got: " + combined_output
    )
    assert "abang" not in combined_output.lower()


def test_baby_diaper_product_maps_to_saya_akak():
    """Baby/diaper products target mothers — must use SAYA_AKAK persona."""
    result = generate_registration_hook_cta(
        {
            "product_name": "MamyPoko Baby Diapers M50",
            "benefits_text": "Lampin pakai buang untuk bayi dengan daya serap tinggi.",
            "target_customer_text": "Ibu bapa",
            "usage_text": "Pakai pada bayi.",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "baby_01",
        }
    )
    combined_output = " ".join(result.get("hook_angles", []) + result.get("cta_angles", []))
    assert "akak" in combined_output.lower(), (
        "Expected SAYA_AKAK persona (akak) for baby diaper product, got: " + combined_output
    )
    assert "abang" not in combined_output.lower()


def test_mens_supplement_maps_to_saya_abang():
    """Explicit male supplement must keep SAYA_ABANG persona."""
    result = generate_registration_hook_cta(
        {
            "product_name": "TestoPower Supplement Lelaki",
            "benefits_text": "Membantu stamina dan vitaliti untuk lelaki.",
            "target_customer_text": "Lelaki aktif",
            "usage_text": "Makan 2 biji sehari.",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "supplement_01",
        }
    )
    combined_output = " ".join(result.get("hook_angles", []) + result.get("cta_angles", []))
    assert "abang" in combined_output.lower(), (
        "Expected SAYA_ABANG persona (abang) for men's supplement, got: " + combined_output
    )


def test_curtain_with_skirting_in_name_is_not_sold_as_beauty():
    """Live incident 2026-07-14: 'Skirting Table Top' (curtain) matched the
    fashion token 'skirt' by SUBSTRING and was pitched as 'produk beauty
    harian'. Word-boundary matching + category-true phrasing must hold."""
    result = generate_registration_hook_cta(
        {
            "product_name": "HOT Langsir Kabinet DESIGN ( RENDA LEKAT ) viral, Skirting Table Top",
            "benefits_text": "",
            "target_customer_text": "",
            "usage_text": "",
            "category": "Textiles & Soft Furnishings > Household Textiles > Curtain & Blind Accessories",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "home_01",
        }
    )
    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "beauty" not in combined
    assert "penjagaan diri" not in combined


def test_akak_tier_fashion_product_does_not_claim_beauty():
    """Baju kurung stays akak-tier but must NOT be called a beauty product."""
    result = generate_registration_hook_cta(
        {
            "product_name": "Bidasari Kurung Cotton Embroidery",
            "benefits_text": "Kain cotton selesa untuk dipakai seharian.",
            "target_customer_text": "Wanita moden",
            "usage_text": "",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "fashion_01",
        }
    )
    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "akak" in combined
    assert "beauty" not in combined


def test_beauty_product_keeps_beauty_phrasing():
    result = generate_registration_hook_cta(
        {
            "product_name": "GlowUp Lip Serum Vitamin E",
            "benefits_text": "Bibir lembap sepanjang hari.",
            "target_customer_text": "",
            "usage_text": "Sapu pada bibir.",
            "category": "Beauty & Personal Care > Lip",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "beauty_01",
        }
    )
    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "akak" in combined
    assert "produk beauty harian" in combined


def test_women_target_customer_not_misrouted_to_abang():
    """Substring bug: 'men' in 'women' routed female-target products to abang."""
    result = generate_registration_hook_cta(
        {
            "product_name": "Ergo Kitchen Organizer Rack",
            "benefits_text": "Susun atur dapur lebih kemas.",
            "target_customer_text": "Working women",
            "usage_text": "",
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "copy_route": "DIRECT",
            "silo": "home_02",
        }
    )
    combined = " ".join(result["hook_angles"] + result["cta_angles"]).casefold()
    assert "abang" not in combined
    assert "akak" in combined


def test_sensitive_product_without_gender_signal_defaults_aku_korang_not_abang():
    """Sensitive product with no clear gender signal must NOT default to abang."""
    result = generate_registration_hook_cta(
        {
            "product_name": "Nutri Slim Detox Tea",
            "benefits_text": "Membantu pengurusan berat badan.",
            "target_customer_text": "",
            "usage_text": "Minum sebelum tidur.",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["slimming", "weight_loss"],
            "copy_route": "SOFT",
            "silo": "health_01",
        }
    )
    combined_output = " ".join(result.get("hook_angles", []) + result.get("cta_angles", []))
    assert "abang" not in combined_output.lower(), (
        "Sensitive gender-neutral product must not assume male persona, got: " + combined_output
    )
