from agent.services.product_mapping import resolve_product_mapping


def test_sumikko_diaper_mapping():
    result = resolve_product_mapping(
        product_name="Sumikko 50PCS Premium Baby Diaper pants disposable diaper tape diaper pants pull-ups Ultra-thin and breathable All size S/M/L/XL/XXL/XXXL",
        source_hint="FASTMOSS",
    )

    assert result["category"] == "Baby Care"
    assert result["subcategory"] == "Diaper"
    assert result["type"] == "Pants"
    assert result["product_type"] == "UNIVERSAL"
    assert result["trigger_id"] == "TRUST_01"


def test_qayraa_jersey_mapping():
    result = resolve_product_mapping(
        product_name="QAYRAA P1 (S-XL) Jersi Muslimah Labuh Microfiber Athleisure Sport Quick Dry",
        source_hint="FASTMOSS",
    )

    assert result["category"] == "Fashion"
    assert result["subcategory"] == "Sportswear"
    assert result["type"] == "Jersey-Athleisure"
    assert result["product_type"] == "UNIVERSAL"
    assert result["trigger_id"] == "CONFIDENCE_01"


def test_seluar_mapping_prefers_specific_phrase_rule():
    result = resolve_product_mapping(
        product_name="Seluar Tarik Ke Atas, SUMIKKO, 50PCS, Lampin Bayi",
        source_hint="MANUAL_PROJECT",
    )

    assert result["category"] == "Baby Care"
    assert result["subcategory"] == "Diaper"
    assert result["type"] == "Pants"
    assert "Conflict resolved: baby_diaper outranked fashion_bottoms due lampin/diaper keywords" in result["notes"]
    assert result["product_type"] == "UNIVERSAL"
    assert result["trigger_id"] == "TRUST_01"


def test_elianto_body_spray_mapping():
    result = resolve_product_mapping(
        product_name="Elianto body spray fresh bloom",
        source_hint="MANUAL_PROJECT",
    )

    assert result["category"] == "Beauty & Personal Care"
    assert result["subcategory"] == "Fragrance"
    assert result["type"] == "Body Mist"


def test_sambal_mapping():
    result = resolve_product_mapping(
        product_name="Sambal Nyet extra pedas",
        source_hint="MANUAL_PROJECT",
    )

    assert result["category"] == "Food & Beverage"
    assert result["subcategory"] == "Ready-to-eat/Food"
    assert result["type"] == "Sauce-Food"


def test_unknown_manual_product_needs_review():
    result = resolve_product_mapping(
        product_name="Mystery artisanal item",
        source_hint="MANUAL_PROJECT",
    )

    assert result["mapping_confidence"] == "NEEDS_REVIEW"
    assert "category" in result["missing_fields"]


def test_kb_hijabsta_pants_mapping_outranks_mat_keyword_noise():
    result = resolve_product_mapping(
        product_name="[ KB HIJABSTA ] Women High Waist Stretch Long Pants Mini BootCut Auto Slim Design Slack Ironless Trousers MATERIAL PREMIUM SCUBA",
        source_hint="FASTMOSS",
    )

    assert result["category"] == "Fashion"
    assert result["subcategory"] == "Bottoms"
    assert result["type"] == "Pants"
    assert result["product_type"] == "UNIVERSAL"
    assert result["silo"] == "fashion_mass_01"
    assert result["trigger_id"] == "CONFIDENCE_01"
    assert result["formula"] == "AIDA"


def test_sampul_duit_raya_mapping():
    result = resolve_product_mapping(
        product_name="(10 pcs) SAMPUL DUIT RAYA BASIC BUNGA BUNGA SAIZ BESAR 2026 Money Packet",
        source_hint="FASTMOSS",
    )

    assert result["category"] == "Stationery"
    assert result["subcategory"] == "Envelope"
    assert result["type"] == "Money Packet"
    assert result["product_type"] == "UNIVERSAL"
    assert result["silo"] == "stationery_mass_01"
    assert result["trigger_id"] == "GIFTING_01"
    assert result["formula"] == "PAS"


def test_food_container_mapping_not_food_and_beverage():
    result = resolve_product_mapping(
        product_name="HOMEWORTH 7 in 1 Food Container Set With Lid Bekas Makanan Hadiah Microwave-safe",
        source_hint="FASTMOSS",
    )

    assert result["category"] == "Home & Living"
    assert result["subcategory"] == "Kitchen Storage"
    assert result["type"] == "Food Container"
    assert result["product_type"] == "UNIVERSAL"
    assert result["silo"] == "household_mass_01"
    assert result["trigger_id"] == "TRUST_01"
    assert result["formula"] == "PAS"